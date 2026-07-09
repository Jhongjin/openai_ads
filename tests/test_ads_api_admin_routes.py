from __future__ import annotations

import unittest
import os
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
                    "industry": "교육",
                    "ads_api_key": "sk-test-ads",
                    "conversion_api_key": "sk-test-conversion",
                    "enabled": True,
                },
                headers=headers,
            )
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json()["item"]["advertiser_name"], advertiser_name)

            listed = client.get("/api/admin/ads-api-keys", headers=headers)
            saved_item = next(item for item in listed.json()["items"] if item["advertiser_name"] == advertiser_name)
            self.assertEqual(saved_item["industry"], "교육")
            self.assertIn("...", saved_item["masked_ads_api_key"])

            denied_reveal = client.get(f"/api/admin/ads-api-keys/{advertiser_path}/reveal")
            self.assertEqual(denied_reveal.status_code, 403)
            revealed = client.get(f"/api/admin/ads-api-keys/{advertiser_path}/reveal", headers=headers)
            self.assertEqual(revealed.status_code, 200)
            self.assertEqual(revealed.json()["ads_api_key"], "sk-test-ads")

            deleted = client.delete(f"/api/admin/ads-api-keys/{advertiser_path}", headers=headers)
            self.assertEqual(deleted.status_code, 200)

            listed_after_delete = client.get("/api/admin/ads-api-keys", headers=headers)
            self.assertFalse(
                any(item["advertiser_name"] == advertiser_name for item in listed_after_delete.json()["items"])
            )

    def test_ads_api_key_industry_options_accept_split_fashion_cosmetics_and_transport(self) -> None:
        client = TestClient(app)
        headers = {"x-admin-password": "nas2026@"}

        with patch("admin_store._ensure_tables", side_effect=RuntimeError("test storage offline")):
            for industry in ["패션", "화장품", "수송"]:
                advertiser_name = f"UnitTest {industry}"
                response = client.post(
                    "/api/admin/ads-api-keys",
                    json={
                        "advertiser_name": advertiser_name,
                        "industry": industry,
                        "ads_api_key": f"sk-test-{industry}",
                        "enabled": True,
                    },
                    headers=headers,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["item"]["industry"], industry)
                client.delete(f"/api/admin/ads-api-keys/{quote(advertiser_name, safe='')}", headers=headers)

            rejected = client.post(
                "/api/admin/ads-api-keys",
                json={
                    "advertiser_name": "UnitTest Old Industry",
                    "industry": "패션/화장품",
                    "ads_api_key": "sk-test-old-industry",
                    "enabled": True,
                },
                headers=headers,
            )

        self.assertEqual(rejected.status_code, 400)

    def test_dashboard_uses_active_advertiser_keys_when_no_advertiser_selected(self) -> None:
        client = TestClient(app)
        headers = {"x-admin-password": "nas2026@"}
        credentials = [{"advertiser_name": "Live Advertiser", "api_key": "sk-live"}]

        with (
            patch("admin_store.get_ads_dashboard_cache", return_value=None),
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

    def test_dashboard_uses_cached_active_advertiser_aggregate(self) -> None:
        client = TestClient(app)
        headers = {"x-admin-password": "nas2026@"}
        cached_payload = {
            "ok": True,
            "advertiser_name": "old",
            "key_source": "advertiser_collection",
            "campaigns": [{"id": "cmp_cached", "advertiser_name": "Cached Advertiser"}],
            "trend": [{"date": "2026-07-01", "spend": 1000}],
            "device_breakdown": [{"device": "mobile", "impressions": 100, "impression_share": 1}],
        }

        with (
            patch("admin_store.list_active_ads_api_key_credentials", return_value=[{"advertiser_name": "Cached Advertiser", "api_key": "sk-live"}]),
            patch(
                "admin_store.get_ads_dashboard_cache",
                return_value={"payload": cached_payload, "refreshed_at": "2026-07-03T09:00:00+09:00"},
            ),
            patch("rag_chatbot.ads_api.fetch_ads_dashboard_for_advertisers", new_callable=AsyncMock) as aggregate,
        ):
            response = client.get("/api/admin/ads-dashboard", headers=headers)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["advertiser_name"], "전체 활성 광고주")
        self.assertEqual(body["cache_status"], "hit")
        self.assertIn("2026-07-03", body["cache_note"])
        self.assertEqual(body["campaigns"][0]["id"], "cmp_cached")
        aggregate.assert_not_awaited()

    def test_dashboard_skips_cached_aggregate_when_range_differs(self) -> None:
        client = TestClient(app)
        headers = {"x-admin-password": "nas2026@"}
        credentials = [{"advertiser_name": "Range Advertiser", "api_key": "sk-live"}]
        cached_payload = {
            "ok": True,
            "advertiser_name": "전체 활성 광고주",
            "key_source": "advertiser_collection",
            "range": {"start_date": "2026-07-02", "end_date": "2026-07-09"},
            "campaigns": [{"id": "cmp_cached"}],
            "trend": [{"date": "2026-07-02", "spend": 1000}],
        }
        fresh_payload = {
            "ok": True,
            "advertiser_name": "전체 활성 광고주",
            "key_source": "advertiser_collection",
            "advertiser_count": 1,
            "range": {"start_date": "2026-06-22", "end_date": "2026-07-09"},
            "campaigns": [{"id": "cmp_fresh", "advertiser_name": "Range Advertiser"}],
            "trend": [{"date": "2026-06-22", "spend": 2000}],
            "device_breakdown": [{"device": "mobile", "impressions": 100}],
        }

        with (
            patch("admin_store.list_active_ads_api_key_credentials", return_value=credentials),
            patch(
                "admin_store.get_ads_dashboard_cache",
                return_value={"payload": cached_payload, "refreshed_at": "2026-07-09T08:00:00+00:00"},
            ) as get_cache,
            patch("admin_store.save_ads_dashboard_cache", return_value={"ok": True, "refreshed_at": "2026-07-09T09:00:00+09:00"}),
            patch("rag_chatbot.ads_api.fetch_ads_dashboard_for_advertisers", new_callable=AsyncMock) as aggregate,
        ):
            aggregate.return_value = fresh_payload
            response = client.get(
                "/api/admin/ads-dashboard?start_date=2026-06-22&end_date=2026-07-09",
                headers=headers,
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["campaigns"][0]["id"], "cmp_fresh")
        self.assertEqual(body["trend"][0]["date"], "2026-06-22")
        self.assertEqual(body["range"]["start_date"], "2026-06-22")
        self.assertEqual(body["cache_status"], "refreshed")
        self.assertIn("전체 활성 광고주(1개)", body["cache_note"])
        get_cache.assert_any_call("active_advertisers:2026-06-22:2026-07-09")
        aggregate.assert_awaited_once()
        self.assertTrue(aggregate.await_args.kwargs["include_aggregate_extensions"])

    def test_admin_can_save_and_apply_campaign_objective_override(self) -> None:
        client = TestClient(app)
        headers = {"x-admin-password": "nas2026@"}

        with patch("admin_store._ensure_tables", side_effect=RuntimeError("test storage offline")):
            denied = client.post(
                "/api/admin/ads-campaign-objectives",
                json={
                    "advertiser_name": "Override Advertiser",
                    "campaign_id": "cmp_override",
                    "campaign_name": "Override Campaign",
                    "objective": "클릭",
                },
            )
            self.assertEqual(denied.status_code, 403)

            saved = client.post(
                "/api/admin/ads-campaign-objectives",
                json={
                    "advertiser_name": "Override Advertiser",
                    "campaign_id": "cmp_override",
                    "campaign_name": "Override Campaign",
                    "objective": "클릭",
                },
                headers=headers,
            )
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json()["item"]["objective"], "클릭")

            listed = client.get("/api/admin/ads-campaign-objectives", headers=headers)
            self.assertTrue(
                any(item["campaign_id"] == "cmp_override" and item["objective"] == "클릭" for item in listed.json()["items"])
            )

            with (
                patch("admin_store.get_ads_dashboard_cache", return_value=None),
                patch(
                    "admin_store.list_active_ads_api_key_credentials",
                    return_value=[{"advertiser_name": "Override Advertiser", "api_key": "sk-live"}],
                ),
                patch("rag_chatbot.ads_api.fetch_ads_dashboard_for_advertisers", new_callable=AsyncMock) as aggregate,
            ):
                aggregate.return_value = {
                    "ok": True,
                    "advertiser_name": "전체 활성 광고주",
                    "campaigns": [
                        {
                            "id": "cmp_override",
                            "advertiser_name": "Override Advertiser",
                            "industry": "교육",
                            "objective": "",
                            "impressions": 100,
                            "clicks": 10,
                            "spend": 1000,
                        }
                    ],
                }
                dashboard = client.get("/api/admin/ads-dashboard", headers=headers)

            self.assertEqual(dashboard.status_code, 200)
            self.assertEqual(dashboard.json()["campaigns"][0]["objective"], "클릭")

            reset = client.post(
                "/api/admin/ads-campaign-objectives",
                json={
                    "advertiser_name": "Override Advertiser",
                    "campaign_id": "cmp_override",
                    "campaign_name": "Override Campaign",
                    "objective": "",
                },
                headers=headers,
            )
            self.assertEqual(reset.status_code, 200)
            self.assertEqual(reset.json()["item"]["objective"], "")

    def test_admin_can_fetch_campaign_hourly_report(self) -> None:
        client = TestClient(app)
        headers = {"x-admin-password": "nas2026@"}

        with (
            patch(
                "admin_store.get_ads_api_key_credential",
                return_value={"advertiser_name": "Kanu", "industry": "식음료", "api_key": "sk-kanu"},
            ),
            patch("rag_chatbot.ads_api.fetch_resource_hourly_insights", new_callable=AsyncMock) as hourly,
        ):
            hourly.return_value = {
                "ok": True,
                "advertiser_name": "Kanu",
                "campaign_id": "cmpn_kanu",
                "campaign_name": "카누 바리스타",
                "timezone": "Asia/Seoul",
                "since": "2026-07-08T00",
                "until": "2026-07-08T06",
                "rows": [{"hour": "2026-07-08T00", "spend": 1000}],
            }
            denied = client.get(
                "/api/admin/ads-dashboard/hourly?advertiser_name=Kanu&campaign_id=cmpn_kanu&since=2026-07-08T00&until=2026-07-08T06",
            )
            response = client.get(
                "/api/admin/ads-dashboard/hourly?advertiser_name=Kanu&campaign_id=cmpn_kanu&campaign_name=카누%20바리스타&since=2026-07-08T00&until=2026-07-08T06",
                headers=headers,
            )

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["campaign_id"], "cmpn_kanu")
        hourly.assert_awaited_once()
        self.assertEqual(hourly.await_args.kwargs["api_key"], "sk-kanu")
        self.assertEqual(hourly.await_args.kwargs["resource_scope"], "campaign")
        self.assertEqual(hourly.await_args.kwargs["resource_id"], "cmpn_kanu")
        self.assertEqual(hourly.await_args.kwargs["resource_name"], "카누 바리스타")
        self.assertEqual(hourly.await_args.kwargs["since_hour"], "2026-07-08T00")
        self.assertEqual(hourly.await_args.kwargs["until_hour"], "2026-07-08T06")

    def test_admin_can_fetch_ad_group_hourly_report(self) -> None:
        client = TestClient(app)
        headers = {"x-admin-password": "nas2026@"}

        with (
            patch(
                "admin_store.get_ads_api_key_credential",
                return_value={"advertiser_name": "Kanu", "industry": "식음료", "api_key": "sk-kanu"},
            ),
            patch("rag_chatbot.ads_api.fetch_resource_hourly_insights", new_callable=AsyncMock) as hourly,
        ):
            hourly.return_value = {
                "ok": True,
                "advertiser_name": "Kanu",
                "resource_scope": "ad_group",
                "resource_id": "adgrp_kanu",
                "resource_name": "00_기본",
                "timezone": "Asia/Seoul",
                "since": "2026-07-08T00",
                "until": "2026-07-08T06",
                "rows": [{"hour": "2026-07-08T00", "spend": 1000}],
            }
            response = client.get(
                "/api/admin/ads-dashboard/hourly?advertiser_name=Kanu&resource_scope=ad_group&resource_id=adgrp_kanu&resource_name=00_%EA%B8%B0%EB%B3%B8&since=2026-07-08T00&until=2026-07-08T06",
                headers=headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resource_scope"], "ad_group")
        hourly.assert_awaited_once()
        self.assertEqual(hourly.await_args.kwargs["resource_scope"], "ad_group")
        self.assertEqual(hourly.await_args.kwargs["resource_id"], "adgrp_kanu")
        self.assertEqual(hourly.await_args.kwargs["resource_name"], "00_기본")

    def test_cron_refreshes_ads_dashboard_cache(self) -> None:
        client = TestClient(app)
        payload = {
            "ok": True,
            "advertiser_name": "전체 활성 광고주",
            "campaigns": [{"id": "cmp_1"}],
            "trend": [{"date": "2026-07-01"}],
            "device_breakdown": [{"device": "mobile"}],
        }

        with (
            patch.dict(os.environ, {"CRON_SECRET": "cron-secret"}, clear=False),
            patch("admin_store.list_active_ads_api_key_credentials", return_value=[{"advertiser_name": "A", "api_key": "sk-a"}]),
            patch("rag_chatbot.ads_api.fetch_ads_dashboard_for_advertisers", new_callable=AsyncMock) as aggregate,
            patch("admin_store.save_ads_dashboard_cache") as save_cache,
        ):
            aggregate.return_value = payload
            save_cache.return_value = {"ok": True, "refreshed_at": "2026-07-03T09:00:00+09:00", "storage": "memory"}
            denied = client.get("/api/cron/ads-dashboard-cache")
            response = client.get("/api/cron/ads-dashboard-cache", headers={"authorization": "Bearer cron-secret"})

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["refreshed"])
        self.assertEqual(body["active_advertiser_count"], 1)
        self.assertEqual(body["trend_count"], 1)
        aggregate.assert_awaited_once()
        self.assertTrue(aggregate.await_args.kwargs["include_aggregate_extensions"])
        save_cache.assert_called_once()

    def test_admin_can_inspect_ads_api_key_metadata(self) -> None:
        client = TestClient(app)
        headers = {"x-admin-password": "nas2026@"}

        with patch("rag_chatbot.ads_api.fetch_ad_account_metadata", new_callable=AsyncMock) as inspect_key:
            inspect_key.return_value = {
                "ok": True,
                "ad_account": {
                    "id": "act_123",
                    "name": "Unit Account",
                    "timezone": "Asia/Seoul",
                    "currency_code": "KRW",
                },
            }
            response = client.post(
                "/api/admin/ads-api-keys/inspect",
                json={"ads_api_key": "sk-inspect"},
                headers=headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ad_account"]["name"], "Unit Account")
        inspect_key.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
