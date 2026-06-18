from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def pixel_guide_html() -> str:
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    start = html.index('<section class="panel" id="pixel-guide-panel">')
    end = html.index("    </main>", start)
    return html[start:end]


class PixelGuideStaticTests(unittest.TestCase):
    def test_pixel_guide_tab_and_pdf_filename_exist(self) -> None:
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

        required = [
            'data-tab="pixelGuide"',
            "픽셀 설치 가이드",
            "pixel-guide-print",
            "print-pixel-guide",
            "PIXEL_GUIDE_PDF_FILENAME",
            "ChatGPT광고_픽셀설치가이드_케이티나스미디어_",
            "pixelGuide: document.querySelector",
            "pixel-guide-notice",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

    def test_pixel_guide_has_pages_and_platform_steps(self) -> None:
        html = pixel_guide_html()

        self.assertEqual(html.count('class="slide-card'), 7)
        required = [
            "OpenAI Ads Measurement Pixel",
            "웹 페이지뷰·전환·이벤트 측정 설정",
            "광고 관리자 → 도구 → 전환 → 데이터 소스 탭",
            "데이터 소스 만들기 → 이름 입력 → 유형은 웹 선택",
            "설정 코드와 Pixel ID",
            "전환 이벤트 탭",
            "캠페인에 연결",
            "https://developers.openai.com/ads/measurement-pixel",
            "https://developers.openai.com/ads/supported-events",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

    def test_pixel_guide_contains_required_install_and_event_code(self) -> None:
        html = pixel_guide_html()

        required = [
            "https://bzrcdn.openai.com/sdk/oaiq.min.js",
            'pixelId: "PIXEL_ID"',
            "debug: true",
            'oaiq("measure", "page_viewed"',
            'oaiq("measure", "contents_viewed"',
            'oaiq("measure", "lead_created"',
            'oaiq("measure", "registration_completed"',
            'oaiq("measure", "order_created"',
            'currency: "KRW"',
            'custom_event_name: "quote_requested"',
            'event_id: "order_12345"',
        ]
        for phrase in required:
            self.assertIn(phrase, html)

    def test_pixel_guide_has_advertiser_safe_guardrails(self) -> None:
        html = pixel_guide_html()

        required = [
            "웹 JavaScript Pixel 기준",
            "HTML &lt;head&gt; 안",
            "페이지당 공통 설치 스크립트는 1회만 추가",
            "원문 이메일·전화번호를 보내지 말고",
            "서버 Conversions API를 직접 호출하지 말고",
            "브라우저 콘솔 debug 로그",
            "이벤트 스트림에서 수신 여부 확인",
        ]
        for phrase in required:
            self.assertIn(phrase, html)


if __name__ == "__main__":
    unittest.main()
