from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MailCollectorAppsScriptStaticTests(unittest.TestCase):
    def test_review_actions_are_supported(self) -> None:
        script = (ROOT / "apps_script" / "mail_collector_webhook.gs").read_text(encoding="utf-8")

        required = [
            'payload.action === "approved_for_rag"',
            'payload.action === "review_list"',
            'payload.action === "review_update"',
            "function reviewList_",
            "function reviewUpdate_",
            "function reviewStats_",
            "function safeReviewRow_",
            "45000 : 1000",
            "approved_summary is required for approved_for_rag",
            "supersedes_duplicate_hash",
            "review_status: reviewStatus",
            "status: reviewStatus",
            "retention_days",
            "function isRecentMailRow_",
            "Date.now() - retentionDays * 24 * 60 * 60 * 1000",
        ]
        for phrase in required:
            self.assertIn(phrase, script)

    def test_mail_sheet_headers_keep_review_columns(self) -> None:
        script = (ROOT / "apps_script" / "mail_collector_webhook.gs").read_text(encoding="utf-8")

        for header in [
            '"review_status"',
            '"review_note"',
            '"approved_title"',
            '"approved_summary"',
            '"approved_by"',
            '"approved_at"',
            '"rag_ingested_at"',
        ]:
            self.assertIn(header, script)


if __name__ == "__main__":
    unittest.main()
