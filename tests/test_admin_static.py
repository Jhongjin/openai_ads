from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADMIN_HTML = ROOT / "dev" / "admin.html"


class AdminStaticTests(unittest.TestCase):
    def test_notice_editor_and_visit_chart_present(self) -> None:
        html = ADMIN_HTML.read_text(encoding="utf-8")
        app_py = (ROOT / "app.py").read_text(encoding="utf-8")
        admin_store = (ROOT / "admin_store.py").read_text(encoding="utf-8")

        required = [
            'id="notice-editor"',
            'contenteditable="true"',
            'data-notice-command="bold"',
            'data-notice-command="insertUnorderedList"',
            'id="visit-chart"',
            "renderVisitChart",
            "body_html",
            'id="notice-status"',
            'id="notice-preview"',
            'id="notice-preview-body"',
            "renderNoticePreview",
            "안내자료 슬라이드 편집",
            'data-admin-view="guides"',
            'id="admin-view-guides"',
            "guide-editable-text",
            "admin-guide-image-file",
            "loadGuides",
            "saveGuides",
            "/api/admin/guide-slides",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

        self.assertIn('"/api/guide-slides"', app_py)
        self.assertIn('"/api/admin/guide-slides"', app_py)
        self.assertIn("DEFAULT_SLIDE_CONTENT", admin_store)
        self.assertIn("admin_slide_content", admin_store)

        self.assertNotIn('id="notice-bullets"', html)
        self.assertNotIn('id="storage-badge"', html)
        self.assertNotIn("저장소:", html)

    def test_mail_review_gate_present(self) -> None:
        html = ADMIN_HTML.read_text(encoding="utf-8")
        app_py = (ROOT / "app.py").read_text(encoding="utf-8")
        admin_store = (ROOT / "admin_store.py").read_text(encoding="utf-8")

        required_html = [
            "메일 검토함",
            "지식 반영안",
            "반영 승인",
            'id="mail-filter"',
            'id="mail-rows"',
            "mail-rag-draft",
            "loadMailReview",
            'id="mail-rows"',
            "mail-approve",
            "/api/admin/mail-review/update",
            "지식 반영안이 비어 있습니다.",
        ]
        for phrase in required_html:
            self.assertIn(phrase, html)

        self.assertIn('"/api/admin/mail-review"', app_py)
        self.assertIn('"/api/admin/mail-review/update"', app_py)
        self.assertIn('"review_list"', admin_store)
        self.assertIn('"review_update"', admin_store)

    def test_official_guide_change_log_present(self) -> None:
        html = ADMIN_HTML.read_text(encoding="utf-8")
        app_py = (ROOT / "app.py").read_text(encoding="utf-8")
        admin_store = (ROOT / "admin_store.py").read_text(encoding="utf-8")
        db_py = (ROOT / "rag_chatbot" / "db.py").read_text(encoding="utf-8")
        ingestion_py = (ROOT / "rag_chatbot" / "ingestion.py").read_text(encoding="utf-8")

        for phrase in [
            "공식 문서 변경 로그",
            'id="official-rows"',
            'id="official-refresh"',
            'id="official-start-date"',
            'id="official-end-date"',
            "loadOfficialChanges",
            "/api/admin/official-changes",
        ]:
            self.assertIn(phrase, html)

        self.assertIn('"/api/admin/official-changes"', app_py)
        self.assertIn('request.query_params.get("page")', app_py)
        self.assertIn('request.query_params.get("start_date")', app_py)
        self.assertIn('request.query_params.get("end_date")', app_py)
        self.assertIn("list_official_guide_changes", admin_store)
        self.assertIn("summarize_official_document_change", admin_store)
        self.assertIn("total_count", admin_store)
        self.assertIn("has_next", admin_store)
        self.assertIn("official_guide_changes", db_py)
        self.assertIn("fetch_official_source_snapshot", db_py)
        self.assertIn("record_official_guide_change", db_py)
        self.assertIn("summarize_official_document_change", db_py)
        self.assertIn("record_official_guide_change", ingestion_py)

    def test_ads_api_dashboard_is_admin_only_ui(self) -> None:
        html = ADMIN_HTML.read_text(encoding="utf-8")
        app_py = (ROOT / "app.py").read_text(encoding="utf-8")

        for phrase in [
            "Ads API 성과 대시보드",
            'id="performance-status"',
            'id="performance-advertiser-select"',
            'id="ads-key-rows"',
            'id="performance-campaign-rows"',
            'id="performance-detail-panel"',
            "전환수",
            "conversion_metrics_available",
            "loadPerformanceDashboard",
            "/api/admin/ads-dashboard",
            "/api/admin/ads-api-keys",
            "OPENAI_ADS_API_KEY",
        ]:
            self.assertIn(phrase, html)

        self.assertIn('"/api/admin/ads-dashboard"', app_py)
        self.assertIn('"/api/admin/ads-api-keys"', app_py)
        self.assertIn('"/api/admin/ads-api-keys/{advertiser_name}"', app_py)
        self.assertNotIn('href="/ads-api"', html)


if __name__ == "__main__":
    unittest.main()
