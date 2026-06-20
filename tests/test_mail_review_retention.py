from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from admin_store import KST, _mail_row_recent, _parse_mail_datetime


class MailReviewRetentionTests(unittest.TestCase):
    def test_parse_mail_datetime_handles_iso_and_kst_text(self) -> None:
        iso_value = _parse_mail_datetime("2026-06-20T16:44:03+09:00")
        kst_value = _parse_mail_datetime("2026-06-20 16:44:03 KST")

        self.assertIsNotNone(iso_value)
        self.assertIsNotNone(kst_value)
        self.assertEqual(iso_value.astimezone(KST).date().isoformat(), "2026-06-20")
        self.assertEqual(kst_value.astimezone(KST).date().isoformat(), "2026-06-20")

    def test_mail_row_recent_filters_older_than_cutoff(self) -> None:
        now = datetime(2026, 6, 21, 12, 0, 0, tzinfo=KST)
        cutoff = now - timedelta(days=14)

        self.assertTrue(_mail_row_recent({"received_at": "2026-06-20 10:00:00 KST"}, cutoff=cutoff))
        self.assertFalse(_mail_row_recent({"received_at": "2026-06-01 10:00:00 KST"}, cutoff=cutoff))
        self.assertTrue(_mail_row_recent({"received_at": ""}, cutoff=cutoff))


if __name__ == "__main__":
    unittest.main()
