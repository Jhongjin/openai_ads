from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def slides_panel_html() -> str:
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    start = html.index('<section class="panel" id="slides-panel">')
    end = html.index('<section class="panel" id="setup-guide-panel">', start)
    return html[start:end]


class AdvertiserSlidesStaticTests(unittest.TestCase):
    def test_slides_have_five_pages_and_print_action(self) -> None:
        html = slides_panel_html()
        full_html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

        self.assertEqual(html.count('class="slide-card'), 5)
        self.assertIn("PDF로 저장", html)
        self.assertIn('const LAST_UPDATED = "2026-06-17"', full_html)
        self.assertIn("ChatGPT광고_집행준비안내_케이티나스미디어_", full_html)
        self.assertIn("window.print()", full_html)

    def test_advertiser_slides_hide_internal_terms(self) -> None:
        html = slides_panel_html()

        forbidden = [
            "나스미디어 내부 자료",
            "OpenAI 공식 문서",
            "확인 대기",
            "미확정",
            "내부 기준",
            "1,000만원",
            "마크업",
            "호스팅 fee",
        ]
        for word in forbidden:
            self.assertNotIn(word, html)

    def test_advertiser_slides_keep_required_public_claims(self) -> None:
        html = slides_panel_html()

        required = [
            "최대 제목 24자 / 권장 16~18자",
            "최대 설명 48자 / 권장 32~36자",
            "OpenAI 공식 워크북 기준",
            "제목 30자 / 설명 60자",
            "정식 오픈 시 Ads Manager 재확인",
            "광고 카피 작성 가이드",
            "건강한 저녁, 빠르게 준비하고 싶다면?",
            "User-agent: OAI-SearchBot",
            "OAI-AdsBot 필수 / OAI-SearchBot 권장 허용",
            "Cloudflare는 OAI-AdsBot 공식 허용이 완료",
            "최소 집행 약정",
            "400만원 / 상세 조건은 영업 담당 안내",
            "VAT 등 세부 정산 조건은 별도 안내드립니다.",
            "정책·수치가 변동될 수 있습니다.",
            "케이티나스미디어 미디어채널실 openai@nasmedia.co.kr",
        ]
        for phrase in required:
            self.assertIn(phrase, html)
        self.assertNotIn("공식 도움말 글자수 미명시", html)

    def test_checklist_tab_removed_from_top_navigation(self) -> None:
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        nav_start = html.index('<nav class="tabs"')
        nav_end = html.index("</nav>", nav_start)
        nav_html = html[nav_start:nav_end]

        self.assertNotIn("광고주 준비물", nav_html)
        self.assertIn("광고주 안내 자료", nav_html)


if __name__ == "__main__":
    unittest.main()
