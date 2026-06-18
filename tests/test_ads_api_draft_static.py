from __future__ import annotations

from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from app import app


ROOT = Path(__file__).resolve().parents[1]


class AdsApiDraftStaticTests(unittest.TestCase):
    def test_ads_api_draft_route_serves_page(self) -> None:
        client = TestClient(app)

        response = client.get("/ads-api-draft")

        self.assertEqual(response.status_code, 200)
        self.assertIn("OpenAI Ads API 운영 검토 초안", response.text)
        self.assertIn("별도 초안 페이지 · 메인 메뉴 미노출", response.text)

    def test_ads_api_draft_keeps_ops_scope_and_sources(self) -> None:
        html = (ROOT / "templates" / "ads_api_draft.html").read_text(encoding="utf-8")

        required = [
            "노출",
            "클릭",
            "비용",
            "spend",
            "CTR",
            "CPC",
            "CPM",
            "완전 실시간 SLA 미확인",
            "time_granularity",
            "hourly/daily/monthly/none",
            "API 키는 Vercel/GitHub Secrets 또는 서버 환경변수에만 저장",
            "https://developers.openai.com/ads/api-overview",
            "https://developers.openai.com/ads/api-reference/insights",
            "https://developers.openai.com/ads/api-reference/campaigns",
            "https://developers.openai.com/ads/api-reference/ad-groups",
            "https://developers.openai.com/ads/api-reference/ads",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

        self.assertIn("인보이스·VAT·결제수단·정산 자동화", html)
        self.assertIn("문서 미확인", html)


if __name__ == "__main__":
    unittest.main()
