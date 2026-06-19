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
            'id="notice-preview"',
            'id="notice-preview-body"',
            "renderNoticePreview",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

        self.assertNotIn('id="notice-bullets"', html)
        self.assertNotIn('id="storage-badge"', html)
        self.assertNotIn("저장소:", html)

    def test_mail_review_gate_present(self) -> None:
        html = (ROOT / "templates" / "admin.html").read_text(encoding="utf-8")
        app_py = (ROOT / "app.py").read_text(encoding="utf-8")
        admin_store = (ROOT / "admin_store.py").read_text(encoding="utf-8")

        required_html = [
            "OpenAI 담당자 메일 검토함",
            "승인 요약",
            "승인하여 RAG 반영",
            'id="mail-review-filter"',
            'id="mail-review-body"',
            'id="mail-detail"',
            "loadMailReview",
            "saveMailReview",
            "/api/admin/mail-review/update",
            "RAG 반영 승인에는 승인 요약이 필요합니다.",
        ]
        for phrase in required_html:
            self.assertIn(phrase, html)

        self.assertIn('"/api/admin/mail-review"', app_py)
        self.assertIn('"/api/admin/mail-review/update"', app_py)
        self.assertIn('"review_list"', admin_store)
        self.assertIn('"review_update"', admin_store)

    def test_official_guide_change_log_present(self) -> None:
        html = (ROOT / "templates" / "admin.html").read_text(encoding="utf-8")
        app_py = (ROOT / "app.py").read_text(encoding="utf-8")
        admin_store = (ROOT / "admin_store.py").read_text(encoding="utf-8")
        db_py = (ROOT / "rag_chatbot" / "db.py").read_text(encoding="utf-8")
        ingestion_py = (ROOT / "rag_chatbot" / "ingestion.py").read_text(encoding="utf-8")

        for phrase in [
            "OpenAI 공식 가이드 변경 로그",
            'id="official-change-body"',
            'id="refresh-official-changes"',
            "loadOfficialChanges",
            "/api/admin/official-changes",
        ]:
            self.assertIn(phrase, html)

        self.assertIn('"/api/admin/official-changes"', app_py)
        self.assertIn("list_official_guide_changes", admin_store)
        self.assertIn("official_guide_changes", db_py)
        self.assertIn("fetch_official_source_snapshot", db_py)
        self.assertIn("record_official_guide_change", db_py)
        self.assertIn("record_official_guide_change", ingestion_py)

    def test_ads_api_dashboard_is_admin_only_ui(self) -> None:
        html = (ROOT / "templates" / "admin.html").read_text(encoding="utf-8")
        app_py = (ROOT / "app.py").read_text(encoding="utf-8")

        for phrase in [
            "Ads API 성과 대시보드",
            'id="ads-dashboard-status"',
            'id="ads-campaign-body"',
            'id="ads-detail-card"',
            "loadAdsDashboard",
            "/api/admin/ads-dashboard",
            "OPENAI_ADS_API_KEY",
        ]:
            self.assertIn(phrase, html)

        self.assertIn('"/api/admin/ads-dashboard"', app_py)
        self.assertNotIn('href="/ads-api"', html)


if __name__ == "__main__":
    unittest.main()
