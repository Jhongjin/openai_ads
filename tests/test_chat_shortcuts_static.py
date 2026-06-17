from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ChatShortcutStaticTests(unittest.TestCase):
    def test_enter_submits_and_ctrl_enter_keeps_newline(self) -> None:
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

        snippet = """chatInput.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        if (event.ctrlKey || event.metaKey) return;
        event.preventDefault();
        runChat();
      });"""

        self.assertIn(snippet, html)


if __name__ == "__main__":
    unittest.main()
