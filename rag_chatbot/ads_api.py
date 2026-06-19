from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
import json
import os
from typing import Any

import httpx


DEFAULT_BASE_URL = "https://api.ads.openai.com"
TIMEZONE = "Asia/Seoul"


@dataclass(frozen=True)
class AdsApiSettings:
    api_key: str
    base_url: str


def load_ads_api_settings(api_key: str | None = None) -> AdsApiSettings:
    return AdsApiSettings(
        api_key=(api_key or os.getenv("OPENAI_ADS_API_KEY") or "").strip(),
        base_url=(os.getenv("OPENAI_ADS_API_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/"),
    )


def default_date_range() -> tuple[str, str]:
    today = date.today()
    return ((today - timedelta(days=7)).isoformat(), today.isoformat())


def _as_number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _nested_get(row: dict[str, Any], path: str) -> Any:
    current: Any = row
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _lookup(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        candidates = [key]
        if "." in key:
            candidates.append(key.replace(".", "_"))
        for candidate in candidates:
            if candidate in row and row[candidate] not in (None, ""):
                return row[candidate]
        if "." in key:
            nested = _nested_get(row, key)
            if nested not in (None, ""):
                return nested
    return None


def _metric_from_row(row: dict[str, Any], key: str) -> float:
    return _as_number(
        _lookup(
            row,
            key,
            f"metrics.{key}",
            f"ad_account.{key}",
            f"campaign.{key}",
            f"ad_group.{key}",
            f"ad.{key}",
        )
    )


def _metric_from_any(row: dict[str, Any], keys: list[str]) -> float:
    for key in keys:
        raw = _lookup(
            row,
            key,
            f"metrics.{key}",
            f"ad_account.{key}",
            f"campaign.{key}",
            f"ad_group.{key}",
            f"ad.{key}",
        )
        if raw not in (None, ""):
            return _as_number(raw)
    return 0.0


def _row_identity(row: dict[str, Any], level: str) -> tuple[str, str]:
    prefix = "ad_group" if level == "ad_group" else level
    resource_id = str(_lookup(row, f"{prefix}.id", f"{prefix}_id", "id") or "")
    name = str(
        _lookup(row, f"{prefix}.name", f"{prefix}_name", "name")
        or _lookup(row, "ad.title", "ad_title", "title")
        or resource_id
        or "-"
    )
    return resource_id, name


def _row_value(row: dict[str, Any], level: str, key: str) -> Any:
    prefix = "ad_group" if level == "ad_group" else level
    return _lookup(row, f"{prefix}.{key}", f"{prefix}_{key}", key) or ""


def _normalize_row(row: dict[str, Any], level: str) -> dict[str, Any]:
    resource_id, name = _row_identity(row, level)
    impressions = _metric_from_row(row, "impressions")
    clicks = _metric_from_row(row, "clicks")
    spend = _metric_from_row(row, "spend")
    ctr = _metric_from_row(row, "ctr")
    cpc = _metric_from_row(row, "cpc")
    cpm = _metric_from_row(row, "cpm")
    conversions = _metric_from_any(
        row,
        [
            "conversions",
            "conversion_count",
            "total_conversions",
            "events",
            "event_count",
        ],
    )
    conversion_value = _metric_from_any(
        row,
        [
            "conversion_value",
            "conversions_value",
            "revenue",
            "purchase_value",
            "value",
        ],
    )
    conversion_rate = _metric_from_any(row, ["conversion_rate", "cvr"])
    cost_per_conversion = _metric_from_any(row, ["cost_per_conversion", "cpa"])
    roas = _metric_from_any(row, ["roas", "return_on_ad_spend"])
    if not ctr and impressions:
        ctr = clicks / impressions
    if not cpc and clicks:
        cpc = spend / clicks
    if not cpm and impressions:
        cpm = spend / impressions * 1000
    if not conversion_rate and clicks:
        conversion_rate = conversions / clicks
    if not cost_per_conversion and conversions:
        cost_per_conversion = spend / conversions
    if not roas and spend:
        roas = conversion_value / spend
    return {
        "id": resource_id,
        "name": name,
        "level": level,
        "impressions": int(impressions),
        "clicks": int(clicks),
        "spend": round(spend, 4),
        "ctr": round(ctr, 6),
        "cpc": round(cpc, 4),
        "cpm": round(cpm, 4),
        "conversions": round(conversions, 4),
        "conversion_value": round(conversion_value, 4),
        "conversion_rate": round(conversion_rate, 6),
        "cost_per_conversion": round(cost_per_conversion, 4),
        "roas": round(roas, 4),
        "status": _row_value(row, level, "status"),
        "review_status": _lookup(row, "ad.review_status", "ad_review_status", "review_status") or "",
        "campaign_id": _lookup(row, "campaign.id", "campaign_id") or "",
        "campaign_name": _lookup(row, "campaign.name", "campaign_name") or "",
        "ad_group_id": _lookup(row, "ad_group.id", "ad_group_id") or "",
        "ad_group_name": _lookup(row, "ad_group.name", "ad_group_name") or "",
        "raw": row,
    }


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    impressions = sum(int(row.get("impressions") or 0) for row in rows)
    clicks = sum(int(row.get("clicks") or 0) for row in rows)
    spend = sum(float(row.get("spend") or 0) for row in rows)
    conversions = sum(float(row.get("conversions") or 0) for row in rows)
    conversion_value = sum(float(row.get("conversion_value") or 0) for row in rows)
    return {
        "impressions": impressions,
        "clicks": clicks,
        "spend": round(spend, 4),
        "ctr": round(clicks / impressions, 6) if impressions else 0,
        "cpc": round(spend / clicks, 4) if clicks else 0,
        "cpm": round(spend / impressions * 1000, 4) if impressions else 0,
        "conversions": round(conversions, 4),
        "conversion_value": round(conversion_value, 4),
        "conversion_rate": round(conversions / clicks, 6) if clicks else 0,
        "cost_per_conversion": round(spend / conversions, 4) if conversions else 0,
        "roas": round(conversion_value / spend, 4) if spend else 0,
    }


class AdsInsightsClient:
    def __init__(self, settings: AdsApiSettings) -> None:
        self.settings = settings

    def _path(self, scope: str, resource_id: str | None = None) -> str:
        if scope == "ad_account":
            return "/v1/ad_account/insights"
        if scope == "campaign":
            return f"/v1/campaigns/{resource_id}/insights"
        if scope == "ad_group":
            return f"/v1/ad_groups/{resource_id}/insights"
        if scope == "ad":
            return f"/v1/ads/{resource_id}/insights"
        raise ValueError(f"Unsupported Ads insights scope: {scope}")

    async def insights(
        self,
        *,
        scope: str,
        aggregation_level: str,
        start_date: str,
        end_date: str,
        resource_id: str | None = None,
        fields: list[str] | None = None,
        filters: list[dict[str, Any]] | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        if scope != "ad_account" and not resource_id:
            raise ValueError("resource_id is required for non-account insights.")
        time_range = {
            "type": "date_range",
            "since": start_date,
            "until": end_date,
            "timezone": TIMEZONE,
        }
        params: list[tuple[str, str]] = [
            ("time_granularity", "none"),
            ("aggregation_level", aggregation_level),
            ("time_ranges[]", json.dumps(time_range, separators=(",", ":"))),
            ("limit", str(limit)),
        ]
        for field in fields or []:
            params.append(("fields[]", field))
        for filter_item in filters or []:
            params.append(("filters[]", json.dumps(filter_item, ensure_ascii=False, separators=(",", ":"))))

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.settings.base_url}{self._path(scope, resource_id)}",
                headers={
                    "Authorization": f"Bearer {self.settings.api_key}",
                    "Accept": "application/json",
                },
                params=params,
            )
        response.raise_for_status()
        return response.json()


ACCOUNT_FIELDS = [
    "ad_account.name",
    "ad_account.impressions",
    "ad_account.clicks",
    "ad_account.spend",
    "ad_account.ctr",
    "ad_account.cpc",
    "ad_account.cpm",
]

CAMPAIGN_FIELDS = [
    "campaign.id",
    "campaign.name",
    "campaign.status",
    "campaign.start_time",
    "campaign.end_time",
    "campaign.budget.lifetime",
    "campaign.budget.daily",
    "campaign.impressions",
    "campaign.clicks",
    "campaign.spend",
    "campaign.ctr",
    "campaign.cpc",
    "campaign.cpm",
]

AD_GROUP_FIELDS = [
    "campaign.id",
    "campaign.name",
    "ad_group.id",
    "ad_group.name",
    "ad_group.status",
    "ad_group.impressions",
    "ad_group.clicks",
    "ad_group.spend",
    "ad_group.ctr",
    "ad_group.cpc",
    "ad_group.cpm",
]

AD_FIELDS = [
    "campaign.id",
    "campaign.name",
    "ad_group.id",
    "ad_group.name",
    "ad.id",
    "ad.name",
    "ad.title",
    "ad.copy",
    "ad.link",
    "ad.status",
    "ad.review_status",
    "ad.impressions",
    "ad.clicks",
    "ad.spend",
    "ad.ctr",
    "ad.cpc",
    "ad.cpm",
]


CONVERSION_FIELD_SUFFIXES = [
    "conversions",
    "conversion_value",
    "conversion_rate",
    "cost_per_conversion",
    "roas",
]


def _with_conversion_fields(fields: list[str], prefix: str) -> list[str]:
    return [*fields, *[f"{prefix}.{suffix}" for suffix in CONVERSION_FIELD_SUFFIXES]]


ACCOUNT_FIELDS_WITH_CONVERSIONS = _with_conversion_fields(ACCOUNT_FIELDS, "ad_account")
CAMPAIGN_FIELDS_WITH_CONVERSIONS = _with_conversion_fields(CAMPAIGN_FIELDS, "campaign")
AD_GROUP_FIELDS_WITH_CONVERSIONS = _with_conversion_fields(AD_GROUP_FIELDS, "ad_group")
AD_FIELDS_WITH_CONVERSIONS = _with_conversion_fields(AD_FIELDS, "ad")


def _is_field_error(exc: httpx.HTTPStatusError) -> bool:
    return exc.response is not None and exc.response.status_code in {400, 422}


async def fetch_ads_dashboard(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    detail_scope: str | None = None,
    detail_id: str | None = None,
    api_key: str | None = None,
    advertiser_name: str | None = None,
) -> dict[str, Any]:
    settings = load_ads_api_settings(api_key=api_key)
    if not settings.api_key:
        return {
            "ok": False,
            "configured": False,
            "error": "광고주별 Ads API 키를 등록하거나 OPENAI_ADS_API_KEY 환경변수를 설정해 주세요.",
            "docs": {
                "overview": "https://developers.openai.com/ads/api-overview",
                "insights": "https://developers.openai.com/ads/api-reference/insights",
            },
        }

    default_start, default_end = default_date_range()
    start_date = start_date or default_start
    end_date = end_date or default_end
    client = AdsInsightsClient(settings)

    try:
        conversion_metrics_available = True
        try:
            account_payload, campaign_payload = await _fetch_account_and_campaigns(
                client,
                start_date,
                end_date,
                include_conversions=True,
            )
        except httpx.HTTPStatusError as exc:
            if not _is_field_error(exc):
                raise
            conversion_metrics_available = False
            account_payload, campaign_payload = await _fetch_account_and_campaigns(
                client,
                start_date,
                end_date,
                include_conversions=False,
            )
        account_rows = [_normalize_row(row, "ad_account") for row in account_payload.get("data", [])]
        campaign_rows = [_normalize_row(row, "campaign") for row in campaign_payload.get("data", [])]
        account_summary = account_rows[0] if account_rows else summarize_rows(campaign_rows)

        detail = None
        if detail_scope and detail_id:
            detail = await _fetch_detail(
                client,
                start_date,
                end_date,
                detail_scope,
                detail_id,
                include_conversions=conversion_metrics_available,
            )
            if detail.get("conversion_metrics_available") is False:
                conversion_metrics_available = False

        return {
            "ok": True,
            "configured": True,
            "advertiser_name": advertiser_name or "",
            "key_source": "advertiser" if api_key else "environment",
            "conversion_metrics_available": conversion_metrics_available,
            "range": {"start_date": start_date, "end_date": end_date, "timezone": TIMEZONE},
            "account": account_summary,
            "campaigns": campaign_rows,
            "campaign_total": summarize_rows(campaign_rows),
            "detail": detail,
            "docs": {
                "overview": "https://developers.openai.com/ads/api-overview",
                "insights": "https://developers.openai.com/ads/api-reference/insights",
            },
        }
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:1000] if exc.response is not None else ""
        return {
            "ok": False,
            "configured": True,
            "error": f"OpenAI Ads API 응답 오류: HTTP {exc.response.status_code}",
            "detail": detail,
        }
    except Exception as exc:
        return {
            "ok": False,
            "configured": True,
            "error": f"OpenAI Ads API 조회 중 오류가 발생했습니다: {exc}",
        }


async def _fetch_account_and_campaigns(
    client: AdsInsightsClient,
    start_date: str,
    end_date: str,
    *,
    include_conversions: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    account_fields = ACCOUNT_FIELDS_WITH_CONVERSIONS if include_conversions else ACCOUNT_FIELDS
    campaign_fields = CAMPAIGN_FIELDS_WITH_CONVERSIONS if include_conversions else CAMPAIGN_FIELDS
    return await asyncio.gather(
        client.insights(
            scope="ad_account",
            aggregation_level="ad_account",
            start_date=start_date,
            end_date=end_date,
            fields=account_fields,
            limit=1,
        ),
        client.insights(
            scope="ad_account",
            aggregation_level="campaign",
            start_date=start_date,
            end_date=end_date,
            fields=campaign_fields,
            limit=200,
        ),
    )


async def _fetch_detail(
    client: AdsInsightsClient,
    start_date: str,
    end_date: str,
    detail_scope: str,
    detail_id: str,
    *,
    include_conversions: bool,
) -> dict[str, Any]:
    if detail_scope == "campaign":
        level = "ad_group"
        fields = AD_GROUP_FIELDS_WITH_CONVERSIONS if include_conversions else AD_GROUP_FIELDS
        fallback_fields = AD_GROUP_FIELDS
    elif detail_scope == "ad_group":
        level = "ad"
        fields = AD_FIELDS_WITH_CONVERSIONS if include_conversions else AD_FIELDS
        fallback_fields = AD_FIELDS
    else:
        level = "ad"
        fields = AD_FIELDS_WITH_CONVERSIONS if include_conversions else AD_FIELDS
        fallback_fields = AD_FIELDS
    conversion_metrics_available = include_conversions
    try:
        payload = await client.insights(
            scope=detail_scope,
            resource_id=detail_id,
            aggregation_level=level,
            start_date=start_date,
            end_date=end_date,
            fields=fields,
            limit=200,
        )
    except httpx.HTTPStatusError as exc:
        if not include_conversions or not _is_field_error(exc):
            raise
        conversion_metrics_available = False
        payload = await client.insights(
            scope=detail_scope,
            resource_id=detail_id,
            aggregation_level=level,
            start_date=start_date,
            end_date=end_date,
            fields=fallback_fields,
            limit=200,
        )
    rows = [_normalize_row(row, level) for row in payload.get("data", [])]
    return {
        "scope": detail_scope,
        "id": detail_id,
        "aggregation_level": level,
        "rows": rows,
        "total": summarize_rows(rows),
        "conversion_metrics_available": conversion_metrics_available,
    }
