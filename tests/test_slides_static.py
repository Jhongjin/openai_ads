from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def slides_panel_html() -> str:
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    start = html.index('<section class="panel" id="slides-panel">')
    end = html.index("    </main>", start)
    return html[start:end]


class AdvertiserSlidesStaticTests(unittest.TestCase):
    def test_slides_have_five_pages_and_print_action(self) -> None:
        html = slides_panel_html()

        self.assertEqual(html.count('class="slide-card"'), 5)
        self.assertIn("PDF로 저장", html)
        self.assertIn("window.print()", (ROOT / "templates" / "index.html").read_text(encoding="utf-8"))

    def test_advertiser_slides_hide_internal_terms(self) -> None:
        html = slides_panel_html()

        forbidden = [
            "나스미디어 내부 자료",
            "OpenAI 공식 문서",
            "확인 대기",
            "미확정",
            "1,000만원",
            "마크업",
            "호스팅 fee",
        ]
        for word in forbidden:
            self.assertNotIn(word, html)

    def test_advertiser_slides_keep_required_public_claims(self) -> None:
        html = slides_panel_html()

        required = [
            "최대 50자(권장 16~24자)",
            "최대 100자(권장 32~48자)",
            "최소 집행 약정",
            "400만원 / 상세 조건은 영업 담당 안내",
            "VAT 등 세부 정산 조건은 별도 안내드립니다.",
            "정책·수치가 변동될 수 있습니다.",
        ]
        for phrase in required:
            self.assertIn(phrase, html)


if __name__ == "__main__":
    unittest.main()
