from __future__ import annotations

import os
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
                "layout": {
                    "decks": {
                        "advertiser": {
                            "slides": [
                                {
                                    "kicker": "테스트 키커",
                                    "kickerKey": "advertiser.custom.kicker",
                                    "title": "테스트 슬라이드",
                                    "titleKey": "advertiser.custom.title",
                                    "cards": [
                                        [
                                            "테스트 박스",
                                            "테스트 내용",
                                            "advertiser.custom.card.body",
                                            "advertiser.custom.card.title",
                                        ]
                                    ],
                                }
                            ]
                        }
                    }
                },
            }
            saved = client.post(
                "/api/admin/guide-slides",
                json=payload,
                headers={"x-admin-password": "nas2026@"},
            )
            self.assertEqual(saved.status_code, 200)
            body = saved.json()
            self.assertEqual(body["storage"], "memory")
            self.assertEqual(body["layout"]["decks"]["advertiser"]["slides"][0]["kicker"], "테스트 키커")
            self.assertTrue(any(item["value"] == "테스트 안내자료 제목" for item in body["items"]))
            self.assertTrue(any(item.get("caption") == "테스트 캡션" for item in body["images"]))

    def test_admin_guide_image_upload_requires_admin_and_storage(self) -> None:
        client = TestClient(app)
        files = {"file": ("guide.png", b"not-an-image", "image/png")}

        denied = client.post("/api/admin/guide-image", files=files)

        self.assertEqual(denied.status_code, 403)

        with patch.dict(
            os.environ,
            {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""},
        ):
            unavailable = client.post(
                "/api/admin/guide-image",
                files={"file": ("guide.png", b"not-an-image", "image/png")},
                headers={"x-admin-password": "nas2026@"},
            )

        self.assertEqual(unavailable.status_code, 503)
        self.assertIn("이미지 업로드 저장소", unavailable.json()["detail"])


if __name__ == "__main__":
    unittest.main()
