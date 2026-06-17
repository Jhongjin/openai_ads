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
_RECEIPT_LOCK = threading.Lock()
_RECEIPT_COUNTERS: dict[str, int] = {}
_RATE_LIMIT_SECONDS = 10
_LAST_SUBMIT_BY_IP: dict[str, float] = {}


class IntakeSubmission(BaseModel):
    advertiser_name: str = Field(..., alias="advertiserName")
    legal_name: str = Field(..., alias="legalName")
    website_url: str = Field(..., alias="websiteUrl")
    target_country: str = Field(default="대한민국", alias="targetCountry")
    billing_currency: Literal["KRW", "USD"] = Field(default="KRW", alias="billingCurrency")
    timezone: str = Field(default="Asia/Seoul", alias="timezone")
    invoice_email: str = Field(default="", alias="invoiceEmail")

    execution_route: Literal["openai_cbt", "criteo"] = Field(..., alias="executionRoute")
    campaign_name: str = Field(..., alias="campaignName")
    campaign_objective: Literal["views", "clicks"] = Field(..., alias="campaignObjective")
    budget_type: Literal["total", "daily"] = Field(..., alias="budgetType")
    budget_amount: float = Field(..., alias="budgetAmount")
    start_date: date = Field(..., alias="startDate")
    end_date: date = Field(..., alias="endDate")

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
        "website_url",
        "target_country",
        "timezone",
        "campaign_name",
        "contact_name",
        "contact_phone",
        "contact_email",
        "sales_owner",
    )
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("필수값이 비어 있습니다.")
        return text

    @field_validator("invoice_email", "notes", "honeypot")
    @classmethod
    def _optional_text(cls, value: str) -> str:
        return str(value or "").strip()

    @field_validator("website_url")
    @classmethod
    def _valid_website(cls, value: str) -> str:
        lowered = value.lower()
        if not lowered.startswith(("http://", "https://")):
            raise ValueError("광고주 웹사이트 URL은 http:// 또는 https://로 시작해야 합니다.")
        return value

    @field_validator("contact_email", "invoice_email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        if value and not _EMAIL_RE.match(value):
            raise ValueError("이메일 형식이 올바르지 않습니다.")
        return value

    @field_validator("budget_amount")
    @classmethod
    def _valid_budget(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("예산 금액은 0보다 커야 합니다.")
        return value

    @model_validator(mode="after")
    def _valid_dates_and_route(self) -> "IntakeSubmission":
        today = datetime.now(KST).date()
        if self.start_date < today:
            raise ValueError("시작일은 오늘 이후여야 합니다.")
        if self.end_date < self.start_date:
            raise ValueError("종료일은 시작일 이후여야 합니다.")
        if self.execution_route == "criteo" and self.campaign_objective != "views":
            raise ValueError("크리테오 경유는 CPM(Views) 목표만 선택할 수 있습니다.")
        return self


def _receipt_number(now: datetime) -> str:
    day = now.strftime("%Y%m%d")
    with _RECEIPT_LOCK:
        next_number = _RECEIPT_COUNTERS.get(day, 0) + 1
        _RECEIPT_COUNTERS[day] = next_number
    return f"KT-OAI-{day}-{next_number:03d}"


def _enforce_spam_controls(submission: IntakeSubmission, client_key: str) -> None:
    if submission.honeypot:
        raise ValueError("스팸 제출로 판단되어 접수하지 않았습니다.")
    if submission.form_started_at:
        elapsed = int(time.time() * 1000) - int(submission.form_started_at)
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
    receipt_number: str,
    submitted_at_kst: str,
    shared_secret: str,
) -> dict[str, Any]:
    data = submission.model_dump(by_alias=True, exclude={"honeypot", "form_started_at"})
    data.update(
        {
            "shared_secret": shared_secret,
            "receiptNumber": receipt_number,
            "submittedAtKst": submitted_at_kst,
            "budgetAmount": int(submission.budget_amount)
            if submission.budget_amount.is_integer()
            else submission.budget_amount,
            "readyStatus": {
                "adsManagerReady": submission.ads_manager_ready,
                "paymentReady": submission.payment_ready,
                "crawlerReady": submission.crawler_ready,
                "faviconReady": submission.favicon_ready,
            },
        }
    )
    return data


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
    receipt_number = _receipt_number(now)
    submitted_at_kst = now.strftime("%Y-%m-%d %H:%M:%S")
    payload = build_sheet_payload(
        submission,
        receipt_number=receipt_number,
        submitted_at_kst=submitted_at_kst,
        shared_secret=shared_secret,
    )

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        response = await client.post(webhook_url, json=payload)
        if response.status_code >= 400:
            raise RuntimeError(f"Google Sheets 기록 실패(HTTP {response.status_code})")

    return {
        "receipt_number": receipt_number,
        "submitted_at_kst": submitted_at_kst,
    }
