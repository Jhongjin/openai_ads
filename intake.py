from __future__ import annotations

from io import BytesIO
import json
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
    upload_mode: Literal["bulk_sheet", "campaigns", "adgroups", "ads"] = Field(
        default="bulk_sheet",
        alias="uploadMode",
    )
    execution_route: Literal["openai_cbt", "criteo"] = Field(..., alias="executionRoute")
    advertiser_name: str = Field(..., alias="advertiserName")
    ads_manager_account: str = Field(default="", alias="adsManagerAccount")

    submitter_name: str = Field(default="", alias="submitterName")
    submitter_email: str = Field(default="", alias="submitterEmail")
    sales_owner: str = Field(..., alias="salesOwner")
    image_policy: str = Field(default="direct_url_or_uploaded", alias="imagePolicy")
    notes: str = ""

    # Legacy booking fields are accepted for compatibility, but the new draft
    # page treats advertiser onboarding and billing as a separate workflow.
    legal_name: str = Field(default="", alias="legalName")
    brn: str = Field(default="", alias="brn")
    advertiser_homepage_url: str = Field(default="", alias="advertiserHomepageUrl")
    invoice_email: str = Field(default="", alias="invoiceEmail")
    contact_name: str = Field(default="", alias="contactName")
    contact_phone: str = Field(default="", alias="contactPhone")
    contact_email: str = Field(default="", alias="contactEmail")
    ads_manager_ready: bool = Field(default=False, alias="adsManagerReady")
    payment_ready: bool = Field(default=False, alias="paymentReady")
    crawler_ready: bool = Field(default=False, alias="crawlerReady")
    favicon_ready: bool = Field(default=False, alias="faviconReady")

    honeypot: str = ""
    form_started_at: int | None = Field(default=None, alias="formStartedAt")

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_contact_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        values = dict(values)
        if not values.get("submitterName") and values.get("contactName"):
            values["submitterName"] = values.get("contactName")
        if not values.get("submitterEmail") and values.get("contactEmail"):
            values["submitterEmail"] = values.get("contactEmail")
        if not values.get("adsManagerAccount") and values.get("advertiserName"):
            values["adsManagerAccount"] = values.get("advertiserName")
        return values

    @field_validator(
        "advertiser_name",
        "ads_manager_account",
        "submitter_name",
        "submitter_email",
        "sales_owner",
    )
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _require_text(value)

    @field_validator(
        "notes",
        "honeypot",
        "image_policy",
        "legal_name",
        "brn",
        "advertiser_homepage_url",
        "invoice_email",
        "contact_name",
        "contact_phone",
        "contact_email",
    )
    @classmethod
    def _optional_text(cls, value: str) -> str:
        return _clean_text(value)

    @field_validator("advertiser_homepage_url")
    @classmethod
    def _valid_homepage(cls, value: str) -> str:
        if not _clean_text(value):
            return ""
        return _valid_http_url(value, "advertiser 공식 홈페이지 URL")

    @field_validator("submitter_email", "invoice_email", "contact_email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        text = _clean_text(value)
        if not text:
            return ""
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

    @field_validator("max_bid", mode="before")
    @classmethod
    def _blank_max_bid(cls, value: Any) -> Any:
        if value == "":
            return None
        return value

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


class AdGroupSubmission(BaseModel):
    adgroup: AdGroupInfo
    ads: list[AdInfo] = Field(..., min_length=1)


class CampaignSubmission(BaseModel):
    campaign: CampaignInfo
    adgroups: list[AdGroupSubmission] = Field(..., min_length=1)


class IntakeSubmission(BaseModel):
    ops_meta: OpsMeta = Field(..., alias="opsMeta")
    campaigns: list[CampaignSubmission] = Field(..., min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_payload(cls, values: Any) -> Any:
        if not isinstance(values, dict) or values.get("campaigns"):
            return values
        campaign = values.get("campaign")
        adgroup = values.get("adgroup")
        ads = values.get("ads")
        if campaign and adgroup and ads:
            values = dict(values)
            values["campaigns"] = [{
                "campaign": campaign,
                "adgroups": [{
                    "adgroup": adgroup,
                    "ads": ads,
                }],
            }]
        return values

    @model_validator(mode="after")
    def _valid_submission(self) -> "IntakeSubmission":
        title_max = 30 if self.ops_meta.execution_route == "criteo" else 24
        copy_max = 60 if self.ops_meta.execution_route == "criteo" else 48
        campaign_names: set[str] = set()
        adgroup_names: set[str] = set()

        for campaign_index, campaign_item in enumerate(self.campaigns, start=1):
            campaign = campaign_item.campaign
            if campaign.campaign_name in campaign_names:
                raise ValueError(f"캠페인명 '{campaign.campaign_name}'이 중복되었습니다.")
            campaign_names.add(campaign.campaign_name)

            if campaign.end_date and campaign.launch_date:
                if campaign.end_date < campaign.launch_date:
                    raise ValueError(f"캠페인 {campaign_index}의 종료일은 시작일 이후여야 합니다.")
            if self.ops_meta.execution_route == "criteo" and campaign.objective != "views":
                raise ValueError("크리테오 경유는 CPM(Views) 목표만 선택할 수 있습니다.")

            for group_index, group_item in enumerate(campaign_item.adgroups, start=1):
                adgroup_name = group_item.adgroup.adgroup_name
                if adgroup_name in adgroup_names:
                    raise ValueError(f"광고그룹명 '{adgroup_name}'이 중복되었습니다.")
                adgroup_names.add(adgroup_name)

                for ad_index, ad in enumerate(group_item.ads, start=1):
                    label = f"캠페인 {campaign_index} / 광고그룹 {group_index} / 소재 {ad_index}"
                    if len(ad.title) > title_max:
                        raise ValueError(f"{label}의 광고 제목은 최대 {title_max}자입니다.")
                    if len(ad.ad_copy) > copy_max:
                        raise ValueError(f"{label}의 광고 설명은 최대 {copy_max}자입니다.")
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
    campaigns: list[dict[str, Any]] = []
    adgroups: list[dict[str, Any]] = []
    ads: list[dict[str, Any]] = []

    for campaign_item in submission.campaigns:
        campaign_name = campaign_item.campaign.campaign_name
        campaigns.append({
            "campaign_name": campaign_name,
            "budget_max": _number_for_sheet(campaign_item.campaign.budget_max),
            "budget_type": campaign_item.campaign.budget_type,
            "launch_date": _date_for_sheet(campaign_item.campaign.launch_date),
            "end_date": _date_for_sheet(campaign_item.campaign.end_date),
            "objective": campaign_item.campaign.objective,
            "target_countries": campaign_item.campaign.target_countries,
        })
        for group_item in campaign_item.adgroups:
            adgroup_name = group_item.adgroup.adgroup_name
            adgroups.append({
                "campaign_name": campaign_name,
                "adgroup_name": adgroup_name,
                "max_bid": _number_for_sheet(group_item.adgroup.max_bid),
                "keywords": group_item.adgroup.keywords,
            })
            ads.extend(
                {
                    "adgroup_name": adgroup_name,
                    "title": ad.title,
                    "copy": ad.ad_copy,
                    "link": ad.link,
                    "image_link": ad.image_link,
                }
                for ad in group_item.ads
            )

    primary_campaign = campaigns[0]
    ops = {
        "upload_mode": submission.ops_meta.upload_mode,
        "route": _route_label(submission.ops_meta.execution_route),
        "advertiser_name": submission.ops_meta.advertiser_name,
        "ads_manager_account": submission.ops_meta.ads_manager_account,
        "submitter_name": submission.ops_meta.submitter_name,
        "submitter_email": submission.ops_meta.submitter_email,
        "sales_owner": submission.ops_meta.sales_owner,
        "image_policy": submission.ops_meta.image_policy,
        "note": submission.ops_meta.notes,
        "legal_name": submission.ops_meta.legal_name,
        "brn": submission.ops_meta.brn,
        "homepage": submission.ops_meta.advertiser_homepage_url,
        "invoice_email": submission.ops_meta.invoice_email,
    }
    return {
        "secret": shared_secret,
        "data": {
            "campaign": primary_campaign,
            "campaigns": campaigns,
            "adgroups": adgroups,
            "ads": ads,
            "ops": ops,
        },
    }


WORKBOOK_COLUMNS = {
    "campaigns": [
        "campaign_name",
        "budget_max",
        "budget_type",
        "launch_date",
        "end_date",
        "objective",
        "target_countries",
    ],
    "adgroups": ["campaign_name", "adgroup_name", "max_bid", "keywords"],
    "ads": ["adgroup_name", "title", "copy", "link", "image_link"],
}


def _sheet_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else value


def create_workbook_bytes(submission: IntakeSubmission) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    sheet_payload = build_sheet_payload(submission, shared_secret="workbook")
    data = sheet_payload["data"]
    wb = Workbook()
    default = wb.active
    wb.remove(default)
    header_fill = PatternFill("solid", fgColor="1F2937")
    header_font = Font(color="FFFFFF", bold=True)

    for sheet_name in ("campaigns", "adgroups", "ads"):
        ws = wb.create_sheet(sheet_name)
        columns = WORKBOOK_COLUMNS[sheet_name]
        ws.append(columns)
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
        for row in data[sheet_name]:
            ws.append([_sheet_value(row.get(column)) for column in columns])
        for column_cells in ws.columns:
            max_length = max(len(str(cell.value or "")) for cell in column_cells)
            ws.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 14), 44)

    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def inspect_workbook_bytes(content: bytes) -> dict[str, Any]:
    from openpyxl import load_workbook

    errors: list[str] = []
    summary: dict[str, Any] = {"sheets": {}, "errors": errors}
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    for sheet_name, required_columns in WORKBOOK_COLUMNS.items():
        if sheet_name not in workbook.sheetnames:
            errors.append(f"{sheet_name} 시트가 없습니다.")
            continue
        ws = workbook[sheet_name]
        header = [str(cell.value or "").strip() for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        missing = [column for column in required_columns if column not in header]
        if missing:
            errors.append(f"{sheet_name} 시트에 필수 컬럼이 없습니다: {', '.join(missing)}")
        rows = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            first = str(row[0] or "").strip()
            if not any(cell not in (None, "") for cell in row):
                continue
            if first in {"Required"} or first.startswith("How we will") or first.startswith("The "):
                continue
            if first.startswith("oaitest"):
                continue
            rows += 1
        summary["sheets"][sheet_name] = {
            "columns": header,
            "rows": rows,
            "missing_columns": missing,
        }
    summary["ok"] = not errors
    return summary


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
