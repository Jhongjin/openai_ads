from __future__ import annotations

import unittest

from rag_chatbot.qa import answer_question


class QaGuardrailTests(unittest.TestCase):
    def test_confirmed_minimum_spend_uses_kr_ops(self) -> None:
        result = answer_question("한국 최소 집행금액 얼마야?")

        self.assertIn("OpenAI 직접(CBT)은 400만원 Net 기준", result["answer"])
        self.assertIn("크리테오 경유는 캠페인별 월 기준 2,500만원", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")

    def test_criteo_confirmed_invoice_answers_with_caveat(self) -> None:
        result = answer_question("크리테오 인보이스는 어떻게 돼?")

        self.assertIn("기존 크리테오 광고 상품 정산과 동일 방식 예정", result["answer"])
        self.assertIn("단, 추후 변경될 수 있습니다", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")

    def test_vat_stays_pending(self) -> None:
        result = answer_question("VAT 별도 여부 알려줘")

        self.assertEqual(
            result["answer"],
            "현재 OpenAI 확인 대기 중입니다. 확정 후 정확히 안내드리겠습니다.",
        )
        self.assertEqual(result["sources"][0]["source_tier"], "pending")

    def test_criteo_fee_stays_pending(self) -> None:
        result = answer_question("크리테오 수수료는 집행금액에 포함돼?")

        self.assertEqual(
            result["answer"],
            "현재 OpenAI 확인 대기 중입니다. 확정 후 정확히 안내드리겠습니다.",
        )
        self.assertEqual(result["sources"][0]["source_tier"], "pending")

    def test_confirmed_billing_modes(self) -> None:
        result = answer_question("OpenAI 직접과 크리테오 입찰 과금 방식 알려줘")

        self.assertIn("OpenAI CBT는 CPC·CPM 모두 가능", result["answer"])
        self.assertIn("크리테오 경유는 CPM만 가능", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")

    def test_cpm_price_question_returns_no_data(self) -> None:
        result = answer_question("정확한 CPM 단가 얼마인가요?")

        self.assertEqual(result["answer"], "제공된 자료에서 확인할 수 없습니다.")
        self.assertEqual(result["sources"], [])

    def test_cpm_or_cpc_question_returns_billing_mode(self) -> None:
        result = answer_question("CPM이야 CPC야?")

        self.assertIn("OpenAI CBT는 CPC·CPM 모두 가능", result["answer"])
        self.assertIn("크리테오 경유는 CPM만 가능", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")

    def test_korean_text_limits_show_both_routes(self) -> None:
        result = answer_question("한글 소재 최대 자수 알려줘")

        self.assertIn("OpenAI 직접은 제목 최대 50자", result["answer"])
        self.assertIn("크리테오 경유는 제목 30자, 설명 60자", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")

    def test_general_text_limits_have_no_pending_caveat(self) -> None:
        result = answer_question("글자수 제한 있어?")

        self.assertIn("OpenAI 직접은 제목 최대 50자", result["answer"])
        self.assertIn("크리테오 경유는 제목 30자, 설명 60자", result["answer"])
        self.assertNotIn("확인 대기", result["answer"])

    def test_out_of_scope_rate_returns_no_data(self) -> None:
        result = answer_question("내일 환율 환산 원화 단가 알려줘")

        self.assertEqual(result["answer"], "제공된 자료에서 확인할 수 없습니다.")
        self.assertEqual(result["sources"], [])


if __name__ == "__main__":
    unittest.main()
