from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch
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

    def test_dashboard_uses_active_advertiser_keys_when_no_advertiser_selected(self) -> None:
        client = TestClient(app)
        headers = {"x-admin-password": "nas2026@"}
        credentials = [{"advertiser_name": "Live Advertiser", "api_key": "sk-live"}]

        with (
            patch("admin_store.list_active_ads_api_key_credentials", return_value=credentials),
            patch("rag_chatbot.ads_api.fetch_ads_dashboard_for_advertisers", new_callable=AsyncMock) as aggregate,
            patch("rag_chatbot.ads_api.fetch_ads_dashboard", new_callable=AsyncMock) as single,
        ):
            aggregate.return_value = {
                "ok": True,
                "advertiser_name": "전체 활성 광고주",
                "campaigns": [{"id": "cmp_live", "advertiser_name": "Live Advertiser"}],
            }
            response = client.get("/api/admin/ads-dashboard", headers=headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["advertiser_name"], "전체 활성 광고주")
        self.assertEqual(response.json()["campaigns"][0]["advertiser_name"], "Live Advertiser")
        aggregate.assert_awaited_once()
        single.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
