from __future__ import annotations

from datetime import datetime, timedelta
import unittest
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from intake import IntakeSubmission, build_sheet_payload


KST = ZoneInfo("Asia/Seoul")


def valid_payload() -> dict:
    tomorrow = datetime.now(KST).date() + timedelta(days=1)
    end = tomorrow + timedelta(days=14)
    return {
        "opsMeta": {
            "executionRoute": "openai_cbt",
            "advertiserName": "테스트 광고주",
            "legalName": "테스트 주식회사",
            "brn": "123-45-67890",
            "advertiserHomepageUrl": "https://example.com",
            "invoiceEmail": "invoice@example.com",
            "adsManagerReady": True,
            "paymentReady": True,
            "crawlerReady": True,
            "faviconReady": True,
            "contactName": "홍길동",
            "contactPhone": "010-0000-0000",
            "contactEmail": "client@example.com",
            "salesOwner": "케이티나스 담당자",
            "notes": "테스트",
            "honeypot": "",
            "formStartedAt": int(datetime.now(KST).timestamp() * 1000) - 3000,
        },
        "campaign": {
            "campaign_name": "ChatGPT Ads 테스트",
            "budget_max": 4000000,
            "budget_type": "lifetime",
            "launch_date": tomorrow.isoformat(),
            "end_date": end.isoformat(),
            "objective": "clicks",
            "target_countries": ["KR"],
        },
        "adgroup": {
            "campaign_name": "ChatGPT Ads 테스트",
            "adgroup_name": "테스트 그룹",
            "max_bid": 1200,
            "keywords": ["밀키트", "저녁"],
        },
        "ads": [
            {
                "adgroup_name": "테스트 그룹",
                "title": "건강한 저녁 준비",
                "copy": "빠르게 차리는 균형 잡힌 한 끼",
                "link": "https://example.com/landing?utm_source=openai",
                "image_link": "https://example.com/image1.jpg",
            },
            {
                "adgroup_name": "테스트 그룹",
                "title": "퇴근 후 간편 식사",
                "copy": "오늘 저녁 고민을 줄여주는 밀키트",
                "link": "https://example.com/landing-2",
                "image_link": "https://example.com/image2.png",
            },
        ],
    }


class IntakeValidationTests(unittest.TestCase):
    def test_valid_payload_builds_four_sheet_sections(self) -> None:
        submission = IntakeSubmission.model_validate(valid_payload())

        payload = build_sheet_payload(
            submission,
            shared_secret="secret",
        )

        self.assertEqual(payload["secret"], "secret")
        self.assertEqual(payload["data"]["campaign"]["campaign_name"], "ChatGPT Ads 테스트")
        self.assertEqual(payload["data"]["campaign"]["budget_max"], "4000000")
        self.assertEqual(payload["data"]["campaign"]["target_countries"], ["KR"])
        self.assertEqual(len(payload["data"]["adgroups"]), 1)
        self.assertEqual(len(payload["data"]["ads"]), 2)
        self.assertEqual(payload["data"]["adgroups"][0]["keywords"], ["밀키트", "저녁"])
        self.assertEqual(payload["data"]["adgroups"][0]["max_bid"], "1200")
        self.assertEqual(payload["data"]["ops"]["route"], "OpenAI 직접 CBT")
        self.assertEqual(payload["data"]["ops"]["brn"], "123-45-67890")
        self.assertEqual(payload["data"]["ops"]["homepage"], "https://example.com")
        self.assertNotIn("honeypot", payload["data"]["ops"])
        self.assertNotIn("receiptNumber", payload)

    def test_multi_campaign_payload_preserves_each_campaign_and_adgroup_link(self) -> None:
        payload = valid_payload()
        tomorrow = datetime.now(KST).date() + timedelta(days=1)
        end = tomorrow + timedelta(days=14)
        payload.pop("campaign")
        payload.pop("adgroup")
        payload.pop("ads")
        payload["campaigns"] = [
            {
                "campaign": {
                    "campaign_name": "campaign_cpm",
                    "budget_max": 4000000,
                    "budget_type": "lifetime",
                    "launch_date": tomorrow.isoformat(),
                    "end_date": end.isoformat(),
                    "objective": "views",
                    "target_countries": ["KR"],
                },
                "adgroups": [
                    {
                        "adgroup": {
                            "adgroup_name": "ag_cpm",
                            "max_bid": 91000,
                            "keywords": ["노출"],
                        },
                        "ads": [
                            {
                                "title": "노출 캠페인 소재",
                                "copy": "브랜드 메시지를 넓게 알립니다",
                                "link": "https://example.com/cpm",
                                "image_link": "https://example.com/cpm.png",
                            }
                        ],
                    }
                ],
            },
            {
                "campaign": {
                    "campaign_name": "campaign_cpc",
                    "budget_max": 4000000,
                    "budget_type": "daily",
                    "launch_date": tomorrow.isoformat(),
                    "end_date": end.isoformat(),
                    "objective": "clicks",
                    "target_countries": ["KR"],
                },
                "adgroups": [
                    {
                        "adgroup": {
                            "adgroup_name": "ag_cpc",
                            "max_bid": 4100,
                            "keywords": ["클릭"],
                        },
                        "ads": [
                            {
                                "title": "클릭 캠페인 소재",
                                "copy": "랜딩 페이지 방문을 유도합니다",
                                "link": "https://example.com/cpc",
                                "image_link": "https://example.com/cpc.png",
                            }
                        ],
                    }
                ],
            },
        ]

        submission = IntakeSubmission.model_validate(payload)
        sheet_payload = build_sheet_payload(submission, shared_secret="secret")

        self.assertEqual(
            [item["campaign_name"] for item in sheet_payload["data"]["campaigns"]],
            ["campaign_cpm", "campaign_cpc"],
        )
        self.assertEqual(
            [item["objective"] for item in sheet_payload["data"]["campaigns"]],
            ["views", "clicks"],
        )
        self.assertEqual(
            [(item["campaign_name"], item["adgroup_name"]) for item in sheet_payload["data"]["adgroups"]],
            [("campaign_cpm", "ag_cpm"), ("campaign_cpc", "ag_cpc")],
        )
        self.assertEqual(len(sheet_payload["data"]["ads"]), 2)

    def test_rejects_special_characters_in_names(self) -> None:
        payload = valid_payload()
        payload["campaign"]["campaign_name"] = "캠페인#1"

        with self.assertRaises(ValidationError):
            IntakeSubmission.model_validate(payload)

    def test_rejects_reversed_dates(self) -> None:
        payload = valid_payload()
        payload["campaign"]["end_date"] = payload["campaign"]["launch_date"]
        payload["campaign"]["launch_date"] = (
            datetime.fromisoformat(payload["campaign"]["end_date"]).date() + timedelta(days=1)
        ).isoformat()

        with self.assertRaises(ValidationError):
            IntakeSubmission.model_validate(payload)

    def test_criteo_forces_views_objective(self) -> None:
        payload = valid_payload()
        payload["opsMeta"]["executionRoute"] = "criteo"
        payload["campaign"]["objective"] = "clicks"

        with self.assertRaises(ValidationError):
            IntakeSubmission.model_validate(payload)

    def test_openai_title_and_copy_limits_are_official_workbook_limits(self) -> None:
        payload = valid_payload()
        payload["ads"][0]["title"] = "가" * 25

        with self.assertRaises(ValidationError):
            IntakeSubmission.model_validate(payload)

        payload = valid_payload()
        payload["ads"][0]["copy"] = "나" * 49

        with self.assertRaises(ValidationError):
            IntakeSubmission.model_validate(payload)

    def test_criteo_uses_30_60_limits(self) -> None:
        payload = valid_payload()
        payload["opsMeta"]["executionRoute"] = "criteo"
        payload["campaign"]["objective"] = "views"
        payload["ads"][0]["title"] = "가" * 30
        payload["ads"][0]["copy"] = "나" * 60
        IntakeSubmission.model_validate(payload)

        payload["ads"][0]["title"] = "가" * 31
        with self.assertRaises(ValidationError):
            IntakeSubmission.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
