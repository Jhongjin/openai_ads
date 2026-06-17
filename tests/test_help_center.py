from __future__ import annotations

from datetime import datetime, timezone
import unittest

from bs4 import BeautifulSoup

from rag_chatbot.crawler import reader_markdown_to_content
from rag_chatbot.help_center import (
    _article_document_from_reader_markdown,
    _extract_markdown_links,
    parse_help_center_updated_at,
    relative_updated_date,
)
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

    def test_yesterday_converts_to_absolute_date(self) -> None:
        crawled_at = datetime(2026, 6, 17, 3, 0, tzinfo=timezone.utc)

        self.assertEqual(
            relative_updated_date("마지막 수정: yesterday", crawled_at),
            ("2026-06-16", False),
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


class ReaderFallbackTests(unittest.TestCase):
    def test_reader_markdown_title_and_content_are_extracted(self) -> None:
        title, content = reader_markdown_to_content(
            "Title: Create Ads for ChatGPT\n\n"
            "URL Source: https://help.openai.com/en/articles/20001212-create-ads-for-chatgpt\n\n"
            "Markdown Content:\nBody text"
        )

        self.assertEqual(title, "Create Ads for ChatGPT")
        self.assertEqual(content, "Body text")

    def test_reader_collection_links_are_extracted(self) -> None:
        article_urls, collection_urls = _extract_markdown_links(
            "[Create Ads](https://help.openai.com/en/articles/20001212-create-ads-for-chatgpt)\n"
            "[Campaign setup](https://help.openai.com/en/collections/20001228-campaign-setup)",
            "https://help.openai.com/en/collections/20001223-chatgpt-ads",
            "en",
        )

        self.assertEqual(len(article_urls), 1)
        self.assertEqual(len(collection_urls), 1)

    def test_reader_article_document_uses_fallback_updated_date(self) -> None:
        crawled_at = datetime(2026, 6, 17, 3, 0, tzinfo=timezone.utc)
        document = _article_document_from_reader_markdown(
            "Title: Create Ads for ChatGPT\n\nMarkdown Content:\nBody text",
            "https://help.openai.com/en/articles/20001212-create-ads-for-chatgpt",
            "en",
            crawled_at,
        )

        self.assertIsNotNone(document)
        assert document is not None
        self.assertEqual(document.metadata["article_id"], "20001212")
        self.assertEqual(document.metadata["source_updated_at"], "2026-06-17")
        self.assertTrue(document.metadata["source_updated_at_is_fallback"])


if __name__ == "__main__":
    unittest.main()
