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
        "advertiserName": "테스트 광고주",
        "legalName": "테스트 주식회사",
        "websiteUrl": "https://example.com",
        "targetCountry": "대한민국",
        "billingCurrency": "KRW",
        "timezone": "Asia/Seoul",
        "invoiceEmail": "invoice@example.com",
        "executionRoute": "openai_cbt",
        "campaignName": "ChatGPT Ads 테스트",
        "campaignObjective": "clicks",
        "budgetType": "total",
        "budgetAmount": 4000000,
        "startDate": tomorrow.isoformat(),
        "endDate": end.isoformat(),
        "adsManagerReady": True,
        "paymentReady": True,
        "crawlerReady": True,
        "faviconReady": True,
        "contactName": "홍길동",
        "contactPhone": "010-0000-0000",
        "contactEmail": "client@example.com",
        "salesOwner": "나스 담당자",
        "notes": "테스트",
        "honeypot": "",
        "formStartedAt": int(datetime.now(KST).timestamp() * 1000) - 3000,
    }


class IntakeValidationTests(unittest.TestCase):
    def test_valid_payload_builds_sheet_payload_with_secret(self) -> None:
        submission = IntakeSubmission.model_validate(valid_payload())

        payload = build_sheet_payload(
            submission,
            receipt_number="KT-OAI-20260617-001",
            submitted_at_kst="2026-06-17 12:00:00",
            shared_secret="secret",
        )

        self.assertEqual(payload["shared_secret"], "secret")
        self.assertEqual(payload["receiptNumber"], "KT-OAI-20260617-001")
        self.assertEqual(payload["submittedAtKst"], "2026-06-17 12:00:00")
        self.assertEqual(payload["readyStatus"]["crawlerReady"], True)
        self.assertNotIn("honeypot", payload)

    def test_rejects_reversed_dates(self) -> None:
        payload = valid_payload()
        payload["endDate"] = payload["startDate"]
        payload["startDate"] = (
            datetime.fromisoformat(payload["endDate"]).date() + timedelta(days=1)
        ).isoformat()

        with self.assertRaises(ValidationError):
            IntakeSubmission.model_validate(payload)

    def test_criteo_forces_views_objective(self) -> None:
        payload = valid_payload()
        payload["executionRoute"] = "criteo"
        payload["campaignObjective"] = "clicks"

        with self.assertRaises(ValidationError):
            IntakeSubmission.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
