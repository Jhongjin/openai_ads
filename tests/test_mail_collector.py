from __future__ import annotations

from email.message import EmailMessage
import unittest

from rag_chatbot.mail_collector import (
    DEFAULT_TARGET_RECIPIENTS,
    DEFAULT_TARGET_SENDERS,
    MailCollectorSettings,
    _imap_utf7_encode,
    parse_message,
    render_mail_markdown,
)


def settings() -> MailCollectorSettings:
    return MailCollectorSettings(
        host="imap.daum.net",
        port=993,
        secure=True,
        user="user",
        password="password",
        folder="RAG_수집함",
        top=50,
        target_senders=DEFAULT_TARGET_SENDERS,
        target_recipients=DEFAULT_TARGET_RECIPIENTS,
        webhook_url="",
        webhook_secret="",
    )


def message(
    *,
    sender: str,
    to: str = "someone@nasmedia.co.kr",
    cc: str = "",
    subject: str = "RE: [Nasmedia] ChatGPT ads CBT 참여 신청",
    body: str = "최소 집행금액은 OpenAI 직접 400만원으로 확정입니다.",
) -> EmailMessage:
    item = EmailMessage()
    item["From"] = sender
    item["To"] = to
    if cc:
        item["Cc"] = cc
    item["Subject"] = subject
    item["Message-ID"] = "<mail-1@example.com>"
    item["Date"] = "Wed, 17 Jun 2026 09:30:00 +0900"
    item.set_content(body)
    return item


class MailCollectorTests(unittest.TestCase):
    def test_matches_openai_sender(self) -> None:
        item = parse_message("101", message(sender="Michael Cho <michaelcho@openai.com>"), settings())

        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.from_email, "michaelcho@openai.com")
        self.assertIn("official_sender", item.tags)
        self.assertIn("confirmation_candidate", item.tags)

    def test_matches_openai_recipient_or_cc(self) -> None:
        item = parse_message(
            "102",
            message(
                sender="윤승환 <ysh0227@nasmedia.co.kr>",
                cc="openai@nasmedia.co.kr, harrisonk@openai.com",
            ),
            settings(),
        )

        self.assertIsNotNone(item)
        assert item is not None
        self.assertIn("openai_nasmedia_thread", item.tags)
        self.assertEqual(item.uid, "102")

    def test_rejects_unrelated_mail(self) -> None:
        item = parse_message(
            "103",
            message(sender="other@example.com", to="client@example.com", cc=""),
            settings(),
        )

        self.assertIsNone(item)

    def test_render_markdown_contains_traceable_metadata(self) -> None:
        item = parse_message("104", message(sender="ads-korea@openai.com"), settings())
        assert item is not None

        markdown = render_mail_markdown([item])

        self.assertIn("OpenAI 담당자 이메일 회신 수집 문서", markdown)
        self.assertIn("나스미디어 내부 자료", markdown)
        self.assertIn("Message-ID", markdown)
        self.assertIn(item.duplicate_hash, markdown)

    def test_imap_utf7_encodes_korean_folder_names(self) -> None:
        encoded = _imap_utf7_encode("RAG_수집함")

        self.assertTrue(encoded.startswith("RAG_&"))
        self.assertTrue(encoded.endswith("-"))


if __name__ == "__main__":
    unittest.main()
