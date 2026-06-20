from __future__ import annotations

from datetime import datetime, timedelta
import unittest
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app import app


KST = ZoneInfo("Asia/Seoul")


def invalid_name_payload() -> dict:
    tomorrow = datetime.now(KST).date() + timedelta(days=1)
    end = tomorrow + timedelta(days=7)
    return {
        "opsMeta": {
            "executionRoute": "openai_cbt",
            "advertiserName": "테스트 광고주",
            "adsManagerAccount": "테스트 브랜드",
            "salesOwner": "담당자",
            "salesOwnerEmail": "owner@example.com",
            "ownerHeadquarters": "본부",
            "ownerOffice": "실",
            "ownerTeam": "팀",
            "notes": "",
            "adsManagerReady": False,
            "paymentReady": False,
            "crawlerReady": False,
            "faviconReady": False,
            "honeypot": "",
            "formStartedAt": int(datetime.now(KST).timestamp() * 1000) - 3000,
        },
        "campaigns": [
            {
                "campaign": {
                    "campaign_name": "캠페인.1",
                    "budget_max": 4000000,
                    "budget_type": "daily",
                    "launch_date": tomorrow.isoformat(),
                    "end_date": end.isoformat(),
                    "objective": "views",
                    "target_countries": [],
                },
                "adgroups": [
                    {
                        "adgroup": {
                            "campaign_name": "캠페인.1",
                            "adgroup_name": "그룹/1",
                            "max_bid": None,
                            "keywords": [],
                        },
                        "ads": [
                            {
                                "adgroup_name": "그룹/1",
                                "ad_name": "소재(1)",
                                "title": "광고 제목",
                                "copy": "광고 설명",
                                "link": "https://example.com",
                                "image_link": "https://example.com/image.png",
                            }
                        ],
                    }
                ],
            }
        ],
    }


class IntakeApiTests(unittest.TestCase):
    def test_workbook_accepts_korean_names(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        payload = invalid_name_payload()
        campaign = payload["campaigns"][0]
        adgroup = campaign["adgroups"][0]
        ad = adgroup["ads"][0]
        campaign["campaign"]["campaign_name"] = "캠페인1"
        adgroup["adgroup"]["campaign_name"] = "캠페인1"
        adgroup["adgroup"]["adgroup_name"] = "그룹1"
        ad["adgroup_name"] = "그룹1"
        ad["ad_name"] = "소재1"

        response = client.post("/intake/workbook", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["content-type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertGreater(len(response.content), 1000)

    def test_workbook_validation_errors_are_json_serializable(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/intake/workbook", json=invalid_name_payload())

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Internal Server Error", response.text)
        body = response.json()
        self.assertIn("캠페인명에는 한글, 영문", body["detail"][0]["msg"])
        self.assertNotIn("ctx", body["detail"][0])

    def test_sheet_validation_errors_are_json_serializable(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/intake", json=invalid_name_payload())

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Internal Server Error", response.text)
        body = response.json()
        self.assertIn("캠페인명에는 한글, 영문", body["detail"][0]["msg"])
        self.assertNotIn("ctx", body["detail"][0])


if __name__ == "__main__":
    unittest.main()
