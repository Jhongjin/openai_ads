from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ChatShortcutStaticTests(unittest.TestCase):
    def test_question_box_uses_button_submit_and_enter_newline(self) -> None:
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

        self.assertIn("Enter는 줄바꿈입니다. 버튼을 눌러 답변을 생성합니다.", html)
        self.assertIn('$("#qa-run").addEventListener("click", runQa);', html)
        self.assertNotIn("event.preventDefault();\n        runChat();", html)


if __name__ == "__main__":
    unittest.main()
