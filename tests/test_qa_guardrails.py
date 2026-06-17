from __future__ import annotations

import unittest

from rag_chatbot.qa import answer_question


class QaGuardrailTests(unittest.TestCase):
    def test_confirmed_minimum_spend_uses_kr_ops(self) -> None:
        result = answer_question("한국 최소 집행금액 얼마야?")

        self.assertIn("OpenAI 직접(CBT)은 400만원 Net 기준", result["answer"])
        self.assertIn("기간 제한 없이 광고비 소진 시까지 운영", result["answer"])
        self.assertIn("크리테오 경유는 1,000만원 Net 기준", result["answer"])
        self.assertIn("월 단위 구좌제", result["answer"])
        self.assertNotIn("2,500만원", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")
        self.assertEqual(result["sources"][0]["title"], "OpenAI/크리테오 확정 회신(2026-06-17)")

    def test_criteo_minimum_spend_uses_new_kr_ops_value(self) -> None:
        result = answer_question("크리테오 최소 집행금액 얼마야?")

        self.assertIn("1,000만원 Net", result["answer"])
        self.assertIn("월 단위 구좌제", result["answer"])
        self.assertNotIn("400만원", result["answer"])
        self.assertNotIn("2,500만원", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")

    def test_slide_minimum_spend_uses_advertiser_safe_copy(self) -> None:
        result = answer_question("슬라이드 최소 집행금액 문구 어떻게 써?")

        self.assertIn("최소 집행 약정 400만원", result["answer"])
        self.assertIn("상세 조건은 영업 담당 안내", result["answer"])
        self.assertIn("슬라이드에 직접 박지 않고", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")

    def test_criteo_confirmed_invoice_answers_with_caveat(self) -> None:
        result = answer_question("크리테오 인보이스는 어떻게 돼?")

        self.assertIn("기존 크리테오 광고 상품 정산과 동일 방식 예정", result["answer"])
        self.assertIn("단, 추후 변경될 수 있습니다", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")

    def test_vat_uses_confirmed_kr_ops(self) -> None:
        result = answer_question("VAT 별도 여부 알려줘")

        self.assertIn("BRN", result["answer"])
        self.assertIn("0%", result["answer"])
        self.assertIn("10%", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")

    def test_criteo_fee_uses_confirmed_kr_ops(self) -> None:
        result = answer_question("크리테오 수수료는 집행금액에 포함돼?")

        self.assertIn("마크업", result["answer"])
        self.assertIn("호스팅 fee 5%", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")

    def test_tracker_uses_confirmed_kr_ops(self) -> None:
        result = answer_question("트래커 제출은 집행 필수야?")

        self.assertIn("필수는 아니지만", result["answer"])
        self.assertIn("전환 최적화 캠페인", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")

    def test_confirmed_billing_modes(self) -> None:
        result = answer_question("OpenAI 직접과 크리테오 입찰 과금 방식 알려줘")

        self.assertIn("OpenAI CBT는 CPC·CPM 선택 가능", result["answer"])
        self.assertIn("크리테오 경유는 CPM만 가능", result["answer"])
        self.assertIn("입찰 조정은 불가", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")

    def test_cpm_price_question_returns_no_data(self) -> None:
        result = answer_question("정확한 CPM 단가 얼마인가요?")

        self.assertEqual(result["answer"], "제공된 자료에서 확인할 수 없습니다.")
        self.assertEqual(result["sources"], [])

    def test_cpm_or_cpc_question_returns_billing_mode(self) -> None:
        result = answer_question("CPM이야 CPC야?")

        self.assertIn("OpenAI CBT는 CPC·CPM 선택 가능", result["answer"])
        self.assertIn("크리테오 경유는 CPM만 가능", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")

    def test_account_spend_cap_is_not_minimum_spend(self) -> None:
        result = answer_question("Account Spend Cap이 뭐야? 월 cap이야?")

        self.assertIn("계정 단위 lifetime spend cap", result["answer"])
        self.assertIn("OpenAI 팀이 설정", result["answer"])
        self.assertIn("월 단위 cap도 아닙니다", result["answer"])
        self.assertIn("전 계정 한도를 상향 예정", result["answer"])
        self.assertIn("최소 집행 약정과는 별개", result["answer"])
        self.assertNotIn("400만원", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")

    def test_budget_minimum_values_are_soft_uncertain_guidance(self) -> None:
        result = answer_question("일예산 최소 KRW 25,000이 확정이야? 총예산 최소값도 알려줘")

        self.assertIn("일 최소 KRW 25,000", result["answer"])
        self.assertIn("총예산 최소 KRW 1,000", result["answer"])
        self.assertIn("미확정", result["answer"])
        self.assertIn("훨씬 높게 설정", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")

    def test_crawler_429_answers_rate_limit_without_inventing_full_list(self) -> None:
        result = answer_question("크롤러 에러코드 429는 무슨 뜻이야?")

        self.assertIn("Too Many Requests", result["answer"])
        self.assertIn("rate limit", result["answer"])
        self.assertIn("작은 배치", result["answer"])
        self.assertIn("전체 크롤러 에러코드 목록은 현재 OpenAI 확인 중", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "official")

    def test_crawler_error_code_full_list_stays_pending(self) -> None:
        result = answer_question("크롤러 에러코드 전체 목록 알려줘")

        self.assertIn("현재 OpenAI 확인 대기 중", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "pending")

    def test_korean_text_limits_show_both_routes(self) -> None:
        result = answer_question("한글 소재 최대 자수 알려줘")

        self.assertIn("OpenAI 직접은 제목 최대 50자", result["answer"])
        self.assertIn("크리테오 경유는 제목 30자, 설명 60자", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "kr_ops")

    def test_general_text_limits_have_no_pending_caveat(self) -> None:
        result = answer_question("글자수 제한 있어?")

        self.assertIn("공식 자료 기준", result["answer"])
        self.assertIn("제목 최대 50자", result["answer"])
        self.assertNotIn("확인 대기", result["answer"])
        self.assertEqual(result["sources"][0]["source_tier"], "official")

    def test_out_of_scope_rate_returns_no_data(self) -> None:
        result = answer_question("내일 환율 환산 원화 단가 알려줘")

        self.assertEqual(result["answer"], "제공된 자료에서 확인할 수 없습니다.")
        self.assertEqual(result["sources"], [])


if __name__ == "__main__":
    unittest.main()
