from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import app


ADMIN_HEADERS = {"x-admin-password": "nas2026@"}


def adcopy_payload() -> dict:
    return {
        "advertiser_name": "캐츠잉글리시",
        "industry": "교육",
        "campaign_name": "01_학습자료",
        "objective": "Views",
        "budget_max": 102600,
        "budget_type": "daily",
        "launch_date": "2026-07-01",
        "end_date": "2026-07-31",
        "target_countries": ["KR"],
        "product_name": "초등 영어 학습 앱",
        "landing_url": "https://example.com/landing",
        "image_link": "https://example.com/image.png",
        "audience": "초등학생 영어 학습을 돕는 학부모",
        "selling_points": "짧은 반복 훈련, 수준별 학습, 학습 리포트 제공",
        "tone": "담백하고 신뢰감 있게",
        "banned_terms": "무조건\n업계 1위",
        "required_phrases": "",
        "adgroup_count": 1,
        "ads_per_adgroup": 2,
    }


def generated_payload() -> dict:
    trace = {
        "source_type": "AI 생성",
        "source_url": "",
        "source_excerpt": "",
        "generation_basis": "초등 영어 반복 학습",
        "confidence_score": 0.82,
        "validation_status": "운영 검수 필요",
        "review_comment": "should be removed",
        "exclusion_reason": "should be removed",
    }
    return {
        "policy": {"banned_terms": []},
        "campaigns": [],
        "adgroups": [
            {
                "campaign_name": "AI가 바꾼 이름",
                "adgroup_name": "01_반복훈련",
                "max_bid": 7000,
                "keywords": [
                    {"text": "초등 영어 앱", "origin": "customer_data"},
                    {"text": "영어 반복 학습", "origin": "ai_inferred"},
                    {"text": "초등 파닉스", "origin": "ai_inferred"},
                    {"text": "초등 영어 리포트", "origin": "ai_inferred"},
                    {"text": "집에서 영어 공부", "origin": "ai_inferred"},
                ],
                "required_phrases": [],
                "trace": trace,
            }
        ],
        "ads": [
            {
                "ad_name": "KID_01_001",
                "adgroup_name": "01_반복훈련",
                "title": "초등 영어 반복 훈련",
                "copy": "짧은 학습 루틴으로 매일 영어 자신감을 키우세요",
                "link": "https://wrong.example",
                "image_link": "https://wrong.example/image.png",
                "trace": trace,
            },
            {
                "ad_name": "KID_01_002",
                "adgroup_name": "01_반복훈련",
                "title": "수준별 영어 학습",
                "copy": "아이 수준에 맞춘 영어 훈련과 리포트를 확인하세요",
                "link": "https://wrong.example",
                "image_link": "https://wrong.example/image.png",
                "trace": trace,
            },
        ],
    }


class AdcopyGeneratorAdminTests(unittest.TestCase):
    def test_admin_adcopy_generation_requires_admin_password(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/admin/adcopy/generate", json=adcopy_payload())
        empty_response = client.post("/api/admin/adcopy/generate", json={})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(empty_response.status_code, 403)

    def test_admin_adcopy_generation_normalizes_and_validates_generated_json(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        mocked_call = AsyncMock(
            return_value={
                "model": "gpt-test",
                "raw_response_id": "resp_test",
                "generated": generated_payload(),
            }
        )

        with patch("app._call_openai_adcopy", mocked_call):
            response = client.post("/api/admin/adcopy/generate", json=adcopy_payload(), headers=ADMIN_HEADERS)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["model"], "gpt-test")
        self.assertEqual(body["generated"]["campaigns"][0]["campaign_name"], "01_학습자료")
        self.assertEqual(body["generated"]["campaigns"][0]["budget_max"], 102600)
        self.assertNotIn("max_bid", body["generated"]["adgroups"][0])
        self.assertEqual(body["generated"]["ads"][0]["link"], "https://example.com/landing")
        self.assertEqual(body["generated"]["ads"][0]["image_link"], "https://example.com/image.png")
        self.assertEqual(body["generated"]["ads"][0]["trace"]["review_comment"], "")
        self.assertEqual(body["summary"]["adgroups"], 1)
        self.assertEqual(body["summary"]["ads"], 2)
        self.assertIn("quality", body["validation_report"])
        self.assertIn("creative_checks", body["validation_report"])
        self.assertGreaterEqual(body["validation_report"]["quality"]["score"], 1)
        self.assertEqual(body["validation_report"]["creative_checks"][0]["ad_name"], "KID_01_001")
        self.assertIn("readiness", body["summary"])

    def test_admin_adcopy_generation_reports_policy_errors(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        generated = generated_payload()
        generated["ads"][0]["title"] = "업계 1위 영어 학습"
        mocked_call = AsyncMock(
            return_value={
                "model": "gpt-test",
                "raw_response_id": "resp_test",
                "generated": generated,
            }
        )

        with patch("app._call_openai_adcopy", mocked_call):
            response = client.post("/api/admin/adcopy/generate", json=adcopy_payload(), headers=ADMIN_HEADERS)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertIn("banned_term", {item["rule"] for item in body["validation_report"]["errors"]})

    def test_admin_adcopy_generation_reports_quality_warnings(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        generated = generated_payload()
        generated["ads"][0]["copy"] = "학습을 고려한 영어 앱"
        mocked_call = AsyncMock(
            return_value={
                "model": "gpt-test",
                "raw_response_id": "resp_test",
                "generated": generated,
            }
        )

        with patch("app._call_openai_adcopy", mocked_call):
            response = client.post("/api/admin/adcopy/generate", json=adcopy_payload(), headers=ADMIN_HEADERS)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        warning_rules = {item["rule"] for item in body["validation_report"]["warnings"]}
        self.assertIn("awkward_phrase", warning_rules)
        self.assertLess(body["validation_report"]["quality"]["score"], 100)
        self.assertEqual(body["validation_report"]["creative_checks"][0]["status"], "warning")

    def test_admin_adcopy_validate_requires_admin_password(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/admin/adcopy/validate", json={"generated": generated_payload()})

        self.assertEqual(response.status_code, 403)

    def test_admin_adcopy_validate_reviews_edited_generated_json(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        generated = generated_payload()
        generated["ads"][0]["title"] = "짧음"

        response = client.post("/api/admin/adcopy/validate", json={"generated": generated}, headers=ADMIN_HEADERS)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("validation_report", body)
        warning_rules = {item["rule"] for item in body["validation_report"]["warnings"]}
        self.assertIn("title_len_recommended", warning_rules)
        self.assertEqual(body["validation_report"]["creative_checks"][0]["status"], "warning")

    def test_admin_adcopy_import_requires_admin_password(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/admin/adcopy/import", json={"generated": generated_payload()})

        self.assertEqual(response.status_code, 403)

    def test_admin_adcopy_import_normalizes_native_generated_json(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        generated = generated_payload()
        generated["campaigns"] = [
            {
                "campaign_name": "01_학습자료",
                "budget_max": 102600,
                "budget_type": "daily",
                "launch_date": "2026-07-01",
                "end_date": "2026-07-31",
                "objective": "Views",
                "target_countries": ["KR"],
            }
        ]

        response = client.post(
            "/api/admin/adcopy/import",
            json={
                "generated": generated,
                "advertiser_name": "캐츠잉글리시",
                "landing_url": "https://example.com/landing",
                "image_link": "https://example.com/image.png",
            },
            headers=ADMIN_HEADERS,
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["model"], "외부 JSON 정규화")
        self.assertEqual(body["import_report"]["source_format"], "native")
        self.assertEqual(body["generated"]["campaigns"][0]["campaign_name"], "01_학습자료")
        self.assertNotIn("max_bid", body["generated"]["adgroups"][0])
        self.assertEqual(body["summary"]["ads"], 2)

    def test_admin_adcopy_import_accepts_ai_team_style_json(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        external = {
            "campaign": {
                "캠페인명": "초등영어_테스트",
                "예산": "25,000원",
                "예산유형": "일 예산",
                "시작일": "2026-07-10",
                "종료일": "2026-07-31",
                "목표": "노출",
                "국가": "KR",
            },
            "ad_groups": [
                {
                    "광고그룹명": "01_학습습관",
                    "확장 키워드": ["초등 영어 앱", "매일 영어 학습", "파닉스 연습", "영어 루틴", "학부모 영어"],
                    "필수 포함 문구": ["영어 루틴"],
                }
            ],
            "creatives": [
                {
                    "소재명": "AD_001",
                    "광고그룹명": "01_학습습관",
                    "제목": "초등 영어 습관 만들기",
                    "카피": "영어 루틴으로 매일 짧게 학습을 이어가요",
                    "랜딩 URL": "https://example.com/landing",
                    "이미지 URL": "https://example.com/image.png",
                    "휴먼 체크": "확인 완료 검수",
                }
            ],
            "policy": {"banned_terms": ["무조건"]},
        }

        response = client.post(
            "/api/admin/adcopy/import",
            json={"generated": external, "advertiser_name": "캐츠잉글리시"},
            headers=ADMIN_HEADERS,
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["generated"]["campaigns"][0]["budget_type"], "daily")
        self.assertEqual(body["generated"]["campaigns"][0]["objective"], "Views")
        self.assertEqual(body["generated"]["adgroups"][0]["keywords"][0]["text"], "초등 영어 앱")
        self.assertEqual(body["generated"]["ads"][0]["trace"]["validation_status"], "승인")
        self.assertIn("무조건", body["generated"]["policy"]["banned_terms"])

    def test_admin_adcopy_landing_inspect_requires_admin_password(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/admin/adcopy/inspect-landing", json={"landing_url": "https://example.com"})
        empty_response = client.post("/api/admin/adcopy/inspect-landing", json={})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(empty_response.status_code, 403)

    def test_admin_adcopy_landing_inspect_extracts_public_metadata(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        html = """
        <html>
          <head>
            <title>카누 디카페인 캡슐</title>
            <meta property="og:title" content="카누 디카페인 캡슐 커피">
            <meta name="description" content="부드러운 캐러멜 향과 돌체구스토 호환 캡슐">
            <meta property="og:image" content="/image.jpg">
            <link rel="Canonical" href="/canonical-product">
          </head>
        </html>
        """
        mocked_fetch = AsyncMock(return_value=(html, "https://example.com/product"))

        with patch("app._fetch_landing_html", mocked_fetch):
            response = client.post(
                "/api/admin/adcopy/inspect-landing",
                json={"landing_url": "https://example.com/product"},
                headers=ADMIN_HEADERS,
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["metadata"]["title"], "카누 디카페인 캡슐 커피")
        self.assertIn("돌체구스토 호환", body["metadata"]["description"])
        self.assertEqual(body["metadata"]["image_url"], "https://example.com/image.jpg")
        self.assertEqual(body["metadata"]["canonical_url"], "https://example.com/canonical-product")

    def test_admin_adcopy_landing_inspect_rejects_private_ip_url(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/admin/adcopy/inspect-landing",
            json={"landing_url": "http://127.0.0.1:8000/private"},
            headers=ADMIN_HEADERS,
        )

        self.assertEqual(response.status_code, 400)

    def test_admin_adcopy_draft_plan_builds_paused_payloads(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        generated = generated_payload()
        generated["campaigns"] = [
            {
                "campaign_name": "01_학습자료",
                "budget_max": 102600,
                "budget_type": "daily",
                "launch_date": "2026-07-01",
                "end_date": "2026-07-03",
                "objective": "Views",
                "target_countries": ["KR"],
            }
        ]
        generated["adgroups"][0].pop("max_bid", None)

        response = client.post(
            "/api/admin/adcopy/draft-plan",
            json={
                "advertiser_name": "캐츠잉글리시",
                "generated": generated,
                "default_max_bid_krw": 7000,
                "location_ids": ["2000043"],
            },
            headers=ADMIN_HEADERS,
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["safety"]["default_status"], "paused")
        self.assertEqual(body["campaign"]["api_payload"]["status"], "paused")
        self.assertEqual(body["campaign"]["api_payload"]["budget"]["lifetime_spend_limit_micros"], 307800000000)
        self.assertEqual(body["ad_groups"][0]["api_payload"]["status"], "paused")
        self.assertEqual(body["ad_groups"][0]["api_payload"]["bidding_config"]["max_bid_micros"], 7000000)
        self.assertEqual(body["ads"][0]["api_payload"]["status"], "paused")
        self.assertEqual(body["summary"]["ads"], 2)

    def test_admin_adcopy_draft_execute_requires_confirm_for_mutation(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        generated = generated_payload()
        generated["campaigns"] = [
            {
                "campaign_name": "01_학습자료",
                "budget_max": 100000,
                "budget_type": "total",
                "launch_date": "2026-07-01",
                "end_date": "2026-07-03",
                "objective": "Views",
                "target_countries": ["KR"],
            }
        ]
        generated["adgroups"][0].pop("max_bid", None)

        with patch("admin_store.get_ads_api_key_credential", return_value={"api_key": "sk-test", "industry": "교육"}):
            response = client.post(
                "/api/admin/adcopy/draft-execute",
                json={
                    "advertiser_name": "캐츠잉글리시",
                    "generated": generated,
                    "action": "create_campaign",
                    "confirm": False,
                },
                headers=ADMIN_HEADERS,
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("실행 확인", response.json()["detail"])

    def test_admin_adcopy_draft_execute_creates_campaign_paused(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        generated = generated_payload()
        generated["campaigns"] = [
            {
                "campaign_name": "01_학습자료",
                "budget_max": 100000,
                "budget_type": "total",
                "launch_date": "2026-07-01",
                "end_date": "2026-07-03",
                "objective": "Views",
                "target_countries": ["KR"],
            }
        ]
        generated["adgroups"][0].pop("max_bid", None)
        mocked_request = AsyncMock(return_value={"id": "cmpn_test", "status": "paused"})

        with patch("admin_store.get_ads_api_key_credential", return_value={"api_key": "sk-test", "industry": "교육"}):
            with patch("app._ads_draft_api_request", mocked_request):
                response = client.post(
                    "/api/admin/adcopy/draft-execute",
                    json={
                        "advertiser_name": "캐츠잉글리시",
                        "generated": generated,
                        "action": "create_campaign",
                        "confirm": True,
                    },
                    headers=ADMIN_HEADERS,
                )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"]["campaign_id"], "cmpn_test")
        called_args = mocked_request.await_args.args
        self.assertEqual(called_args[1], "POST")
        self.assertEqual(called_args[2], "/v1/campaigns")
        self.assertEqual(called_args[3]["status"], "paused")


if __name__ == "__main__":
    unittest.main()
