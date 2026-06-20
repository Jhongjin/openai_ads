from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app import app


class DevRoutesStaticTests(unittest.TestCase):
    def test_dev_redesign_routes_are_available(self) -> None:
        client = TestClient(app)

        routes = {
            "/dev": "OpenAI Ads 운영 워크벤치",
            "/dev/admin": "OpenAI Ads 운영 관리자 콘솔",
            "/dev/creative-upload-draft": "소재 접수 및 업로드 워크북 생성",
        }
        for path, phrase in routes.items():
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(phrase, response.text)
                self.assertIn('/dev-assets/dev-redesign.css', response.text)
                self.assertIn("@tabler/core", response.text)

    def test_dev_pages_use_new_command_center_markup(self) -> None:
        client = TestClient(app)

        home = client.get("/dev").text
        admin = client.get("/dev/admin").text
        intake = client.get("/dev/creative-upload-draft").text

        self.assertIn('class="app-frame"', home)
        self.assertIn('data-view-button="qa"', home)
        self.assertIn('id="admin-app"', admin)
        self.assertIn("echarts@5", admin)
        self.assertIn('id="campaign-template"', intake)
        self.assertIn('id="adgroup-template"', intake)
        self.assertIn("수동 국가", intake)
        self.assertIn("xlsx target_countries", intake)
        self.assertIn("수동 세팅 입찰가", intake)
        self.assertIn("xlsx max_bid", intake)
        self.assertIn("campaign-manual-country", intake)
        self.assertIn("adgroup-manual-bid", intake)
        self.assertIn("required-mark", intake)
        self.assertIn('<option value="ALL">전체</option>', intake)
        self.assertIn('<option value="US">미국</option>', intake)
        self.assertIn('<option value="AU">오스트레일리아</option>', intake)
        self.assertIn('<option value="CA">캐나다</option>', intake)
        self.assertIn('<option value="JP">일본</option>', intake)
        self.assertIn('<option value="NZ">뉴질랜드</option>', intake)
        self.assertIn('<option value="KR">대한민국</option>', intake)
        self.assertIn('<option value="GB">영국</option>', intake)
        self.assertNotIn("Ads Manager 계정 준비", intake)
        self.assertNotIn("정산 정보 확인", intake)
        self.assertNotIn("랜딩 접근 확인", intake)
        self.assertNotIn("로고·파비콘 확인", intake)
        self.assertNotIn("대한민국은 수동 세팅에서는 선택하고", intake)

    def test_dev_redesign_css_asset_is_available(self) -> None:
        client = TestClient(app)

        response = client.get("/dev-assets/dev-redesign.css")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/css", response.headers.get("content-type", ""))
        self.assertIn("DEV redesign layer", response.text)
        self.assertIn("body.dev-console", response.text)
        self.assertIn(".app-frame", response.text)
        self.assertIn(".data-grid", response.text)

    def test_dev_assets_do_not_expose_copied_html_pages(self) -> None:
        client = TestClient(app)

        response = client.get("/dev-assets/index.html")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
