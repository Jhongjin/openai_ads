from __future__ import annotations

import unittest

from rag_chatbot.qa import answer_question


class QaGuardrailTests(unittest.TestCase):
    def test_pending_minimum_spend_uses_fixed_answer(self) -> None:
        result = answer_question("한국 최소 집행금액 얼마야?")

        self.assertEqual(
            result["answer"],
            "현재 OpenAI 확인 대기 중입니다. 확정 후 정확히 안내드리겠습니다.",
        )
        self.assertEqual(result["sources"][0]["source_tier"], "pending")

    def test_criteo_routes_to_korea_confirmation(self) -> None:
        result = answer_question("크리테오 인보이스는 어떻게 돼?")

        self.assertEqual(
            result["answer"],
            "크리테오 경유 세부사항은 크리테오 코리아에 확인이 필요합니다.",
        )
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")

    def test_out_of_scope_rate_returns_no_data(self) -> None:
        result = answer_question("내일 환율 환산 원화 단가 알려줘")

        self.assertEqual(result["answer"], "제공된 자료에서 확인할 수 없습니다.")
        self.assertEqual(result["sources"], [])


if __name__ == "__main__":
    unittest.main()
