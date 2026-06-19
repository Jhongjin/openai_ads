from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app


class GuideSlidesAdminTests(unittest.TestCase):
    def test_public_and_admin_slide_content_routes(self) -> None:
        client = TestClient(app)

        with patch("admin_store._ensure_tables", side_effect=RuntimeError("test storage offline")):
            public_response = client.get("/api/guide-slides")
            self.assertEqual(public_response.status_code, 200)
            self.assertIn("items", public_response.json())
            self.assertIn("images", public_response.json())

            denied = client.get("/api/admin/guide-slides")
            self.assertEqual(denied.status_code, 403)

            payload = {
                "items": [
                    {"key": "advertiser.hero.title", "value": "테스트 안내자료 제목"},
                    {"key": "advertiser.condition.minimum", "value": "테스트 최소 집행 문구"},
                ],
                "images": [
                    {
                        "key": "campaign_step1",
                        "value": "/images/guide/campaign_step1.png",
                        "alt": "테스트 대체 텍스트",
                        "caption": "테스트 캡션",
                    }
                ],
            }
            saved = client.post(
                "/api/admin/guide-slides",
                json=payload,
                headers={"x-admin-password": "nas2026@"},
            )
            self.assertEqual(saved.status_code, 200)
            body = saved.json()
            self.assertEqual(body["storage"], "memory")
            self.assertTrue(any(item["value"] == "테스트 안내자료 제목" for item in body["items"]))
            self.assertTrue(any(item.get("caption") == "테스트 캡션" for item in body["images"]))


if __name__ == "__main__":
    unittest.main()
