from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def index_html() -> str:
    return (ROOT / "templates" / "index.html").read_text(encoding="utf-8")


class AdvertiserSlidesStaticTests(unittest.TestCase):
    def test_guides_workspace_has_three_decks_and_pdf_action(self) -> None:
        html = index_html()

        required = [
            'id="guide-tabs"',
            'data-guide-deck="advertiser"',
            'data-guide-deck="setup"',
            'data-guide-deck="pixel"',
            'id="guide-deck"',
            'id="guide-pdf"',
            "PDF로 저장",
            "ChatGPT광고_집행준비안내_케이티나스미디어",
            "window.print()",
            "loadGuides",
            "/api/guide-slides",
            "/api/guide-deck-html",
            "GUIDE_LAYOUT_VERSION = 5",
            "GUIDE_LAYOUT_FINGERPRINT",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

    def test_advertiser_slides_hide_internal_terms(self) -> None:
        html = index_html()

        forbidden = [
            "나스미디어 내부 자료",
            "미확정",
            "1,000만원",
            "마크업",
            "호스팅 fee",
        ]
        for word in forbidden:
            self.assertNotIn(word, html)

    def test_advertiser_slides_keep_required_public_claims(self) -> None:
        html = index_html()

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

    def test_old_checklist_tab_is_not_in_new_rail_navigation(self) -> None:
        html = index_html()
        rail_start = html.index('<aside class="rail"')
        rail_end = html.index("</aside>", rail_start)
        rail_html = html[rail_start:rail_end]

        self.assertNotIn("광고주 준비물", rail_html)
        self.assertIn("광고주 안내자료", rail_html)


if __name__ == "__main__":
    unittest.main()
