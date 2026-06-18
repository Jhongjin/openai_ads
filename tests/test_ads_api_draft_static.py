from __future__ import annotations

from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from app import app


ROOT = Path(__file__).resolve().parents[1]


class AdsApiDraftStaticTests(unittest.TestCase):
    def test_ads_api_draft_route_serves_page(self) -> None:
        client = TestClient(app)

        response = client.get("/ads-api")

        self.assertEqual(response.status_code, 200)
        self.assertIn("OpenAI Ads API 성과 대시보드 준비", response.text)
        self.assertIn("공식 문서 기반 · 권한 확인 필요", response.text)
        self.assertIn("관리자 페이지로 돌아가기", response.text)

        legacy_response = client.get("/ads-api-draft")
        self.assertEqual(legacy_response.status_code, 200)

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
            'page: "apiOps"',
            'label: "Ads API 성과 대시보드 준비"',
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

    def test_ads_api_page_is_removed_from_public_navigation(self) -> None:
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        nav = html.split('<nav class="tabs"', 1)[1].split("</nav>", 1)[0]
        admin_html = (ROOT / "templates" / "admin.html").read_text(encoding="utf-8")
        app_py = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertNotIn('data-page-link="apiOps"', nav)
        self.assertNotIn('href="/ads-api"', nav)
        self.assertNotIn("API 운영 검토", nav)
        self.assertIn('.tab-group[data-group="docs"]::before', html)
        self.assertIn('grid-template-columns: repeat(3, minmax(0, 1fr));', html)

        self.assertIn('href="/ads-api"', admin_html)
        self.assertIn("Ads API 성과 대시보드 준비", admin_html)
        self.assertIn('"apiOps": "Ads API 성과 대시보드 준비"', app_py)


if __name__ == "__main__":
    unittest.main()
