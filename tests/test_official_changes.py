from __future__ import annotations

import unittest

from rag_chatbot.official_changes import (
    GENERIC_UPDATED_SUMMARY,
    is_generic_official_summary,
    summarize_official_document_change,
)


class OfficialChangeSummaryTests(unittest.TestCase):
    def test_summary_uses_document_content(self) -> None:
        summary = summarize_official_document_change(
            title="Quickstart: Launch your first campaign",
            content="""
# Quickstart: Launch your first campaign

Create a campaign, set a campaign objective, define a budget, and add your first ad group.

## Campaign setup
Choose the objective, location, daily or lifetime budget, and schedule.

## Ad group setup
Set bids, URLs, and targeting context.
""",
            change_type="updated",
        )

        self.assertFalse(is_generic_official_summary(summary))
        self.assertIn("Quickstart: Launch your first campaign", summary)
        self.assertIn("Create a campaign", summary)
        self.assertIn("Campaign setup", summary)

    def test_generic_summary_detection(self) -> None:
        self.assertTrue(is_generic_official_summary(GENERIC_UPDATED_SUMMARY))
        self.assertTrue(is_generic_official_summary(""))
        self.assertFalse(is_generic_official_summary("문서 변경 감지: 실제 문서 요약"))


if __name__ == "__main__":
    unittest.main()
