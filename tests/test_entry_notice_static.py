from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EntryNoticeStaticTests(unittest.TestCase):
    def test_entry_notice_modal_contains_required_guidance(self) -> None:
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

        required = [
            "OpenAI 광고 집행 의뢰 안내",
            "최종 업데이트:",
            "notice-update-date",
            "https://help.openai.com/en/collections/20001223-chatgpt-ads",
            "OpenAI Ads Guide",
            "하루 2회 최신 정보를 자동 확인·업데이트합니다.",
            "제목 24자 / 설명 48자 최대",
            "권장 제목 16~18자 / 설명 32~36자",
            "크리테오 경유 제목 30자 / 설명 60자",
            "640×640~1200×1200",
            "OAI-AdsBot",
            "청구 통화 KRW 고정 / 시간대 Asia/Seoul",
            "openai@nasmedia.co.kr",
            "오늘 더 이상 보지 않기",
            "확인하고 시작하기",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

    def test_entry_notice_has_daily_localstorage_and_focus_trap(self) -> None:
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

        required = [
            "openaiAdsEntryNoticeDismissedDate",
            'timeZone: "Asia/Seoul"',
            "localStorage.setItem",
            "localStorage.getItem",
            "window.location.pathname === \"/\"",
            "trapEntryNoticeFocus",
            "pageMain.inert = true",
            "body.modal-open",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

    def test_email_domain_is_not_truncated(self) -> None:
        files = [
            ROOT / "templates" / "index.html",
            ROOT / "public" / "index.html",
            ROOT / "README.md",
            ROOT / "tests" / "test_slides_static.py",
        ]
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("openai@nasmedia.co.k ", text)
            self.assertNotIn("openai@nasmedia.co.k<", text)
            self.assertNotIn("openai@nasmedia.co.k\n", text)


if __name__ == "__main__":
    unittest.main()
