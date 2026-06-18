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
            "campaigns / adgroups / ads / ops_meta",
            "① 캠페인 정보",
            "② 광고그룹 정보",
            "③ 소재 정보",
            "campaign_name",
            "adgroup_name",
            "budget_max",
            "target_countries",
            "image_link",
            "소재 추가",
            "BRN / 사업자등록번호",
            "KRW 고정",
            "Asia/Seoul 고정",
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


if __name__ == "__main__":
    unittest.main()
