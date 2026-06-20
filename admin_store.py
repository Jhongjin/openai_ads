from __future__ import annotations

import json
import os
import re
from html import escape as html_escape
from html import unescape as html_unescape
from html.parser import HTMLParser
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

from rag_chatbot.config import load_settings


KST = timezone(timedelta(hours=9))


DEFAULT_NOTICE: dict[str, Any] = {
    "title": "📢 OpenAI 광고 집행 의뢰 안내",
    "updated_at": "2026-06-17",
    "bullets": [
        "글자수 — 제목 24자 / 설명 48자 최대, 권장 제목 16~18자 / 설명 32~36자, 크리테오 경유 제목 30자 / 설명 60자",
        "이미지 — 1:1 정사각형, 640×640~1200×1200, PNG/JPG, 공개 직접접근 링크, 로고를 메인 비주얼로 쓰지 말 것",
        "랜딩 — OpenAI 크롤러(OAI-AdsBot) 접근 허용 필수, 차단 시 노출 제한 가능",
        "청구 — 청구 통화 KRW 고정 / 시간대 Asia/Seoul",
        "문의 — 케이티나스미디어 미디어채널실 openai@nasmedia.co.kr",
    ],
    "body_html": """
<ul>
  <li><strong>글자수</strong> — 제목 24자 / 설명 48자 최대, 권장 제목 16~18자 / 설명 32~36자, 크리테오 경유 제목 30자 / 설명 60자</li>
  <li><strong>이미지</strong> — 1:1 정사각형, 640×640~1200×1200, PNG/JPG, 공개 직접접근 링크, 로고를 메인 비주얼로 쓰지 말 것</li>
  <li><strong>랜딩</strong> — OpenAI 크롤러(OAI-AdsBot) 접근 허용 필수, 차단 시 노출 제한 가능</li>
  <li><strong>청구</strong> — 청구 통화 KRW 고정 / 시간대 Asia/Seoul</li>
  <li><strong>문의</strong> — 케이티나스미디어 미디어채널실 openai@nasmedia.co.kr</li>
</ul>
""".strip(),
    "modal_background": "#ffffff",
    "source_label": "OpenAI Ads Guide 기준으로 하루 2회 최신 정보를 자동 확인·업데이트합니다.",
    "source_url": "https://help.openai.com/en/collections/20001223-chatgpt-ads",
    "enabled": True,
}

DEFAULT_SLIDE_CONTENT: dict[str, Any] = {
    "updated_at": "2026-06-17",
    "items": [
        {
            "key": "advertiser.hero.title",
            "deck": "advertiser",
            "label": "광고주 안내자료 표지 제목",
            "default": "ChatGPT 광고 집행 준비 안내",
            "value": "ChatGPT 광고 집행 준비 안내",
            "multiline": False,
        },
        {
            "key": "advertiser.hero.subtitle",
            "deck": "advertiser",
            "label": "광고주 안내자료 표지 부제",
            "default": "광고주님께서 준비해주실 항목",
            "value": "광고주님께서 준비해주실 항목",
            "multiline": False,
        },
        {
            "key": "advertiser.material.title",
            "deck": "advertiser",
            "label": "소재 준비물 슬라이드 제목",
            "default": "광고 소재 준비물",
            "value": "광고 소재 준비물",
            "multiline": False,
        },
        {
            "key": "advertiser.material.image",
            "deck": "advertiser",
            "label": "이미지 준비 기준",
            "default": "PNG/JPG, 1:1 정사각형, 최대 1200×1200, 공개 직접 접근 링크. 로고를 메인 비주얼로 쓰지 말 것",
            "value": "PNG/JPG, 1:1 정사각형, 최대 1200×1200, 공개 직접 접근 링크. 로고를 메인 비주얼로 쓰지 말 것",
            "multiline": True,
        },
        {
            "key": "advertiser.condition.minimum",
            "deck": "advertiser",
            "label": "최소 집행 약정 공개 문구",
            "default": "400만원 / 상세 조건은 영업 담당 안내",
            "value": "400만원 / 상세 조건은 영업 담당 안내",
            "multiline": False,
        },
        {
            "key": "advertiser.footer.contact",
            "deck": "advertiser",
            "label": "광고주 안내자료 문의처",
            "default": "문의처: 케이티나스미디어 미디어채널실 openai@nasmedia.co.kr",
            "value": "문의처: 케이티나스미디어 미디어채널실 openai@nasmedia.co.kr",
            "multiline": False,
        },
        {
            "key": "setup.hero.title",
            "deck": "setup",
            "label": "캠페인 세팅 가이드 표지 제목",
            "default": "광고 캠페인 세팅 가이드",
            "value": "광고 캠페인 세팅 가이드",
            "multiline": False,
        },
        {
            "key": "setup.step1.title",
            "deck": "setup",
            "label": "캠페인 만들기 슬라이드 제목",
            "default": "캠페인 만들기",
            "value": "캠페인 만들기",
            "multiline": False,
        },
        {
            "key": "setup.step2.title",
            "deck": "setup",
            "label": "광고그룹 만들기 슬라이드 제목",
            "default": "광고그룹 만들기",
            "value": "광고그룹 만들기",
            "multiline": False,
        },
        {
            "key": "setup.step3.title",
            "deck": "setup",
            "label": "광고 만들기 슬라이드 제목",
            "default": "광고 만들기",
            "value": "광고 만들기",
            "multiline": False,
        },
        {
            "key": "pixel.hero.title",
            "deck": "pixel",
            "label": "픽셀 설치 가이드 표지 제목",
            "default": "픽셀 설치 가이드",
            "value": "픽셀 설치 가이드",
            "multiline": False,
        },
        {
            "key": "pixel.head.title",
            "deck": "pixel",
            "label": "공통 설치 코드 슬라이드 제목",
            "default": "웹사이트 head에 설치",
            "value": "웹사이트 head에 설치",
            "multiline": False,
        },
        {
            "key": "pixel.gtm.title",
            "deck": "pixel",
            "label": "GTM 슬라이드 제목",
            "default": "GTM 삽입 방법",
            "value": "GTM 삽입 방법",
            "multiline": False,
        },
        {
            "key": "pixel.footer.support",
            "deck": "pixel",
            "label": "픽셀 지원 문의 문구",
            "default": "나스미디어는 GTM 기반 OpenAI Pixel 세팅을 지원합니다. 관련 문의: adso@nasmedia.co.kr",
            "value": "나스미디어는 GTM 기반 OpenAI Pixel 세팅을 지원합니다. 관련 문의: adso@nasmedia.co.kr",
            "multiline": False,
        },
    ],
    "images": [
        {"key": "campaign_step1", "deck": "setup", "label": "캠페인 만들기 화면", "default": "/images/guide/campaign_step1.png", "value": "/images/guide/campaign_step1.png"},
        {"key": "campaign_step2", "deck": "setup", "label": "광고그룹 만들기 화면", "default": "/images/guide/campaign_step2.png", "value": "/images/guide/campaign_step2.png"},
        {"key": "campaign_step3", "deck": "setup", "label": "광고 만들기 화면", "default": "/images/guide/campaign_step3.png", "value": "/images/guide/campaign_step3.png"},
        {"key": "campaign_preview", "deck": "setup", "label": "광고 소재 미리보기", "default": "/images/guide/campaign_preview.png", "value": "/images/guide/campaign_preview.png"},
        {"key": "pixel_step1_conversion_home", "deck": "pixel", "label": "전환 데이터 소스 탭", "default": "/images/guide/pixel_step1_conversion_home.png", "value": "/images/guide/pixel_step1_conversion_home.png"},
        {"key": "pixel_step2_create_source", "deck": "pixel", "label": "새 데이터 소스 모달", "default": "/images/guide/pixel_step2_create_source.png", "value": "/images/guide/pixel_step2_create_source.png"},
        {"key": "pixel_step3_setup_code", "deck": "pixel", "label": "픽셀 설정 코드", "default": "/images/guide/pixel_step3_setup_code.png", "value": "/images/guide/pixel_step3_setup_code.png"},
        {"key": "pixel_step4_create_event", "deck": "pixel", "label": "전환 이벤트 만들기", "default": "/images/guide/pixel_step4_create_event.png", "value": "/images/guide/pixel_step4_create_event.png"},
        {"key": "pixel_step5_event_code", "deck": "pixel", "label": "이벤트 코드", "default": "/images/guide/pixel_step5_event_code.png", "value": "/images/guide/pixel_step5_event_code.png"},
        {"key": "pixel_step6_event_list", "deck": "pixel", "label": "전환 이벤트 목록", "default": "/images/guide/pixel_step6_event_list.png", "value": "/images/guide/pixel_step6_event_list.png"},
        {"key": "pixel_step7_gtm_workspace", "deck": "pixel", "label": "GTM 작업공간", "default": "/images/guide/pixel_step7_gtm_workspace.png", "value": "/images/guide/pixel_step7_gtm_workspace.png"},
    ],
}


_memory_notice = DEFAULT_NOTICE.copy()
_memory_slide_content = json.loads(json.dumps(DEFAULT_SLIDE_CONTENT, ensure_ascii=False))
_memory_visits: dict[str, dict[str, Any]] = {}
_memory_visit_days: dict[str, int] = {}
_memory_visit_events: list[dict[str, Any]] = []
_memory_chat_questions: list[dict[str, Any]] = []
_memory_ads_api_keys: dict[str, dict[str, Any]] = {}
_db_ready = False


def _is_analytics_event(page: str) -> bool:
    return str(page or "").startswith(("download:", "action:", "guide-pdf:", "dev:guide-pdf:"))


def _visit_event_type(page: str, page_label: str = "") -> str:
    page_value = str(page or "")
    label_value = str(page_label or "")
    lower_page = page_value.lower()
    download_tokens = (
        "download:",
        "action:",
        "guide-pdf:",
        "dev:guide-pdf:",
    )
    label_tokens = (
        "다운로드",
        "pdf 저장",
        "이미지 저장",
        "csv",
        "xlsx",
        "인쇄",
    )
    if lower_page.startswith(download_tokens) or any(token in label_value.lower() for token in label_tokens):
        return "download"
    return "page"


QUESTION_CATEGORY_RULES: tuple[dict[str, Any], ...] = (
    {
        "category": "budget",
        "label": "예산·입찰",
        "keywords": (
            "예산",
            "최소 집행",
            "약정",
            "spend cap",
            "account spend",
            "입찰",
            "bid",
            "cpc",
            "cpm",
            "금액",
            "청구",
        ),
    },
    {
        "category": "creative",
        "label": "소재·이미지",
        "keywords": (
            "제목",
            "설명",
            "카피",
            "이미지",
            "로고",
            "파비콘",
            "favicon",
            "문구",
            "글자",
            "사이즈",
            "규격",
        ),
    },
    {
        "category": "landing",
        "label": "랜딩·크롤러",
        "keywords": (
            "랜딩",
            "url",
            "robots",
            "crawler",
            "크롤러",
            "oai-adsbot",
            "접근",
            "차단",
            "방화벽",
        ),
    },
    {
        "category": "measurement",
        "label": "픽셀·전환",
        "keywords": (
            "픽셀",
            "pixel",
            "전환",
            "conversion",
            "gtm",
            "태그",
            "추적",
            "이벤트",
        ),
    },
    {
        "category": "campaign_setup",
        "label": "캠페인 세팅",
        "keywords": (
            "캠페인",
            "광고그룹",
            "광고 그룹",
            "소재",
            "objective",
            "목표",
            "국가",
            "위치",
            "bulk",
            "xlsx",
            "벌크",
        ),
    },
    {
        "category": "policy",
        "label": "정책·심사",
        "keywords": (
            "정책",
            "심사",
            "승인",
            "거절",
            "제한",
            "금지",
            "의료",
            "금융",
            "주류",
            "광고주",
        ),
    },
    {
        "category": "ops",
        "label": "운영·문의",
        "keywords": (
            "문의",
            "담당자",
            "계정",
            "권한",
            "정산",
            "메일",
            "요청",
            "준비",
            "운영",
        ),
    },
)


def categorize_chat_question(question: str, answer: str = "") -> dict[str, str]:
    text = f"{question or ''} {answer or ''}".lower()
    for rule in QUESTION_CATEGORY_RULES:
        if any(str(keyword).lower() in text for keyword in rule["keywords"]):
            return {"category": rule["category"], "label": rule["label"]}
    return {"category": "general", "label": "기타"}


MAIL_REVIEW_STATUSES = {
    "needs_review": "검토 필요",
    "approved_for_rag": "RAG 반영 승인",
    "hold": "보류",
    "rejected": "제외",
    "superseded": "이전 내용 대체",
}

_SAFE_STYLE_NAMES = {"color", "background-color", "font-size"}
_SAFE_CLASSES = {"ql-size-small", "ql-size-large", "ql-size-huge"}
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")
_RGB_COLOR_RE = re.compile(
    r"^rgba?\(\s*(?:25[0-5]|2[0-4]\d|1?\d?\d)\s*,\s*"
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)\s*,\s*"
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"
    r"(?:\s*,\s*(?:0|1|0?\.\d+))?\s*\)$"
)
_FONT_SIZE_RE = re.compile(r"^(?:1[0-9]|2[0-8])px$")


def _is_safe_css_color(value: str) -> bool:
    stripped = str(value or "").strip()
    return bool(_HEX_COLOR_RE.match(stripped) or _RGB_COLOR_RE.match(stripped))


def _sanitize_inline_style(value: str | None) -> str:
    safe: list[str] = []
    for item in str(value or "").split(";"):
        if ":" not in item:
            continue
        name, raw = item.split(":", 1)
        name = name.strip().lower()
        raw = raw.strip()
        if name not in _SAFE_STYLE_NAMES:
            continue
        if name in {"color", "background-color"} and not _is_safe_css_color(raw):
            continue
        if name == "font-size" and not _FONT_SIZE_RE.match(raw):
            continue
        safe.append(f"{name}: {raw}")
    return "; ".join(safe)


def _sanitize_hex_color(value: Any, fallback: str = "#ffffff") -> str:
    raw = str(value or "").strip()
    return raw if _HEX_COLOR_RE.match(raw) else fallback


class _NoticeHtmlSanitizer(HTMLParser):
    _allowed_tags = {
        "p",
        "br",
        "hr",
        "strong",
        "b",
        "em",
        "i",
        "u",
        "s",
        "strike",
        "ul",
        "ol",
        "li",
        "a",
        "span",
        "h2",
        "blockquote",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in self._allowed_tags:
            return
        if tag in {"br", "hr"}:
            self.parts.append(f"<{tag}>")
            return
        safe_attrs: list[str] = []
        for name, value in attrs:
            attr_name = name.lower()
            if attr_name == "class" and value:
                classes = [item for item in str(value).split() if item in _SAFE_CLASSES]
                if classes:
                    safe_attrs.append(f'class="{html_escape(" ".join(classes), quote=True)}"')
            elif attr_name == "style" and value:
                style = _sanitize_inline_style(value)
                if style:
                    safe_attrs.append(f'style="{html_escape(style, quote=True)}"')
        attr_text = (" " + " ".join(safe_attrs)) if safe_attrs else ""
        if tag == "a":
            href = ""
            for name, value in attrs:
                if name.lower() == "href" and value and re.match(r"^(https?://|mailto:)", value.strip(), re.I):
                    href = html_escape(value.strip(), quote=True)
                    break
            if href:
                self.parts.append(f'<a href="{href}" target="_blank" rel="noreferrer"{attr_text}>')
            else:
                self.parts.append(f"<a{attr_text}>")
            return
        self.parts.append(f"<{tag}{attr_text}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._allowed_tags and tag not in {"br", "hr"}:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(html_escape(data))

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")


def _sanitize_notice_html(value: str) -> str:
    parser = _NoticeHtmlSanitizer()
    parser.feed(value or "")
    html = "".join(parser.parts).strip()
    return html or DEFAULT_NOTICE["body_html"]


def _bullets_to_html(bullets: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{html_escape(item)}</li>" for item in bullets if item) + "</ul>"


def _html_to_lines(value: str) -> list[str]:
    text = re.sub(r"</(li|p)>", "\n", value or "", flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return [line.strip() for line in html_unescape(text).splitlines() if line.strip()]


def _today_kst() -> str:
    return datetime.now(KST).date().isoformat()


def _iso_value(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value or "")


def _quote_ident(value: str) -> str:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value):
        raise ValueError("Invalid Supabase schema name.")
    return f'"{value}"'


def _storage_info(mode: str, error: str | None = None) -> dict[str, str]:
    info = {"storage": mode}
    if error:
        info["storage_error"] = error
    return info


def _analytics_period(period: str | int | None) -> dict[str, Any]:
    raw_value = str(period or "30").strip().lower()
    today = datetime.now(KST).date()
    if raw_value in {"all", "전체"}:
        return {
            "value": "all",
            "label": "전체 기간",
            "days": None,
            "start_date": "0001-01-01",
            "end_date": today.isoformat(),
        }

    try:
        days = int(raw_value)
    except ValueError:
        days = 30
    days = max(1, min(days, 365))
    start_date = today - timedelta(days=days - 1)
    return {
        "value": str(days),
        "label": f"최근 {days}일",
        "days": days,
        "start_date": start_date.isoformat(),
        "end_date": today.isoformat(),
    }


def _public_visit_item(item: dict[str, Any]) -> dict[str, Any]:
    page = str(item.get("page") or "")
    page_label = str(item.get("page_label") or page)
    event_type = str(item.get("event_type") or _visit_event_type(page, page_label))
    return {
        "page": page,
        "page_label": page_label,
        "event_type": event_type,
        "total_count": int(item.get("total_count") or item.get("period_count") or 0),
        "today_count": int(item.get("today_count") or 0),
        "today_date": str(item.get("today_date") or _today_kst()),
        "last_seen_at": _iso_value(item.get("last_seen_at")),
    }


def _split_visit_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    public_items = [_public_visit_item(item) for item in items]
    page_items = [item for item in public_items if item["event_type"] != "download"]
    download_items = [item for item in public_items if item["event_type"] == "download"]
    return page_items, download_items


def _visit_pie_items(page_items: list[dict[str, Any]], download_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    combined = sorted(
        page_items + download_items,
        key=lambda item: (-int(item.get("total_count") or 0), item.get("page_label", "")),
    )[:10]
    return [
        {
            "name": item.get("page_label") or item.get("page") or "-",
            "value": int(item.get("total_count") or 0),
            "event_type": item.get("event_type") or "page",
        }
        for item in combined
        if int(item.get("total_count") or 0) > 0
    ]


def _source_summary(sources: Any) -> str:
    if not isinstance(sources, list):
        return ""
    labels: list[str] = []
    for source in sources[:3]:
        if isinstance(source, dict):
            label = (
                source.get("title")
                or source.get("source")
                or source.get("source_label")
                or source.get("url")
                or source.get("name")
            )
        else:
            label = str(source)
        label = str(label or "").strip()
        if label:
            labels.append(label)
    return " / ".join(labels)[:300]


def _aggregate_question_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    categories: dict[str, dict[str, Any]] = {}
    for row in rows:
        category = str(row.get("category") or "general")
        category_label = str(row.get("category_label") or "기타")
        bucket = categories.setdefault(
            category,
            {
                "category": category,
                "label": category_label,
                "count": 0,
                "latest_at": "",
                "questions": {},
            },
        )
        question = re.sub(r"\s+", " ", str(row.get("question") or "")).strip()
        if not question:
            continue
        latest_at = _iso_value(row.get("created_at"))
        key = question[:180]
        item = bucket["questions"].setdefault(
            key,
            {
                "question": question,
                "count": 0,
                "latest_at": latest_at,
                "answer_excerpt": str(row.get("answer_excerpt") or ""),
                "source_summary": str(row.get("source_summary") or ""),
            },
        )
        item["count"] += 1
        if latest_at and latest_at > str(item.get("latest_at") or ""):
            item["latest_at"] = latest_at
            item["answer_excerpt"] = str(row.get("answer_excerpt") or "")
            item["source_summary"] = str(row.get("source_summary") or "")
        bucket["count"] += 1
        if latest_at and latest_at > str(bucket.get("latest_at") or ""):
            bucket["latest_at"] = latest_at

    ordered_categories = []
    for bucket in categories.values():
        questions = sorted(
            bucket["questions"].values(),
            key=lambda item: (int(item.get("count") or 0), str(item.get("latest_at") or "")),
            reverse=True,
        )[:10]
        ordered_categories.append(
            {
                "category": bucket["category"],
                "label": bucket["label"],
                "count": bucket["count"],
                "latest_at": bucket["latest_at"],
                "questions": questions,
            }
        )
    ordered_categories.sort(key=lambda item: (-int(item.get("count") or 0), str(item.get("label") or "")))
    return {"total": sum(int(item.get("count") or 0) for item in ordered_categories), "categories": ordered_categories}


def _connect():
    settings = load_settings()
    if not settings.supabase_db_url:
        raise RuntimeError("SUPABASE_DB_URL is not configured.")
    return psycopg.connect(settings.supabase_db_url)


def _mail_webhook_config() -> tuple[str, str]:
    webhook_url = os.getenv("MAIL_COLLECTOR_SHEETS_WEBHOOK_URL", "").strip()
    webhook_secret = (
        os.getenv("MAIL_COLLECTOR_SHEETS_SHARED_SECRET")
        or os.getenv("SHEETS_SHARED_SECRET")
        or ""
    ).strip()
    if not webhook_url or not webhook_secret:
        raise RuntimeError(
            "MAIL_COLLECTOR_SHEETS_WEBHOOK_URL/MAIL_COLLECTOR_SHEETS_SHARED_SECRET is not configured."
        )
    return webhook_url, webhook_secret


def _post_mail_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    webhook_url, webhook_secret = _mail_webhook_config()
    response = httpx.post(
        webhook_url,
        json={"secret": webhook_secret, **payload},
        timeout=30,
        follow_redirects=True,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("메일 검토 시트 응답 형식이 올바르지 않습니다.")
    return data


def _schema() -> str:
    return _quote_ident(load_settings().supabase_schema)


def _ensure_tables() -> None:
    global _db_ready
    if _db_ready:
        return

    schema = _schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.admin_notice (
                    id text PRIMARY KEY,
                    title text NOT NULL,
                    updated_at text NOT NULL,
                    bullets jsonb NOT NULL DEFAULT '[]'::jsonb,
                    body_html text NOT NULL DEFAULT '',
                    modal_background text NOT NULL DEFAULT '#ffffff',
                    source_label text NOT NULL,
                    source_url text NOT NULL,
                    enabled boolean NOT NULL DEFAULT true,
                    updated_at_utc timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(f"ALTER TABLE {schema}.admin_notice ADD COLUMN IF NOT EXISTS body_html text NOT NULL DEFAULT ''")
            cur.execute(
                f"ALTER TABLE {schema}.admin_notice ADD COLUMN IF NOT EXISTS modal_background text NOT NULL DEFAULT '#ffffff'"
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.admin_slide_content (
                    id text PRIMARY KEY,
                    updated_at text NOT NULL,
                    content jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                    updated_at_utc timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.page_visits (
                    page text PRIMARY KEY,
                    page_label text NOT NULL,
                    total_count bigint NOT NULL DEFAULT 0,
                    today_date text NOT NULL,
                    today_count bigint NOT NULL DEFAULT 0,
                    last_seen_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.page_visit_days (
                    visit_date text PRIMARY KEY,
                    total_count bigint NOT NULL DEFAULT 0,
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.page_visit_events (
                    id bigserial PRIMARY KEY,
                    page text NOT NULL,
                    page_label text NOT NULL,
                    event_type text NOT NULL DEFAULT 'page',
                    event_date text NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS page_visit_events_date_idx
                ON {schema}.page_visit_events (event_date DESC)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS page_visit_events_type_date_idx
                ON {schema}.page_visit_events (event_type, event_date DESC)
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.chat_question_logs (
                    id bigserial PRIMARY KEY,
                    question text NOT NULL,
                    answer_excerpt text NOT NULL DEFAULT '',
                    category text NOT NULL,
                    category_label text NOT NULL,
                    source_summary text NOT NULL DEFAULT '',
                    asked_date text NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS chat_question_logs_date_idx
                ON {schema}.chat_question_logs (asked_date DESC)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS chat_question_logs_category_date_idx
                ON {schema}.chat_question_logs (category, asked_date DESC)
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.official_guide_changes (
                    id bigserial PRIMARY KEY,
                    source_identity text NOT NULL,
                    article_id text,
                    lang text,
                    title text NOT NULL,
                    source_url text NOT NULL,
                    change_type text NOT NULL,
                    previous_hash text,
                    current_hash text NOT NULL,
                    previous_source_updated_at date,
                    current_source_updated_at date,
                    detected_at timestamptz NOT NULL DEFAULT now(),
                    summary text NOT NULL DEFAULT '',
                    metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                    CONSTRAINT official_guide_changes_type_check
                        CHECK (change_type IN ('new', 'updated')),
                    CONSTRAINT official_guide_changes_identity_hash_unique
                        UNIQUE (source_identity, current_hash)
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS official_guide_changes_detected_idx
                ON {schema}.official_guide_changes (detected_at DESC)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS official_guide_changes_article_lang_idx
                ON {schema}.official_guide_changes (article_id, lang)
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.ads_api_keys (
                    advertiser_name text PRIMARY KEY,
                    ads_api_key text NOT NULL DEFAULT '',
                    conversion_api_key text NOT NULL DEFAULT '',
                    enabled boolean NOT NULL DEFAULT true,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                f"""
                INSERT INTO {schema}.admin_notice
                    (id, title, updated_at, bullets, body_html, modal_background, source_label, source_url, enabled)
                VALUES
                    ('main', %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    DEFAULT_NOTICE["title"],
                    DEFAULT_NOTICE["updated_at"],
                    json.dumps(DEFAULT_NOTICE["bullets"], ensure_ascii=False),
                    DEFAULT_NOTICE["body_html"],
                    DEFAULT_NOTICE["modal_background"],
                    DEFAULT_NOTICE["source_label"],
                    DEFAULT_NOTICE["source_url"],
                    DEFAULT_NOTICE["enabled"],
                ),
            )
            cur.execute(
                f"""
                UPDATE {schema}.admin_notice
                SET body_html = %s
                WHERE id = 'main' AND COALESCE(body_html, '') = ''
                """,
                (DEFAULT_NOTICE["body_html"],),
            )
            cur.execute(
                f"""
                INSERT INTO {schema}.admin_slide_content
                    (id, updated_at, content)
                VALUES
                    ('main', %s, %s::jsonb)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    DEFAULT_SLIDE_CONTENT["updated_at"],
                    json.dumps(DEFAULT_SLIDE_CONTENT, ensure_ascii=False),
                ),
            )
    _db_ready = True


def get_notice_config() -> dict[str, Any]:
    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT title, updated_at, bullets, body_html, modal_background, source_label, source_url, enabled
                    FROM {schema}.admin_notice
                    WHERE id = 'main'
                    """
                )
                row = cur.fetchone()
        if not row:
            return {**DEFAULT_NOTICE, **_storage_info("memory")}
        title, updated_at, bullets, body_html, modal_background, source_label, source_url, enabled = row
        return {
            "title": title,
            "updated_at": updated_at,
            "bullets": bullets or [],
            "body_html": body_html or _bullets_to_html(bullets or []),
            "modal_background": modal_background or DEFAULT_NOTICE["modal_background"],
            "source_label": source_label,
            "source_url": source_url,
            "enabled": bool(enabled),
            **_storage_info("supabase"),
        }
    except Exception as exc:
        return {**_memory_notice, **_storage_info("memory", str(exc))}


def save_notice_config(payload: dict[str, Any]) -> dict[str, Any]:
    bullets = [
        str(item).strip()
        for item in payload.get("bullets", [])
        if str(item).strip()
    ]
    body_html = _sanitize_notice_html(str(payload.get("body_html") or ""))
    modal_background = _sanitize_hex_color(payload.get("modal_background"), DEFAULT_NOTICE["modal_background"])
    if not bullets:
        bullets = _html_to_lines(body_html) or list(DEFAULT_NOTICE["bullets"])
    notice = {
        "title": str(payload.get("title") or DEFAULT_NOTICE["title"]).strip(),
        "updated_at": _today_kst(),
        "bullets": bullets,
        "body_html": body_html,
        "modal_background": modal_background,
        "source_label": str(payload.get("source_label") or DEFAULT_NOTICE["source_label"]).strip(),
        "source_url": str(payload.get("source_url") or DEFAULT_NOTICE["source_url"]).strip(),
        "enabled": bool(payload.get("enabled", True)),
    }

    global _memory_notice
    _memory_notice = notice.copy()

    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {schema}.admin_notice
                        (id, title, updated_at, bullets, body_html, modal_background, source_label, source_url, enabled, updated_at_utc)
                    VALUES
                        ('main', %s, %s, %s::jsonb, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        updated_at = EXCLUDED.updated_at,
                        bullets = EXCLUDED.bullets,
                        body_html = EXCLUDED.body_html,
                        modal_background = EXCLUDED.modal_background,
                        source_label = EXCLUDED.source_label,
                        source_url = EXCLUDED.source_url,
                        enabled = EXCLUDED.enabled,
                        updated_at_utc = now()
                    """,
                    (
                        notice["title"],
                        notice["updated_at"],
                        json.dumps(notice["bullets"], ensure_ascii=False),
                        notice["body_html"],
                        notice["modal_background"],
                        notice["source_label"],
                        notice["source_url"],
                        notice["enabled"],
                    ),
                )
        return {**notice, **_storage_info("supabase")}
    except Exception as exc:
        return {**notice, **_storage_info("memory", str(exc))}


def _clean_slide_text(value: Any, *, multiline: bool = False, fallback: str = "") -> str:
    text = str(value if value is not None else fallback).strip()
    if multiline:
        text = re.sub(r"\r\n?", "\n", text)
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)[:1200] or fallback
    return re.sub(r"\s+", " ", text)[:300] or fallback


def _clean_slide_image_url(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if text.startswith("/images/") or re.match(r"^https?://[^\s]+$", text, re.I):
        return text[:500]
    return fallback


def _merged_slide_content(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    source = payload or {}
    base = json.loads(json.dumps(DEFAULT_SLIDE_CONTENT, ensure_ascii=False))
    incoming_items = {
        str(item.get("key") or ""): item
        for item in source.get("items", [])
        if isinstance(item, dict)
    }
    incoming_images = {
        str(item.get("key") or ""): item
        for item in source.get("images", [])
        if isinstance(item, dict)
    }

    for item in base["items"]:
        incoming = incoming_items.get(item["key"], {})
        item["value"] = _clean_slide_text(
            incoming.get("value", item.get("value")),
            multiline=bool(item.get("multiline")),
            fallback=item["default"],
        )

    base_item_keys = {str(item.get("key") or "") for item in base["items"]}
    for key, incoming in incoming_items.items():
        clean_key = re.sub(r"[^a-zA-Z0-9_.:-]", "", key).strip()[:120]
        if not clean_key or clean_key in base_item_keys:
            continue
        deck = _clean_slide_text(incoming.get("deck"), fallback="custom")[:40]
        label = _clean_slide_text(incoming.get("label"), fallback=clean_key)[:200]
        default = _clean_slide_text(incoming.get("default"), multiline=True, fallback="")[:1200]
        multiline = bool(incoming.get("multiline", False))
        base["items"].append(
            {
                "key": clean_key,
                "deck": deck,
                "label": label,
                "default": default,
                "value": _clean_slide_text(
                    incoming.get("value"),
                    multiline=multiline,
                    fallback=default,
                ),
                "multiline": multiline,
            }
        )
        base_item_keys.add(clean_key)

    for item in base["images"]:
        incoming = incoming_images.get(item["key"], {})
        item["value"] = _clean_slide_image_url(incoming.get("value", item.get("value")), item["default"])
        item["alt"] = _clean_slide_text(incoming.get("alt", item.get("alt", item["label"])), fallback=item["label"])
        item["caption"] = _clean_slide_text(
            incoming.get("caption", item.get("caption", item["label"])),
            fallback=item["label"],
        )

    base_image_keys = {str(item.get("key") or "") for item in base["images"]}
    for key, incoming in incoming_images.items():
        clean_key = re.sub(r"[^a-zA-Z0-9_.:-]", "", key).strip()[:120]
        if not clean_key or clean_key in base_image_keys:
            continue
        deck = _clean_slide_text(incoming.get("deck"), fallback="custom")[:40]
        label = _clean_slide_text(incoming.get("label"), fallback=clean_key)[:200]
        default = _clean_slide_image_url(incoming.get("default"), "")
        value = _clean_slide_image_url(incoming.get("value"), default)
        base["images"].append(
            {
                "key": clean_key,
                "deck": deck,
                "label": label,
                "default": default,
                "value": value,
                "alt": _clean_slide_text(incoming.get("alt"), fallback=label),
                "caption": _clean_slide_text(incoming.get("caption"), fallback=label),
            }
        )
        base_image_keys.add(clean_key)

    base["updated_at"] = _clean_slide_text(source.get("updated_at"), fallback=_today_kst())
    return base


def get_slide_content() -> dict[str, Any]:
    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT content, updated_at
                    FROM {schema}.admin_slide_content
                    WHERE id = 'main'
                    """
                )
                row = cur.fetchone()
        if not row:
            return {**_merged_slide_content(DEFAULT_SLIDE_CONTENT), **_storage_info("memory")}
        content, updated_at = row
        merged = _merged_slide_content(content or {})
        merged["updated_at"] = str(updated_at or merged["updated_at"])
        return {**merged, **_storage_info("supabase")}
    except Exception as exc:
        return {**_merged_slide_content(_memory_slide_content), **_storage_info("memory", str(exc))}


def save_slide_content(payload: dict[str, Any]) -> dict[str, Any]:
    content = _merged_slide_content({**payload, "updated_at": _today_kst()})

    global _memory_slide_content
    _memory_slide_content = json.loads(json.dumps(content, ensure_ascii=False))

    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {schema}.admin_slide_content
                        (id, updated_at, content, updated_at_utc)
                    VALUES
                        ('main', %s, %s::jsonb, now())
                    ON CONFLICT (id) DO UPDATE SET
                        updated_at = EXCLUDED.updated_at,
                        content = EXCLUDED.content,
                        updated_at_utc = now()
                    """,
                    (
                        content["updated_at"],
                        json.dumps(content, ensure_ascii=False),
                    ),
                )
        return {**content, **_storage_info("supabase")}
    except Exception as exc:
        return {**content, **_storage_info("memory", str(exc))}


def record_page_visit(page: str, page_label: str) -> dict[str, Any]:
    page = (page or "unknown")[:80]
    page_label = (page_label or page)[:120]
    today = _today_kst()
    event_type = _visit_event_type(page, page_label)

    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {schema}.page_visits
                        (page, page_label, total_count, today_date, today_count, last_seen_at)
                    VALUES
                        (%s, %s, 1, %s, 1, now())
                    ON CONFLICT (page) DO UPDATE SET
                        page_label = EXCLUDED.page_label,
                        total_count = {schema}.page_visits.total_count + 1,
                        today_count = CASE
                            WHEN {schema}.page_visits.today_date = EXCLUDED.today_date
                            THEN {schema}.page_visits.today_count + 1
                            ELSE 1
                        END,
                        today_date = EXCLUDED.today_date,
                        last_seen_at = now()
                    RETURNING page, page_label, total_count, today_count, today_date, last_seen_at
                    """,
                    (page, page_label, today),
                )
                row = cur.fetchone()
                cur.execute(
                    f"""
                    INSERT INTO {schema}.page_visit_events
                        (page, page_label, event_type, event_date, created_at)
                    VALUES
                        (%s, %s, %s, %s, now())
                    """,
                    (page, page_label, event_type, today),
                )
                if event_type != "download":
                    cur.execute(
                        f"""
                        INSERT INTO {schema}.page_visit_days
                            (visit_date, total_count, updated_at)
                        VALUES
                            (%s, 1, now())
                        ON CONFLICT (visit_date) DO UPDATE SET
                            total_count = {schema}.page_visit_days.total_count + 1,
                            updated_at = now()
                        """,
                        (today,),
                    )
        return {
            "page": row[0],
            "page_label": row[1],
            "total_count": row[2],
            "today_count": row[3],
            "today_date": row[4],
            "last_seen_at": row[5].isoformat() if row[5] else "",
            **_storage_info("supabase"),
        }
    except Exception as exc:
        current = _memory_visits.setdefault(
            page,
            {
                "page": page,
                "page_label": page_label,
                "total_count": 0,
                "today_count": 0,
                "today_date": today,
                "last_seen_at": "",
            },
        )
        current["page_label"] = page_label
        current["total_count"] += 1
        current["today_count"] = current["today_count"] + 1 if current["today_date"] == today else 1
        current["today_date"] = today
        current["last_seen_at"] = datetime.now(KST).isoformat()
        _memory_visit_events.append(
            {
                "page": page,
                "page_label": page_label,
                "event_type": event_type,
                "event_date": today,
                "created_at": current["last_seen_at"],
            }
        )
        del _memory_visit_events[:-5000]
        if event_type != "download":
            _memory_visit_days[today] = _memory_visit_days.get(today, 0) + 1
        return {**current, **_storage_info("memory", str(exc))}


def record_chat_question(question: str, answer: str = "", sources: Any = None) -> dict[str, Any]:
    question_text = re.sub(r"\s+", " ", str(question or "")).strip()[:500]
    if not question_text:
        return {"recorded": False, "reason": "empty_question"}
    answer_excerpt = re.sub(r"\s+", " ", str(answer or "")).strip()[:700]
    category = categorize_chat_question(question_text, answer_excerpt)
    source_summary = _source_summary(sources)
    today = _today_kst()
    created_at = datetime.now(KST).isoformat()
    record = {
        "question": question_text,
        "answer_excerpt": answer_excerpt,
        "category": category["category"],
        "category_label": category["label"],
        "source_summary": source_summary,
        "asked_date": today,
        "created_at": created_at,
    }

    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {schema}.chat_question_logs
                        (question, answer_excerpt, category, category_label, source_summary, asked_date, created_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, now())
                    """,
                    (
                        question_text,
                        answer_excerpt,
                        category["category"],
                        category["label"],
                        source_summary,
                        today,
                    ),
                )
        return {"recorded": True, **category, **_storage_info("supabase")}
    except Exception as exc:
        _memory_chat_questions.append(record)
        del _memory_chat_questions[:-1000]
        return {"recorded": True, **category, **_storage_info("memory", str(exc))}


def get_visit_analytics(period: str | int | None = "30") -> dict[str, Any]:
    period_info = _analytics_period(period)
    start_date = period_info["start_date"]
    end_date = period_info["end_date"]
    today = _today_kst()

    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT page, page_label, total_count, today_count, today_date, last_seen_at
                    FROM {schema}.page_visits
                    ORDER BY total_count DESC, page_label ASC
                    """
                )
                rows = cur.fetchall()
                cur.execute(
                    f"""
                    SELECT page, page_label, event_type, COUNT(*)::bigint AS period_count,
                        SUM(CASE WHEN event_date = %s THEN 1 ELSE 0 END)::bigint AS today_count,
                        MAX(created_at) AS last_seen_at
                    FROM {schema}.page_visit_events
                    WHERE event_date BETWEEN %s AND %s
                    GROUP BY page, page_label, event_type
                    ORDER BY period_count DESC, page_label ASC
                    """,
                    (today, start_date, end_date),
                )
                event_rows = cur.fetchall()
                cur.execute(
                    f"""
                    SELECT event_date, COUNT(*)::bigint
                    FROM {schema}.page_visit_events
                    WHERE event_type <> 'download'
                        AND event_date BETWEEN %s AND %s
                    GROUP BY event_date
                    ORDER BY event_date DESC
                    LIMIT 365
                    """,
                    (start_date, end_date),
                )
                event_series_rows = cur.fetchall()
                cur.execute(
                    f"""
                    SELECT visit_date, total_count
                    FROM {schema}.page_visit_days
                    ORDER BY visit_date DESC
                    LIMIT 365
                    """
                )
                series_rows = cur.fetchall()
                cur.execute(
                    f"""
                    SELECT category, category_label, question, answer_excerpt, source_summary, created_at
                    FROM {schema}.chat_question_logs
                    WHERE asked_date BETWEEN %s AND %s
                    ORDER BY created_at DESC
                    LIMIT 500
                    """,
                    (start_date, end_date),
                )
                question_rows = cur.fetchall()
        items = [
            {
                "page": row[0],
                "page_label": row[1],
                "event_type": _visit_event_type(row[0], row[1]),
                "total_count": row[2],
                "today_count": row[3],
                "today_date": row[4],
                "last_seen_at": row[5].isoformat() if row[5] else "",
            }
            for row in rows
        ]
        event_items = [
            {
                "page": row[0],
                "page_label": row[1],
                "event_type": row[2],
                "total_count": row[3],
                "today_count": row[4],
                "today_date": today,
                "last_seen_at": row[5].isoformat() if row[5] else "",
            }
            for row in event_rows
        ]
        if not event_items:
            event_items = items
        page_items, download_items = _split_visit_items(event_items)
        selected_series_rows = event_series_rows or series_rows
        series = [
            {"date": row[0], "total_count": row[1]}
            for row in reversed(selected_series_rows)
        ]
        question_items = [
            {
                "category": row[0],
                "category_label": row[1],
                "question": row[2],
                "answer_excerpt": row[3],
                "source_summary": row[4],
                "created_at": row[5],
            }
            for row in question_rows
        ]
        return {
            "items": items,
            "page_items": page_items,
            "download_items": download_items,
            "pie_items": _visit_pie_items(page_items, download_items),
            "series": series,
            "period": period_info,
            "questions": _aggregate_question_rows(question_items),
            **_storage_info("supabase"),
        }
    except Exception as exc:
        items = sorted(
            [_public_visit_item(item) for item in _memory_visits.values()],
            key=lambda item: (-int(item.get("total_count", 0)), item.get("page_label", "")),
        )
        period_events = [
            item
            for item in _memory_visit_events
            if start_date <= str(item.get("event_date") or "") <= end_date
        ]
        event_counts: dict[tuple[str, str, str], dict[str, Any]] = {}
        for event in period_events:
            key = (
                str(event.get("page") or ""),
                str(event.get("page_label") or ""),
                str(event.get("event_type") or _visit_event_type(event.get("page"), event.get("page_label"))),
            )
            bucket = event_counts.setdefault(
                key,
                {
                    "page": key[0],
                    "page_label": key[1],
                    "event_type": key[2],
                    "total_count": 0,
                    "today_count": 0,
                    "today_date": today,
                    "last_seen_at": "",
                },
            )
            bucket["total_count"] += 1
            if event.get("event_date") == today:
                bucket["today_count"] += 1
            created_at = str(event.get("created_at") or "")
            if created_at > str(bucket.get("last_seen_at") or ""):
                bucket["last_seen_at"] = created_at
        event_items = sorted(
            event_counts.values() or items,
            key=lambda item: (-int(item.get("total_count", 0)), item.get("page_label", "")),
        )
        page_items, download_items = _split_visit_items(event_items)
        series = [
            {"date": date, "total_count": count}
            for date, count in sorted(_memory_visit_days.items())
            if start_date <= date <= end_date
        ]
        question_items = [
            item
            for item in _memory_chat_questions
            if start_date <= str(item.get("asked_date") or "") <= end_date
        ]
        return {
            "items": items,
            "page_items": page_items,
            "download_items": download_items,
            "pie_items": _visit_pie_items(page_items, download_items),
            "series": series,
            "period": period_info,
            "questions": _aggregate_question_rows(question_items),
            **_storage_info("memory", str(exc)),
        }


def _mask_secret(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    if len(value) <= 10:
        return f"{value[:2]}...{value[-2:]}"
    return f"{value[:8]}...{value[-4:]}"


def _public_ads_api_key_row(row: dict[str, Any]) -> dict[str, Any]:
    ads_api_key = str(row.get("ads_api_key") or "")
    conversion_api_key = str(row.get("conversion_api_key") or "")
    return {
        "advertiser_name": str(row.get("advertiser_name") or ""),
        "has_ads_api_key": bool(ads_api_key),
        "masked_ads_api_key": _mask_secret(ads_api_key),
        "has_conversion_api_key": bool(conversion_api_key),
        "masked_conversion_api_key": _mask_secret(conversion_api_key),
        "enabled": bool(row.get("enabled", True)),
        "created_at": _iso_value(row.get("created_at")),
        "updated_at": _iso_value(row.get("updated_at")),
    }


def list_ads_api_keys() -> dict[str, Any]:
    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT advertiser_name, ads_api_key, conversion_api_key, enabled, created_at, updated_at
                    FROM {schema}.ads_api_keys
                    ORDER BY advertiser_name ASC
                    """
                )
                rows = cur.fetchall()
        return {
            "ok": True,
            "items": [_public_ads_api_key_row(dict(row)) for row in rows],
            **_storage_info("supabase"),
        }
    except Exception as exc:
        return {
            "ok": True,
            "items": [
                _public_ads_api_key_row(row)
                for row in sorted(_memory_ads_api_keys.values(), key=lambda item: item.get("advertiser_name", ""))
            ],
            **_storage_info("memory", str(exc)),
        }


def get_ads_api_key(advertiser_name: str) -> str:
    advertiser_name = str(advertiser_name or "").strip()
    if not advertiser_name:
        return ""
    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT ads_api_key
                    FROM {schema}.ads_api_keys
                    WHERE advertiser_name = %s AND enabled = true
                    """,
                    (advertiser_name,),
                )
                row = cur.fetchone()
        return str(row["ads_api_key"] or "") if row else ""
    except Exception:
        row = _memory_ads_api_keys.get(advertiser_name) or {}
        return str(row.get("ads_api_key") or "") if row.get("enabled", True) else ""


def upsert_ads_api_key(payload: dict[str, Any]) -> dict[str, Any]:
    advertiser_name = str(payload.get("advertiser_name") or "").strip()
    new_ads_api_key = str(payload.get("ads_api_key") or "").strip()
    new_conversion_api_key = str(payload.get("conversion_api_key") or "").strip()
    enabled = bool(payload.get("enabled", True))
    if not advertiser_name:
        raise ValueError("광고주명이 필요합니다.")

    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT advertiser_name, ads_api_key, conversion_api_key, enabled, created_at, updated_at
                    FROM {schema}.ads_api_keys
                    WHERE advertiser_name = %s
                    """,
                    (advertiser_name,),
                )
                existing = cur.fetchone()
                ads_api_key = new_ads_api_key or (existing["ads_api_key"] if existing else "")
                conversion_api_key = new_conversion_api_key or (existing["conversion_api_key"] if existing else "")
                if not ads_api_key:
                    raise ValueError("Ads API Key가 필요합니다.")
                cur.execute(
                    f"""
                    INSERT INTO {schema}.ads_api_keys
                        (advertiser_name, ads_api_key, conversion_api_key, enabled, created_at, updated_at)
                    VALUES
                        (%s, %s, %s, %s, COALESCE(%s, now()), now())
                    ON CONFLICT (advertiser_name) DO UPDATE SET
                        ads_api_key = EXCLUDED.ads_api_key,
                        conversion_api_key = EXCLUDED.conversion_api_key,
                        enabled = EXCLUDED.enabled,
                        updated_at = now()
                    RETURNING advertiser_name, ads_api_key, conversion_api_key, enabled, created_at, updated_at
                    """,
                    (
                        advertiser_name,
                        ads_api_key,
                        conversion_api_key,
                        enabled,
                        existing["created_at"] if existing else None,
                    ),
                )
                row = cur.fetchone()
        return {
            "ok": True,
            "item": _public_ads_api_key_row(dict(row)),
            **_storage_info("supabase"),
        }
    except ValueError:
        raise
    except Exception as exc:
        existing = _memory_ads_api_keys.get(advertiser_name) or {}
        ads_api_key = new_ads_api_key or str(existing.get("ads_api_key") or "")
        conversion_api_key = new_conversion_api_key or str(existing.get("conversion_api_key") or "")
        if not ads_api_key:
            raise ValueError("Ads API Key가 필요합니다.") from exc
        now = datetime.now(KST).isoformat()
        row = {
            "advertiser_name": advertiser_name,
            "ads_api_key": ads_api_key,
            "conversion_api_key": conversion_api_key,
            "enabled": enabled,
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
        }
        _memory_ads_api_keys[advertiser_name] = row
        return {
            "ok": True,
            "item": _public_ads_api_key_row(row),
            **_storage_info("memory", str(exc)),
        }


def delete_ads_api_key(advertiser_name: str) -> dict[str, Any]:
    advertiser_name = str(advertiser_name or "").strip()
    if not advertiser_name:
        raise ValueError("광고주명이 필요합니다.")
    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {schema}.ads_api_keys WHERE advertiser_name = %s",
                    (advertiser_name,),
                )
        return {"ok": True, **_storage_info("supabase")}
    except Exception as exc:
        _memory_ads_api_keys.pop(advertiser_name, None)
        return {"ok": True, **_storage_info("memory", str(exc))}


def list_official_guide_changes(*, limit: int = 80) -> dict[str, Any]:
    limit = max(1, min(int(limit or 80), 300))
    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT
                        id,
                        source_identity,
                        article_id,
                        lang,
                        title,
                        source_url,
                        change_type,
                        previous_hash,
                        current_hash,
                        previous_source_updated_at,
                        current_source_updated_at,
                        detected_at,
                        summary
                    FROM {schema}.official_guide_changes
                    ORDER BY detected_at DESC, id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
        items = []
        for row in rows:
            items.append(
                {
                    "id": row["id"],
                    "source_identity": row["source_identity"],
                    "article_id": row["article_id"] or "",
                    "lang": (row["lang"] or "").upper(),
                    "title": row["title"],
                    "source_url": row["source_url"],
                    "change_type": row["change_type"],
                    "previous_hash": row["previous_hash"] or "",
                    "current_hash": row["current_hash"],
                    "previous_source_updated_at": _iso_value(row["previous_source_updated_at"]),
                    "current_source_updated_at": _iso_value(row["current_source_updated_at"]),
                    "detected_at": _iso_value(row["detected_at"]),
                    "summary": row["summary"] or "",
                }
            )
        return {
            "ok": True,
            "items": items,
            **_storage_info("supabase"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "items": [],
            "error": str(exc),
            **_storage_info("memory", str(exc)),
        }


def list_mail_review_rows(*, status_filter: str = "", limit: int = 100) -> dict[str, Any]:
    status_filter = (status_filter or "").strip()
    if status_filter and status_filter not in MAIL_REVIEW_STATUSES and status_filter != "all":
        status_filter = ""
    limit = max(1, min(int(limit or 100), 300))

    try:
        payload = _post_mail_webhook(
            {
                "action": "review_list",
                "status": status_filter,
                "limit": limit,
            }
        )
        payload.setdefault("statusLabels", MAIL_REVIEW_STATUSES)
        return payload
    except Exception as exc:
        return {
            "ok": False,
            "rows": [],
            "stats": {},
            "statusLabels": MAIL_REVIEW_STATUSES,
            "error": str(exc),
        }


def update_mail_review_row(payload: dict[str, Any]) -> dict[str, Any]:
    duplicate_hash = str(payload.get("duplicate_hash") or "").strip()
    review_status = str(payload.get("review_status") or "").strip()
    if not duplicate_hash:
        raise ValueError("duplicate_hash가 필요합니다.")
    if review_status not in MAIL_REVIEW_STATUSES:
        raise ValueError("지원하지 않는 검토 상태입니다.")

    clean_payload = {
        "action": "review_update",
        "duplicate_hash": duplicate_hash,
        "review_status": review_status,
        "review_note": str(payload.get("review_note") or "").strip()[:2000],
        "approved_title": str(payload.get("approved_title") or "").strip()[:300],
        "approved_summary": str(payload.get("approved_summary") or "").strip()[:8000],
        "approved_by": str(payload.get("approved_by") or "").strip()[:80],
        "supersedes_duplicate_hash": str(payload.get("supersedes_duplicate_hash") or "").strip()[:128],
    }
    if review_status == "approved_for_rag" and not clean_payload["approved_summary"]:
        raise ValueError("RAG 반영 승인에는 승인 요약이 필요합니다.")

    response = _post_mail_webhook(clean_payload)
    response.setdefault("statusLabels", MAIL_REVIEW_STATUSES)
    return response
