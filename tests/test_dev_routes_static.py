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
                self.assertIn("DEV redesign layer", response.text)
                self.assertIn('/dev-assets/dev-redesign.css', response.text)

    def test_dev_redesign_css_asset_is_available(self) -> None:
        client = TestClient(app)

        response = client.get("/dev-assets/dev-redesign.css")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/css", response.headers.get("content-type", ""))
        self.assertIn("body.dev-home main", response.text)
        self.assertIn("body.dev-admin .topbar", response.text)
        self.assertIn("body.dev-creative .page", response.text)

    def test_dev_assets_do_not_expose_copied_html_pages(self) -> None:
        client = TestClient(app)

        response = client.get("/dev-assets/index.html")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
