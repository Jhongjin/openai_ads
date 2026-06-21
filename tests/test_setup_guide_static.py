from __future__ import annotations

from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from app import app


ROOT = Path(__file__).resolve().parents[1]


def index_html() -> str:
    return (ROOT / "templates" / "index.html").read_text(encoding="utf-8")


class SetupGuideStaticTests(unittest.TestCase):
    def test_setup_guide_tab_and_pdf_filename_exist(self) -> None:
        html = index_html()

        required = [
            'data-guide-deck="setup"',
            "캠페인 세팅 가이드",
            "ChatGPT광고_캠페인세팅가이드_케이티나스미디어",
            "printCurrentGuideDeck",
            "document.body.classList.add(\"dev-guide-print\")",
            "/api/guide-deck-html",
            "state.guideDeckHtml",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

    def test_setup_guide_has_cover_three_steps_and_preview(self) -> None:
        html = index_html()

        required = [
            "광고 캠페인 세팅 가이드",
            "캠페인 → 광고그룹 → 광고 생성 프로세스",
            "https://ads.openai.com/",
            "STEP 1 · 캠페인",
            "STEP 2 · 광고그룹",
            "STEP 3 · 광고 만들기",
            "플래너에게 받아야 할 캠페인 정보 및 소재",
            "광고 소재 미리보기",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

    def test_setup_guide_required_fields_and_copy_limits(self) -> None:
        html = index_html()

        required = [
            "캠페인 이름",
            "필수 · 최소 3자 이상 입력",
            "표준(디폴트) / 제품피드 선택 가능",
            "클릭(디폴트) / 도달 / 전환(coming soon)",
            "대한민국",
            "총예산 설정 후 일예산 변경 가능",
            "일예산 설정 후 총예산 변경 불가",
            "시작일 / 종료일 시간까지 설정 필요",
            "입찰가(CPC/CPM)",
            "최대 입찰가",
            "4,100원부터 경쟁력 있는 비딩가",
            "CPM 입찰",
            "컨텍스트 힌트",
            "정확히 일치하는 표적을 공략하기 위한 규칙은 아님",
            "헤드라인",
            "최소 3자 ~ 최대 50자",
            "설명",
            "최소 3자 ~ 최대 100자",
            "PNG 또는 JPG 업로드",
            "광고 클릭 시 이동하는 URL",
            "접수 폼(24/48)·크리테오 경유(30/60)와는 별개 채널 기준",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

    def test_setup_guide_image_slots_use_fixed_paths_and_captions(self) -> None:
        html = index_html()

        required = [
            'imageKey: "campaign_step1"',
            'imageKey: "campaign_step2"',
            'imageKey: "campaign_step3"',
            'imageKey: "campaign_preview"',
            "캠페인 만들기 화면",
            "광고그룹 만들기 화면",
            "광고 만들기 화면",
            "광고 소재 미리보기",
            "관리자 콘솔에서 이미지를 수정할 수 있습니다.",
            "실계정명/개인정보가 노출될 경우 업로드 전 마스킹",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

    def test_setup_guide_images_are_served_as_static_assets(self) -> None:
        client = TestClient(app)
        response = client.get("/images/guide/campaign_step1.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")


if __name__ == "__main__":
    unittest.main()
