from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def intake_panel_html() -> str:
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    start = html.index('<section class="panel" id="intake-panel">')
    end = html.index('<section class="panel" id="slides-panel">', start)
    return html[start:end]


class IntakeFormStaticTests(unittest.TestCase):
    def test_intake_form_uses_workbook_three_level_structure(self) -> None:
        html = intake_panel_html()

        required = [
            "Ads Manager 벌크 업로드",
            "소재 접수 기본 정보",
            "campaign_name",
            "adgroup_name",
            "budget_max",
            "target_countries",
            "image_link",
            "이미지 파일 첨부",
            "소재 추가",
            "업로드용 .xlsx 생성",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

    def test_old_flat_intake_fields_are_removed(self) -> None:
        html = intake_panel_html()

        removed = [
            'name="websiteUrl"',
            'name="budgetAmount"',
            'name="campaignObjective"',
            'name="startDate"',
            'name="targetCountry"',
            "업로드 유형",
            "uploadMode",
        ]
        for phrase in removed:
            self.assertNotIn(phrase, html)

    def test_intake_form_has_campaign_color_and_collapse_controls(self) -> None:
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        panel = intake_panel_html()

        required = [
            "campaignPalette",
            "data-collapsible",
            "collapse-toggle",
            "expandIntakeAncestors",
            "--campaign-color",
            "접기",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

        self.assertIn("캠페인 추가", panel)
        self.assertIn("광고그룹 추가", panel)
        self.assertIn("소재 추가", panel)

    def test_campaign_clone_isolates_radios_before_append(self) -> None:
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function isolateCampaignRadioNames", html)

        start = html.index("function addCampaignItem()")
        end = html.index("function addAdgroupItem(", start)
        add_campaign = html[start:end]

        self.assertLess(add_campaign.index("isolateCampaignRadioNames"), add_campaign.index("campaignList.append(item)"))
        self.assertIn('campaignList.addEventListener("change", handleIntakeHierarchyInput)', html)

    def test_intake_payload_selectors_follow_collapsible_nesting(self) -> None:
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

        self.assertIn('querySelectorAll(":scope .adgroup-list > [data-adgroup-item]")', html)
        self.assertIn('querySelectorAll(":scope .ad-list > [data-ad-item]")', html)
        self.assertNotIn('querySelectorAll(":scope > .adgroup-list > [data-adgroup-item]")', html)
        self.assertNotIn('querySelectorAll(":scope > .ad-list > [data-ad-item]")', html)

    def test_intake_tab_is_temporarily_disabled(self) -> None:
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

        self.assertIn('data-tab="intake"', html)
        self.assertIn("소재 업로드 도구는 개편 중입니다.", html)
        self.assertIn('aria-disabled="true"', html)

    def test_creative_upload_draft_page_exists_off_main_tab(self) -> None:
        html = (ROOT / "templates" / "creative_upload_draft.html").read_text(encoding="utf-8")

        required = [
            "OpenAI 광고 소재 업로드 시트 생성",
            "DRAFT · 메인 탭 비활성 상태로 작업 중",
            "워크북 파일 불러오기",
            "Ads Manager 업로드용 XLSX 다운로드",
            "/intake/workbook",
            "/intake/inspect-workbook",
            "populateFromWorkbook",
            "collapse-toggle",
            "campaign-body",
            "adgroup-body",
            "ad-body",
            "expandInvalidAncestors",
            "clearCollapsedState",
            "담당자명",
            "담당자 이메일",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

        removed = [
            "/intake/upload-image",
            "이미지 파일 첨부",
            "ad-image-file",
            "image-upload-status",
            "이미지 처리 방식",
            "OpenAI 직접 업로드",
            "크리테오 경유",
            "케이티나스미디어 담당자",
            "업로드 유형",
            "uploadMode",
        ]
        for phrase in removed:
            self.assertNotIn(phrase, html)

    def test_creative_upload_draft_reviews_before_sheet_submit(self) -> None:
        html = (ROOT / "templates" / "creative_upload_draft.html").read_text(encoding="utf-8")

        required = [
            "제출 전 확인",
            "확인 후 제출",
            "pendingSubmissionPayload",
            "openReviewModal(payload())",
            "submitReviewedPayload",
            "구글 시트에 기록하고 담당자 알림 메일을 발송하고 있습니다.",
            "openai@nasmedia.co.kr 알림 발송",
            "메일 발송 확인 필요",
            "body.mail_sent === false",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

        submit_start = html.index("async function submitSheet")
        submit_end = html.index("async function inspectWorkbook", submit_start)
        submit_block = html[submit_start:submit_end]
        self.assertNotIn('fetch("/intake"', submit_block)

    def test_creative_upload_draft_has_structure_overview(self) -> None:
        html = (ROOT / "templates" / "creative_upload_draft.html").read_text(encoding="utf-8")

        required = [
            'id="structure-overview"',
            "function updateStructureOverview",
            "structure-chip",
            "data-jump-campaign",
            "광고그룹 ${adgroupCount}개",
            "소재 ${adCount}개",
        ]
        for phrase in required:
            self.assertIn(phrase, html)


if __name__ == "__main__":
    unittest.main()
