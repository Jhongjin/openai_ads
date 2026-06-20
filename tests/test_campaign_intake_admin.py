from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from admin_store import CAMPAIGN_INTAKE_STATUSES, _build_campaign_intake_items, list_campaign_intake_items
from app import app


class CampaignIntakeAdminTests(unittest.TestCase):
    def test_build_campaign_intake_items_groups_by_receipt_and_setup_order(self) -> None:
        payload = {
            "sheets": {
                "ops_meta": [
                    {
                        "receipt_number": "KT-OAI-20260620-001",
                        "submitted_at_kst": "2026-06-20 16:44:00",
                        "advertiser_name": "나스미디어",
                        "brand_name": "브랜드",
                        "sales_owner": "담당자",
                        "sales_owner_email": "owner@example.com",
                        "owner_headquarters": "본부",
                        "owner_office": "실",
                        "owner_team": "팀",
                    }
                ],
                "campaigns": [
                    {
                        "receipt_number": "KT-OAI-20260620-001",
                        "campaign_name": "캠페인1",
                        "budget_max": "4000000",
                        "budget_type": "lifetime",
                        "launch_date": "2026-06-20",
                        "end_date": "2026-06-30",
                        "objective": "views",
                        "target_countries": '["KR"]',
                    }
                ],
                "adgroups": [
                    {
                        "receipt_number": "KT-OAI-20260620-001",
                        "campaign_name": "캠페인1",
                        "adgroup_name": "광고그룹1",
                        "max_bid": "5300",
                        "keywords": '["ai"]',
                    }
                ],
                "ads": [
                    {
                        "receipt_number": "KT-OAI-20260620-001",
                        "adgroup_name": "광고그룹1",
                        "ad_name": "소재1",
                        "title": "제목",
                        "copy": "설명",
                        "link": "https://example.com",
                        "image_link": "https://example.com/image.png",
                    }
                ],
            }
        }

        items = _build_campaign_intake_items(
            payload,
            {
                "KT-OAI-20260620-001": {
                    "operator_name": "운영자",
                    "status": "in_progress",
                    "memo": "세팅 중",
                }
            },
        )

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["receipt_number"], "KT-OAI-20260620-001")
        self.assertEqual(item["advertiser_name"], "나스미디어")
        self.assertEqual(item["operator_name"], "운영자")
        self.assertEqual(item["status_label"], "진행중")
        self.assertEqual(item["campaign_count"], 1)
        self.assertEqual(item["adgroup_count"], 1)
        self.assertEqual(item["ad_count"], 1)
        self.assertEqual(item["campaigns"][0]["campaign_name"], "캠페인1")
        self.assertEqual(item["campaigns"][0]["adgroups"][0]["adgroup_name"], "광고그룹1")
        self.assertEqual(item["campaigns"][0]["adgroups"][0]["ads"][0]["ad_name"], "소재1")

    def test_campaign_intake_admin_endpoints_are_admin_only(self) -> None:
        client = TestClient(app)
        headers = {"x-admin-password": "nas2026@"}

        denied = client.get("/api/admin/campaign-intakes")
        self.assertEqual(denied.status_code, 403)

        with patch("admin_store.list_campaign_intake_items", return_value={"ok": True, "items": []}):
            listed = client.get("/api/admin/campaign-intakes", headers=headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["items"], [])

        with patch("admin_store.update_campaign_intake_ops", return_value={"ok": True, "item": {"receipt_number": "KT-OAI-1"}}):
            updated = client.post(
                "/api/admin/campaign-intakes/update",
                headers=headers,
                json={"receipt_number": "KT-OAI-1", "operator_name": "운영자", "status": "done"},
            )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["item"]["receipt_number"], "KT-OAI-1")

    def test_campaign_intake_status_labels_match_ops_workflow(self) -> None:
        self.assertEqual(
            CAMPAIGN_INTAKE_STATUSES,
            {
                "ready": "대기",
                "in_progress": "진행중",
                "done": "완료",
                "canceled": "취소",
            },
        )

    def test_campaign_intake_list_reports_old_apps_script_action_clearly(self) -> None:
        with patch("admin_store._post_intake_webhook", return_value={"ok": False, "error": "campaigns is required"}):
            result = list_campaign_intake_items()

        self.assertFalse(result["ok"])
        self.assertIn("Apps Script", result["error"])
        self.assertIn("새 버전", result["error"])


if __name__ == "__main__":
    unittest.main()
