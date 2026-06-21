from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def intake_html() -> str:
    return (ROOT / "templates" / "creative_upload_draft.html").read_text(encoding="utf-8")


class IntakeFormStaticTests(unittest.TestCase):
    def test_creative_upload_page_uses_workbook_three_level_structure(self) -> None:
        html = intake_html()

        required = [
            "소재 접수 및 업로드 파일 생성",
            "기존 업로드 파일 불러오기",
            "캠페인 / 광고그룹 / 소재",
            "campaign_name 자동 참조",
            "adgroup_name 자동 참조",
            "Ads Manager용 .xlsx 다운로드",
            "내부 시트 저장 및 알림 발송",
            "담당자 이메일",
            "본부",
            "실",
            "팀",
            'id="workbook-file"',
            'id="workbook-file-name"',
            "file-upload-card",
            "/intake/inspect-workbook",
            "populateFromWorkbook",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

        removed = [
            "이미지 파일 첨부",
            "업로드 유형",
            "OpenAI 직접 업로드",
            "크리테오 경유",
            "케이티나스미디어 담당자",
        ]
        for phrase in removed:
            self.assertNotIn(phrase, html)

    def test_creative_upload_has_campaign_color_collapse_and_reference_controls(self) -> None:
        html = intake_html()

        required = [
            "campaignThemes",
            "applyCampaignTheme",
            "collapse-toggle",
            "expandInvalidAncestors",
            "--block-accent",
            "접기",
            "캠페인 추가",
            "광고그룹 추가",
            "소재그룹 추가",
            "Ads Manager Reference",
            "표준 캠페인",
            "제품피드 캠페인",
            "아직 비활성",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

    def test_creative_upload_validates_names_and_derived_references(self) -> None:
        html = intake_html()

        required = [
            "validateNameFields",
            "validateDerivedFields",
            "캠페인명은 최소 3자 이상 입력해 주세요.",
            "광고그룹명은 최소 3자 이상 입력해 주세요.",
            "소재명은 최소 3자 이상 입력해 주세요.",
            "isSafeWorkbookName",
            "campaignBlocks().map(readCampaign)",
            ".adgroup-block",
            ".ad-block",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

    def test_creative_upload_reviews_before_sheet_submit(self) -> None:
        html = intake_html()

        required = [
            "제출 전 확인",
            "저장하고 알림 보내기",
            "pendingSubmissionPayload",
            "openReviewModal(payload())",
            "submitReviewedPayload",
            "내부 시트에 저장하고 알림을 요청하는 중입니다.",
            "메일 발송 요청 완료",
            "body.mail_sent",
            "body.mail_error",
            "메일 발송 실패",
            "body.mail_sent === false",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

        submit_start = html.index('$("#intake-form").addEventListener("submit"')
        submit_end = html.index("reviewCancel.addEventListener", submit_start)
        submit_block = html[submit_start:submit_end]
        self.assertNotIn('fetch("/intake"', submit_block)

    def test_creative_upload_has_manual_vs_bulk_output_fields(self) -> None:
        html = intake_html()

        required = [
            "manual_target_country",
            "manual_target_country_label",
            "manual_max_bid",
            "수동 국가",
            "수동 입찰가(KRW)",
            '<option value="ALL">전체</option>',
            '<option value="US">미국</option>',
            '<option value="AU">오스트레일리아</option>',
            '<option value="CA">캐나다</option>',
            '<option value="JP">일본</option>',
            '<option value="NZ">뉴질랜드</option>',
            '<option value="KR">대한민국</option>',
            '<option value="GB">영국</option>',
            "target_countries",
            "max_bid",
        ]
        for phrase in required:
            self.assertIn(phrase, html)

        self.assertNotIn("대한민국은 수동 세팅에서는 선택하고", html)
        self.assertNotIn("xlsx target_countries", html)
        self.assertNotIn("xlsx max_bid", html)

    def test_creative_upload_has_structure_overview_and_summary(self) -> None:
        html = intake_html()

        required = [
            "캠페인 입력 요약",
            "광고그룹 입력 요약",
            "소재 입력 요약",
            "summary-ad-name",
            "summary-ad-link",
            "summary-campaign-name",
            "summary-adgroup-name",
            "summary-ad-title",
            "scheduleSummary",
        ]
        for phrase in required:
            self.assertIn(phrase, html)


if __name__ == "__main__":
    unittest.main()
