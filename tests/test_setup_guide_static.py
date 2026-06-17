from __future__ import annotations

from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from app import app


ROOT = Path(__file__).resolve().parents[1]


def setup_guide_html() -> str:
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    start = html.index('<section class="panel" id="setup-guide-panel">')
    end = html.index("    </main>", start)
    return html[start:end]


class SetupGuideStaticTests(unittest.TestCase):
    def test_setup_guide_tab_and_pdf_filename_exist(self) -> None:
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

        self.assertIn('data-tab="setupGuide"', html)
        self.assertIn("캠페인 세팅 가이드", html)
        self.assertIn("ChatGPT광고_캠페인세팅가이드_케이티나스미디어_", html)
        self.assertIn("print-guide", html)

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
            "광고 소재 미리보기",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

    def test_setup_guide_required_fields_and_copy_limits(self) -> None:
        html = setup_guide_html()

        required = [
            "캠페인 이름",
            "필수 입력, 3자 이상",
            "표준 기본 / 제품피드",
            "클릭 기본 / 도달·전환 coming soon",
            "대한민국",
            "최초 설정 후 유형 변경 불가",
            "GMT+9",
            "최대 CPC 입찰가",
            "4,000원은 게재 경쟁력이 낮을 수 있음",
            "4,100원 이상은 경쟁력 있을 가능성",
            "컨텍스트 힌트",
            "정확 일치 규칙은 아닙니다",
            "헤드라인",
            "3~50자",
            "설명",
            "3~100자",
            "PNG/JPG, 정사각형, 최소 256×256px 권장",
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
