from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def index_html() -> str:
    return (ROOT / "templates" / "index.html").read_text(encoding="utf-8")


def intake_panel_html() -> str:
    html = index_html()
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
            "소재 추가",
            "Ads Manager용 .xlsx 다운로드",
            "구글 시트 저장 후 알림 보내기",
            "담당자 이메일",
            "본부",
            "실",
            "팀",
            "기존 워크북 파일 불러오기",
            'id="intake-workbook-file"',
        ]
        for phrase in required:
            self.assertIn(phrase, html)

        full_html = index_html()
        self.assertIn("/intake/inspect-workbook", full_html)
        self.assertIn("populateIntakeFromWorkbook", full_html)

        removed = [
            "이미지 파일 첨부",
            "업로드용 .xlsx 생성",
            "이미지 처리 방식",
        ]
        for phrase in removed:
            self.assertNotIn(phrase, html)

    def test_old_flat_and_onboarding_fields_are_removed(self) -> None:
        html = intake_panel_html()

        removed = [
            'name="websiteUrl"',
            'name="budgetAmount"',
            'name="campaignObjective"',
            'name="startDate"',
            'name="targetCountry"',
            'name="executionRoute"',
            'name="legalName"',
            'name="brn"',
            'name="advertiserHomepageUrl"',
            'name="invoiceEmail"',
            'name="contactName"',
            'name="contactPhone"',
            'name="contactEmail"',
            'name="submitterName"',
            'name="submitterEmail"',
            "업로드 유형",
            "uploadMode",
            "OpenAI 직접 업로드",
            "크리테오 경유",
            "케이티나스미디어 담당자",
        ]
        for phrase in removed:
            self.assertNotIn(phrase, html)

    def test_intake_form_has_campaign_color_and_collapse_controls(self) -> None:
        html = index_html()
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

    def test_campaign_clone_isolates_radios_without_resetting_existing_items(self) -> None:
        html = index_html()
        self.assertIn("let campaignInstanceId", html)
        self.assertIn("function isolateCampaignRadioNames", html)

        add_start = html.index("function addCampaignItem()")
        add_end = html.index("function addAdgroupItem(", add_start)
        add_campaign = html[add_start:add_end]
        self.assertIn("captureCampaignSelections", add_campaign)
        self.assertIn("restoreCampaignSelections", add_campaign)
        self.assertIn("isolateCampaignRadioNames(item, campaignInstanceId)", add_campaign)
        self.assertLess(add_campaign.index("isolateCampaignRadioNames"), add_campaign.index("campaignList.append(item)"))

        update_start = html.index("function updateIntakeStructureState()")
        update_end = html.index("function addCampaignItem()", update_start)
        update_block = html[update_start:update_end]
        self.assertNotIn("isolateCampaignRadioNames", update_block)

    def test_intake_payload_selectors_follow_collapsible_nesting(self) -> None:
        html = index_html()

        self.assertIn('querySelectorAll(":scope .adgroup-list > [data-adgroup-item]")', html)
        self.assertIn('querySelectorAll(":scope .ad-list > [data-ad-item]")', html)
        self.assertNotIn('querySelectorAll(":scope > .adgroup-list > [data-adgroup-item]")', html)
        self.assertNotIn('querySelectorAll(":scope > .ad-list > [data-ad-item]")', html)

    def test_intake_tab_is_active(self) -> None:
        html = index_html()

        self.assertIn('data-tab="intake"', html)
        self.assertIn("소재 업로드", html)
        self.assertNotIn("소재 업로드 도구는 개편 중입니다.", html)
        self.assertNotIn('aria-disabled="true"', html)

    def test_intake_reviews_before_sheet_submit(self) -> None:
        html = index_html()

        required = [
            "intake-review-modal",
            "pendingIntakePayload",
            "openIntakeReviewModal(intakePayload())",
            "submitReviewedIntake",
            "저장하고 알림 보내기",
            "구글 시트에 저장할 내용을 확인해 주세요",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

        submit_start = html.index("async function submitIntake")
        submit_end = html.index("async function downloadIntakeWorkbook", submit_start)
        submit_block = html[submit_start:submit_end]
        self.assertNotIn('fetch("/intake"', submit_block)

    def test_creative_upload_draft_page_exists_off_main_tab(self) -> None:
        html = (ROOT / "templates" / "creative_upload_draft.html").read_text(encoding="utf-8")

        required = [
            "OpenAI Ads Manager 업로드 워크북 작성",
            "내부 운영용 · 벌크 업로드 준비",
            "워크북 파일 불러오기",
            "Ads Manager용 .xlsx 다운로드",
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
            "DRAFT · 메인 탭 비활성 상태로 작업 중",
        ]
        for phrase in removed:
            self.assertNotIn(phrase, html)

    def test_creative_upload_draft_reviews_before_sheet_submit(self) -> None:
        html = (ROOT / "templates" / "creative_upload_draft.html").read_text(encoding="utf-8")

        required = [
            "제출 전 확인",
            "저장하고 알림 보내기",
            "pendingSubmissionPayload",
            "openReviewModal(payload())",
            "submitReviewedPayload",
            "구글 시트에 저장하고 담당자 알림 메일을 발송하고 있습니다.",
            "메일 발송 요청 완료",
            "body.mail_sender",
            "body.mail_recipient",
            "body.mail_cc",
            "메일 발송 실패",
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
