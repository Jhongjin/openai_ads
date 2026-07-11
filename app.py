from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import ipaddress
from io import BytesIO
import json
import os
from pathlib import Path
import re
import socket
from uuid import uuid4
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from rag_chatbot.config import project_root


app = FastAPI(title="Nasmedia ChatGPT Ads RAG", version="0.1.0")
app.mount(
    "/images",
    StaticFiles(directory=project_root() / "public" / "images", check_dir=False),
    name="images",
)
app.mount(
    "/dev-assets",
    StaticFiles(directory=project_root() / "dev" / "assets", check_dir=False),
    name="dev-assets",
)
app.mount(
    "/assets",
    StaticFiles(directory=project_root() / "dev" / "assets", check_dir=False),
    name="assets",
)


IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
ADS_DASHBOARD_CACHE_KEY = "active_advertisers"
KST = timezone(timedelta(hours=9))


def _configured_access_networks() -> list[IpNetwork]:
    raw = os.getenv("ACCESS_ALLOWED_IPS", "").strip()
    if not raw:
        return []
    networks: list[IpNetwork] = []
    for item in re.split(r"[,\s]+", raw):
        value = item.strip()
        if not value:
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return networks


def _request_client_ip(request: Request) -> IpAddress | None:
    header_value = (
        request.headers.get("x-vercel-forwarded-for")
        or request.headers.get("x-forwarded-for")
        or request.headers.get("x-real-ip")
        or ""
    )
    candidate = header_value.split(",", 1)[0].strip()
    if not candidate and request.client:
        candidate = request.client.host
    if not candidate:
        return None
    candidate = candidate.strip("[]")
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


@app.middleware("http")
async def restrict_access_by_ip(request: Request, call_next):
    networks = _configured_access_networks()
    if not networks:
        return await call_next(request)
    client_ip = _request_client_ip(request)
    if client_ip and any(client_ip in network for network in networks):
        return await call_next(request)
    return PlainTextResponse("허용된 사내 네트워크에서만 접속할 수 있습니다.", status_code=403)

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]]


class CheckRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, max_length=100)


class CheckResultResponse(BaseModel):
    input_url: str
    normalized_url: str
    origin: str
    path: str
    robots_url: str
    verdict: str
    badge: str
    reason: str
    action: str
    http_status: int | None
    robots_txt: str
    firewall_hint: bool = False
    firewall_badge: str | None = None
    bot_details: list[dict[str, str]] = Field(default_factory=list)


class FaviconCheckRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, max_length=100)


class FaviconCheckResultResponse(BaseModel):
    input_url: str
    normalized_url: str
    verdict: str
    badge: str
    size: str
    width: int | None
    height: int | None
    format: str
    background: str
    reason: str
    action: str
    http_status: int | None
    preview_url: str | None


class IngestResponse(BaseModel):
    counts: dict[str, int]


class IntakeResponse(BaseModel):
    receipt_number: str
    submitted_at_kst: str
    mail_sent: bool | None = None
    mail_error: str | None = None
    mail_sender: str | None = None
    mail_recipient: str | None = None
    mail_cc: str | None = None
    mail_quota_remaining: int | None = None


class WorkbookInspectResponse(BaseModel):
    ok: bool
    sheets: dict[str, Any]
    errors: list[str]
    warnings: list[str] = Field(default_factory=list)
    data: dict[str, Any] | None = None


class ImageUploadResponse(BaseModel):
    image_url: str
    width: int
    height: int
    content_type: str


class NoticeConfigRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    body_html: str | None = Field(default=None, max_length=8000)
    modal_background: str | None = Field(default="#ffffff", max_length=20)
    bullets: list[str] = Field(default_factory=list, max_length=20)
    source_label: str = Field(..., min_length=1, max_length=200)
    source_url: str = Field(..., min_length=1, max_length=300)
    enabled: bool = True


class MenuSettingsRequest(BaseModel):
    menus: dict[str, bool] = Field(default_factory=dict)
    guide_decks: dict[str, bool] = Field(default_factory=dict)


class SlideContentItemRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=120)
    value: str = Field(default="", max_length=1200)
    deck: str | None = Field(default="", max_length=40)
    label: str | None = Field(default="", max_length=200)
    default: str | None = Field(default="", max_length=1200)
    multiline: bool | None = False
    alt: str | None = Field(default="", max_length=300)
    caption: str | None = Field(default="", max_length=300)


class SlideContentRequest(BaseModel):
    items: list[SlideContentItemRequest] = Field(default_factory=list, max_length=700)
    images: list[SlideContentItemRequest] = Field(default_factory=list, max_length=120)
    layout: dict[str, Any] | None = Field(default_factory=dict)


class MailReviewUpdateRequest(BaseModel):
    duplicate_hash: str = Field(..., min_length=8, max_length=128)
    review_status: str = Field(..., min_length=1, max_length=40)
    review_note: str | None = Field(default="", max_length=2000)
    approved_title: str | None = Field(default="", max_length=300)
    approved_summary: str | None = Field(default="", max_length=8000)
    approved_by: str | None = Field(default="", max_length=80)
    supersedes_duplicate_hash: str | None = Field(default="", max_length=128)


class ManualRagItemRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=300)
    category: str | None = Field(default="", max_length=120)
    source_note: str | None = Field(default="", max_length=1000)
    content: str = Field(..., min_length=1, max_length=20000)


class FaqCategoryRequest(BaseModel):
    id: str | None = Field(default="", max_length=40)
    label: str = Field(..., min_length=1, max_length=80)
    sort_order: int | None = Field(default=0)


class FaqItemRequest(BaseModel):
    category: str = Field(..., min_length=1, max_length=40)
    question: str = Field(..., min_length=1, max_length=500)
    answer: str = Field(..., min_length=1, max_length=3000)
    source_summary: str | None = Field(default="관리자 FAQ 관리", max_length=300)


class CampaignIntakeOpsRequest(BaseModel):
    receipt_number: str = Field(..., min_length=3, max_length=80)
    operator_name: str | None = Field(default="", max_length=80)
    status: str = Field(default="ready", min_length=1, max_length=40)
    memo: str | None = Field(default="", max_length=1000)


class VisitRequest(BaseModel):
    page: str = Field(..., min_length=1, max_length=80)
    label: str | None = Field(default=None, max_length=120)


class AdsApiKeyRequest(BaseModel):
    advertiser_name: str = Field(..., min_length=1, max_length=120)
    industry: str | None = Field(default="", max_length=40)
    ads_api_key: str | None = Field(default="", max_length=500)
    conversion_api_key: str | None = Field(default="", max_length=500)
    enabled: bool = True


class AdsApiKeyInspectRequest(BaseModel):
    ads_api_key: str = Field(..., min_length=1, max_length=500)


class AdsCampaignObjectiveRequest(BaseModel):
    advertiser_name: str = Field(..., min_length=1, max_length=120)
    campaign_id: str = Field(..., min_length=1, max_length=160)
    campaign_name: str | None = Field(default="", max_length=1000)
    objective: str | None = Field(default="", max_length=40)


class AdsAdcopyGenerateRequest(BaseModel):
    advertiser_name: str = Field(..., min_length=1, max_length=120)
    industry: str | None = Field(default="", max_length=40)
    campaign_name: str = Field(..., min_length=1, max_length=160)
    objective: str = Field(default="Views", min_length=1, max_length=40)
    budget_max: float | None = Field(default=None, ge=0)
    budget_type: str = Field(default="daily", min_length=1, max_length=20)
    launch_date: str | None = Field(default="", max_length=20)
    end_date: str | None = Field(default="", max_length=20)
    target_countries: list[str] = Field(default_factory=lambda: ["KR"], max_length=20)
    product_name: str = Field(..., min_length=1, max_length=200)
    landing_url: str = Field(..., min_length=1, max_length=1000)
    image_link: str | None = Field(default="", max_length=1000)
    audience: str | None = Field(default="", max_length=1000)
    selling_points: str | None = Field(default="", max_length=2000)
    tone: str | None = Field(default="", max_length=300)
    banned_terms: str | None = Field(default="", max_length=1500)
    required_phrases: str | None = Field(default="", max_length=1500)
    adgroup_count: int = Field(default=3, ge=1, le=12)
    ads_per_adgroup: int = Field(default=3, ge=1, le=8)


class AdsAdcopyLandingInspectRequest(BaseModel):
    landing_url: str = Field(..., min_length=1, max_length=1000)


class AdsAdcopyDraftPlanRequest(BaseModel):
    advertiser_name: str = Field(..., min_length=1, max_length=120)
    generated: dict[str, Any] = Field(default_factory=dict)
    default_max_bid_krw: float | None = Field(default=7000, ge=0)
    location_ids: list[str] = Field(default_factory=list, max_length=50)


class AdsAdcopyDraftExecuteRequest(AdsAdcopyDraftPlanRequest):
    action: str = Field(..., min_length=1, max_length=40)
    state: dict[str, Any] = Field(default_factory=dict)
    confirm: bool = False


PAGE_LABELS = {
    "root": "메인",
    "chat": "광고 Q&A",
    "crawler": "랜딩 URL 검사",
    "favicon": "파비콘 검사",
    "intake": "소재 업로드",
    "slides": "광고주 안내 자료",
    "setupGuide": "캠페인 세팅 가이드",
    "pixelGuide": "픽셀 설치 가이드",
}

GUIDE_DECK_PANELS = {
    "advertiser": "slides-panel",
    "setup": "setup-guide-panel",
    "pixel": "pixel-guide-panel",
}


def _admin_password() -> str:
    return os.getenv("ADMIN_PASSWORD") or "nas2026@"


def _require_admin(request: Request) -> None:
    provided = request.headers.get("x-admin-password", "")
    if provided != _admin_password():
        raise HTTPException(status_code=403, detail="관리자 비밀번호가 올바르지 않습니다.")


def _require_cron(request: Request) -> None:
    cron_secret = os.getenv("CRON_SECRET", "").strip()
    if cron_secret:
        expected = f"Bearer {cron_secret}"
        if request.headers.get("authorization", "") != expected:
            raise HTTPException(status_code=401, detail="cron authorization failed")


def _join_unique_messages(*messages: str) -> str:
    return " · ".join(dict.fromkeys(str(message or "").strip() for message in messages if str(message or "").strip()))


def _date_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KST)
        return parsed.astimezone(KST).date().isoformat()
    except ValueError:
        return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else text


def _ads_dashboard_range_cache_key(start_date: str | None, end_date: str | None) -> str:
    if start_date and end_date:
        return f"{ADS_DASHBOARD_CACHE_KEY}:{start_date}:{end_date}"
    return ADS_DASHBOARD_CACHE_KEY


def _ads_dashboard_payload_matches_range(payload: dict[str, Any], start_date: str | None, end_date: str | None) -> bool:
    if not start_date or not end_date:
        return True
    range_payload = payload.get("range") if isinstance(payload.get("range"), dict) else {}
    return str(range_payload.get("start_date") or "") == start_date and str(range_payload.get("end_date") or "") == end_date


def _split_admin_list(value: str | None) -> list[str]:
    items = re.split(r"[\n,]+", str(value or ""))
    return [item.strip() for item in items if item.strip()]


ADCOPY_LANDING_MAX_BYTES = 300_000


def _clean_meta_text(value: str | None, max_length: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:max_length]


def _landing_url_parts(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="랜딩 URL은 http 또는 https 주소여야 합니다.")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="사용자 정보가 포함된 URL은 지원하지 않습니다.")
    return parsed.scheme, parsed.hostname, parsed.port


def _assert_public_ip_address(address: str) -> None:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="랜딩 URL 호스트를 확인하지 못했습니다.") from exc
    if not ip.is_global:
        raise HTTPException(status_code=400, detail="내부망 또는 비공개 IP로 연결되는 랜딩 URL은 읽을 수 없습니다.")


async def _assert_public_landing_url(url: str) -> None:
    _, host, port = _landing_url_parts(url)
    try:
        literal_ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if not literal_ip.is_global:
            raise HTTPException(status_code=400, detail="내부망 또는 비공개 IP로 연결되는 랜딩 URL은 읽을 수 없습니다.")
        return
    if host.lower() in {"localhost", "localhost.localdomain"} or host.lower().endswith(".local"):
        raise HTTPException(status_code=400, detail="내부 호스트로 보이는 랜딩 URL은 읽을 수 없습니다.")
    try:
        addr_info = await asyncio.to_thread(socket.getaddrinfo, host, port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="랜딩 URL 호스트를 확인하지 못했습니다.") from exc
    for item in addr_info:
        sockaddr = item[4]
        if sockaddr:
            _assert_public_ip_address(str(sockaddr[0]))


async def _fetch_landing_html(url: str) -> tuple[str, str]:
    current_url = str(url or "").strip()
    headers = {
        "User-Agent": "NasmediaOpenAIAdsAdmin/1.0 (+https://openads.admate.ai.kr)",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0), follow_redirects=False) as client:
        for _ in range(4):
            await _assert_public_landing_url(current_url)
            async with client.stream("GET", current_url, headers=headers) as response:
                if response.status_code in {301, 302, 303, 307, 308} and response.headers.get("location"):
                    current_url = urljoin(current_url, response.headers["location"])
                    continue
                if response.status_code >= 400:
                    raise HTTPException(status_code=502, detail=f"랜딩 URL 응답 오류: HTTP {response.status_code}")
                content_type = response.headers.get("content-type", "")
                if content_type and "html" not in content_type.lower() and "text/" not in content_type.lower():
                    raise HTTPException(status_code=400, detail="랜딩 URL이 HTML 문서로 응답하지 않았습니다.")
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= ADCOPY_LANDING_MAX_BYTES:
                        break
            raw = b"".join(chunks)[:ADCOPY_LANDING_MAX_BYTES]
            return raw.decode("utf-8", errors="ignore"), str(response.url)
    raise HTTPException(status_code=400, detail="랜딩 URL 리다이렉트가 너무 많습니다.")


def _meta_content(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return _clean_meta_text(tag.get("content"))
    return ""


def _link_rel_contains(value: Any, token: str) -> bool:
    items = value if isinstance(value, list) else str(value or "").split()
    return token.lower() in {str(item).lower() for item in items}


def _inspect_landing_html(html: str, final_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html or "", "html.parser")
    title = _clean_meta_text(_meta_content(soup, "og:title", "twitter:title") or (soup.title.string if soup.title else ""), 180)
    description = _clean_meta_text(_meta_content(soup, "og:description", "twitter:description", "description"), 600)
    image_url = _clean_meta_text(_meta_content(soup, "og:image", "twitter:image"), 1000)
    if image_url:
        image_url = urljoin(final_url, image_url)
    canonical_tag = soup.find("link", attrs={"rel": lambda value: _link_rel_contains(value, "canonical")})
    canonical_url = urljoin(final_url, canonical_tag.get("href")) if canonical_tag and canonical_tag.get("href") else final_url
    suggestions = [item for item in [title, description] if item]
    selling_points = "\n".join(suggestions)
    return {
        "title": title,
        "description": description,
        "image_url": image_url,
        "canonical_url": canonical_url,
        "selling_points": selling_points[:1200],
    }


def _adcopy_trace(
    source_type: str = "AI 생성",
    source_url: str = "",
    source_excerpt: str = "",
    generation_basis: str = "",
    confidence_score: float = 0.7,
    validation_status: str = "운영 검수 필요",
) -> dict[str, Any]:
    return {
        "source_type": source_type,
        "source_url": source_url,
        "source_excerpt": source_excerpt,
        "generation_basis": generation_basis,
        "confidence_score": confidence_score,
        "validation_status": validation_status,
        "review_comment": "",
        "exclusion_reason": "",
    }


def _adcopy_response_schema() -> dict[str, Any]:
    trace_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "source_type": {"type": "string"},
            "source_url": {"type": "string"},
            "source_excerpt": {"type": "string"},
            "generation_basis": {"type": "string"},
            "confidence_score": {"type": "number"},
            "validation_status": {"type": "string"},
            "review_comment": {"type": "string"},
            "exclusion_reason": {"type": "string"},
        },
        "required": [
            "source_type",
            "source_url",
            "source_excerpt",
            "generation_basis",
            "confidence_score",
            "validation_status",
            "review_comment",
            "exclusion_reason",
        ],
    }
    keyword_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "text": {"type": "string"},
            "origin": {"type": "string", "enum": ["customer_data", "ai_inferred"]},
        },
        "required": ["text", "origin"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "policy": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "banned_terms": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["banned_terms"],
            },
            "campaigns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "campaign_name": {"type": "string"},
                        "budget_max": {"type": "number"},
                        "budget_type": {"type": "string"},
                        "launch_date": {"type": "string"},
                        "end_date": {"type": "string"},
                        "objective": {"type": "string"},
                        "target_countries": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": [
                        "campaign_name",
                        "budget_max",
                        "budget_type",
                        "launch_date",
                        "end_date",
                        "objective",
                        "target_countries",
                    ],
                },
            },
            "adgroups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "campaign_name": {"type": "string"},
                        "adgroup_name": {"type": "string"},
                        "keywords": {"type": "array", "items": keyword_schema},
                        "required_phrases": {"type": "array", "items": {"type": "string"}},
                        "trace": trace_schema,
                    },
                    "required": ["campaign_name", "adgroup_name", "keywords", "required_phrases", "trace"],
                },
            },
            "ads": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "ad_name": {"type": "string"},
                        "adgroup_name": {"type": "string"},
                        "title": {"type": "string"},
                        "copy": {"type": "string"},
                        "link": {"type": "string"},
                        "image_link": {"type": "string"},
                        "trace": trace_schema,
                    },
                    "required": ["ad_name", "adgroup_name", "title", "copy", "link", "image_link", "trace"],
                },
            },
        },
        "required": ["policy", "campaigns", "adgroups", "ads"],
    }


def _adcopy_system_prompt() -> str:
    return (
        "You are an expert Korean OpenAI Ads copy strategist. "
        "Generate upload-ready draft data for the exact JSON schema only. "
        "Do not create or activate campaigns. The output is only a human-review draft. "
        "Keep campaigns from the user brief unchanged. Generate only adgroups and ads. "
        "Never include max_bid. Titles must be 24 Korean characters or fewer. "
        "Prefer Korean titles around 16 to 18 characters when possible. "
        "Ad copy must be 48 Korean characters or fewer and should usually be 18 to 42 characters. "
        "Write natural Korean that a Korean ads operator would approve; avoid stiff phrases like '고려한', "
        "generic filler, awkward noun stacks, unverifiable superlatives, guarantees, sensitive targeting language, "
        "and banned terms. Each ad must carry one concrete product benefit or usage situation from the brief, "
        "and ads inside the same adgroup must not repeat the same title/copy structure. Context hint keywords "
        "must be concrete Korean search or intent phrases and each keyword origin must be customer_data or ai_inferred."
    )


def _adcopy_user_prompt(payload: AdsAdcopyGenerateRequest) -> str:
    banned_terms = _split_admin_list(payload.banned_terms)
    required_phrases = _split_admin_list(payload.required_phrases)
    brief = {
        "advertiser_name": payload.advertiser_name.strip(),
        "industry": (payload.industry or "").strip(),
        "campaign": {
            "campaign_name": payload.campaign_name.strip(),
            "budget_max": float(payload.budget_max or 0),
            "budget_type": payload.budget_type.strip() or "daily",
            "launch_date": (payload.launch_date or "").strip(),
            "end_date": (payload.end_date or "").strip(),
            "objective": payload.objective.strip() or "Views",
            "target_countries": payload.target_countries or ["KR"],
        },
        "product_name": payload.product_name.strip(),
        "landing_url": payload.landing_url.strip(),
        "image_link": (payload.image_link or "").strip(),
        "audience": (payload.audience or "").strip(),
        "selling_points": (payload.selling_points or "").strip(),
        "tone": (payload.tone or "").strip(),
        "banned_terms": banned_terms,
        "required_phrases": required_phrases,
        "generation_quantity": {
            "adgroups": payload.adgroup_count,
            "ads_per_adgroup": payload.ads_per_adgroup,
        },
    }
    return (
        "Create Korean OpenAI Ads draft copy from this brief.\n"
        "- Return exactly one campaign, copied from brief.campaign.\n"
        "- Create the requested number of adgroups and ads.\n"
        "- Set adgroups.required_phrases to the brief required_phrases array.\n"
        "- Use landing_url and image_link for every ad.\n"
        "- Make adgroup themes distinct by audience intent, product benefit, or usage situation.\n"
        "- Prefer title length 16~18 Korean characters; never exceed 24 characters.\n"
        "- Prefer copy length 18~42 Korean characters; never exceed 48 characters.\n"
        "- If a required phrase exists, include it in every ad title or copy without forcing awkward grammar.\n"
        "- Keep Korean phrasing crisp, specific, and natural enough to be used after a human review.\n"
        "- Set trace.review_comment and trace.exclusion_reason to empty strings.\n"
        "- Set trace.validation_status to '운영 검수 필요' unless a concrete warning is needed.\n"
        f"\nBRIEF_JSON:\n{json.dumps(brief, ensure_ascii=False, indent=2)}"
    )


def _extract_openai_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                return content["text"]
    return ""


async def _call_openai_adcopy(payload: AdsAdcopyGenerateRequest) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_ADCOPY_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY 또는 OPENAI_ADCOPY_API_KEY가 설정되어 있지 않습니다.")
    model = os.getenv("OPENAI_ADCOPY_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5"
    base_url = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    request_body = {
        "model": model,
        "input": [
            {"role": "system", "content": _adcopy_system_prompt()},
            {"role": "user", "content": _adcopy_user_prompt(payload)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "openai_ads_adcopy_generated",
                "strict": True,
                "schema": _adcopy_response_schema(),
            }
        },
        "max_output_tokens": 12000,
        "store": False,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(f"{base_url}/responses", headers=headers, json=request_body)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"OpenAI 카피 생성 API 오류: HTTP {response.status_code} · {response.text[:600]}")
    data = response.json()
    raw_text = _extract_openai_response_text(data)
    if not raw_text.strip():
        raise HTTPException(status_code=502, detail="OpenAI 카피 생성 응답에서 JSON 텍스트를 찾지 못했습니다.")
    try:
        generated = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="OpenAI 카피 생성 응답 JSON 파싱에 실패했습니다.") from exc
    return {"model": model, "raw_response_id": data.get("id"), "generated": generated}


def _normalize_generated_adcopy(data: dict[str, Any], payload: AdsAdcopyGenerateRequest) -> dict[str, Any]:
    campaign = {
        "campaign_name": payload.campaign_name.strip(),
        "budget_max": float(payload.budget_max or 0),
        "budget_type": payload.budget_type.strip() or "daily",
        "launch_date": (payload.launch_date or "").strip(),
        "end_date": (payload.end_date or "").strip(),
        "objective": payload.objective.strip() or "Views",
        "target_countries": [country.strip().upper() for country in payload.target_countries if str(country or "").strip()] or ["KR"],
    }
    banned_terms = _split_admin_list(payload.banned_terms)
    model_policy = data.get("policy") if isinstance(data.get("policy"), dict) else {}
    merged_banned_terms = list(dict.fromkeys([*banned_terms, *[str(item).strip() for item in model_policy.get("banned_terms") or [] if str(item).strip()]]))
    required_phrases = _split_admin_list(payload.required_phrases)
    adgroups: list[dict[str, Any]] = []
    seen_adgroups: set[str] = set()
    for index, item in enumerate(data.get("adgroups") or [], start=1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("adgroup_name") or f"{index:02d}_광고그룹").strip()
        if not name:
            name = f"{index:02d}_광고그룹"
        if name in seen_adgroups:
            name = f"{name}_{index:02d}"
        seen_adgroups.add(name)
        keywords = []
        for keyword in item.get("keywords") or []:
            if isinstance(keyword, dict):
                text = str(keyword.get("text") or "").strip()
                origin = str(keyword.get("origin") or "ai_inferred").strip()
            else:
                text = str(keyword or "").strip()
                origin = "ai_inferred"
            if text:
                keywords.append({"text": text, "origin": origin if origin in {"customer_data", "ai_inferred"} else "ai_inferred"})
        trace = item.get("trace") if isinstance(item.get("trace"), dict) else _adcopy_trace()
        adgroups.append({
            "campaign_name": campaign["campaign_name"],
            "adgroup_name": name,
            "keywords": keywords,
            "required_phrases": [str(value).strip() for value in (item.get("required_phrases") or required_phrases) if str(value).strip()],
            "trace": {**_adcopy_trace(), **trace, "review_comment": "", "exclusion_reason": ""},
        })
    valid_adgroup_names = {item["adgroup_name"] for item in adgroups}
    ads: list[dict[str, Any]] = []
    for index, item in enumerate(data.get("ads") or [], start=1):
        if not isinstance(item, dict):
            continue
        adgroup_name = str(item.get("adgroup_name") or "").strip()
        if adgroup_name not in valid_adgroup_names and adgroups:
            adgroup_name = adgroups[min(index - 1, len(adgroups) - 1)]["adgroup_name"]
        trace = item.get("trace") if isinstance(item.get("trace"), dict) else _adcopy_trace()
        ads.append({
            "ad_name": str(item.get("ad_name") or f"AD_{index:03d}").strip(),
            "adgroup_name": adgroup_name,
            "title": str(item.get("title") or "").strip(),
            "copy": str(item.get("copy") or "").strip(),
            "link": payload.landing_url.strip(),
            "image_link": (payload.image_link or "").strip(),
            "trace": {**_adcopy_trace(), **trace, "review_comment": "", "exclusion_reason": ""},
        })
    return {"policy": {"banned_terms": merged_banned_terms}, "campaigns": [campaign], "adgroups": adgroups, "ads": ads}


def _adcopy_finding(level: str, scope: str, item: str, field: str, rule: str, message: str) -> dict[str, str]:
    return {"level": level, "scope": scope, "item": item, "field": field, "rule": rule, "message": message}


ADCOPY_AWKWARD_PATTERNS = (
    "고려한",
    "누려보세요",
    "만나보세요",
    "도와드립니다",
    "최적의",
    "완벽한",
    "획기적인",
)


def _adcopy_recommendation(kind: str, title: str, message: str) -> dict[str, str]:
    return {"kind": kind, "title": title, "message": message}


def _adcopy_quality_grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 55:
        return "D"
    return "F"


def _validate_generated_adcopy(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    creative_checks: list[dict[str, Any]] = []
    campaigns = data.get("campaigns") if isinstance(data.get("campaigns"), list) else []
    adgroups = data.get("adgroups") if isinstance(data.get("adgroups"), list) else []
    ads = data.get("ads") if isinstance(data.get("ads"), list) else []
    policy = data.get("policy") if isinstance(data.get("policy"), dict) else {}
    banned_terms = [str(term).strip() for term in policy.get("banned_terms") or [] if str(term).strip()]
    if not campaigns:
        errors.append(_adcopy_finding("error", "campaigns", "-", "campaign_name", "campaign_required", "캠페인 정보가 비어 있습니다."))
    for campaign in campaigns:
        name = str(campaign.get("campaign_name") or "").strip()
        if not name:
            errors.append(_adcopy_finding("error", "campaigns", "-", "campaign_name", "campaign_name_required", "캠페인명이 비어 있습니다."))
        if not campaign.get("target_countries"):
            errors.append(_adcopy_finding("error", "campaigns", name or "-", "target_countries", "countries_required", "target_countries가 비어 있습니다."))
        if float(campaign.get("budget_max") or 0) <= 0:
            warnings.append(_adcopy_finding("warning", "campaigns", name or "-", "budget_max", "budget_empty", "예산이 0 또는 미입력입니다. 업로드 전 확인하세요."))
    adgroup_names = {str(item.get("adgroup_name") or "").strip() for item in adgroups}
    if not adgroups:
        errors.append(_adcopy_finding("error", "adgroups", "-", "adgroup_name", "adgroup_required", "광고그룹이 생성되지 않았습니다."))
    for adgroup in adgroups:
        name = str(adgroup.get("adgroup_name") or "").strip()
        if not name:
            errors.append(_adcopy_finding("error", "adgroups", "-", "adgroup_name", "adgroup_name_required", "광고그룹명이 비어 있습니다."))
        if adgroup.get("max_bid") not in (None, "", []):
            errors.append(_adcopy_finding("error", "adgroups", name or "-", "max_bid", "max_bid_must_be_empty", "max_bid는 항상 빈칸이어야 합니다."))
        keywords = adgroup.get("keywords") or []
        if len(keywords) < 5:
            warnings.append(_adcopy_finding("warning", "adgroups", name or "-", "keywords", "keyword_count_low", "Context Hints가 5개 미만입니다."))
        required_phrases = [str(value).strip() for value in adgroup.get("required_phrases") or [] if str(value).strip()]
        if required_phrases and not any(str(ad.get("adgroup_name") or "").strip() == name for ad in ads):
            warnings.append(_adcopy_finding("warning", "adgroups", name or "-", "required_phrases", "required_phrase_no_ads", "필수 문구 검수 대상 광고가 없습니다."))
        for keyword in keywords:
            keyword_text = str(keyword.get("text") if isinstance(keyword, dict) else keyword).strip()
            if any(term in keyword_text for term in banned_terms):
                errors.append(_adcopy_finding("error", "adgroups", name or "-", "keywords", "banned_term", f"금지어 포함: {keyword_text}"))
    seen_creatives: dict[str, str] = {}
    if not ads:
        errors.append(_adcopy_finding("error", "ads", "-", "title", "ads_required", "광고 소재가 생성되지 않았습니다."))
    for ad in ads:
        ad_name = str(ad.get("ad_name") or "").strip() or "-"
        adgroup_name = str(ad.get("adgroup_name") or "").strip()
        title = str(ad.get("title") or "").strip()
        copy = str(ad.get("copy") or "").strip()
        combined = f"{title} {copy}"
        ad_issues: list[dict[str, str]] = []
        if adgroup_name not in adgroup_names:
            errors.append(_adcopy_finding("error", "ads", ad_name, "adgroup_name", "adgroup_missing", "존재하지 않는 광고그룹을 참조합니다."))
            ad_issues.append({"level": "error", "rule": "adgroup_missing", "message": "존재하지 않는 광고그룹을 참조합니다."})
        if not title:
            errors.append(_adcopy_finding("error", "ads", ad_name, "title", "title_required", "제목이 비어 있습니다."))
            ad_issues.append({"level": "error", "rule": "title_required", "message": "제목이 비어 있습니다."})
        elif len(title) > 24:
            errors.append(_adcopy_finding("error", "ads", ad_name, "title", "title_max_24", f"제목 {len(title)}자 — 최대 24자"))
            ad_issues.append({"level": "error", "rule": "title_max_24", "message": f"제목 {len(title)}자 — 최대 24자"})
        elif len(title) < 16 or len(title) > 18:
            warnings.append(_adcopy_finding("warning", "ads", ad_name, "title", "title_len_recommended", f"제목 {len(title)}자 — 권장 16~18자"))
            ad_issues.append({"level": "warning", "rule": "title_len_recommended", "message": f"제목 {len(title)}자 — 권장 16~18자"})
        if not copy:
            errors.append(_adcopy_finding("error", "ads", ad_name, "copy", "copy_required", "카피가 비어 있습니다."))
            ad_issues.append({"level": "error", "rule": "copy_required", "message": "카피가 비어 있습니다."})
        elif len(copy) > 48:
            errors.append(_adcopy_finding("error", "ads", ad_name, "copy", "copy_max_48", f"카피 {len(copy)}자 — 최대 48자"))
            ad_issues.append({"level": "error", "rule": "copy_max_48", "message": f"카피 {len(copy)}자 — 최대 48자"})
        elif len(copy) < 18 or len(copy) > 42:
            warnings.append(_adcopy_finding("warning", "ads", ad_name, "copy", "copy_len_recommended", f"카피 {len(copy)}자 — 권장 18~42자"))
            ad_issues.append({"level": "warning", "rule": "copy_len_recommended", "message": f"카피 {len(copy)}자 — 권장 18~42자"})
        awkward_hits = [pattern for pattern in ADCOPY_AWKWARD_PATTERNS if pattern and pattern in combined]
        if awkward_hits:
            message = f"운영 검수에서 어색할 수 있는 표현: {', '.join(awkward_hits)}"
            warnings.append(_adcopy_finding("warning", "ads", ad_name, "title/copy", "awkward_phrase", message))
            ad_issues.append({"level": "warning", "rule": "awkward_phrase", "message": message})
        if title and title == copy:
            errors.append(_adcopy_finding("error", "ads", ad_name, "copy", "copy_equals_title", "카피가 제목과 동일합니다."))
            ad_issues.append({"level": "error", "rule": "copy_equals_title", "message": "카피가 제목과 동일합니다."})
        creative_key = title + "\x00" + copy
        if title and creative_key in seen_creatives:
            errors.append(_adcopy_finding("error", "ads", ad_name, "title", "creative_duplicate", f"제목·카피가 {seen_creatives[creative_key]}와 동일합니다."))
            ad_issues.append({"level": "error", "rule": "creative_duplicate", "message": f"제목·카피가 {seen_creatives[creative_key]}와 동일합니다."})
        seen_creatives[creative_key] = ad_name
        for field in ("link", "image_link"):
            url = str(ad.get(field) or "").strip()
            if not re.match(r"^https?://", url):
                errors.append(_adcopy_finding("error", "ads", ad_name, field, "url_required", f"{field}는 http 또는 https URL이어야 합니다."))
                ad_issues.append({"level": "error", "rule": "url_required", "message": f"{field}는 http 또는 https URL이어야 합니다."})
        for term in banned_terms:
            if term and term in combined:
                errors.append(_adcopy_finding("error", "ads", ad_name, "title/copy", "banned_term", f"금지어 포함: {term}"))
                ad_issues.append({"level": "error", "rule": "banned_term", "message": f"금지어 포함: {term}"})
        group = next((group for group in adgroups if str(group.get("adgroup_name") or "").strip() == adgroup_name), None)
        for phrase in [str(value).strip() for value in (group or {}).get("required_phrases") or [] if str(value).strip()]:
            if phrase not in combined:
                errors.append(_adcopy_finding("error", "ads", ad_name, "title/copy", "required_phrase_missing", f"필수 문구 누락: {phrase}"))
                ad_issues.append({"level": "error", "rule": "required_phrase_missing", "message": f"필수 문구 누락: {phrase}"})
        status = "error" if any(issue["level"] == "error" for issue in ad_issues) else ("warning" if ad_issues else "pass")
        creative_checks.append(
            {
                "ad_name": ad_name,
                "adgroup_name": adgroup_name,
                "title_length": len(title),
                "copy_length": len(copy),
                "status": status,
                "issues": ad_issues[:5],
            }
        )
    warning_rules = [item.get("rule", "") for item in warnings]
    total_keywords = 0
    customer_keywords = 0
    confidence_values: list[float] = []
    for adgroup in adgroups:
        for keyword in adgroup.get("keywords") or []:
            total_keywords += 1
            if isinstance(keyword, dict) and keyword.get("origin") == "customer_data":
                customer_keywords += 1
        trace = adgroup.get("trace") if isinstance(adgroup.get("trace"), dict) else {}
        try:
            confidence = float(trace.get("confidence_score"))
            if 0 <= confidence <= 1:
                confidence_values.append(confidence)
        except (TypeError, ValueError):
            pass
    for ad in ads:
        trace = ad.get("trace") if isinstance(ad.get("trace"), dict) else {}
        try:
            confidence = float(trace.get("confidence_score"))
            if 0 <= confidence <= 1:
                confidence_values.append(confidence)
        except (TypeError, ValueError):
            pass
    average_confidence = round(sum(confidence_values) / len(confidence_values), 2) if confidence_values else None
    quality_score = 0 if not ads else max(0, min(100, 100 - (len(errors) * 24) - (len(warnings) * 6)))
    grade = _adcopy_quality_grade(quality_score)
    if errors:
        readiness = "업로드 보류"
    elif quality_score >= 90 and not warnings:
        readiness = "초안 양호"
    elif quality_score >= 75:
        readiness = "운영 검수 권장"
    else:
        readiness = "수정 권장"
    recommendations: list[dict[str, str]] = []
    if errors:
        recommendations.append(_adcopy_recommendation("error", "오류 우선 수정", "필수 문구 누락, URL, 길이 초과 같은 오류를 먼저 해결해야 합니다."))
    if "title_len_recommended" in warning_rules:
        recommendations.append(_adcopy_recommendation("copy", "제목 길이 보정", "제목은 가능하면 16~18자로 맞추면 노출 영역에서 더 안정적으로 보입니다."))
    if "copy_len_recommended" in warning_rules:
        recommendations.append(_adcopy_recommendation("copy", "카피 밀도 조정", "카피는 18~42자 안에서 구체적 혜택이나 사용 상황을 한 가지 넣는 편이 좋습니다."))
    if "awkward_phrase" in warning_rules:
        recommendations.append(_adcopy_recommendation("tone", "자연어 표현 수정", "'고려한', '누려보세요' 같은 문어체 표현은 더 구체적인 사용 장면으로 바꾸는 편이 좋습니다."))
    if total_keywords and customer_keywords == 0:
        recommendations.append(_adcopy_recommendation("brief", "브리프 기반 키워드 보강", "모든 Context Hints가 AI 추론입니다. 광고주가 제공한 검색어 또는 제품 표현을 1개 이상 넣어 주세요."))
    if average_confidence is not None and average_confidence < 0.75:
        recommendations.append(_adcopy_recommendation("review", "검수 강도 상향", "모델 confidence가 낮습니다. 랜딩 페이지와 소재 이미지의 실제 표현을 한 번 더 대조해 주세요."))
    if not recommendations and not errors:
        recommendations.append(_adcopy_recommendation("ok", "수동 검수 후 사용 가능", "자동 검수에서 큰 문제는 없습니다. 광고주명, 랜딩, 이미지, 정책 표현만 최종 확인하세요."))
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "creative_checks": creative_checks,
        "quality": {
            "score": quality_score,
            "grade": grade,
            "readiness": readiness,
            "average_confidence": average_confidence,
            "customer_keyword_count": customer_keywords,
            "keyword_count": total_keywords,
            "recommendations": recommendations[:5],
        },
        "summary": {
            "campaigns": len(campaigns),
            "adgroups": len(adgroups),
            "ads": len(ads),
            "errors": len(errors),
            "warnings": len(warnings),
            "quality_score": quality_score,
            "quality_grade": grade,
            "readiness": readiness,
        },
    }


def _safe_float(value: Any) -> float:
    try:
        return float(str(value or 0).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _money_to_micros(value: Any) -> int:
    return max(0, int(round(_safe_float(value) * 1_000_000)))


def _cpm_krw_to_max_bid_micros(value: Any) -> int:
    # OpenAI Ads max_bid_micros is per impression. Operators enter CPM in KRW.
    return max(0, int(round(_safe_float(value) * 1000)))


def _date_to_kst_timestamp(value: Any, *, end_of_day: bool = False) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text[:10])
    except ValueError:
        return None
    hour, minute, second = (23, 59, 59) if end_of_day else (0, 0, 0)
    parsed = parsed.replace(hour=hour, minute=minute, second=second, microsecond=0, tzinfo=KST)
    return int(parsed.timestamp())


def _campaign_day_count(start_date: Any, end_date: Any) -> int:
    try:
        start = datetime.fromisoformat(str(start_date or "")[:10]).date()
        end = datetime.fromisoformat(str(end_date or "")[:10]).date()
    except ValueError:
        return 1
    return max(1, (end - start).days + 1)


def _adcopy_trace_status(item: dict[str, Any]) -> str:
    trace = item.get("trace") if isinstance(item.get("trace"), dict) else {}
    return str(trace.get("validation_status") or "").strip()


def _adcopy_is_excluded(item: dict[str, Any]) -> bool:
    return _adcopy_trace_status(item) in {"제외", "excluded", "exclude"}


def _adcopy_keyword_texts(group: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for keyword in group.get("keywords") or []:
        if isinstance(keyword, dict):
            text = str(keyword.get("text") or "").strip()
        else:
            text = str(keyword or "").strip()
        if text:
            values.append(text)
    return list(dict.fromkeys(values))


def _first_campaign(data: dict[str, Any]) -> dict[str, Any]:
    campaigns = data.get("campaigns") if isinstance(data.get("campaigns"), list) else []
    for campaign in campaigns:
        if isinstance(campaign, dict):
            return campaign
    return {}


def _build_adcopy_draft_plan(payload: AdsAdcopyDraftPlanRequest) -> dict[str, Any]:
    generated = payload.generated if isinstance(payload.generated, dict) else {}
    validation_report = _validate_generated_adcopy(generated)
    campaign = _first_campaign(generated)
    campaign_name = str(campaign.get("campaign_name") or "").strip()
    if not campaign_name:
        raise HTTPException(status_code=400, detail="draft 세팅을 만들 캠페인명이 없습니다. 먼저 카피 초안을 생성하거나 generated.json을 확인해 주세요.")
    adgroups = [item for item in (generated.get("adgroups") or []) if isinstance(item, dict)]
    ads_all = [item for item in (generated.get("ads") or []) if isinstance(item, dict)]
    ads = [item for item in ads_all if not _adcopy_is_excluded(item)]
    if not ads:
        raise HTTPException(status_code=400, detail="draft 세팅에 포함할 소재가 없습니다. 운영 상태가 제외가 아닌 소재를 1개 이상 남겨 주세요.")
    adgroup_names = {str(ad.get("adgroup_name") or "").strip() for ad in ads if str(ad.get("adgroup_name") or "").strip()}
    included_adgroups = [group for group in adgroups if str(group.get("adgroup_name") or "").strip() in adgroup_names]
    if not included_adgroups and adgroups:
        included_adgroups = adgroups

    warnings: list[str] = []
    budget_type = str(campaign.get("budget_type") or "daily").strip().lower()
    budget_max = _safe_float(campaign.get("budget_max"))
    days = _campaign_day_count(campaign.get("launch_date"), campaign.get("end_date"))
    lifetime_budget = budget_max * days if budget_type in {"daily", "일 예산", "일예산"} else budget_max
    if budget_type in {"daily", "일 예산", "일예산"}:
        warnings.append(f"일 예산 {int(budget_max):,}원을 캠페인 기간 {days}일 기준 총 예산 {int(lifetime_budget):,}원으로 변환합니다.")
    if lifetime_budget <= 0:
        warnings.append("캠페인 예산이 0원입니다. 실제 생성 전 예산을 확인해야 합니다.")

    default_bid_krw = _safe_float(payload.default_max_bid_krw)
    default_bid_micros = _cpm_krw_to_max_bid_micros(default_bid_krw)
    if default_bid_micros <= 0:
        warnings.append("기본 CPM 입찰가가 0원입니다. 광고그룹 생성 단계는 입찰가를 입력해야 진행할 수 있습니다.")
    if not payload.location_ids:
        warnings.append("Location ID가 비어 있어 위치 타깃 payload를 보내지 않습니다. 필요 시 국가/지역 location id를 입력해 주세요.")

    objective = str(campaign.get("objective") or "").strip()
    if objective and objective.lower() not in {"views", "view", "reach", "impression", "impressions", "노출"}:
        warnings.append("캠페인 목표값은 운영 메타와 검수 기준으로만 사용합니다. OpenAI Ads 생성 payload에는 별도 목표 필드를 보내지 않습니다.")

    campaign_payload: dict[str, Any] = {
        "name": campaign_name,
        "status": "paused",
        "budget": {"lifetime_spend_limit_micros": _money_to_micros(lifetime_budget)},
    }
    start_time = _date_to_kst_timestamp(campaign.get("launch_date"))
    end_time = _date_to_kst_timestamp(campaign.get("end_date"), end_of_day=True)
    if start_time:
        campaign_payload["start_time"] = start_time
    if end_time:
        campaign_payload["end_time"] = end_time
    locations = [str(item).strip() for item in payload.location_ids if str(item or "").strip()]
    if locations:
        campaign_payload["targeting"] = {"locations": {"include": [{"id": item} for item in locations]}}

    adgroup_payloads: list[dict[str, Any]] = []
    for index, group in enumerate(included_adgroups, start=1):
        name = str(group.get("adgroup_name") or f"{index:02d}_광고그룹").strip()
        context_hints = _adcopy_keyword_texts(group)
        if not context_hints:
            warnings.append(f"{name} 광고그룹의 Context Hints가 비어 있습니다.")
        adgroup_payloads.append(
            {
                "name": name,
                "ad_count": sum(1 for ad in ads if str(ad.get("adgroup_name") or "").strip() == name),
                "context_hints": context_hints,
                "api_payload": {
                    "name": name,
                    "status": "paused",
                    "context_hints": context_hints,
                    "bidding_config": {
                        "billing_event_type": "impression",
                        "max_bid_micros": default_bid_micros,
                    },
                },
            }
        )

    image_urls = list(dict.fromkeys(str(ad.get("image_link") or "").strip() for ad in ads if re.match(r"^https?://", str(ad.get("image_link") or "").strip(), re.I)))
    assets = [{"image_url": url} for url in image_urls]
    if not assets:
        warnings.append("업로드할 이미지 URL이 없습니다. 소재 생성 전 이미지 URL을 확인해야 합니다.")

    ad_payloads: list[dict[str, Any]] = []
    for index, ad in enumerate(ads, start=1):
        ad_name = str(ad.get("ad_name") or f"AD_{index:03d}").strip()
        adgroup_name = str(ad.get("adgroup_name") or "").strip()
        target_url = str(ad.get("link") or "").strip()
        image_url = str(ad.get("image_link") or "").strip()
        if not re.match(r"^https?://", target_url, re.I):
            warnings.append(f"{ad_name} 소재의 랜딩 URL이 올바르지 않습니다.")
        if not re.match(r"^https?://", image_url, re.I):
            warnings.append(f"{ad_name} 소재의 이미지 URL이 올바르지 않습니다.")
        ad_payloads.append(
            {
                "key": f"{adgroup_name}::{ad_name}",
                "name": ad_name,
                "adgroup_name": adgroup_name,
                "image_url": image_url,
                "api_payload": {
                    "name": ad_name,
                    "status": "paused",
                    "creative": {
                        "type": "chat_card",
                        "title": str(ad.get("title") or "").strip(),
                        "body": str(ad.get("copy") or "").strip(),
                        "target_url": target_url,
                    },
                },
            }
        )

    return {
        "ok": True,
        "advertiser_name": payload.advertiser_name,
        "mode": "draft_paused",
        "safety": {
            "default_status": "paused",
            "activation_requires_explicit_confirm": True,
            "operator_step_required": True,
        },
        "summary": {
            "campaigns": 1,
            "adgroups": len(adgroup_payloads),
            "ads": len(ad_payloads),
            "assets": len(assets),
            "excluded_ads": len(ads_all) - len(ads),
            "validation_errors": len(validation_report.get("errors") or []),
            "validation_warnings": len(validation_report.get("warnings") or []),
        },
        "warnings": list(dict.fromkeys(warnings)),
        "campaign": {
            "name": campaign_name,
            "objective": objective,
            "budget_type": budget_type or "-",
            "budget_krw": lifetime_budget,
            "start_date": campaign.get("launch_date") or "",
            "end_date": campaign.get("end_date") or "",
            "api_payload": campaign_payload,
        },
        "ad_groups": adgroup_payloads,
        "assets": assets,
        "ads": ad_payloads,
        "next_steps": [
            "광고주 계정 확인",
            "paused 캠페인 draft 생성",
            "이미지 파일 업로드",
            "paused 광고그룹 draft 생성",
            "paused 소재 draft 생성",
            "운영자 최종 확인 후 명시적 활성화",
        ],
        "validation_report": validation_report,
    }


async def _ads_draft_api_request(
    api_key: str,
    method: str,
    path: str,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from rag_chatbot.ads_api import load_ads_api_settings

    settings = load_ads_api_settings(api_key=api_key)
    url = f"{settings.base_url}{path}"
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(method.upper(), url, headers=headers, json=json_body)
    if response.status_code >= 400:
        raise httpx.HTTPStatusError(
            f"HTTP {response.status_code}",
            request=response.request,
            response=response,
        )
    if not response.text.strip():
        return {}
    return response.json()


def _state_mapping(state: dict[str, Any], key: str) -> dict[str, str]:
    value = state.get(key)
    return dict(value) if isinstance(value, dict) else {}


def _ads_response_id(data: dict[str, Any]) -> str:
    for key in ("id", "campaign_id", "ad_group_id", "ad_id", "file_id"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    nested = data.get("data")
    if isinstance(nested, dict):
        return _ads_response_id(nested)
    return ""


def _ads_api_error_detail(exc: httpx.HTTPStatusError) -> str:
    response = exc.response
    detail = response.text[:1000] if response is not None else str(exc)
    status = response.status_code if response is not None else "?"
    return f"OpenAI Ads API draft 실행 실패: HTTP {status} · {detail}"


def _ads_dashboard_cached_payload(cache_row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(cache_row.get("payload") or {})
    refreshed_at = str(cache_row.get("refreshed_at") or "")
    advertiser_count = int(payload.get("advertiser_count") or payload.get("live_status_total_advertisers") or 0)
    advertiser_label = f"전체 활성 광고주({advertiser_count}개)" if advertiser_count else "전체 활성 광고주"
    refreshed_label = _date_label(refreshed_at)
    cache_note = "전체 활성 광고주 지표는 백그라운드 캐시 기준입니다. 개별 광고주 실시간 조회와 수치가 조금 다를 수 있습니다."
    if refreshed_label:
        cache_note = f"{advertiser_label} 지표는 {refreshed_label} 캐시 기준입니다. 개별 광고주 실시간 조회와 수치가 조금 다를 수 있습니다."
    payload.update(
        {
            "cache_status": "hit",
            "cache_source": "background",
            "cache_refreshed_at": refreshed_at,
            "cache_note": cache_note,
            "key_source": "advertiser_collection",
            "advertiser_name": "전체 활성 광고주",
            "advertiser_label": advertiser_label,
        }
    )
    payload["warning"] = _join_unique_messages(cache_note, str(payload.get("warning") or ""))
    return payload


def _validation_error_details(exc: ValidationError) -> list[dict[str, Any]]:
    return exc.errors(include_url=False, include_input=False, include_context=False)


async def _validated_admin_payload(request: Request, model: type[BaseModel], invalid_message: str) -> Any:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=invalid_message) from exc
    try:
        return model.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_validation_error_details(exc)) from exc


def _production_guide_decks() -> dict[str, str]:
    root = project_root()
    source_candidates = [
        root / "backups" / "production_pages_20260621_pre_dev_cutover" / "index.html",
        root / "public" / "index.html",
        root / "templates" / "index.html",
    ]
    missing_panels: list[str] = []
    for source in source_candidates:
        if not source.exists():
            continue
        soup = BeautifulSoup(source.read_text(encoding="utf-8"), "html.parser")
        decks: dict[str, str] = {}
        missing_panels = []
        for deck_key, panel_id in GUIDE_DECK_PANELS.items():
            deck = soup.select_one(f"#{panel_id} .slide-deck")
            if deck is None:
                missing_panels.append(panel_id)
                break
            decks[deck_key] = deck.decode_contents()
        if not missing_panels:
            return decks
    missing = ", ".join(missing_panels or GUIDE_DECK_PANELS.values())
    raise HTTPException(status_code=500, detail=f"{missing} 안내자료 슬라이드를 찾을 수 없습니다.")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _index_file() -> FileResponse:
    return FileResponse(project_root() / "templates" / "index.html")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return _index_file()


@app.get("/checker", include_in_schema=False)
def checker_page() -> FileResponse:
    return _index_file()


@app.get("/rag", include_in_schema=False)
def rag_page() -> FileResponse:
    return _index_file()


@app.get("/intake", include_in_schema=False)
def intake_page() -> FileResponse:
    return _index_file()


@app.get("/creative-upload-draft", include_in_schema=False)
def creative_upload_draft_page() -> FileResponse:
    return FileResponse(project_root() / "templates" / "creative_upload_draft.html")


@app.get("/ads-api-draft", include_in_schema=False)
def ads_api_draft_page() -> FileResponse:
    raise HTTPException(status_code=404, detail="공개 접근이 제한된 검토 페이지입니다.")


@app.get("/slides", include_in_schema=False)
def slides_page() -> FileResponse:
    return _index_file()


@app.get("/admin", include_in_schema=False)
def admin_page() -> FileResponse:
    return FileResponse(project_root() / "dev" / "admin.html")


@app.get("/dev", include_in_schema=False)
def dev_index_page() -> FileResponse:
    return FileResponse(project_root() / "dev" / "index.html")


@app.get("/dev/admin", include_in_schema=False)
def dev_admin_page() -> FileResponse:
    return FileResponse(project_root() / "dev" / "admin.html")


@app.get("/dev/creative-upload-draft", include_in_schema=False)
def dev_creative_upload_draft_page() -> FileResponse:
    return FileResponse(project_root() / "dev" / "creative_upload_draft.html")


@app.get("/api/notice", include_in_schema=False)
def public_notice() -> dict[str, Any]:
    from admin_store import get_notice_config

    return get_notice_config()


@app.get("/api/menu-settings", include_in_schema=False)
def public_menu_settings() -> dict[str, Any]:
    from admin_store import get_menu_settings

    return get_menu_settings()


@app.post("/api/analytics/visit", include_in_schema=False)
def analytics_visit(request: VisitRequest) -> dict[str, Any]:
    from admin_store import record_page_visit

    raw_page = (request.page or "root").strip()
    page = raw_page[:80] or "root"
    label = (request.label or "").strip()[:120] or PAGE_LABELS.get(page, page)
    return record_page_visit(page, label)


@app.get("/api/faqs", include_in_schema=False)
def public_operating_faqs() -> dict[str, Any]:
    from admin_store import list_static_operating_faqs

    return list_static_operating_faqs()


@app.post("/api/admin/faqs/refresh", include_in_schema=False)
def admin_refresh_operating_faqs(request: Request) -> dict[str, Any]:
    _require_admin(request)
    return {
        "ok": True,
        "disabled": True,
        "message": "FAQ 자동 업데이트는 비활성화되어 있습니다. FAQ 관리 메뉴에서 저장한 항목만 사용자 화면에 노출됩니다.",
    }


@app.get("/api/admin/faqs", include_in_schema=False)
def admin_operating_faqs(request: Request) -> dict[str, Any]:
    from admin_store import list_admin_operating_faqs

    _require_admin(request)
    include_deleted = str(request.query_params.get("include_deleted") or "1").lower() in {"1", "true", "yes"}
    return list_admin_operating_faqs(include_deleted=include_deleted)


@app.post("/api/admin/faqs/categories", include_in_schema=False)
def admin_create_faq_category(request: Request, item: FaqCategoryRequest) -> dict[str, Any]:
    from admin_store import upsert_operating_faq_category

    _require_admin(request)
    try:
        return upsert_operating_faq_category(item.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/faqs/categories/{category_id}/update", include_in_schema=False)
def admin_update_faq_category(request: Request, category_id: str, item: FaqCategoryRequest) -> dict[str, Any]:
    from admin_store import upsert_operating_faq_category

    _require_admin(request)
    try:
        return upsert_operating_faq_category(item.model_dump(), category_id=category_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/faqs/categories/{category_id}/delete", include_in_schema=False)
def admin_delete_faq_category(request: Request, category_id: str) -> dict[str, Any]:
    from admin_store import delete_operating_faq_category

    _require_admin(request)
    try:
        return delete_operating_faq_category(category_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/faqs/items", include_in_schema=False)
def admin_create_faq_item(request: Request, item: FaqItemRequest) -> dict[str, Any]:
    from admin_store import upsert_operating_faq_item

    _require_admin(request)
    try:
        return upsert_operating_faq_item(item.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/faqs/items/{item_id}/update", include_in_schema=False)
def admin_update_faq_item(request: Request, item_id: str, item: FaqItemRequest) -> dict[str, Any]:
    from admin_store import upsert_operating_faq_item

    _require_admin(request)
    try:
        return upsert_operating_faq_item(item.model_dump(), item_id=item_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/faqs/items/{item_id}/delete", include_in_schema=False)
def admin_delete_faq_item(request: Request, item_id: str) -> dict[str, Any]:
    from admin_store import delete_operating_faq_item

    _require_admin(request)
    try:
        return delete_operating_faq_item(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/cron/faqs", include_in_schema=False)
def cron_refresh_operating_faqs(request: Request) -> dict[str, Any]:
    _require_cron(request)
    return {
        "ok": True,
        "disabled": True,
        "message": "FAQ automatic refresh is disabled.",
    }


@app.get("/api/cron/ads-dashboard-cache", include_in_schema=False)
async def cron_refresh_ads_dashboard_cache(request: Request) -> dict[str, Any]:
    _require_cron(request)
    from admin_store import (
        get_ads_campaign_objective_override_map,
        list_active_ads_api_key_credentials,
        save_ads_dashboard_cache,
    )
    from rag_chatbot.ads_api import apply_campaign_objective_overrides, fetch_ads_dashboard_for_advertisers

    credentials = list_active_ads_api_key_credentials()
    if not credentials:
        payload = {
            "ok": False,
            "configured": False,
            "advertiser_name": "전체 활성 광고주",
            "key_source": "advertiser_collection",
            "error": "활성화된 광고주 Ads API 키가 없습니다.",
        }
    else:
        payload = await fetch_ads_dashboard_for_advertisers(
            credentials,
            include_aggregate_extensions=True,
        )
    payload = apply_campaign_objective_overrides(payload, get_ads_campaign_objective_override_map())
    saved = save_ads_dashboard_cache(payload, ADS_DASHBOARD_CACHE_KEY)
    return {
        "ok": True,
        "refreshed": True,
        "cache_key": ADS_DASHBOARD_CACHE_KEY,
        "refreshed_at": saved.get("refreshed_at", ""),
        "active_advertiser_count": len(credentials),
        "payload_ok": bool(payload.get("ok")),
        "campaign_count": len(payload.get("campaigns") or []),
        "trend_count": len(payload.get("trend") or []),
        "device_count": len(payload.get("device_breakdown") or []),
        "storage": saved.get("storage", ""),
    }


@app.get("/api/admin/notice", include_in_schema=False)
def admin_notice(request: Request) -> dict[str, Any]:
    from admin_store import get_notice_config

    _require_admin(request)
    return get_notice_config()


@app.post("/api/admin/notice", include_in_schema=False)
def update_admin_notice(request: Request, notice: NoticeConfigRequest) -> dict[str, Any]:
    from admin_store import save_notice_config

    _require_admin(request)
    return save_notice_config(notice.model_dump())


@app.get("/api/admin/menu-settings", include_in_schema=False)
def admin_menu_settings(request: Request) -> dict[str, Any]:
    from admin_store import get_menu_settings

    _require_admin(request)
    return get_menu_settings()


@app.post("/api/admin/menu-settings", include_in_schema=False)
def update_admin_menu_settings(request: Request, settings: MenuSettingsRequest) -> dict[str, Any]:
    from admin_store import save_menu_settings

    _require_admin(request)
    return save_menu_settings(settings.model_dump())


@app.get("/api/guide-slides", include_in_schema=False)
def public_guide_slides() -> dict[str, Any]:
    from admin_store import get_slide_content

    return get_slide_content()


@app.get("/api/guide-deck-html", include_in_schema=False)
def public_guide_deck_html() -> dict[str, Any]:
    return {"decks": _production_guide_decks()}


@app.get("/api/admin/guide-slides", include_in_schema=False)
def admin_guide_slides(request: Request) -> dict[str, Any]:
    from admin_store import get_slide_content

    _require_admin(request)
    return get_slide_content()


@app.post("/api/admin/guide-slides", include_in_schema=False)
def update_admin_guide_slides(request: Request, slides: SlideContentRequest) -> dict[str, Any]:
    from admin_store import save_slide_content

    _require_admin(request)
    return save_slide_content(slides.model_dump())


@app.post("/api/admin/guide-image", response_model=ImageUploadResponse, include_in_schema=False)
async def upload_admin_guide_image(request: Request, file: UploadFile = File(...)) -> ImageUploadResponse:
    _require_admin(request)

    supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "openai-ad-assets").strip()
    if not supabase_url or not service_role_key:
        raise HTTPException(
            status_code=503,
            detail="이미지 업로드 저장소가 아직 설정되지 않았습니다. 공개 직접 이미지 URL을 입력해 주세요.",
        )

    suffix_by_type = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }
    content_type = file.content_type or ""
    suffix = suffix_by_type.get(content_type)
    if not suffix:
        raise HTTPException(status_code=400, detail="PNG, JPG, WEBP 이미지만 업로드할 수 있습니다.")

    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="안내자료 이미지는 8MB 이하만 업로드할 수 있습니다.")

    try:
        from PIL import Image

        image = Image.open(BytesIO(data))
        width, height = image.size
    except Exception as exc:
        raise HTTPException(status_code=400, detail="이미지 파일을 열 수 없습니다.") from exc
    if width < 240 or height < 160 or width > 4096 or height > 4096:
        raise HTTPException(status_code=400, detail="안내자료 이미지는 240×160 이상, 4096×4096 이하만 업로드할 수 있습니다.")

    safe_stem = re.sub(r"[^0-9A-Za-z._-]+", "-", Path(file.filename or "guide-image").stem).strip("-")
    object_name = f"guide-slides/{uuid4().hex}-{safe_stem or 'guide-image'}{suffix}"
    upload_url = f"{supabase_url}/storage/v1/object/{bucket}/{object_name}"
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": content_type,
        "x-upsert": "false",
    }
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.post(upload_url, content=data, headers=headers)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Supabase Storage 업로드 실패(HTTP {response.status_code})")

    public_url = f"{supabase_url}/storage/v1/object/public/{bucket}/{object_name}"
    return ImageUploadResponse(
        image_url=public_url,
        width=width,
        height=height,
        content_type=content_type,
    )


@app.get("/api/admin/analytics", include_in_schema=False)
def admin_analytics(request: Request) -> dict[str, Any]:
    from admin_store import get_visit_analytics

    _require_admin(request)
    return get_visit_analytics(request.query_params.get("period", "30"))


@app.get("/api/admin/ads-api-keys", include_in_schema=False)
def admin_ads_api_keys(request: Request) -> dict[str, Any]:
    from admin_store import list_ads_api_keys

    _require_admin(request)
    return list_ads_api_keys()


@app.post("/api/admin/ads-api-keys", include_in_schema=False)
def admin_save_ads_api_key(request: Request, payload: AdsApiKeyRequest) -> dict[str, Any]:
    from admin_store import upsert_ads_api_key

    _require_admin(request)
    try:
        return upsert_ads_api_key(payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/ads-api-keys/inspect", include_in_schema=False)
async def admin_inspect_ads_api_key(request: Request, payload: AdsApiKeyInspectRequest) -> dict[str, Any]:
    from rag_chatbot.ads_api import fetch_ad_account_metadata

    _require_admin(request)
    try:
        return await fetch_ad_account_metadata(payload.ads_api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/admin/ads-campaign-objectives", include_in_schema=False)
def admin_ads_campaign_objectives(request: Request) -> dict[str, Any]:
    from admin_store import list_ads_campaign_objective_overrides

    _require_admin(request)
    return list_ads_campaign_objective_overrides()


@app.post("/api/admin/ads-campaign-objectives", include_in_schema=False)
def admin_save_ads_campaign_objective(
    request: Request,
    payload: AdsCampaignObjectiveRequest,
) -> dict[str, Any]:
    from admin_store import upsert_ads_campaign_objective_override

    _require_admin(request)
    try:
        return upsert_ads_campaign_objective_override(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/adcopy/generate", include_in_schema=False)
async def admin_generate_adcopy(request: Request) -> dict[str, Any]:
    _require_admin(request)
    payload = await _validated_admin_payload(request, AdsAdcopyGenerateRequest, "생성할 카피 브리프 본문이 올바르지 않습니다.")
    generated_payload = await _call_openai_adcopy(payload)
    generated = _normalize_generated_adcopy(generated_payload.get("generated") or {}, payload)
    validation_report = _validate_generated_adcopy(generated)
    return {
        "ok": validation_report["ok"],
        "model": generated_payload.get("model"),
        "response_id": generated_payload.get("raw_response_id"),
        "generated": generated,
        "validation_report": validation_report,
        "summary": validation_report["summary"],
        "notice": "초안 생성 결과입니다. 업로드 또는 캠페인 세팅 전 운영자 검수와 광고주 확인이 필요합니다.",
    }


@app.post("/api/admin/adcopy/validate", include_in_schema=False)
async def admin_validate_adcopy(request: Request) -> dict[str, Any]:
    _require_admin(request)
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="검수할 generated.json 본문이 올바르지 않습니다.") from exc
    generated = body.get("generated") if isinstance(body, dict) and isinstance(body.get("generated"), dict) else body
    if not isinstance(generated, dict):
        raise HTTPException(status_code=400, detail="generated 객체를 전달해 주세요.")
    validation_report = _validate_generated_adcopy(generated)
    return {
        "ok": validation_report["ok"],
        "generated": generated,
        "validation_report": validation_report,
        "summary": validation_report["summary"],
        "notice": "수정된 generated.json을 다시 검수했습니다. 업로드 전 운영자 최종 확인이 필요합니다.",
    }


@app.post("/api/admin/adcopy/inspect-landing", include_in_schema=False)
async def admin_inspect_adcopy_landing(request: Request) -> dict[str, Any]:
    _require_admin(request)
    payload = await _validated_admin_payload(request, AdsAdcopyLandingInspectRequest, "읽을 랜딩 URL 본문이 올바르지 않습니다.")
    html, final_url = await _fetch_landing_html(payload.landing_url)
    metadata = _inspect_landing_html(html, final_url)
    return {
        "ok": True,
        "source_url": payload.landing_url,
        "final_url": final_url,
        "metadata": metadata,
        "notice": "랜딩 페이지의 공개 메타 정보를 읽었습니다. 자동 입력 전 운영자가 내용을 확인해야 합니다.",
    }


@app.post("/api/admin/adcopy/draft-plan", include_in_schema=False)
async def admin_adcopy_draft_plan(request: Request) -> dict[str, Any]:
    _require_admin(request)
    payload = await _validated_admin_payload(request, AdsAdcopyDraftPlanRequest, "draft 세팅 본문이 올바르지 않습니다.")
    return _build_adcopy_draft_plan(payload)


@app.post("/api/admin/adcopy/draft-execute", include_in_schema=False)
async def admin_adcopy_draft_execute(request: Request) -> dict[str, Any]:
    from admin_store import get_ads_api_key_credential
    from rag_chatbot.ads_api import fetch_ad_account_metadata

    _require_admin(request)
    payload = await _validated_admin_payload(request, AdsAdcopyDraftExecuteRequest, "draft 실행 본문이 올바르지 않습니다.")
    action = payload.action.strip()
    state = dict(payload.state or {})
    credential = get_ads_api_key_credential(payload.advertiser_name)
    api_key = credential.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail=f"{payload.advertiser_name}의 활성 Ads API 키가 필요합니다.")
    plan = _build_adcopy_draft_plan(payload)

    if action == "verify_account":
        account = await fetch_ad_account_metadata(api_key)
        state["account_verified_at"] = datetime.now(KST).isoformat()
        return {"ok": True, "action": action, "plan": plan, "state": state, "account": account}

    if action not in {"create_campaign", "upload_assets", "create_ad_groups", "create_ads", "activate_all"}:
        raise HTTPException(status_code=400, detail="지원하지 않는 draft 실행 단계입니다.")
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="실행 확인이 필요합니다. 각 단계는 운영자 확인 후에만 진행됩니다.")

    logs: list[dict[str, Any]] = []
    try:
        if action == "create_campaign":
            if state.get("campaign_id"):
                logs.append({"level": "info", "message": "이미 생성된 캠페인 ID를 사용합니다.", "id": state.get("campaign_id")})
            else:
                data = await _ads_draft_api_request(api_key, "POST", "/v1/campaigns", plan["campaign"]["api_payload"])
                campaign_id = _ads_response_id(data)
                if not campaign_id:
                    raise HTTPException(status_code=502, detail="캠페인 생성 응답에서 campaign id를 찾지 못했습니다.")
                state["campaign_id"] = campaign_id
                logs.append({"level": "success", "message": "paused 캠페인 draft를 생성했습니다.", "id": campaign_id})

        elif action == "upload_assets":
            file_ids = _state_mapping(state, "file_ids")
            for asset in plan["assets"]:
                image_url = asset["image_url"]
                if file_ids.get(image_url):
                    logs.append({"level": "info", "message": "이미 업로드된 이미지를 재사용합니다.", "url": image_url, "id": file_ids[image_url]})
                    continue
                data = await _ads_draft_api_request(api_key, "POST", "/v1/upload", {"image_url": image_url})
                file_id = str(data.get("file_id") or _ads_response_id(data)).strip()
                if not file_id:
                    raise HTTPException(status_code=502, detail=f"이미지 업로드 응답에서 file_id를 찾지 못했습니다: {image_url}")
                file_ids[image_url] = file_id
                logs.append({"level": "success", "message": "소재 이미지를 업로드했습니다.", "url": image_url, "id": file_id})
            state["file_ids"] = file_ids

        elif action == "create_ad_groups":
            campaign_id = str(state.get("campaign_id") or "").strip()
            if not campaign_id:
                raise HTTPException(status_code=400, detail="광고그룹 생성 전 캠페인 draft를 먼저 생성해야 합니다.")
            ad_group_ids = _state_mapping(state, "ad_group_ids")
            for group in plan["ad_groups"]:
                name = group["name"]
                if ad_group_ids.get(name):
                    logs.append({"level": "info", "message": "이미 생성된 광고그룹을 재사용합니다.", "name": name, "id": ad_group_ids[name]})
                    continue
                api_payload = dict(group["api_payload"])
                if _safe_float(api_payload.get("bidding_config", {}).get("max_bid_micros")) <= 0:
                    raise HTTPException(status_code=400, detail="광고그룹 생성 전 기본 CPM 입찰가를 0보다 크게 입력해 주세요.")
                api_payload["campaign_id"] = campaign_id
                data = await _ads_draft_api_request(api_key, "POST", "/v1/ad_groups", api_payload)
                ad_group_id = _ads_response_id(data)
                if not ad_group_id:
                    raise HTTPException(status_code=502, detail=f"광고그룹 생성 응답에서 ad group id를 찾지 못했습니다: {name}")
                ad_group_ids[name] = ad_group_id
                logs.append({"level": "success", "message": "paused 광고그룹 draft를 생성했습니다.", "name": name, "id": ad_group_id})
            state["ad_group_ids"] = ad_group_ids

        elif action == "create_ads":
            ad_group_ids = _state_mapping(state, "ad_group_ids")
            file_ids = _state_mapping(state, "file_ids")
            if not ad_group_ids:
                raise HTTPException(status_code=400, detail="소재 생성 전 광고그룹 draft를 먼저 생성해야 합니다.")
            ad_ids = _state_mapping(state, "ad_ids")
            for ad in plan["ads"]:
                ad_name = ad["name"]
                ad_key = ad.get("key") or ad_name
                if ad_ids.get(ad_key):
                    logs.append({"level": "info", "message": "이미 생성된 소재를 재사용합니다.", "name": ad_name, "id": ad_ids[ad_key]})
                    continue
                ad_group_id = ad_group_ids.get(ad["adgroup_name"])
                file_id = file_ids.get(ad["image_url"])
                if not ad_group_id:
                    raise HTTPException(status_code=400, detail=f"{ad['adgroup_name']} 광고그룹 ID가 없습니다. 광고그룹 생성 단계를 먼저 완료해 주세요.")
                if not file_id:
                    raise HTTPException(status_code=400, detail=f"{ad_name} 소재 이미지 file_id가 없습니다. 이미지 업로드 단계를 먼저 완료해 주세요.")
                api_payload = json.loads(json.dumps(ad["api_payload"]))
                api_payload["ad_group_id"] = ad_group_id
                api_payload["creative"]["file_id"] = file_id
                data = await _ads_draft_api_request(api_key, "POST", "/v1/ads", api_payload)
                ad_id = _ads_response_id(data)
                if not ad_id:
                    raise HTTPException(status_code=502, detail=f"소재 생성 응답에서 ad id를 찾지 못했습니다: {ad_name}")
                ad_ids[ad_key] = ad_id
                logs.append({"level": "success", "message": "paused 소재 draft를 생성했습니다.", "name": ad_name, "id": ad_id})
            state["ad_ids"] = ad_ids

        elif action == "activate_all":
            campaign_id = str(state.get("campaign_id") or "").strip()
            ad_group_ids = _state_mapping(state, "ad_group_ids")
            ad_ids = _state_mapping(state, "ad_ids")
            if not campaign_id or not ad_group_ids or not ad_ids:
                raise HTTPException(status_code=400, detail="활성화 전 캠페인, 광고그룹, 소재 draft 생성이 모두 완료되어야 합니다.")
            for name, ad_id in ad_ids.items():
                await _ads_draft_api_request(api_key, "POST", f"/v1/ads/{ad_id}/activate", {})
                logs.append({"level": "success", "message": "소재를 활성화했습니다.", "name": name.rsplit("::", 1)[-1], "id": ad_id})
            for name, ad_group_id in ad_group_ids.items():
                await _ads_draft_api_request(api_key, "POST", f"/v1/ad_groups/{ad_group_id}/activate", {})
                logs.append({"level": "success", "message": "광고그룹을 활성화했습니다.", "name": name, "id": ad_group_id})
            await _ads_draft_api_request(api_key, "POST", f"/v1/campaigns/{campaign_id}/activate", {})
            logs.append({"level": "success", "message": "캠페인을 활성화했습니다.", "id": campaign_id})
            state["activated_at"] = datetime.now(KST).isoformat()

    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=_ads_api_error_detail(exc)) from exc

    state["last_action"] = action
    state["updated_at"] = datetime.now(KST).isoformat()
    return {"ok": True, "action": action, "plan": plan, "state": state, "logs": logs}


@app.get("/api/admin/ads-api-keys/{advertiser_name}/reveal", include_in_schema=False)
def admin_reveal_ads_api_key(advertiser_name: str, request: Request) -> dict[str, Any]:
    from admin_store import get_ads_api_key_secrets

    _require_admin(request)
    try:
        return get_ads_api_key_secrets(advertiser_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/admin/ads-api-keys/{advertiser_name}", include_in_schema=False)
def admin_delete_ads_api_key(advertiser_name: str, request: Request) -> dict[str, Any]:
    from admin_store import delete_ads_api_key

    _require_admin(request)
    try:
        return delete_ads_api_key(advertiser_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/admin/ads-dashboard", include_in_schema=False)
async def admin_ads_dashboard(request: Request) -> dict[str, Any]:
    from admin_store import get_ads_campaign_objective_override_map
    from rag_chatbot.ads_api import (
        apply_campaign_objective_overrides,
        fetch_ads_dashboard,
        fetch_ads_dashboard_for_advertisers,
    )

    _require_admin(request)
    start_date = str(request.query_params.get("start_date") or "") or None
    end_date = str(request.query_params.get("end_date") or "") or None
    detail_scope = str(request.query_params.get("detail_scope") or "") or None
    detail_id = str(request.query_params.get("detail_id") or "") or None
    advertiser_name = str(request.query_params.get("advertiser_name") or "").strip()
    detail_advertiser_name = str(request.query_params.get("detail_advertiser_name") or "").strip()
    api_key = None
    advertiser_industry = ""
    if advertiser_name:
        from admin_store import get_ads_api_key_credential

        credential = get_ads_api_key_credential(advertiser_name)
        api_key = credential.get("api_key", "")
        advertiser_industry = credential.get("industry", "")
        if not api_key:
            return {
                "ok": False,
                "configured": False,
                "advertiser_name": advertiser_name,
                "error": f"{advertiser_name} Ads API 키가 등록되어 있지 않거나 비활성 상태입니다.",
            }
    else:
        from admin_store import get_ads_dashboard_cache, list_active_ads_api_key_credentials, save_ads_dashboard_cache

        credentials = list_active_ads_api_key_credentials()
        if credentials:
            if not detail_scope and not detail_id:
                cache_key = _ads_dashboard_range_cache_key(start_date, end_date)
                cache_row = get_ads_dashboard_cache(cache_key)
                if cache_row and not _ads_dashboard_payload_matches_range(
                    dict(cache_row.get("payload") or {}),
                    start_date,
                    end_date,
                ):
                    cache_row = None
                if not cache_row and cache_key != ADS_DASHBOARD_CACHE_KEY:
                    legacy_cache_row = get_ads_dashboard_cache(ADS_DASHBOARD_CACHE_KEY)
                    if legacy_cache_row and _ads_dashboard_payload_matches_range(
                        dict(legacy_cache_row.get("payload") or {}),
                        start_date,
                        end_date,
                    ):
                        cache_row = legacy_cache_row
                if cache_row and cache_row.get("payload"):
                    return apply_campaign_objective_overrides(
                        _ads_dashboard_cached_payload(cache_row),
                        get_ads_campaign_objective_override_map(),
                    )
            data = await fetch_ads_dashboard_for_advertisers(
                credentials,
                start_date=start_date,
                end_date=end_date,
                detail_scope=detail_scope,
                detail_id=detail_id,
                detail_advertiser_name=detail_advertiser_name,
                include_aggregate_extensions=not (detail_scope or detail_id),
            )
            if not detail_scope and not detail_id:
                if data.get("ok"):
                    cache_key = _ads_dashboard_range_cache_key(
                        str(data.get("range", {}).get("start_date") or start_date or ""),
                        str(data.get("range", {}).get("end_date") or end_date or ""),
                    )
                    saved = save_ads_dashboard_cache(data, cache_key)
                    advertiser_count = int(data.get("advertiser_count") or len(credentials))
                    advertiser_label = f"전체 활성 광고주({advertiser_count}개)"
                    range_payload = data.get("range") if isinstance(data.get("range"), dict) else {}
                    range_label = f"{range_payload.get('start_date') or start_date or ''} ~ {range_payload.get('end_date') or end_date or ''}".strip()
                    cache_note = f"{advertiser_label} 지표는 {range_label} 선택 기간 기준으로 새로 계산했습니다. 다음 조회부터 같은 기간은 캐시를 사용합니다."
                    data["cache_status"] = "refreshed"
                    data["cache_source"] = "request"
                    data["cache_refreshed_at"] = saved.get("refreshed_at", "")
                    data["cache_note"] = cache_note
                    data["advertiser_label"] = advertiser_label
                    data["warning"] = _join_unique_messages(cache_note, str(data.get("warning") or ""))
                else:
                    data["cache_status"] = "miss"
                    data["cache_note"] = "전체 활성 광고주 캐시가 아직 준비되지 않아 기본 성과만 실시간 조회했습니다. 백그라운드 캐시 갱신 후 디바이스/추이 차트가 표시됩니다."
                    data["warning"] = _join_unique_messages(data["cache_note"], str(data.get("warning") or ""))
            return apply_campaign_objective_overrides(data, get_ads_campaign_objective_override_map())
    data = await fetch_ads_dashboard(
        start_date=start_date,
        end_date=end_date,
        detail_scope=detail_scope,
        detail_id=detail_id,
        api_key=api_key,
        advertiser_name=advertiser_name,
        advertiser_industry=advertiser_industry,
    )
    return apply_campaign_objective_overrides(data, get_ads_campaign_objective_override_map())


@app.get("/api/admin/ads-dashboard/hourly", include_in_schema=False)
async def admin_ads_dashboard_hourly(request: Request) -> dict[str, Any]:
    from admin_store import get_ads_api_key_credential
    from rag_chatbot.ads_api import fetch_resource_hourly_insights

    _require_admin(request)
    advertiser_name = str(request.query_params.get("advertiser_name") or "").strip()
    resource_scope = str(request.query_params.get("resource_scope") or "campaign").strip()
    resource_id = str(request.query_params.get("resource_id") or "").strip()
    resource_name = str(request.query_params.get("resource_name") or "").strip()
    campaign_id = str(request.query_params.get("campaign_id") or "").strip()
    campaign_name = str(request.query_params.get("campaign_name") or "").strip()
    if not resource_id and campaign_id:
        resource_scope = "campaign"
        resource_id = campaign_id
        resource_name = resource_name or campaign_name
    since_hour = str(request.query_params.get("since") or "").strip()
    until_hour = str(request.query_params.get("until") or "").strip()
    if not advertiser_name:
        raise HTTPException(status_code=400, detail="광고주명이 필요합니다.")
    credential = get_ads_api_key_credential(advertiser_name)
    api_key = credential.get("api_key", "")
    if not api_key:
        return {
            "ok": False,
            "configured": False,
            "advertiser_name": advertiser_name,
            "campaign_id": campaign_id,
            "resource_scope": resource_scope,
            "resource_id": resource_id,
            "error": f"{advertiser_name} Ads API 키가 등록되어 있지 않거나 비활성 상태입니다.",
        }
    try:
        return await fetch_resource_hourly_insights(
            advertiser_name=advertiser_name,
            resource_scope=resource_scope,
            resource_id=resource_id,
            resource_name=resource_name,
            since_hour=since_hour,
            until_hour=until_hour,
            api_key=api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/admin/official-changes", include_in_schema=False)
def admin_official_changes(request: Request) -> dict[str, Any]:
    from admin_store import list_official_guide_changes

    _require_admin(request)
    try:
        limit = int(str(request.query_params.get("limit") or "15"))
    except ValueError:
        limit = 15
    try:
        page = int(str(request.query_params.get("page") or "1"))
    except ValueError:
        page = 1
    return list_official_guide_changes(
        limit=limit,
        page=page,
        start_date=str(request.query_params.get("start_date") or ""),
        end_date=str(request.query_params.get("end_date") or ""),
    )


@app.get("/api/admin/mail-review", include_in_schema=False)
def admin_mail_review(request: Request) -> dict[str, Any]:
    from admin_store import list_mail_review_rows

    _require_admin(request)
    status_filter = str(request.query_params.get("status") or "")
    try:
        limit = int(str(request.query_params.get("limit") or "10"))
    except ValueError:
        limit = 10
    try:
        page = int(str(request.query_params.get("page") or "1"))
    except ValueError:
        page = 1
    return list_mail_review_rows(status_filter=status_filter, limit=limit, page=page)


@app.post("/api/admin/mail-review/update", include_in_schema=False)
def admin_update_mail_review(request: Request, update: MailReviewUpdateRequest) -> dict[str, Any]:
    from admin_store import update_mail_review_row

    _require_admin(request)
    try:
        return update_mail_review_row(update.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/admin/manual-rag", include_in_schema=False)
def admin_manual_rag_items(request: Request) -> dict[str, Any]:
    from admin_store import list_manual_rag_items

    _require_admin(request)
    include_deleted = str(request.query_params.get("include_deleted") or "").lower() in {"1", "true", "yes"}
    try:
        limit = int(str(request.query_params.get("limit") or "200"))
    except ValueError:
        limit = 200
    return list_manual_rag_items(include_deleted=include_deleted, limit=limit)


@app.post("/api/admin/manual-rag", include_in_schema=False)
def admin_create_manual_rag(request: Request, item: ManualRagItemRequest) -> dict[str, Any]:
    from admin_store import create_manual_rag_item

    _require_admin(request)
    try:
        return create_manual_rag_item(item.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/manual-rag/{item_id}/update", include_in_schema=False)
def admin_update_manual_rag(request: Request, item_id: str, item: ManualRagItemRequest) -> dict[str, Any]:
    from admin_store import update_manual_rag_item

    _require_admin(request)
    try:
        return update_manual_rag_item(item_id, item.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/manual-rag/{item_id}/delete", include_in_schema=False)
def admin_delete_manual_rag(request: Request, item_id: str) -> dict[str, Any]:
    from admin_store import delete_manual_rag_item

    _require_admin(request)
    try:
        return delete_manual_rag_item(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/admin/campaign-intakes", include_in_schema=False)
def admin_campaign_intakes(request: Request) -> dict[str, Any]:
    from admin_store import list_campaign_intake_items

    _require_admin(request)
    return list_campaign_intake_items()


@app.post("/api/admin/campaign-intakes/update", include_in_schema=False)
def admin_update_campaign_intake(
    request: Request,
    update: CampaignIntakeOpsRequest,
) -> dict[str, Any]:
    from admin_store import update_campaign_intake_ops

    _require_admin(request)
    try:
        return update_campaign_intake_ops(update.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    try:
        from rag_chatbot.qa import answer_question

        result = answer_question(request.question)
        try:
            from admin_store import record_chat_question

            record_chat_question(request.question, result.get("answer", ""), result.get("sources", []))
        except Exception:
            pass
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ChatResponse(**result)


@app.post("/check", response_model=list[CheckResultResponse])
async def check(request: CheckRequest) -> list[CheckResultResponse]:
    try:
        from checker import check_urls

        results = await check_urls(request.urls)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return [CheckResultResponse(**result.to_dict()) for result in results]


@app.post("/check-favicon", response_model=list[FaviconCheckResultResponse])
async def check_favicon(
    request: FaviconCheckRequest,
) -> list[FaviconCheckResultResponse]:
    try:
        from favicon_checker import check_favicon_urls

        results = await check_favicon_urls(request.urls)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return [FaviconCheckResultResponse(**result.to_dict()) for result in results]


@app.post("/intake", response_model=IntakeResponse)
async def intake(request: Request) -> IntakeResponse:
    try:
        from intake import IntakeSubmission, forward_intake_to_sheet

        payload = await request.json()
        submission = IntakeSubmission.model_validate(payload)
        client_key = request.client.host if request.client else "unknown"
        result = await forward_intake_to_sheet(submission, client_key=client_key)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=_validation_error_details(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return IntakeResponse(**result)


@app.post("/intake/workbook", include_in_schema=False)
async def intake_workbook(request: Request) -> StreamingResponse:
    try:
        from intake import IntakeSubmission, create_workbook_bytes

        payload = await request.json()
        submission = IntakeSubmission.model_validate(payload)
        workbook_bytes = create_workbook_bytes(submission)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=_validation_error_details(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    filename = "openai_ads_bulk_upload.xlsx"
    return StreamingResponse(
        BytesIO(workbook_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/intake/inspect-workbook", response_model=WorkbookInspectResponse, include_in_schema=False)
async def inspect_intake_workbook(file: UploadFile = File(...)) -> WorkbookInspectResponse:
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="xlsx 파일만 업로드할 수 있습니다.")
    try:
        from intake import inspect_workbook_bytes

        content = await file.read()
        if len(content) > 8 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="파일은 8MB 이하만 업로드할 수 있습니다.")
        result = inspect_workbook_bytes(content)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"워크북을 읽을 수 없습니다: {exc}") from exc
    return WorkbookInspectResponse(**result)


@app.post("/intake/upload-image", response_model=ImageUploadResponse, include_in_schema=False)
async def upload_intake_image(file: UploadFile = File(...)) -> ImageUploadResponse:
    supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "openai-ad-assets").strip()
    if not supabase_url or not service_role_key:
        raise HTTPException(
            status_code=503,
            detail="이미지 업로드 저장소가 아직 설정되지 않았습니다. 공개 직접 이미지 URL을 입력해 주세요.",
        )

    content_type = file.content_type or ""
    if content_type not in {"image/png", "image/jpeg"}:
        raise HTTPException(status_code=400, detail="PNG 또는 JPG 이미지만 첨부할 수 있습니다.")
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="이미지 파일은 5MB 이하만 첨부할 수 있습니다.")

    try:
        from PIL import Image

        image = Image.open(BytesIO(data))
        width, height = image.size
    except Exception as exc:
        raise HTTPException(status_code=400, detail="이미지 파일을 열 수 없습니다.") from exc
    if width != height:
        raise HTTPException(status_code=400, detail="이미지는 정사각형이어야 합니다.")
    if width < 640 or height < 640 or width > 1200 or height > 1200:
        raise HTTPException(status_code=400, detail="이미지는 640×640 이상, 1200×1200 이하이어야 합니다.")

    suffix = ".png" if content_type == "image/png" else ".jpg"
    safe_stem = re.sub(r"[^0-9A-Za-z._-]+", "-", Path(file.filename or "image").stem).strip("-")
    object_name = f"creative-upload/{uuid4().hex}-{safe_stem or 'image'}{suffix}"
    upload_url = f"{supabase_url}/storage/v1/object/{bucket}/{object_name}"
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": content_type,
        "x-upsert": "false",
    }
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.post(upload_url, content=data, headers=headers)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Supabase Storage 업로드 실패(HTTP {response.status_code})")

    public_url = f"{supabase_url}/storage/v1/object/public/{bucket}/{object_name}"
    return ImageUploadResponse(
        image_url=public_url,
        width=width,
        height=height,
        content_type=content_type,
    )


@app.post("/admin/reindex", response_model=IngestResponse, include_in_schema=False)
async def admin_reindex(request: Request) -> IngestResponse:
    token = os.getenv("INGEST_TOKEN")
    provided = request.headers.get("x-ingest-token")
    if not token or provided != token:
        raise HTTPException(status_code=404, detail="Not found")

    try:
        from rag_chatbot.ingestion import ingest_collections

        counts = await asyncio.to_thread(ingest_collections)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return IngestResponse(counts=counts)
