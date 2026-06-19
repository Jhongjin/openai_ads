from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
