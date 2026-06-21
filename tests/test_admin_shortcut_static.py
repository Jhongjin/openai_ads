from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminShortcutStaticTests(unittest.TestCase):
    def test_main_header_links_to_admin_page(self) -> None:
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

        required = [
            'href="/admin"',
            "btn-command",
            "ti-lock-cog",
            "관리자",
        ]
        for phrase in required:
            self.assertIn(phrase, html)


if __name__ == "__main__":
    unittest.main()
