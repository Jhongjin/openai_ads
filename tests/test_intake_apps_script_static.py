from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class IntakeAppsScriptStaticTests(unittest.TestCase):
    def test_multi_campaign_apps_script_preserves_adgroup_campaign_name(self) -> None:
        script = (ROOT / "apps_script" / "intake_webhook.gs").read_text(encoding="utf-8")

        self.assertIn("data.campaigns || data.campaign", script)
        self.assertIn('appendRows_("campaigns", campaigns.map(withReceipt))', script)
        self.assertIn("const adgroupsForSheet = adgroups.map", script)
        self.assertIn("campaign_name: row.campaign_name || campaigns[0].campaign_name || \"\"", script)
        self.assertIn('appendRows_("adgroups", adgroupsForSheet.map(withReceipt))', script)
        self.assertNotIn("primaryCampaignName", script)
        self.assertNotIn("adgroupsWithCampaigns", script)


if __name__ == "__main__":
    unittest.main()
