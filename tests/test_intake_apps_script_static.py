from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class IntakeAppsScriptStaticTests(unittest.TestCase):
    def test_multi_campaign_apps_script_preserves_adgroup_campaign_name(self) -> None:
        script = (ROOT / "apps_script" / "intake_webhook.gs").read_text(encoding="utf-8")

        self.assertIn("data.campaigns || data.campaign_rows || data.campaign", script)
        self.assertIn('appendRows_("campaigns", campaigns.map(withReceipt))', script)
        self.assertIn("const adgroupsForSheet = adgroups.map", script)
        self.assertIn("const fallbackCampaignName = campaigns.length === 1", script)
        self.assertIn("campaign_name: row.campaign_name || fallbackCampaignName", script)
        self.assertIn("has no campaign_name", script)
        self.assertIn('appendRows_("adgroups", adgroupsForSheet.map(withReceipt))', script)
        self.assertIn("브랜드명", script)
        self.assertIn("담당자명", script)
        self.assertIn("담당자 이메일", script)
        self.assertIn("owner_headquarters", script)
        self.assertIn('sheetName === "ops_meta"', script)
        self.assertNotIn("AdsManager계정명", script)
        self.assertNotIn("업로드채널", script)
        self.assertNotIn("업로드유형", script)
        self.assertNotIn("케이티나스미디어담당자", script)
        self.assertNotIn("담당자이메일", script)
        self.assertNotIn("submitter_email", script)
        self.assertNotIn("primaryCampaignName", script)
        self.assertNotIn("adgroupsWithCampaigns", script)
        self.assertIn("mailSent: mailResult.sent", script)
        self.assertIn("mailError: mailResult.error", script)
        self.assertIn("mailSender: mailResult.sender", script)
        self.assertIn("htmlBody", script)
        self.assertIn("buildNotificationHtml_", script)
        self.assertIn("구글 시트 바로가기", script)
        self.assertIn("INTAKE_SHEET_URL", script)
        self.assertIn("function getMailSender_()", script)
        self.assertIn("return { sent: true", script)
        self.assertIn("return { sent: false", script)
        self.assertIn("function sendMailAuthTest()", script)
        self.assertIn("function debugMailConfig()", script)


if __name__ == "__main__":
    unittest.main()
