from __future__ import annotations

import unittest
from unittest.mock import patch
from urllib.parse import quote

from fastapi.testclient import TestClient

from app import app


class AdsApiAdminRouteTests(unittest.TestCase):
    def test_admin_can_save_list_and_delete_ads_api_key(self) -> None:
        client = TestClient(app)
        advertiser_name = "UnitTest Advertiser"
        advertiser_path = quote(advertiser_name, safe="")
        headers = {"x-admin-password": "nas2026@"}

        with patch("admin_store._ensure_tables", side_effect=RuntimeError("test storage offline")):
            denied = client.delete(f"/api/admin/ads-api-keys/{advertiser_path}")
            self.assertEqual(denied.status_code, 403)

            saved = client.post(
                "/api/admin/ads-api-keys",
                json={
                    "advertiser_name": advertiser_name,
                    "ads_api_key": "sk-test-ads",
                    "conversion_api_key": "sk-test-conversion",
                    "enabled": True,
                },
                headers=headers,
            )
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json()["item"]["advertiser_name"], advertiser_name)

            listed = client.get("/api/admin/ads-api-keys", headers=headers)
            self.assertTrue(any(item["advertiser_name"] == advertiser_name for item in listed.json()["items"]))

            deleted = client.delete(f"/api/admin/ads-api-keys/{advertiser_path}", headers=headers)
            self.assertEqual(deleted.status_code, 200)

            listed_after_delete = client.get("/api/admin/ads-api-keys", headers=headers)
            self.assertFalse(
                any(item["advertiser_name"] == advertiser_name for item in listed_after_delete.json()["items"])
            )


if __name__ == "__main__":
    unittest.main()
