from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

import httpx

from rag_chatbot.ads_api import fetch_ads_dashboard, summarize_rows


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


if __name__ == "__main__":
    unittest.main()
