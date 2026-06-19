from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app import app


class DevRoutesStaticTests(unittest.TestCase):
    def test_dev_redesign_routes_are_available(self) -> None:
        client = TestClient(app)

        routes = {
            "/dev": "OpenAI 광고 사내 도구",
            "/dev/admin": "관리자 설정",
            "/dev/creative-upload-draft": "OpenAI Ads Manager 업로드 워크북 작성",
        }
        for path, phrase in routes.items():
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(phrase, response.text)
                self.assertIn("DEV redesign layer", response.text)


if __name__ == "__main__":
    unittest.main()
