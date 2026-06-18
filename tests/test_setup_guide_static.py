from __future__ import annotations

from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from app import app


ROOT = Path(__file__).resolve().parents[1]


def setup_guide_html() -> str:
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    start = html.index('<section class="panel" id="setup-guide-panel">')
    end = html.index('<section class="panel" id="pixel-guide-panel">', start)
    return html[start:end]


class SetupGuideStaticTests(unittest.TestCase):
    def test_setup_guide_tab_and_pdf_filename_exist(self) -> None:
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

        self.assertIn('data-tab="setupGuide"', html)
        self.assertIn("캠페인 세팅 가이드", html)
        self.assertIn('.tab[data-tab="setupGuide"] > span:last-child', html)
        self.assertIn("white-space: nowrap", html)
        self.assertIn("ChatGPT광고_캠페인세팅가이드_케이티나스미디어_", html)
        self.assertIn("print-guide", html)
        self.assertIn("size: A4 landscape", html)
        self.assertIn("width: 297mm", html)
        self.assertIn(".guide-two-column", html)
        self.assertIn("grid-template-columns: minmax(58mm, 0.72fr) minmax(0, 1.28fr) !important", html)
        self.assertIn("object-fit: contain", html)

    def test_setup_guide_has_cover_three_steps_and_preview(self) -> None:
        html = setup_guide_html()

        self.assertEqual(html.count('class="slide-card'), 5)
        required = [
            "광고 캠페인 세팅 가이드",
            "캠페인 → 광고그룹 → 광고 생성 프로세스",
            "https://ads.openai.com/",
            "STEP 1 · 캠페인",
            "STEP 2 · 광고그룹",
            "STEP 3 · 광고 만들기",
            "플래너에게 받아야 할 캠페인 정보 및 소재",
            "CPC 최대 152,000원 / CPM 최대 100,000원",
            "광고 소재 미리보기",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

    def test_setup_guide_required_fields_and_copy_limits(self) -> None:
        html = setup_guide_html()

        required = [
            "캠페인 이름",
            "필수 · 최소 3자 이상 입력(자유롭게 설정)",
            "표준(디폴트) / 제품피드 선택 가능",
            "클릭(디폴트) / 도달 / 전환(coming soon)",
            "대한민국",
            "총예산 설정 후 일예산 변경 가능",
            "일예산 설정 후 총예산 변경 불가",
            "시작일 / 종료일 시간까지 설정 필요",
            "입찰가(CPC/CPM)",
            "최대 입찰가",
            "최대 152,000원 세팅 가능",
            "4,100원부터 경쟁력 있는 비딩가",
            "CPM 입찰(최대 100,000원 세팅 가능)",
            "의미 체크 필요",
            "컨텍스트 힌트",
            "정확히 일치하는 표적을 공략하기 위한 규칙은 아님",
            "헤드라인",
            "최소 3자 ~ 최대 50자",
            "한글·알파벳·숫자·띄어쓰기 모두 1자로 카운팅",
            "설명",
            "최소 3자 ~ 최대 100자",
            "PNG 또는 JPG 업로드",
            "광고 클릭 시 이동하는 URL",
            "접수 폼(24/48)·크리테오 경유(30/60)와는 별개 채널 기준",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

    def test_setup_guide_image_slots_use_fixed_paths_and_captions(self) -> None:
        html = setup_guide_html()

        required = [
            "/images/guide/campaign_step1.png",
            "/images/guide/campaign_step2.png",
            "/images/guide/campaign_step3.png",
            "/images/guide/campaign_preview.png",
            "캠페인 만들기 화면",
            "광고그룹 만들기 화면",
            "광고 만들기 화면",
            "광고 소재 미리보기",
            "캡처 이미지 삽입 위치",
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
