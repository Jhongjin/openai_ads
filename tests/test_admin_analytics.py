from __future__ import annotations

import unittest

from admin_store import categorize_chat_question


class AdminAnalyticsTests(unittest.TestCase):
    def test_categorizes_budget_questions(self) -> None:
        result = categorize_chat_question("Account Spend Cap과 최소 집행 예산 기준이 뭐야?", "")

        self.assertEqual(result["category"], "budget")
        self.assertEqual(result["label"], "예산·입찰")

    def test_categorizes_landing_questions(self) -> None:
        result = categorize_chat_question("robots.txt가 OAI-AdsBot을 막으면 캠페인 영향이 있어?", "")

        self.assertEqual(result["category"], "landing")
        self.assertEqual(result["label"], "랜딩·크롤러")


if __name__ == "__main__":
    unittest.main()
