from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminStaticTests(unittest.TestCase):
    def test_notice_editor_and_visit_chart_present(self) -> None:
        html = (ROOT / "templates" / "admin.html").read_text(encoding="utf-8")

        required = [
            'id="notice-editor"',
            'contenteditable="true"',
            'data-command="bold"',
            'data-command="insertUnorderedList"',
            'id="visit-chart"',
            "renderVisitChart",
            "body_html",
            'id="notice-updated"',
        ]
        for phrase in required:
            self.assertIn(phrase, html)

        self.assertNotIn('id="notice-bullets"', html)


if __name__ == "__main__":
    unittest.main()
