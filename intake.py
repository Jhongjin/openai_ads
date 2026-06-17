from __future__ import annotations

from datetime import date, datetime
import os
import re
import threading
import time
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field, field_validator, model_validator


KST = ZoneInfo("Asia/Seoul")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SAFE_NAME_RE = re.compile(r"^[0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ _-]+$")
_RECEIPT_LOCK = threading.Lock()
_RECEIPT_COUNTERS: dict[str, int] = {}
_RATE_LIMIT_SECONDS = 10
_LAST_SUBMIT_BY_IP: dict[str, float] = {}


def _clean_text(value: str) -> str:
    return str(value or "").strip()


def _require_text(value: str) -> str:
    text = _clean_text(value)
    if not text:
        raise ValueError("필수값이 비어 있습니다.")
    return text


def _valid_http_url(value: str, label: str = "URL") -> str:
    text = _require_text(value)
    lowered = text.lower()
    if not lowered.startswith(("http://", "https://")):
        raise ValueError(f"{label}은 http:// 또는 https://로 시작해야 합니다.")
    return text


def _valid_safe_name(value: str, label: str) -> str:
    text = _require_text(value)
    if not _SAFE_NAME_RE.fullmatch(text):
        raise ValueError(f"{label}에는 한글, 영문, 숫자, 공백, 하이픈, 언더스코어만 사용할 수 있습니다.")
    return text


def _number_for_sheet(value: float | None) -> str:
    if value is None:
        return ""
    number = int(value) if float(value).is_integer() else value
    return str(number)


def _date_for_sheet(value: date | None) -> str:
    return value.isoformat() if value else ""


def _route_label(route: str) -> str:
    return "크리테오 경유" if route == "criteo" else "OpenAI 직접 CBT"


class OpsMeta(BaseModel):
    execution_route: Literal["openai_cbt", "criteo"] = Field(..., alias="executionRoute")
    advertiser_name: str = Field(..., alias="advertiserName")
    legal_name: str = Field(..., alias="legalName")
    brn: str = Field(..., alias="brn")
    advertiser_homepage_url: str = Field(..., alias="advertiserHomepageUrl")
    invoice_email: str = Field(..., alias="invoiceEmail")

    ads_manager_ready: bool = Field(default=False, alias="adsManagerReady")
    payment_ready: bool = Field(default=False, alias="paymentReady")
    crawler_ready: bool = Field(default=False, alias="crawlerReady")
    favicon_ready: bool = Field(default=False, alias="faviconReady")

    contact_name: str = Field(..., alias="contactName")
    contact_phone: str = Field(..., alias="contactPhone")
    contact_email: str = Field(..., alias="contactEmail")
    sales_owner: str = Field(..., alias="salesOwner")
    notes: str = ""

    honeypot: str = ""
    form_started_at: int | None = Field(default=None, alias="formStartedAt")

    @field_validator(
        "advertiser_name",
        "legal_name",
        "brn",
        "invoice_email",
        "contact_name",
        "contact_phone",
        "contact_email",
        "sales_owner",
    )
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _require_text(value)

    @field_validator("notes", "honeypot")
    @classmethod
    def _optional_text(cls, value: str) -> str:
        return _clean_text(value)

    @field_validator("advertiser_homepage_url")
    @classmethod
    def _valid_homepage(cls, value: str) -> str:
        return _valid_http_url(value, "advertiser 공식 홈페이지 URL")

    @field_validator("invoice_email", "contact_email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        text = _require_text(value)
        if not _EMAIL_RE.match(text):
            raise ValueError("이메일 형식이 올바르지 않습니다.")
        return text


class CampaignInfo(BaseModel):
    campaign_name: str
    budget_max: float
    budget_type: Literal["lifetime", "daily"] = "lifetime"
    launch_date: date | None = None
    end_date: date | None = None
    objective: Literal["views", "clicks"]
    target_countries: list[str] = Field(default_factory=lambda: ["KR"])

    @field_validator("campaign_name")
    @classmethod
    def _valid_campaign_name(cls, value: str) -> str:
        return _valid_safe_name(value, "캠페인명")

    @field_validator("budget_max")
    @classmethod
    def _valid_budget(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("예산 금액은 0보다 커야 합니다.")
        return value

    @field_validator("target_countries")
    @classmethod
    def _valid_countries(cls, values: list[str]) -> list[str]:
        cleaned = [str(value or "").strip().upper() for value in values if str(value or "").strip()]
        if not cleaned:
            cleaned = ["KR"]
        invalid = [value for value in cleaned if not re.fullmatch(r"[A-Z]{2}", value)]
        if invalid:
            raise ValueError("국가는 2자리 ISO 코드로 저장해야 합니다.")
        return cleaned


class AdGroupInfo(BaseModel):
    campaign_name: str = ""
    adgroup_name: str
    max_bid: float | None = None
    keywords: list[str] = Field(default_factory=list)

    @field_validator("campaign_name")
    @classmethod
    def _clean_campaign_name(cls, value: str) -> str:
        return _clean_text(value)

    @field_validator("adgroup_name")
    @classmethod
    def _valid_adgroup_name(cls, value: str) -> str:
        return _valid_safe_name(value, "광고그룹명")

    @field_validator("max_bid")
    @classmethod
    def _valid_max_bid(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("최대 입찰가는 0보다 커야 합니다.")
        return value

    @field_validator("keywords")
    @classmethod
    def _clean_keywords(cls, values: list[str]) -> list[str]:
        return [_clean_text(value) for value in values if _clean_text(value)]


class AdInfo(BaseModel):
    adgroup_name: str = ""
    title: str
    ad_copy: str = Field(..., alias="copy")
    link: str
    image_link: str

    @field_validator("adgroup_name")
    @classmethod
    def _clean_adgroup_name(cls, value: str) -> str:
        return _clean_text(value)

    @field_validator("title", "ad_copy")
    @classmethod
    def _required_copy(cls, value: str) -> str:
        return _require_text(value)

    @field_validator("link")
    @classmethod
    def _valid_link(cls, value: str) -> str:
        return _valid_http_url(value, "랜딩 URL")

    @field_validator("image_link")
    @classmethod
    def _valid_image_link(cls, value: str) -> str:
        return _valid_http_url(value, "이미지 URL")


class IntakeSubmission(BaseModel):
    ops_meta: OpsMeta = Field(..., alias="opsMeta")
    campaign: CampaignInfo
    adgroup: AdGroupInfo
    ads: list[AdInfo] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _valid_submission(self) -> "IntakeSubmission":
        if self.campaign.end_date and self.campaign.launch_date:
            if self.campaign.end_date < self.campaign.launch_date:
                raise ValueError("종료일은 시작일 이후여야 합니다.")
        if self.ops_meta.execution_route == "criteo" and self.campaign.objective != "views":
            raise ValueError("크리테오 경유는 CPM(Views) 목표만 선택할 수 있습니다.")

        title_max = 30 if self.ops_meta.execution_route == "criteo" else 24
        copy_max = 60 if self.ops_meta.execution_route == "criteo" else 48
        for index, ad in enumerate(self.ads, start=1):
            if len(ad.title) > title_max:
                raise ValueError(f"소재 {index}의 광고 제목은 최대 {title_max}자입니다.")
            if len(ad.ad_copy) > copy_max:
                raise ValueError(f"소재 {index}의 광고 설명은 최대 {copy_max}자입니다.")
        return self


def _receipt_number(now: datetime) -> str:
    day = now.strftime("%Y%m%d")
    with _RECEIPT_LOCK:
        next_number = _RECEIPT_COUNTERS.get(day, 0) + 1
        _RECEIPT_COUNTERS[day] = next_number
    return f"KT-OAI-{day}-{next_number:03d}"


def _enforce_spam_controls(submission: IntakeSubmission, client_key: str) -> None:
    if submission.ops_meta.honeypot:
        raise ValueError("스팸 제출로 판단되어 접수하지 않았습니다.")
    if submission.ops_meta.form_started_at:
        elapsed = int(time.time() * 1000) - int(submission.ops_meta.form_started_at)
        if elapsed < 2500:
            raise ValueError("제출이 너무 빠릅니다. 내용을 확인한 뒤 다시 제출해 주세요.")

    now = time.monotonic()
    last_submit = _LAST_SUBMIT_BY_IP.get(client_key)
    if last_submit and now - last_submit < _RATE_LIMIT_SECONDS:
        raise ValueError("연속 제출 간격이 너무 짧습니다. 잠시 후 다시 시도해 주세요.")
    _LAST_SUBMIT_BY_IP[client_key] = now


def build_sheet_payload(
    submission: IntakeSubmission,
    *,
    shared_secret: str,
) -> dict[str, Any]:
    adgroup_name = submission.adgroup.adgroup_name

    campaign = {
        "campaign_name": submission.campaign.campaign_name,
        "budget_max": _number_for_sheet(submission.campaign.budget_max),
        "budget_type": submission.campaign.budget_type,
        "launch_date": _date_for_sheet(submission.campaign.launch_date),
        "end_date": _date_for_sheet(submission.campaign.end_date),
        "objective": submission.campaign.objective,
        "target_countries": submission.campaign.target_countries,
    }
    adgroups = [{
        "adgroup_name": adgroup_name,
        "max_bid": _number_for_sheet(submission.adgroup.max_bid),
        "keywords": submission.adgroup.keywords,
    }]
    ads = [
        {
            "adgroup_name": adgroup_name,
            "title": ad.title,
            "copy": ad.ad_copy,
            "link": ad.link,
            "image_link": ad.image_link,
        }
        for ad in submission.ads
    ]
    ops = {
        "route": _route_label(submission.ops_meta.execution_route),
        "advertiser_name": submission.ops_meta.advertiser_name,
        "legal_name": submission.ops_meta.legal_name,
        "brn": submission.ops_meta.brn,
        "homepage": submission.ops_meta.advertiser_homepage_url,
        "invoice_email": submission.ops_meta.invoice_email,
        "contact_name": submission.ops_meta.contact_name,
        "contact_phone": submission.ops_meta.contact_phone,
        "contact_email": submission.ops_meta.contact_email,
        "sales_owner": submission.ops_meta.sales_owner,
        "ready_ads_manager": submission.ops_meta.ads_manager_ready,
        "ready_payment": submission.ops_meta.payment_ready,
        "ready_crawler": submission.ops_meta.crawler_ready,
        "ready_favicon": submission.ops_meta.favicon_ready,
        "note": submission.ops_meta.notes,
    }
    return {
        "secret": shared_secret,
        "data": {
            "campaign": campaign,
            "adgroups": adgroups,
            "ads": ads,
            "ops": ops,
        },
    }


async def forward_intake_to_sheet(
    submission: IntakeSubmission,
    *,
    client_key: str,
) -> dict[str, str]:
    _enforce_spam_controls(submission, client_key)

    webhook_url = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
    shared_secret = os.getenv("SHEETS_SHARED_SECRET", "").strip()
    if not webhook_url or not shared_secret:
        raise RuntimeError(
            "GOOGLE_SHEETS_WEBHOOK_URL 또는 SHEETS_SHARED_SECRET 환경변수가 설정되지 않았습니다."
        )

    now = datetime.now(KST)
    fallback_receipt_number = _receipt_number(now)
    fallback_submitted_at_kst = now.strftime("%Y-%m-%d %H:%M:%S")
    payload = build_sheet_payload(
        submission,
        shared_secret=shared_secret,
    )

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        response = await client.post(webhook_url, json=payload)
        if response.status_code >= 400:
            raise RuntimeError(f"Google Sheets 기록 실패(HTTP {response.status_code})")
        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {}
        if isinstance(response_payload, dict) and response_payload.get("ok") is False:
            error = response_payload.get("error") or "Apps Script가 접수를 거부했습니다."
            raise RuntimeError(f"Google Sheets 기록 실패({error})")

    return {
        "receipt_number": str(
            response_payload.get("receiptNumber")
            or response_payload.get("receipt_number")
            or fallback_receipt_number
        ),
        "submitted_at_kst": str(
            response_payload.get("submittedAtKst")
            or response_payload.get("submitted_at_kst")
            or fallback_submitted_at_kst
        ),
    }
