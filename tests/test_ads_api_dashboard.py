from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

import httpx

from rag_chatbot.ads_api import (
    AdsApiSettings,
    AdsInsightsClient,
    apply_campaign_objective_overrides,
    build_benchmarks,
    fetch_campaign_hourly_insights,
    fetch_resource_hourly_insights,
    fetch_ads_dashboard,
    fetch_ads_dashboard_for_advertisers,
    fetch_live_status_snapshot_for_advertisers,
    _fetch_detail,
    _normalize_row,
    summarize_rows,
)


class AdsApiDashboardTests(unittest.TestCase):
    def test_missing_api_key_returns_configured_false(self) -> None:
        with patch.dict(os.environ, {"OPENAI_ADS_API_KEY": ""}, clear=False):
            data = asyncio.run(fetch_ads_dashboard())

        self.assertFalse(data["ok"])
        self.assertFalse(data["configured"])
        self.assertIn("OPENAI_ADS_API_KEY", data["error"])
        self.assertIn("insights", data["docs"])

    def test_summarize_rows_derives_rates_from_totals(self) -> None:
        summary = summarize_rows(
            [
                {"impressions": 1000, "clicks": 25, "spend": 5000},
                {"impressions": 3000, "clicks": 75, "spend": 15000},
            ]
        )

        self.assertEqual(summary["impressions"], 4000)
        self.assertEqual(summary["clicks"], 100)
        self.assertEqual(summary["spend"], 20000)
        self.assertEqual(summary["ctr"], 0.025)
        self.assertEqual(summary["cpc"], 200)
        self.assertEqual(summary["cpm"], 5000)

    def test_campaign_objective_is_not_inferred_from_name(self) -> None:
        row = _normalize_row(
            {
                "campaign": {
                    "id": "cmp_1",
                    "name": "brand_cpc_campaign",
                    "status": "ACTIVE",
                    "impressions": 1000,
                }
            },
            "campaign",
        )

        self.assertEqual(row["objective"], "")

    def test_campaign_objective_uses_api_metadata_when_present(self) -> None:
        async def fake_insights(self, *, aggregation_level, **kwargs):
            if aggregation_level == "ad_account":
                return {"data": []}
            return {
                "data": [
                    {
                        "campaign": {
                            "id": "cmp_1",
                            "name": "Brand campaign",
                            "status": "ACTIVE",
                            "impressions": 1000,
                        }
                    }
                ]
            }

        async def fake_list_campaigns(self, **kwargs):
            return {
                "data": [
                    {
                        "id": "cmp_1",
                        "name": "Brand campaign",
                        "objective": "clicks",
                    }
                ],
                "has_more": False,
            }

        with (
            patch.dict(os.environ, {"OPENAI_ADS_API_KEY": "sk-test"}, clear=False),
            patch("rag_chatbot.ads_api.AdsInsightsClient.insights", new=fake_insights),
            patch("rag_chatbot.ads_api.AdsInsightsClient.list_campaigns", new=fake_list_campaigns),
        ):
            data = asyncio.run(fetch_ads_dashboard(include_conversions=False, include_account_summary=False))

        self.assertEqual(data["campaigns"][0]["objective"], "clicks")

    def test_campaign_objective_manual_override_updates_benchmarks(self) -> None:
        payload = {
            "campaigns": [
                {
                    "advertiser_name": "Advertiser",
                    "id": "cmp_1",
                    "industry": "교육",
                    "objective": "",
                    "impressions": 1000,
                    "clicks": 25,
                    "spend": 50000,
                }
            ],
            "benchmarks": [],
        }

        result = apply_campaign_objective_overrides(
            payload,
            {"Advertiser␟cmp_1": "클릭"},
        )

        self.assertEqual(result["campaigns"][0]["objective"], "클릭")
        self.assertEqual(result["campaigns"][0]["objective_source"], "manual")
        self.assertEqual(result["benchmarks"][0]["objective"], "클릭")

    def test_build_benchmarks_groups_by_industry_and_objective(self) -> None:
        rows = [
            {"industry": "교육", "objective": "Click", "impressions": 1000, "clicks": 20, "spend": 40000},
            {"industry": "교육", "objective": "Click", "impressions": 3000, "clicks": 80, "spend": 160000},
            {"industry": "금융", "objective": "Reach", "impressions": 2000, "clicks": 10, "spend": 60000},
        ]

        benchmarks = build_benchmarks(rows)
        education = next(
            item
            for item in benchmarks
            if item["type"] == "industry_objective" and item["industry"] == "교육" and item["objective"] == "Click"
        )
        education_total = next(
            item
            for item in benchmarks
            if item["type"] == "industry" and item["industry"] == "교육" and item["objective"] == "전체"
        )
        click_total = next(
            item
            for item in benchmarks
            if item["type"] == "objective" and item["industry"] == "전체" and item["objective"] == "Click"
        )

        self.assertEqual(education["objective"], "Click")
        self.assertEqual(education["campaign_count"], 2)
        self.assertEqual(education["impressions"], 4000)
        self.assertEqual(education["clicks"], 100)
        self.assertEqual(education["cpc"], 2000)
        self.assertEqual(education["cpm"], 50000)
        self.assertEqual(education_total["campaign_count"], 2)
        self.assertEqual(click_total["campaign_count"], 2)

    def test_ad_group_bid_value_keeps_whole_won_when_api_returns_plain_amount(self) -> None:
        row = _normalize_row(
            {
                "ad_group": {
                    "id": "adgrp_1",
                    "name": "00_기본",
                    "status": "ACTIVE",
                    "bidding_config": {"max_bid_micros": 7000},
                }
            },
            "ad_group",
        )

        self.assertEqual(row["max_bid"], 7000)

    def test_ad_group_bid_value_converts_large_micro_amounts(self) -> None:
        row = _normalize_row(
            {
                "ad_group": {
                    "id": "adgrp_1",
                    "name": "00_기본",
                    "status": "ACTIVE",
                    "bidding_config": {"max_bid_micros": 7_000_000_000},
                }
            },
            "ad_group",
        )

        self.assertEqual(row["max_bid"], 7000)

    def test_ad_group_cpm_bid_value_converts_per_impression_amounts(self) -> None:
        row = _normalize_row(
            {
                "ad_group": {
                    "id": "adgrp_1",
                    "name": "00_기본",
                    "status": "ACTIVE",
                    "bidding_config": {
                        "billing_event_type": "IMPRESSION",
                        "max_bid_micros": 7,
                    },
                }
            },
            "ad_group",
        )

        self.assertEqual(row["billing_event_type"], "IMPRESSION")
        self.assertEqual(row["max_bid"], 7000)

    def test_campaign_detail_falls_back_to_listed_ad_groups_when_insights_empty(self) -> None:
        async def fake_insights(self, **kwargs):
            return {"data": []}

        async def fake_list_ad_groups(self, campaign_id, **kwargs):
            return {
                "data": [
                    {
                        "id": "adgrp_1",
                        "name": "00_기본",
                        "status": "active",
                        "bidding_config": {
                            "billing_event_type": "impression",
                            "max_bid_micros": 7,
                        },
                    }
                ]
            }

        client = AdsInsightsClient(AdsApiSettings("sk-test", "https://api.ads.openai.com"))
        with (
            patch("rag_chatbot.ads_api.AdsInsightsClient.insights", new=fake_insights),
            patch("rag_chatbot.ads_api.AdsInsightsClient.list_ad_groups", new=fake_list_ad_groups),
        ):
            detail = asyncio.run(
                _fetch_detail(
                    client,
                    "2026-07-01",
                    "2026-07-08",
                    "campaign",
                    "cmpn_1",
                    include_conversions=False,
                )
            )

        self.assertEqual(detail["aggregation_level"], "ad_group")
        self.assertEqual(len(detail["rows"]), 1)
        self.assertEqual(detail["rows"][0]["id"], "adgrp_1")
        self.assertEqual(detail["rows"][0]["name"], "00_기본")
        self.assertEqual(detail["rows"][0]["status"], "active")
        self.assertEqual(detail["rows"][0]["max_bid"], 7000)
        self.assertEqual(detail["total"]["impressions"], 0)

    def test_ad_group_detail_falls_back_to_listed_ads_when_insights_empty(self) -> None:
        async def fake_insights(self, **kwargs):
            return {"data": []}

        async def fake_list_ads(self, ad_group_id, **kwargs):
            return {
                "data": [
                    {
                        "id": "ad_1",
                        "name": "소재 A",
                        "status": "active",
                        "review_status": "approved",
                        "creative": {
                            "title": "Try it",
                            "body": "Now",
                        },
                    }
                ]
            }

        client = AdsInsightsClient(AdsApiSettings("sk-test", "https://api.ads.openai.com"))
        with (
            patch("rag_chatbot.ads_api.AdsInsightsClient.insights", new=fake_insights),
            patch("rag_chatbot.ads_api.AdsInsightsClient.list_ads", new=fake_list_ads),
        ):
            detail = asyncio.run(
                _fetch_detail(
                    client,
                    "2026-07-01",
                    "2026-07-08",
                    "ad_group",
                    "adgrp_1",
                    include_conversions=False,
                )
            )

        self.assertEqual(detail["aggregation_level"], "ad")
        self.assertEqual(len(detail["rows"]), 1)
        self.assertEqual(detail["rows"][0]["id"], "ad_1")
        self.assertEqual(detail["rows"][0]["name"], "소재 A")
        self.assertEqual(detail["rows"][0]["status"], "active")
        self.assertEqual(detail["rows"][0]["review_status"], "approved")
        self.assertEqual(detail["rows"][0]["ad_group_id"], "adgrp_1")

    def test_conversion_insights_403_falls_back_to_base_metrics(self) -> None:
        async def fake_insights(self, *, aggregation_level, fields=None, **kwargs):
            if any(field.endswith(".conversions") or field.endswith(".roas") for field in fields or []):
                request = httpx.Request("GET", "https://api.ads.openai.com/v1/ad_account/insights")
                response = httpx.Response(
                    403,
                    request=request,
                    text='{"error":{"message":"403: Conversions in insights are not enabled for this ad account."}}',
                )
                raise httpx.HTTPStatusError("conversion insights disabled", request=request, response=response)
            if aggregation_level == "ad_account":
                return {
                    "data": [
                        {
                            "ad_account": {
                                "id": "acct_1",
                                "name": "Test account",
                                "impressions": 2000,
                                "clicks": 100,
                                "spend": 50000,
                            }
                        }
                    ]
                }
            return {
                "data": [
                    {
                        "campaign": {
                            "id": "cmp_1",
                            "name": "Test campaign",
                            "status": "ACTIVE",
                            "impressions": 2000,
                            "clicks": 100,
                            "spend": 50000,
                        }
                    }
                ]
            }

        with patch("rag_chatbot.ads_api.AdsInsightsClient.insights", new=fake_insights):
            data = asyncio.run(fetch_ads_dashboard(api_key="sk-test"))

        self.assertTrue(data["ok"])
        self.assertFalse(data["conversion_metrics_available"])
        self.assertIn("전환 인사이트", data["warning"])
        self.assertEqual(data["campaign_total"]["impressions"], 2000)
        self.assertEqual(data["campaign_total"]["clicks"], 100)
        self.assertEqual(data["campaign_total"]["spend"], 50000)

    def test_sales_performance_fields_403_falls_back_to_base_metrics(self) -> None:
        async def fake_insights(self, *, aggregation_level, fields=None, **kwargs):
            if any(field.endswith(".conversion_value") or field.endswith(".roas") for field in fields or []):
                request = httpx.Request("GET", "https://api.ads.openai.com/v1/ad_account/insights")
                response = httpx.Response(
                    403,
                    request=request,
                    text='{"error":{"message":"403: Sales performance fields are not enabled for this ad account."}}',
                )
                raise httpx.HTTPStatusError("sales performance disabled", request=request, response=response)
            if aggregation_level == "ad_account":
                return {
                    "data": [
                        {
                            "ad_account": {
                                "id": "acct_1",
                                "name": "Test account",
                                "impressions": 3000,
                                "clicks": 120,
                                "spend": 60000,
                            }
                        }
                    ]
                }
            return {
                "data": [
                    {
                        "campaign": {
                            "id": "cmp_1",
                            "name": "Test campaign",
                            "status": "ACTIVE",
                            "impressions": 3000,
                            "clicks": 120,
                            "spend": 60000,
                        }
                    }
                ]
            }

        with patch("rag_chatbot.ads_api.AdsInsightsClient.insights", new=fake_insights):
            data = asyncio.run(fetch_ads_dashboard(api_key="sk-test"))

        self.assertTrue(data["ok"])
        self.assertFalse(data["conversion_metrics_available"])
        self.assertIn("전환 인사이트", data["warning"])
        self.assertEqual(data["campaign_total"]["impressions"], 3000)
        self.assertEqual(data["campaign_total"]["clicks"], 120)
        self.assertEqual(data["campaign_total"]["spend"], 60000)

    def test_dashboard_trend_uses_campaign_daily_rows(self) -> None:
        daily_calls: list[tuple[str, list[str]]] = []

        async def fake_insights(self, *, aggregation_level, fields=None, time_granularity="none", **kwargs):
            if time_granularity == "daily":
                daily_calls.append((aggregation_level, list(fields or [])))
                return {
                    "data": [
                        {
                            "readable_time": "2026-07-01",
                            "campaign_id": "cmp_1",
                            "campaign_name": "A",
                            "impressions": 1000,
                            "clicks": 50,
                            "spend": 10000,
                        },
                        {
                            "readable_time": "2026-07-01",
                            "campaign_id": "cmp_2",
                            "campaign_name": "B",
                            "impressions": 500,
                            "clicks": 25,
                            "spend": 5000,
                        },
                        {
                            "readable_time": "2026-07-02",
                            "campaign_id": "cmp_1",
                            "campaign_name": "A",
                            "impressions": 800,
                            "clicks": 20,
                            "spend": 7000,
                        },
                    ]
                }
            if kwargs.get("segments"):
                return {"data": []}
            if aggregation_level == "ad_account":
                return {
                    "data": [
                        {
                            "ad_account": {
                                "id": "acct_1",
                                "name": "Test account",
                                "impressions": 2300,
                                "clicks": 95,
                                "spend": 22000,
                            }
                        }
                    ]
                }
            return {
                "data": [
                    {
                        "campaign": {
                            "id": "cmp_1",
                            "name": "A",
                            "status": "ACTIVE",
                            "impressions": 1800,
                            "clicks": 70,
                            "spend": 17000,
                        }
                    }
                ]
            }

        with patch("rag_chatbot.ads_api.AdsInsightsClient.insights", new=fake_insights):
            data = asyncio.run(fetch_ads_dashboard(api_key="sk-test", include_conversions=False))

        self.assertEqual(daily_calls[0][0], "campaign")
        self.assertIn("campaign.spend", daily_calls[0][1])
        self.assertEqual(data["trend"][0]["date"], "2026-07-01")
        self.assertEqual(data["trend"][0]["spend"], 15000)
        self.assertEqual(data["trend"][0]["impressions"], 1500)
        self.assertEqual(data["trend"][0]["clicks"], 75)
        self.assertEqual(data["trend"][1]["date"], "2026-07-02")
        self.assertEqual(data["trend"][1]["spend"], 7000)

    def test_campaign_hourly_insights_uses_hour_range(self) -> None:
        captured: dict[str, object] = {}

        async def fake_insights(self, **kwargs):
            captured.update(kwargs)
            return {
                "data": [
                    {
                        "readable_time": "2026-07-08T00",
                        "campaign_id": "cmpn_1",
                        "impressions": 1200,
                        "clicks": 30,
                        "spend": 50000,
                    },
                    {
                        "readable_time": "2026-07-08T01",
                        "campaign_id": "cmpn_1",
                        "impressions": 800,
                        "clicks": 20,
                        "spend": 30000,
                    },
                ]
            }

        with patch("rag_chatbot.ads_api.AdsInsightsClient.insights", new=fake_insights):
            data = asyncio.run(
                fetch_campaign_hourly_insights(
                    api_key="sk-test",
                    advertiser_name="Kanu",
                    campaign_id="cmpn_1",
                    campaign_name="카누 바리스타",
                    since_hour="2026-07-08T00",
                    until_hour="2026-07-08T06",
                )
            )

        self.assertTrue(data["ok"])
        self.assertEqual(data["timezone"], "Asia/Seoul")
        self.assertEqual(data["row_count"], 2)
        self.assertEqual(data["total"]["spend"], 80000)
        self.assertEqual(captured["scope"], "campaign")
        self.assertEqual(captured["resource_id"], "cmpn_1")
        self.assertEqual(captured["aggregation_level"], "campaign")
        self.assertEqual(captured["time_granularity"], "hourly")
        self.assertEqual(
            captured["time_range"],
            {
                "type": "hour_range",
                "since": "2026-07-08T00",
                "until": "2026-07-08T06",
                "timezone": "Asia/Seoul",
            },
        )

    def test_ad_group_hourly_insights_uses_ad_group_scope(self) -> None:
        captured: dict[str, object] = {}

        async def fake_insights(self, **kwargs):
            captured.update(kwargs)
            return {
                "data": [
                    {
                        "readable_time": "2026-07-08T00",
                        "ad_group_id": "adgrp_1",
                        "impressions": 300,
                        "clicks": 5,
                        "spend": 7000,
                    }
                ]
            }

        with patch("rag_chatbot.ads_api.AdsInsightsClient.insights", new=fake_insights):
            data = asyncio.run(
                fetch_resource_hourly_insights(
                    api_key="sk-test",
                    advertiser_name="Kanu",
                    resource_scope="ad_group",
                    resource_id="adgrp_1",
                    resource_name="00_기본",
                    since_hour="2026-07-08T00",
                    until_hour="2026-07-08T06",
                )
            )

        self.assertTrue(data["ok"])
        self.assertEqual(data["resource_scope"], "ad_group")
        self.assertEqual(data["resource_id"], "adgrp_1")
        self.assertEqual(data["resource_name"], "00_기본")
        self.assertEqual(captured["scope"], "ad_group")
        self.assertEqual(captured["resource_id"], "adgrp_1")
        self.assertEqual(captured["aggregation_level"], "ad_group")
        self.assertIn("ad_group.spend", captured["fields"])

    def test_multi_advertiser_dashboard_aggregates_campaigns_by_default(self) -> None:
        async def fake_insights(self, *, aggregation_level, **kwargs):
            advertiser = "Alpha" if self.settings.api_key == "sk-alpha" else "Beta"
            multiplier = 1 if advertiser == "Alpha" else 2
            if aggregation_level == "ad_account":
                return {
                    "data": [
                        {
                            "ad_account": {
                                "id": f"acct_{advertiser.lower()}",
                                "name": advertiser,
                                "impressions": 1000 * multiplier,
                                "clicks": 50 * multiplier,
                                "spend": 10000 * multiplier,
                            }
                        }
                    ]
                }
            return {
                "data": [
                    {
                        "campaign": {
                            "id": f"cmp_{advertiser.lower()}",
                            "name": f"{advertiser} Campaign",
                            "status": "ACTIVE",
                            "impressions": 1000 * multiplier,
                            "clicks": 50 * multiplier,
                            "spend": 10000 * multiplier,
                        }
                    }
                ]
            }

        async def fake_list_campaigns(self, **kwargs):
            advertiser = "Alpha" if self.settings.api_key == "sk-alpha" else "Beta"
            return {
                "data": [
                    {
                        "id": f"cmp_{advertiser.lower()}",
                        "name": f"{advertiser} Campaign",
                        "status": "active",
                    }
                ],
                "has_more": False,
            }

        advertisers = [
            {"advertiser_name": "Alpha", "api_key": "sk-alpha"},
            {"advertiser_name": "Beta", "api_key": "sk-beta"},
        ]
        with (
            patch("rag_chatbot.ads_api.AdsInsightsClient.insights", new=fake_insights),
            patch("rag_chatbot.ads_api.AdsInsightsClient.list_campaigns", new=fake_list_campaigns),
        ):
            data = asyncio.run(fetch_ads_dashboard_for_advertisers(advertisers))

        self.assertTrue(data["ok"])
        self.assertEqual(data["advertiser_name"], "전체 활성 광고주")
        self.assertEqual(data["key_source"], "advertiser_collection")
        self.assertEqual(data["advertiser_count"], 2)
        self.assertEqual(data["queried_advertiser_count"], 2)
        self.assertEqual(data["skipped_advertiser_count"], 0)
        self.assertEqual(len(data["campaigns"]), 2)
        self.assertEqual({row["advertiser_name"] for row in data["campaigns"]}, {"Alpha", "Beta"})
        self.assertEqual(data["campaign_total"]["impressions"], 3000)
        self.assertEqual(data["campaign_total"]["clicks"], 150)
        self.assertEqual(data["campaign_total"]["spend"], 30000)
        self.assertEqual(data["live_advertiser_count"], 2)
        self.assertEqual(data["live_campaign_count"], 2)
        self.assertTrue(data["live_status_complete"])

    def test_cached_aggregate_extensions_fetch_all_active_advertisers_despite_realtime_limit(self) -> None:
        async def fake_insights(self, *, aggregation_level, time_granularity="none", segments=None, **kwargs):
            advertiser = self.settings.api_key.removeprefix("sk-").title()
            if time_granularity == "daily":
                return {
                    "data": [
                        {
                            "readable_time": "2026-07-01",
                            "campaign_id": f"cmp_{advertiser.lower()}",
                            "campaign_name": f"{advertiser} Campaign",
                            "impressions": 100,
                            "clicks": 10,
                            "spend": 1000,
                        }
                    ]
                }
            if segments:
                return {
                    "data": [
                        {
                            "device.type": "mobile",
                            "device.impressions": 100,
                            "device.clicks": 10,
                            "device.spend": 1000,
                        }
                    ]
                }
            return {
                "data": [
                    {
                        "campaign": {
                            "id": f"cmp_{advertiser.lower()}",
                            "name": f"{advertiser} Campaign",
                            "status": "ACTIVE",
                            "impressions": 100,
                            "clicks": 10,
                            "spend": 1000,
                        }
                    }
                ]
            }

        async def fake_list_campaigns(self, **kwargs):
            advertiser = self.settings.api_key.removeprefix("sk-").lower()
            return {"data": [{"id": f"cmp_{advertiser}", "status": "active"}], "has_more": False}

        advertisers = [
            {"advertiser_name": "Alpha", "api_key": "sk-alpha"},
            {"advertiser_name": "Beta", "api_key": "sk-beta"},
            {"advertiser_name": "Gamma", "api_key": "sk-gamma"},
        ]
        with (
            patch.dict(
                os.environ,
                {
                    "OPENAI_ADS_AGGREGATE_ADVERTISER_LIMIT": "1",
                    "OPENAI_ADS_AGGREGATE_CACHE_FETCH_TIMEOUT": "5",
                },
                clear=False,
            ),
            patch("rag_chatbot.ads_api.AdsInsightsClient.insights", new=fake_insights),
            patch("rag_chatbot.ads_api.AdsInsightsClient.list_campaigns", new=fake_list_campaigns),
        ):
            data = asyncio.run(fetch_ads_dashboard_for_advertisers(advertisers, include_aggregate_extensions=True))

        self.assertTrue(data["ok"])
        self.assertEqual(data["advertiser_count"], 3)
        self.assertEqual(data["queried_advertiser_count"], 3)
        self.assertEqual(data["skipped_advertiser_count"], 0)
        self.assertEqual({row["advertiser_name"] for row in data["campaigns"]}, {"Alpha", "Beta", "Gamma"})
        self.assertEqual(len(data["trend"]), 1)
        self.assertEqual(len(data["device_breakdown"]), 1)
        self.assertNotIn("우선 조회", data["warning"])

    def test_live_status_snapshot_uses_campaign_list_not_insights_rows(self) -> None:
        async def fake_list_campaigns(self, **kwargs):
            if self.settings.api_key == "sk-alpha":
                return {
                    "data": [
                        {"id": "cmp_live", "status": "active"},
                        {"id": "cmp_paused", "status": "paused"},
                    ],
                    "has_more": False,
                }
            return {
                "data": [
                    {"id": "cmp_beta", "status": "active", "end_time": 946684800},
                ],
                "has_more": False,
            }

        advertisers = [
            {"advertiser_name": "Alpha", "api_key": "sk-alpha"},
            {"advertiser_name": "Beta", "api_key": "sk-beta"},
        ]
        with patch("rag_chatbot.ads_api.AdsInsightsClient.list_campaigns", new=fake_list_campaigns):
            snapshot = asyncio.run(fetch_live_status_snapshot_for_advertisers(advertisers))

        self.assertTrue(snapshot["live_status_complete"])
        self.assertEqual(snapshot["live_advertisers"], ["Alpha"])
        self.assertEqual(snapshot["live_advertiser_count"], 1)
        self.assertEqual(snapshot["live_campaign_count"], 1)


if __name__ == "__main__":
    unittest.main()
