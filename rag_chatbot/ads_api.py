from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import os
from typing import Any
from zoneinfo import ZoneInfo

import httpx


DEFAULT_BASE_URL = "https://api.ads.openai.com"
TIMEZONE = "Asia/Seoul"
DEFAULT_ADVERTISER_FETCH_TIMEOUT = 10.0
DEFAULT_ADVERTISER_FETCH_CONCURRENCY = 8
DEFAULT_AGGREGATE_FETCH_TIMEOUT = 30.0
DEFAULT_AGGREGATE_ADVERTISER_LIMIT = 100
DEFAULT_LIVE_STATUS_FETCH_TIMEOUT = 8.0
DEFAULT_LIVE_STATUS_FETCH_CONCURRENCY = 12
DEFAULT_LIVE_STATUS_AGGREGATE_TIMEOUT = 20.0


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


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
            f"product.{key}",
            f"country.{key}",
            f"device.{key}",
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


CAMPAIGN_OBJECTIVE_KEYS = (
    "campaign.objective",
    "campaign_objective",
    "campaign.goal",
    "campaign_goal",
    "campaign.optimization_goal",
    "campaign_optimization_goal",
    "campaign.delivery_goal",
    "campaign_delivery_goal",
    "objective",
    "goal",
    "optimization_goal",
    "delivery_goal",
)


def _campaign_objective_value(row: dict[str, Any]) -> str:
    value = _lookup(row, *CAMPAIGN_OBJECTIVE_KEYS)
    return str(value or "").strip()


def _campaign_metadata_by_id(campaigns: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(_lookup(campaign, "campaign.id", "campaign_id", "id") or ""): campaign
        for campaign in campaigns
        if _lookup(campaign, "campaign.id", "campaign_id", "id")
    }


def _merge_campaign_metadata(
    row: dict[str, Any],
    campaign_metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    campaign_id = str(_lookup(row, "campaign.id", "campaign_id", "id") or "")
    metadata = campaign_metadata.get(campaign_id)
    if not metadata:
        return row
    merged = dict(row)
    existing_campaign = merged.get("campaign") if isinstance(merged.get("campaign"), dict) else {}
    merged["campaign"] = {**metadata, **existing_campaign}
    objective = _campaign_objective_value(metadata)
    if objective and not _campaign_objective_value(merged):
        merged["campaign_objective"] = objective
    return merged


async def _fetch_campaign_metadata_by_id(client: "AdsInsightsClient") -> dict[str, dict[str, Any]]:
    campaigns: list[dict[str, Any]] = []
    after: str | None = None
    while True:
        payload = await client.list_campaigns(limit=500, after=after)
        campaigns.extend(payload.get("data") or [])
        if not payload.get("has_more"):
            break
        after = str(payload.get("last_id") or "")
        if not after:
            break
    return _campaign_metadata_by_id(campaigns)


def _format_ads_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        timestamp = float(value)
        if timestamp > 0:
            return datetime.fromtimestamp(timestamp, ZoneInfo(TIMEZONE)).date().isoformat()
    except (TypeError, ValueError, OSError):
        pass
    text = str(value).strip()
    return text[:10] if text else ""


def _micros_to_money(value: Any) -> float:
    number = _as_number(value)
    return round(number / 1_000_000, 4) if number else 0.0


def _is_cpm_bid_event(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return any(token in text for token in ("impression", "cpm", "view", "views", "reach", "노출", "도달"))


def _bid_value_to_money(value: Any, *, billing_event_type: Any = "") -> float:
    """Normalize bid fields that may arrive as KRW or micros depending on source."""

    number = _as_number(value)
    if not number:
        return 0.0
    if number >= 1_000_000:
        number = number / 1_000_000
    if _is_cpm_bid_event(billing_event_type) and 0 < number < 1000:
        number *= 1000
    return round(number, 4)


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
    daily_budget = _metric_from_any(
        row,
        [
            "campaign.budget.daily",
            "budget.daily",
            "campaign_daily_budget",
            "daily_budget",
        ],
    ) or _micros_to_money(
        _lookup(
            row,
            "campaign.budget.daily_spend_limit_micros",
            "budget.daily_spend_limit_micros",
            "campaign_daily_spend_limit_micros",
            "daily_spend_limit_micros",
        )
    )
    lifetime_budget = _metric_from_any(
        row,
        [
            "campaign.budget.lifetime",
            "budget.lifetime",
            "campaign_lifetime_budget",
            "lifetime_budget",
        ],
    ) or _micros_to_money(
        _lookup(
            row,
            "campaign.budget.lifetime_spend_limit_micros",
            "budget.lifetime_spend_limit_micros",
            "campaign_lifetime_spend_limit_micros",
            "lifetime_spend_limit_micros",
        )
    )
    billing_event_type = str(
        _lookup(
            row,
            "ad_group.bidding_config.billing_event_type",
            "bidding_config.billing_event_type",
            "ad_group_billing_event_type",
            "billing_event_type",
        )
        or ""
    )
    max_bid = _bid_value_to_money(
        _lookup(
            row,
            "ad_group.bidding_config.max_bid",
            "bidding_config.max_bid",
            "ad_group.max_bid",
            "max_bid",
        ),
        billing_event_type=billing_event_type,
    ) or _bid_value_to_money(
        _lookup(
            row,
            "ad_group.bidding_config.max_bid_micros",
            "bidding_config.max_bid_micros",
            "ad_group_max_bid_micros",
            "max_bid_micros",
        ),
        billing_event_type=billing_event_type,
    )
    budget_type = "daily" if daily_budget else ("lifetime" if lifetime_budget else "")
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
        "objective": _campaign_objective_value(row),
        "start_date": _format_ads_date(_row_value(row, level, "start_time") or _lookup(row, "start_time")),
        "end_date": _format_ads_date(_row_value(row, level, "end_time") or _lookup(row, "end_time")),
        "daily_budget": round(daily_budget, 4),
        "lifetime_budget": round(lifetime_budget, 4),
        "budget_type": budget_type,
        "max_bid": round(max_bid, 4),
        "billing_event_type": billing_event_type,
        "review_status": _lookup(row, "ad.review_status", "ad_review_status", "review_status") or "",
        "campaign_id": _lookup(row, "campaign.id", "campaign_id") or "",
        "campaign_name": _lookup(row, "campaign.name", "campaign_name") or "",
        "ad_group_id": _lookup(row, "ad_group.id", "ad_group_id") or "",
        "ad_group_name": _lookup(row, "ad_group.name", "ad_group_name") or "",
        "raw": row,
    }


def _detail_metadata_row(item: dict[str, Any], level: str, *, parent_id: str = "") -> dict[str, Any]:
    if level == "ad_group":
        row = _normalize_row({"ad_group": item, "campaign": {"id": parent_id}}, level)
        row["campaign_id"] = row.get("campaign_id") or parent_id
        return row
    row = _normalize_row({"ad": item, "ad_group": {"id": parent_id}}, level)
    row["ad_group_id"] = row.get("ad_group_id") or parent_id
    return row


def _merge_detail_metadata(rows: list[dict[str, Any]], metadata_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not metadata_rows:
        return rows

    rows_by_id = {
        str(row.get("id") or ""): row
        for row in rows
        if row.get("id")
    }
    merged_rows: list[dict[str, Any]] = []
    metadata_keys = (
        "name",
        "status",
        "objective",
        "start_date",
        "end_date",
        "daily_budget",
        "lifetime_budget",
        "budget_type",
        "max_bid",
        "billing_event_type",
        "review_status",
        "campaign_id",
        "campaign_name",
        "ad_group_id",
        "ad_group_name",
    )

    for metadata_row in metadata_rows:
        row_id = str(metadata_row.get("id") or "")
        insight_row = rows_by_id.pop(row_id, None)
        if not insight_row:
            merged_rows.append(metadata_row)
            continue
        merged = {**metadata_row, **insight_row}
        for key in metadata_keys:
            if merged.get(key) in (None, "", 0) and metadata_row.get(key) not in (None, "", 0):
                merged[key] = metadata_row[key]
        merged["raw"] = {
            "metadata": metadata_row.get("raw", {}),
            "insights": insight_row.get("raw", {}),
        }
        merged_rows.append(merged)

    merged_rows.extend(rows_by_id.values())
    return merged_rows


def _active_status(value: Any) -> bool:
    return str(value or "").strip().lower() in {"active", "enabled", "live", "라이브", "활성"}


def _row_time_label(row: dict[str, Any], *, granularity: str = "date") -> str:
    readable = _lookup(row, "metadata.readable_time", "readable_time")
    if readable:
        return str(readable)
    start_time = _lookup(row, "start_time")
    try:
        parsed = datetime.fromtimestamp(float(start_time), ZoneInfo(TIMEZONE))
        if granularity == "hour":
            return parsed.strftime("%Y-%m-%dT%H")
        return parsed.date().isoformat()
    except (TypeError, ValueError, OSError):
        return str(start_time or "")


def _normalize_trend_rows(rows: list[dict[str, Any]], level: str = "ad_account") -> list[dict[str, Any]]:
    trend: list[dict[str, Any]] = []
    for row in rows:
        normalized = _normalize_row(row, level)
        trend.append(
            {
                "date": _row_time_label(row),
                "spend": normalized["spend"],
                "impressions": normalized["impressions"],
                "clicks": normalized["clicks"],
                "ctr": normalized["ctr"],
                "cpc": normalized["cpc"],
                "cpm": normalized["cpm"],
            }
        )
    return trend


def _normalize_hourly_rows(rows: list[dict[str, Any]], level: str = "campaign") -> list[dict[str, Any]]:
    hourly: list[dict[str, Any]] = []
    for row in rows:
        normalized = _normalize_row(row, level)
        hour = _row_time_label(row, granularity="hour")
        hourly.append(
            {
                "hour": hour,
                "date": hour[:10] if len(hour) >= 10 else "",
                "hour_of_day": int(hour[11:13]) if len(hour) >= 13 and hour[11:13].isdigit() else None,
                "spend": normalized["spend"],
                "impressions": normalized["impressions"],
                "clicks": normalized["clicks"],
                "ctr": normalized["ctr"],
                "cpc": normalized["cpc"],
                "cpm": normalized["cpm"],
            }
        )
    return sorted(hourly, key=lambda item: str(item.get("hour") or ""))


def _normalize_device_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for row in rows:
        device_type = str(_lookup(row, "device.type", "device_type", "type") or "unknown")
        devices.append(
            {
                "device": device_type,
                "impressions": int(_metric_from_row(row, "impressions")),
                "clicks": int(_metric_from_row(row, "clicks")),
                "spend": round(_metric_from_row(row, "spend"), 4),
                "ctr": round(_metric_from_row(row, "ctr"), 6),
                "cpc": round(_metric_from_row(row, "cpc"), 4),
                "cpm": round(_metric_from_row(row, "cpm"), 4),
            }
        )
    total_impressions = sum(item["impressions"] for item in devices)
    for item in devices:
        item["impression_share"] = round(item["impressions"] / total_impressions, 6) if total_impressions else 0
    return devices


def _aggregate_trend(results: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, Any]] = {}
    for rows in results:
        for row in rows:
            key = str(row.get("date") or "")
            if not key:
                continue
            target = by_date.setdefault(key, {"date": key, "spend": 0.0, "impressions": 0, "clicks": 0})
            target["spend"] += float(row.get("spend") or 0)
            target["impressions"] += int(row.get("impressions") or 0)
            target["clicks"] += int(row.get("clicks") or 0)
    trend = []
    for row in sorted(by_date.values(), key=lambda item: item["date"]):
        spend = float(row["spend"])
        impressions = int(row["impressions"])
        clicks = int(row["clicks"])
        trend.append(
            {
                "date": row["date"],
                "spend": round(spend, 4),
                "impressions": impressions,
                "clicks": clicks,
                "ctr": round(clicks / impressions, 6) if impressions else 0,
                "cpc": round(spend / clicks, 4) if clicks else 0,
                "cpm": round(spend / impressions * 1000, 4) if impressions else 0,
            }
        )
    return trend


def _aggregate_devices(results: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    by_device: dict[str, dict[str, Any]] = {}
    for rows in results:
        for row in rows:
            key = str(row.get("device") or "unknown")
            target = by_device.setdefault(key, {"device": key, "spend": 0.0, "impressions": 0, "clicks": 0})
            target["spend"] += float(row.get("spend") or 0)
            target["impressions"] += int(row.get("impressions") or 0)
            target["clicks"] += int(row.get("clicks") or 0)
    total_impressions = sum(item["impressions"] for item in by_device.values())
    devices = []
    for row in sorted(by_device.values(), key=lambda item: item["impressions"], reverse=True):
        spend = float(row["spend"])
        impressions = int(row["impressions"])
        clicks = int(row["clicks"])
        devices.append(
            {
                "device": row["device"],
                "spend": round(spend, 4),
                "impressions": impressions,
                "clicks": clicks,
                "ctr": round(clicks / impressions, 6) if impressions else 0,
                "cpc": round(spend / clicks, 4) if clicks else 0,
                "cpm": round(spend / impressions * 1000, 4) if impressions else 0,
                "impression_share": round(impressions / total_impressions, 6) if total_impressions else 0,
            }
        )
    return devices


def build_benchmarks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        industry = str(row.get("industry") or "미지정")
        objective = str(row.get("objective") or "-")
        groups.setdefault(("industry_objective", industry, objective), []).append(row)
        groups.setdefault(("industry", industry, "전체"), []).append(row)
        groups.setdefault(("objective", "전체", objective), []).append(row)
    benchmarks = []
    order = {"industry_objective": 0, "industry": 1, "objective": 2}
    for (benchmark_type, industry, objective), group_rows in sorted(
        groups.items(),
        key=lambda item: (order.get(item[0][0], 9), item[0][1], item[0][2]),
    ):
        total = summarize_rows(group_rows)
        benchmarks.append(
            {
                "type": benchmark_type,
                "industry": industry,
                "objective": objective,
                "campaign_count": len(group_rows),
                "impressions": total["impressions"],
                "clicks": total["clicks"],
                "spend": total["spend"],
                "ctr": total["ctr"],
                "cpc": total["cpc"],
                "cpm": total["cpm"],
            }
        )
    return benchmarks


def _override_map_key(advertiser_name: Any, campaign_id: Any) -> str:
    return f"{str(advertiser_name or '').strip()}\u241f{str(campaign_id or '').strip()}"


def apply_campaign_objective_overrides(
    payload: dict[str, Any],
    overrides: dict[str, str] | None,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or not overrides:
        return payload
    campaigns = payload.get("campaigns")
    if not isinstance(campaigns, list):
        return payload
    changed = False
    for row in campaigns:
        if not isinstance(row, dict):
            continue
        campaign_id = row.get("id") or row.get("campaign_id")
        advertiser_name = row.get("advertiser_name") or payload.get("advertiser_name")
        objective = overrides.get(_override_map_key(advertiser_name, campaign_id))
        if objective:
            row["objective"] = objective
            row["objective_source"] = "manual"
            changed = True
    if changed:
        payload["benchmarks"] = build_benchmarks(campaigns)
    return payload


def live_advertiser_count(rows: list[dict[str, Any]]) -> int:
    return len(live_advertiser_names(rows))


def live_advertiser_names(rows: list[dict[str, Any]]) -> list[str]:
    names = {
        str(row.get("advertiser_name") or row.get("name") or "").strip()
        for row in rows
        if _active_status(row.get("status"))
    }
    return sorted((name for name in names if name), key=lambda value: value.lower())


def _campaign_timestamp(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _campaign_is_live(campaign: dict[str, Any], *, now_ts: float | None = None) -> bool:
    if not _active_status(campaign.get("status")):
        return False
    now_ts = now_ts or datetime.now(ZoneInfo(TIMEZONE)).timestamp()
    start_ts = _campaign_timestamp(campaign.get("start_time"))
    end_ts = _campaign_timestamp(campaign.get("end_time"))
    if start_ts is not None and start_ts > now_ts:
        return False
    if end_ts is not None and end_ts < now_ts:
        return False
    return True


def _empty_live_status_snapshot(total_advertisers: int) -> dict[str, Any]:
    return {
        "live_advertiser_count": 0,
        "live_advertisers": [],
        "live_campaign_count": 0,
        "live_status_complete": False,
        "live_status_checked_advertiser_count": 0,
        "live_status_failed_advertisers": [],
        "live_status_total_advertisers": total_advertisers,
    }


async def fetch_live_status_snapshot_for_advertisers(
    advertisers: list[dict[str, str]],
) -> dict[str, Any]:
    """Fetch lightweight campaign status for all advertiser keys.

    Insights can be slow and partial across many ad accounts. This status pass uses
    the Campaigns list endpoint so live counts are not coupled to performance rows.
    """

    credentials = [
        {
            "advertiser_name": str(item.get("advertiser_name") or "").strip(),
            "api_key": str(item.get("api_key") or "").strip(),
        }
        for item in advertisers
        if str(item.get("api_key") or "").strip()
    ]
    if not credentials:
        return _empty_live_status_snapshot(0)

    concurrency = max(
        1,
        int(_env_float("OPENAI_ADS_LIVE_STATUS_FETCH_CONCURRENCY", DEFAULT_LIVE_STATUS_FETCH_CONCURRENCY)),
    )
    request_timeout = _env_float("OPENAI_ADS_LIVE_STATUS_FETCH_TIMEOUT", DEFAULT_LIVE_STATUS_FETCH_TIMEOUT)
    aggregate_timeout = _env_float(
        "OPENAI_ADS_LIVE_STATUS_AGGREGATE_TIMEOUT",
        DEFAULT_LIVE_STATUS_AGGREGATE_TIMEOUT,
    )
    semaphore = asyncio.Semaphore(concurrency)
    now_ts = datetime.now(ZoneInfo(TIMEZONE)).timestamp()

    async def fetch_one(index: int, item: dict[str, str]) -> tuple[int, dict[str, Any]]:
        async with semaphore:
            try:
                client = AdsInsightsClient(load_ads_api_settings(api_key=item["api_key"]))
                campaigns: list[dict[str, Any]] = []
                after: str | None = None
                while True:
                    payload = await asyncio.wait_for(
                        client.list_campaigns(limit=500, after=after),
                        timeout=request_timeout,
                    )
                    campaigns.extend(payload.get("data") or [])
                    if not payload.get("has_more"):
                        break
                    after = str(payload.get("last_id") or "")
                    if not after:
                        break
                live_campaigns = [campaign for campaign in campaigns if _campaign_is_live(campaign, now_ts=now_ts)]
                return index, {
                    "ok": True,
                    "advertiser_name": item["advertiser_name"],
                    "live_campaign_count": len(live_campaigns),
                    "campaign_metadata": _campaign_metadata_by_id(campaigns),
                }
            except asyncio.TimeoutError:
                return index, {
                    "ok": False,
                    "advertiser_name": item["advertiser_name"],
                    "error": f"라이브 상태 조회 시간이 {request_timeout:g}초를 초과했습니다.",
                }
            except Exception as exc:
                return index, {
                    "ok": False,
                    "advertiser_name": item["advertiser_name"],
                    "error": str(exc) or "라이브 상태 조회 실패",
                }

    results: list[dict[str, Any]] = [
        {
            "ok": False,
            "advertiser_name": item["advertiser_name"],
            "error": f"라이브 상태 전체 제한 시간 {aggregate_timeout:g}초 안에 응답하지 않았습니다.",
        }
        for item in credentials
    ]
    tasks = [asyncio.create_task(fetch_one(index, item)) for index, item in enumerate(credentials)]
    try:
        for future in asyncio.as_completed(tasks, timeout=aggregate_timeout):
            index, result = await future
            results[index] = result
    except asyncio.TimeoutError:
        pass
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()

    ok_results = [result for result in results if result.get("ok")]
    failed = [
        {
            "advertiser_name": str(result.get("advertiser_name") or ""),
            "error": str(result.get("error") or "라이브 상태 조회 실패"),
        }
        for result in results
        if not result.get("ok")
    ]
    live_names = sorted(
        (
            str(result.get("advertiser_name") or "")
            for result in ok_results
            if int(result.get("live_campaign_count") or 0) > 0
        ),
        key=lambda value: value.lower(),
    )
    campaign_metadata_by_advertiser = {
        str(result.get("advertiser_name") or ""): result.get("campaign_metadata") or {}
        for result in ok_results
    }
    return {
        "live_advertiser_count": len(live_names),
        "live_advertisers": live_names,
        "live_campaign_count": sum(int(result.get("live_campaign_count") or 0) for result in ok_results),
        "live_status_complete": len(failed) == 0,
        "live_status_checked_advertiser_count": len(ok_results),
        "live_status_failed_advertisers": failed,
        "live_status_total_advertisers": len(credentials),
        "campaign_metadata_by_advertiser": campaign_metadata_by_advertiser,
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
        start_date: str | None = None,
        end_date: str | None = None,
        resource_id: str | None = None,
        fields: list[str] | None = None,
        filters: list[dict[str, Any]] | None = None,
        time_granularity: str = "none",
        time_range: dict[str, Any] | None = None,
        segments: list[str] | None = None,
        override_segment_group_order: list[str] | None = None,
        includes: list[str] | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        if scope != "ad_account" and not resource_id:
            raise ValueError("resource_id is required for non-account insights.")
        if time_range is None:
            if not start_date or not end_date:
                raise ValueError("start_date and end_date are required when time_range is not provided.")
            time_range = {
                "type": "date_range",
                "since": start_date,
                "until": end_date,
                "timezone": TIMEZONE,
            }
        params: list[tuple[str, str]] = [
            ("time_granularity", time_granularity),
            ("aggregation_level", aggregation_level),
            ("time_ranges[]", json.dumps(time_range, separators=(",", ":"))),
            ("limit", str(limit)),
        ]
        for field in fields or []:
            params.append(("fields[]", field))
        for filter_item in filters or []:
            params.append(("filters[]", json.dumps(filter_item, ensure_ascii=False, separators=(",", ":"))))
        for segment in segments or []:
            params.append(("segments[]", segment))
        for item in override_segment_group_order or []:
            params.append(("override_segment_group_order[]", item))
        for item in includes or []:
            params.append(("includes[]", item))

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

    async def list_ad_groups(self, campaign_id: str, *, limit: int = 500) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.settings.base_url}/v1/ad_groups",
                headers={
                    "Authorization": f"Bearer {self.settings.api_key}",
                    "Accept": "application/json",
                },
                params={"campaign_id": campaign_id, "limit": str(limit)},
            )
        response.raise_for_status()
        return response.json()

    async def list_ads(self, ad_group_id: str, *, limit: int = 500) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.settings.base_url}/v1/ads",
                headers={
                    "Authorization": f"Bearer {self.settings.api_key}",
                    "Accept": "application/json",
                },
                params={"ad_group_id": ad_group_id, "limit": str(limit)},
            )
        response.raise_for_status()
        return response.json()

    async def list_campaigns(
        self,
        *,
        limit: int = 500,
        after: str | None = None,
    ) -> dict[str, Any]:
        params = {"limit": str(limit)}
        if after:
            params["after"] = after
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.settings.base_url}/v1/campaigns",
                headers={
                    "Authorization": f"Bearer {self.settings.api_key}",
                    "Accept": "application/json",
                },
                params=params,
            )
        response.raise_for_status()
        return response.json()


async def fetch_ad_account_metadata(api_key: str) -> dict[str, Any]:
    settings = load_ads_api_settings(api_key=api_key)
    if not settings.api_key:
        raise ValueError("Ads API Key를 입력해 주세요.")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{settings.base_url}/v1/ad_account",
                headers={
                    "Authorization": f"Bearer {settings.api_key}",
                    "Accept": "application/json",
                },
            )
        response.raise_for_status()
        payload = response.json()
        return {
            "ok": True,
            "ad_account": {
                "id": payload.get("id") or "",
                "name": payload.get("name") or "",
                "url": payload.get("url") or "",
                "preview_url": payload.get("preview_url") or "",
                "timezone": payload.get("timezone") or "",
                "currency_code": payload.get("currency_code") or "",
            },
        }
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:1000] if exc.response is not None else ""
        return {
            "ok": False,
            "error": f"OpenAI Ads API 계정 확인 실패: HTTP {exc.response.status_code}",
            "detail": detail,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"OpenAI Ads API 계정 확인 중 오류가 발생했습니다: {exc}",
        }


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


CONVERSION_INSIGHTS_DISABLED_MESSAGES = (
    "conversions in insights are not enabled",
    "sales performance fields are not enabled",
)
CONVERSION_METRICS_WARNING = (
    "이 광고 계정은 전환 인사이트가 아직 활성화되지 않아 전환수·전환값·CPA·ROAS는 제외하고 표시합니다."
)


def _is_field_error(exc: httpx.HTTPStatusError) -> bool:
    return exc.response is not None and exc.response.status_code in {400, 422}


def _is_conversion_insights_disabled_error(exc: httpx.HTTPStatusError) -> bool:
    if exc.response is None or exc.response.status_code != 403:
        return False
    text = exc.response.text.lower()
    return any(message in text for message in CONVERSION_INSIGHTS_DISABLED_MESSAGES)


def _is_conversion_metric_error(exc: httpx.HTTPStatusError) -> bool:
    return _is_field_error(exc) or _is_conversion_insights_disabled_error(exc)


async def fetch_ads_dashboard(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    detail_scope: str | None = None,
    detail_id: str | None = None,
    api_key: str | None = None,
    advertiser_name: str | None = None,
    advertiser_industry: str | None = None,
    include_extensions: bool = True,
    include_conversions: bool = True,
    include_account_summary: bool = True,
    include_campaign_metadata: bool = True,
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
        warning = ""
        if include_conversions:
            try:
                account_payload, campaign_payload = await _fetch_account_and_campaigns(
                    client,
                    start_date,
                    end_date,
                    include_conversions=True,
                    include_account_summary=include_account_summary,
                )
            except httpx.HTTPStatusError as exc:
                if not _is_conversion_metric_error(exc):
                    raise
                conversion_metrics_available = False
                warning = CONVERSION_METRICS_WARNING
                account_payload, campaign_payload = await _fetch_account_and_campaigns(
                    client,
                    start_date,
                    end_date,
                    include_conversions=False,
                    include_account_summary=include_account_summary,
                )
        else:
            conversion_metrics_available = False
            warning = CONVERSION_METRICS_WARNING
            account_payload, campaign_payload = await _fetch_account_and_campaigns(
                client,
                start_date,
                end_date,
                include_conversions=False,
                include_account_summary=include_account_summary,
            )
        if include_campaign_metadata:
            try:
                campaign_metadata = await _fetch_campaign_metadata_by_id(client)
            except Exception:
                campaign_metadata = {}
        else:
            campaign_metadata = {}
        account_rows = [_normalize_row(row, "ad_account") for row in account_payload.get("data", [])]
        campaign_rows = [
            _normalize_row(_merge_campaign_metadata(row, campaign_metadata), "campaign")
            for row in campaign_payload.get("data", [])
        ]
        advertiser_industry = str(advertiser_industry or "")
        if advertiser_name or advertiser_industry:
            campaign_rows = [
                {
                    **row,
                    "advertiser_name": advertiser_name or "",
                    "industry": advertiser_industry,
                }
                for row in campaign_rows
            ]
        account_summary = account_rows[0] if account_rows else summarize_rows(campaign_rows)
        if include_extensions:
            trend, device_breakdown, extension_warning = await _fetch_dashboard_extensions(
                client,
                start_date,
                end_date,
            )
        else:
            trend, device_breakdown, extension_warning = [], [], ""

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
                warning = warning or CONVERSION_METRICS_WARNING

        return {
            "ok": True,
            "configured": True,
            "advertiser_name": advertiser_name or "",
            "key_source": "advertiser" if api_key else "environment",
            "conversion_metrics_available": conversion_metrics_available,
            "warning": " · ".join(part for part in (warning, extension_warning) if part),
            "range": {"start_date": start_date, "end_date": end_date, "timezone": TIMEZONE},
            "account": account_summary,
            "campaigns": campaign_rows,
            "campaign_total": summarize_rows(campaign_rows),
            "trend": trend,
            "device_breakdown": device_breakdown,
            "benchmarks": build_benchmarks(campaign_rows),
            "live_advertiser_count": live_advertiser_count(campaign_rows) or (1 if campaign_rows else 0),
            "live_advertisers": live_advertiser_names(campaign_rows),
            "extension_warning": extension_warning,
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


async def fetch_ads_dashboard_for_advertisers(
    advertisers: list[dict[str, str]],
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    detail_scope: str | None = None,
    detail_id: str | None = None,
    detail_advertiser_name: str | None = None,
    include_aggregate_extensions: bool = False,
) -> dict[str, Any]:
    default_start, default_end = default_date_range()
    start_date = start_date or default_start
    end_date = end_date or default_end
    credentials = [
        {
            "advertiser_name": str(item.get("advertiser_name") or "").strip(),
            "industry": str(item.get("industry") or "").strip(),
            "api_key": str(item.get("api_key") or "").strip(),
        }
        for item in advertisers
        if str(item.get("api_key") or "").strip()
    ]
    if not credentials:
        return {
            "ok": False,
            "configured": False,
            "error": "활성화된 광고주 Ads API 키가 없습니다.",
            "docs": {
                "overview": "https://developers.openai.com/ads/api-overview",
                "insights": "https://developers.openai.com/ads/api-reference/insights",
            },
        }

    detail_advertiser_name = str(detail_advertiser_name or "").strip()
    aggregate_limit = max(
        1,
        int(_env_float("OPENAI_ADS_AGGREGATE_ADVERTISER_LIMIT", DEFAULT_AGGREGATE_ADVERTISER_LIMIT)),
    )
    queried_credentials = credentials
    skipped_credentials: list[dict[str, str]] = []
    if not detail_advertiser_name and not include_aggregate_extensions and len(credentials) > aggregate_limit:
        queried_credentials = credentials[:aggregate_limit]
        skipped_credentials = credentials[aggregate_limit:]
    advertiser_concurrency = max(
        1,
        int(_env_float("OPENAI_ADS_ADVERTISER_FETCH_CONCURRENCY", DEFAULT_ADVERTISER_FETCH_CONCURRENCY)),
    )
    semaphore = asyncio.Semaphore(advertiser_concurrency)
    advertiser_timeout = _env_float("OPENAI_ADS_ADVERTISER_FETCH_TIMEOUT", DEFAULT_ADVERTISER_FETCH_TIMEOUT)
    live_status_task = asyncio.create_task(fetch_live_status_snapshot_for_advertisers(credentials))

    async def fetch_one(index: int, item: dict[str, str]) -> tuple[int, dict[str, Any]]:
        async with semaphore:
            include_detail = detail_advertiser_name and item["advertiser_name"] == detail_advertiser_name
            include_extensions = bool(include_detail or (include_aggregate_extensions and not detail_advertiser_name))
            try:
                result = await asyncio.wait_for(
                    fetch_ads_dashboard(
                        start_date=start_date,
                        end_date=end_date,
                        detail_scope=detail_scope if include_detail else None,
                        detail_id=detail_id if include_detail else None,
                        api_key=item["api_key"],
                        advertiser_name=item["advertiser_name"],
                        advertiser_industry=item["industry"],
                        include_extensions=include_extensions,
                        include_conversions=include_detail,
                        include_account_summary=include_detail,
                        include_campaign_metadata=False,
                    ),
                    timeout=advertiser_timeout,
                )
                return index, result
            except asyncio.TimeoutError:
                return index, {
                    "ok": False,
                    "configured": True,
                    "error": f"광고주 조회 시간이 {advertiser_timeout:g}초를 초과했습니다.",
                }

    if include_aggregate_extensions and not detail_advertiser_name:
        aggregate_timeout = _env_float("OPENAI_ADS_AGGREGATE_CACHE_FETCH_TIMEOUT", 90.0)
    else:
        aggregate_timeout = _env_float("OPENAI_ADS_AGGREGATE_FETCH_TIMEOUT", DEFAULT_AGGREGATE_FETCH_TIMEOUT)
    results: list[dict[str, Any]] = [
        {
            "ok": False,
            "configured": True,
            "error": f"전체 조회 제한 시간 {aggregate_timeout:g}초 안에 응답하지 않았습니다.",
        }
        for _ in queried_credentials
    ]
    aggregate_timed_out = False
    tasks = [asyncio.create_task(fetch_one(index, item)) for index, item in enumerate(queried_credentials)]
    try:
        for future in asyncio.as_completed(tasks, timeout=aggregate_timeout):
            index, result = await future
            results[index] = result
    except asyncio.TimeoutError:
        aggregate_timed_out = True
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
    try:
        live_status_snapshot = await live_status_task
    except Exception:
        live_status_snapshot = _empty_live_status_snapshot(len(credentials))
    ok_results = [result for result in results if result.get("ok")]
    failed = [
        {
            "advertiser_name": queried_credentials[index]["advertiser_name"],
            "error": str(result.get("error") or "조회 실패"),
        }
        for index, result in enumerate(results)
        if not result.get("ok")
    ]

    if not ok_results:
        return {
            "ok": False,
            "configured": True,
            "advertiser_name": "전체 활성 광고주",
            "key_source": "advertiser_collection",
            "error": "등록된 활성 광고주 키로 조회된 Ads 성과가 없습니다.",
            "detail": "; ".join(
                f"{item['advertiser_name']}: {item['error']}" for item in failed[:5]
            ),
            "range": {"start_date": start_date, "end_date": end_date, "timezone": TIMEZONE},
        }

    campaign_rows: list[dict[str, Any]] = []
    detail = None
    industry_by_advertiser = {item["advertiser_name"]: item.get("industry", "") for item in credentials}
    campaign_metadata_by_advertiser = live_status_snapshot.get("campaign_metadata_by_advertiser") or {}
    for result in ok_results:
        advertiser = str(result.get("advertiser_name") or "")
        industry = str(industry_by_advertiser.get(advertiser) or "")
        campaign_metadata = campaign_metadata_by_advertiser.get(advertiser) or {}
        for row in result.get("campaigns") or []:
            metadata = campaign_metadata.get(str(row.get("id") or row.get("campaign_id") or ""))
            objective = _campaign_objective_value(metadata) if isinstance(metadata, dict) else ""
            campaign_rows.append({
                **row,
                "objective": objective or row.get("objective") or "",
                "advertiser_name": advertiser,
                "industry": row.get("industry") or industry,
            })
        if result.get("detail"):
            detail_rows = [
                {**row, "advertiser_name": advertiser}
                for row in result["detail"].get("rows", [])
            ]
            detail = {**result["detail"], "rows": detail_rows}

    warning_parts = [str(result.get("warning") or "") for result in ok_results if result.get("warning")]
    warning_parts.extend(str(result.get("extension_warning") or "") for result in ok_results if result.get("extension_warning"))
    if not detail_advertiser_name and not include_aggregate_extensions:
        warning_parts.append("전체 활성 광고주 실시간 조회는 응답 속도를 위해 추이·디바이스 확장 지표를 생략합니다. 백그라운드 캐시가 준비되면 전체 차트가 표시됩니다.")
    if skipped_credentials:
        warning_parts.append(f"전체 활성 광고주 {len(credentials)}개 중 응답 속도를 위해 {len(queried_credentials)}개를 우선 조회했습니다.")
    if aggregate_timed_out:
        warning_parts.append(f"전체 조회 제한 시간 {aggregate_timeout:g}초를 초과해 일부 광고주만 표시합니다.")
    if failed:
        names = ", ".join(item["advertiser_name"] or "이름 없음" for item in failed[:5])
        warning_parts.append(f"일부 광고주 조회 실패: {names}")
    live_failed = live_status_snapshot.get("live_status_failed_advertisers") or []
    if live_failed:
        names = ", ".join(str(item.get("advertiser_name") or "이름 없음") for item in live_failed[:5])
        warning_parts.append(f"라이브 상태 일부 조회 실패: {names}")

    conversion_metrics_available = any(
        result.get("conversion_metrics_available") is not False for result in ok_results
    )

    return {
        "ok": True,
        "configured": True,
        "advertiser_name": "전체 활성 광고주",
        "key_source": "advertiser_collection",
        "advertiser_count": len(credentials),
        "queried_advertiser_count": len(queried_credentials),
        "skipped_advertiser_count": len(skipped_credentials),
        "successful_advertiser_count": len(ok_results),
        "failed_advertisers": failed,
        "conversion_metrics_available": conversion_metrics_available,
        "warning": " · ".join(dict.fromkeys(part for part in warning_parts if part)),
        "range": {"start_date": start_date, "end_date": end_date, "timezone": TIMEZONE},
        "account": summarize_rows(campaign_rows),
        "campaigns": campaign_rows,
        "campaign_total": summarize_rows(campaign_rows),
        "trend": _aggregate_trend([result.get("trend") or [] for result in ok_results]),
        "device_breakdown": _aggregate_devices([result.get("device_breakdown") or [] for result in ok_results]),
        "benchmarks": build_benchmarks(campaign_rows),
        "live_advertiser_count": live_status_snapshot.get("live_advertiser_count", 0),
        "live_advertisers": live_status_snapshot.get("live_advertisers", []),
        "live_campaign_count": live_status_snapshot.get("live_campaign_count", 0),
        "live_status_complete": live_status_snapshot.get("live_status_complete", False),
        "live_status_checked_advertiser_count": live_status_snapshot.get("live_status_checked_advertiser_count", 0),
        "live_status_total_advertisers": live_status_snapshot.get("live_status_total_advertisers", len(credentials)),
        "live_status_failed_advertisers": live_status_snapshot.get("live_status_failed_advertisers", []),
        "detail": detail,
        "docs": {
            "overview": "https://developers.openai.com/ads/api-overview",
            "insights": "https://developers.openai.com/ads/api-reference/insights",
        },
    }


async def _fetch_account_and_campaigns(
    client: AdsInsightsClient,
    start_date: str,
    end_date: str,
    *,
    include_conversions: bool,
    include_account_summary: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    account_fields = ACCOUNT_FIELDS_WITH_CONVERSIONS if include_conversions else ACCOUNT_FIELDS
    campaign_fields = CAMPAIGN_FIELDS_WITH_CONVERSIONS if include_conversions else CAMPAIGN_FIELDS
    campaign_task = client.insights(
        scope="ad_account",
        aggregation_level="campaign",
        start_date=start_date,
        end_date=end_date,
        fields=campaign_fields,
        limit=2000,
    )
    if not include_account_summary:
        return {"data": []}, await campaign_task
    account_payload, campaign_payload = await asyncio.gather(
        client.insights(
            scope="ad_account",
            aggregation_level="ad_account",
            start_date=start_date,
            end_date=end_date,
            fields=account_fields,
            limit=1,
        ),
        campaign_task,
    )
    return account_payload, campaign_payload


async def _fetch_spend_trend(
    client: AdsInsightsClient,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    payload = await client.insights(
        scope="ad_account",
        aggregation_level="campaign",
        start_date=start_date,
        end_date=end_date,
        time_granularity="daily",
        fields=[
            "metadata.readable_time",
            "campaign.id",
            "campaign.name",
            "campaign.impressions",
            "campaign.clicks",
            "campaign.spend",
            "campaign.ctr",
            "campaign.cpc",
            "campaign.cpm",
        ],
        limit=2000,
    )
    trend = _aggregate_trend([_normalize_trend_rows(payload.get("data", []), "campaign")])
    if trend:
        return trend
    payload = await client.insights(
        scope="ad_account",
        aggregation_level="ad_account",
        start_date=start_date,
        end_date=end_date,
        time_granularity="daily",
        fields=[
            "metadata.readable_time",
            "ad_account.impressions",
            "ad_account.clicks",
            "ad_account.spend",
            "ad_account.ctr",
            "ad_account.cpc",
            "ad_account.cpm",
        ],
        limit=2000,
    )
    return _normalize_trend_rows(payload.get("data", []))


async def _fetch_device_breakdown(
    client: AdsInsightsClient,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    payload = await client.insights(
        scope="ad_account",
        aggregation_level="ad_account",
        start_date=start_date,
        end_date=end_date,
        time_granularity="none",
        segments=["device"],
        override_segment_group_order=["device", "ad_account"],
        fields=[
            "device.type",
            "device.impressions",
            "device.clicks",
            "device.spend",
            "device.ctr",
            "device.cpc",
            "device.cpm",
        ],
        limit=200,
    )
    return _normalize_device_rows(payload.get("data", []))


async def _fetch_dashboard_extensions(
    client: AdsInsightsClient,
    start_date: str,
    end_date: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    trend: list[dict[str, Any]] = []
    device_breakdown: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        trend = await _fetch_spend_trend(client, start_date, end_date)
    except Exception:
        warnings.append("일별 소진액 추이는 현재 응답에서 제외했습니다.")
    try:
        device_breakdown = await _fetch_device_breakdown(client, start_date, end_date)
    except Exception:
        warnings.append("디바이스별 노출 비중은 현재 응답에서 제외했습니다.")
    return trend, device_breakdown, " · ".join(warnings)


def _normalize_hour_range_value(value: str, fallback_hour: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 13:
        text = text[:13]
    if len(text) == 10:
        text = f"{text}T{fallback_hour}"
    try:
        datetime.strptime(text, "%Y-%m-%dT%H")
        return text
    except ValueError as exc:
        raise ValueError("시간 범위는 YYYY-MM-DDTHH 형식이어야 합니다.") from exc


async def fetch_campaign_hourly_insights(
    *,
    campaign_id: str,
    since_hour: str,
    until_hour: str,
    api_key: str | None = None,
    advertiser_name: str | None = None,
    campaign_name: str | None = None,
) -> dict[str, Any]:
    return await fetch_resource_hourly_insights(
        resource_scope="campaign",
        resource_id=campaign_id,
        resource_name=campaign_name,
        since_hour=since_hour,
        until_hour=until_hour,
        api_key=api_key,
        advertiser_name=advertiser_name,
    )


async def fetch_resource_hourly_insights(
    *,
    resource_scope: str,
    resource_id: str,
    since_hour: str,
    until_hour: str,
    api_key: str | None = None,
    advertiser_name: str | None = None,
    resource_name: str | None = None,
) -> dict[str, Any]:
    scope = str(resource_scope or "campaign").strip()
    if scope not in {"campaign", "ad_group", "ad"}:
        raise ValueError("시간대별 리포트 범위는 campaign, ad_group, ad만 지원합니다.")
    resource_id = str(resource_id or "").strip()
    if not resource_id:
        scope_label = {"campaign": "캠페인", "ad_group": "광고그룹", "ad": "소재"}[scope]
        raise ValueError(f"{scope_label} ID가 필요합니다.")
    since_hour = _normalize_hour_range_value(since_hour, "00")
    until_hour = _normalize_hour_range_value(until_hour, "23")
    if until_hour <= since_hour:
        raise ValueError("종료 시간은 시작 시간보다 늦어야 합니다.")

    settings = load_ads_api_settings(api_key=api_key)
    if not settings.api_key:
        return {
            "ok": False,
            "configured": False,
            "error": "광고주별 Ads API 키를 등록하거나 OPENAI_ADS_API_KEY 환경변수를 설정해 주세요.",
        }
    field_prefix = scope
    client = AdsInsightsClient(settings)
    payload = await client.insights(
        scope=scope,
        resource_id=resource_id,
        aggregation_level=scope,
        time_granularity="hourly",
        time_range={
            "type": "hour_range",
            "since": since_hour,
            "until": until_hour,
            "timezone": TIMEZONE,
        },
        fields=[
            "metadata.readable_time",
            f"{field_prefix}.impressions",
            f"{field_prefix}.clicks",
            f"{field_prefix}.spend",
            f"{field_prefix}.ctr",
            f"{field_prefix}.cpc",
            f"{field_prefix}.cpm",
        ],
        limit=2000,
    )
    rows = _normalize_hourly_rows(payload.get("data", []), scope)
    return {
        "ok": True,
        "configured": True,
        "advertiser_name": str(advertiser_name or ""),
        "resource_scope": scope,
        "resource_id": resource_id,
        "resource_name": str(resource_name or ""),
        "campaign_id": resource_id if scope == "campaign" else "",
        "campaign_name": str(resource_name or "") if scope == "campaign" else "",
        "timezone": TIMEZONE,
        "since": since_hour,
        "until": until_hour,
        "rows": rows,
        "total": summarize_rows(rows),
        "row_count": len(rows),
        "docs": {
            "insights": "https://developers.openai.com/ads/api-reference/insights",
        },
    }


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
        if not include_conversions or not _is_conversion_metric_error(exc):
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
    if detail_scope == "campaign" and level == "ad_group":
        try:
            ad_group_payload = await client.list_ad_groups(detail_id)
            metadata_rows = [
                _detail_metadata_row(item, "ad_group", parent_id=detail_id)
                for item in ad_group_payload.get("data", [])
                if item.get("id")
            ]
            rows = _merge_detail_metadata(rows, metadata_rows)
        except Exception:
            pass
    elif detail_scope == "ad_group" and level == "ad":
        try:
            ads_payload = await client.list_ads(detail_id)
            metadata_rows = [
                _detail_metadata_row(item, "ad", parent_id=detail_id)
                for item in ads_payload.get("data", [])
                if item.get("id")
            ]
            rows = _merge_detail_metadata(rows, metadata_rows)
        except Exception:
            pass
    return {
        "scope": detail_scope,
        "id": detail_id,
        "aggregation_level": level,
        "rows": rows,
        "total": summarize_rows(rows),
        "conversion_metrics_available": conversion_metrics_available,
    }
