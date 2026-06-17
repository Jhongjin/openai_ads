from __future__ import annotations

from datetime import datetime, timezone
import unittest

from bs4 import BeautifulSoup

from rag_chatbot.help_center import parse_help_center_updated_at, relative_updated_date
from rag_chatbot.qa import answer_question


class HelpCenterUpdatedAtTests(unittest.TestCase):
    def test_days_ago_converts_to_absolute_date(self) -> None:
        crawled_at = datetime(2026, 6, 17, 3, 0, tzinfo=timezone.utc)

        self.assertEqual(
            relative_updated_date("Updated 15 days ago", crawled_at),
            ("2026-06-02", False),
        )

    def test_hours_ago_uses_crawl_date(self) -> None:
        crawled_at = datetime(2026, 6, 17, 3, 0, tzinfo=timezone.utc)

        self.assertEqual(
            relative_updated_date("Updated 2 hours ago", crawled_at),
            ("2026-06-17", False),
        )

    def test_text_tertiary_updated_at_is_parsed(self) -> None:
        crawled_at = datetime(2026, 6, 17, 3, 0, tzinfo=timezone.utc)
        soup = BeautifulSoup(
            '<span class="foo text-tertiary bar">Updated a day ago</span>',
            "html.parser",
        )

        self.assertEqual(parse_help_center_updated_at(soup, crawled_at), ("2026-06-16", False))

    def test_parse_failure_uses_fallback_flag(self) -> None:
        crawled_at = datetime(2026, 6, 17, 3, 0, tzinfo=timezone.utc)
        soup = BeautifulSoup("<main>No update marker</main>", "html.parser")

        self.assertEqual(parse_help_center_updated_at(soup, crawled_at), ("2026-06-17", True))


class SourceMetadataTests(unittest.TestCase):
    def test_kr_ops_guardrail_source_has_updated_at(self) -> None:
        result = answer_question("국내 최소 집행금액?")

        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")
        self.assertEqual(result["sources"][0]["source_updated_at"], "2026-06-17")

    def test_no_data_has_no_sources(self) -> None:
        result = answer_question("정확한 CPM 단가 얼마?")

        self.assertEqual(result["answer"], "제공된 자료에서 확인할 수 없습니다.")
        self.assertEqual(result["sources"], [])

    def test_best_practice_uses_official_source(self) -> None:
        result = answer_question("광고 만들 때 모범 사례?")

        self.assertIn("공식 자료 기준", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "official")
        self.assertIn("source_updated_at", result["sources"][0])


if __name__ == "__main__":
    unittest.main()
