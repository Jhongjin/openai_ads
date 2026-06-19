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


def load_ads_api_settings() -> AdsApiSettings:
    return AdsApiSettings(
        api_key=(os.getenv("OPENAI_ADS_API_KEY") or "").strip(),
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
    if not ctr and impressions:
        ctr = clicks / impressions
    if not cpc and clicks:
        cpc = spend / clicks
    if not cpm and impressions:
        cpm = spend / impressions * 1000
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
    return {
        "impressions": impressions,
        "clicks": clicks,
        "spend": round(spend, 4),
        "ctr": round(clicks / impressions, 6) if impressions else 0,
        "cpc": round(spend / clicks, 4) if clicks else 0,
        "cpm": round(spend / impressions * 1000, 4) if impressions else 0,
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


async def fetch_ads_dashboard(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    detail_scope: str | None = None,
    detail_id: str | None = None,
) -> dict[str, Any]:
    settings = load_ads_api_settings()
    if not settings.api_key:
        return {
            "ok": False,
            "configured": False,
            "error": "OPENAI_ADS_API_KEY 환경변수가 설정되어 있지 않습니다.",
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
        account_payload, campaign_payload = await _fetch_account_and_campaigns(client, start_date, end_date)
        account_rows = [_normalize_row(row, "ad_account") for row in account_payload.get("data", [])]
        campaign_rows = [_normalize_row(row, "campaign") for row in campaign_payload.get("data", [])]
        account_summary = account_rows[0] if account_rows else summarize_rows(campaign_rows)

        detail = None
        if detail_scope and detail_id:
            detail = await _fetch_detail(client, start_date, end_date, detail_scope, detail_id)

        return {
            "ok": True,
            "configured": True,
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
) -> tuple[dict[str, Any], dict[str, Any]]:
    return await asyncio.gather(
        client.insights(
            scope="ad_account",
            aggregation_level="ad_account",
            start_date=start_date,
            end_date=end_date,
            fields=ACCOUNT_FIELDS,
            limit=1,
        ),
        client.insights(
            scope="ad_account",
            aggregation_level="campaign",
            start_date=start_date,
            end_date=end_date,
            fields=CAMPAIGN_FIELDS,
            limit=200,
        ),
    )


async def _fetch_detail(
    client: AdsInsightsClient,
    start_date: str,
    end_date: str,
    detail_scope: str,
    detail_id: str,
) -> dict[str, Any]:
    if detail_scope == "campaign":
        level = "ad_group"
        fields = AD_GROUP_FIELDS
    elif detail_scope == "ad_group":
        level = "ad"
        fields = AD_FIELDS
    else:
        level = "ad"
        fields = AD_FIELDS
    payload = await client.insights(
        scope=detail_scope,
        resource_id=detail_id,
        aggregation_level=level,
        start_date=start_date,
        end_date=end_date,
        fields=fields,
        limit=200,
    )
    rows = [_normalize_row(row, level) for row in payload.get("data", [])]
    return {
        "scope": detail_scope,
        "id": detail_id,
        "aggregation_level": level,
        "rows": rows,
        "total": summarize_rows(rows),
    }
