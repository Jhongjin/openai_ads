from __future__ import annotations

import unittest

import httpx

from checker import NormalizedUrl, check_url, evaluate_robots_txt, normalize_url


def normalized(url: str) -> NormalizedUrl:
    parsed = normalize_url(url)
    return parsed


class CheckerDecisionTests(unittest.TestCase):
    def test_oai_group_root_disallow_blocks(self) -> None:
        result = evaluate_robots_txt(
            normalized("https://example.com/landing"),
            "User-agent: OAI-AdsBot\nDisallow: /\n",
        )
        self.assertEqual(result.verdict, "block")
        self.assertTrue(any(detail.label == "OAI-AdsBot" and detail.status == "block" for detail in result.bot_details))

    def test_star_group_root_disallow_blocks(self) -> None:
        result = evaluate_robots_txt(
            normalized("https://example.com/landing"),
            "User-agent: *\nDisallow: /\n",
        )
        self.assertEqual(result.verdict, "block")

    def test_empty_disallow_allows(self) -> None:
        result = evaluate_robots_txt(
            normalized("https://example.com/landing"),
            "User-agent: *\nDisallow:\n",
        )
        self.assertEqual(result.verdict, "allow")

    def test_landing_path_disallow_warns(self) -> None:
        result = evaluate_robots_txt(
            normalized("https://example.com/itg/ln/page"),
            "User-agent: *\nAllow: /\nDisallow: /itg/ln/\n",
        )
        self.assertEqual(result.verdict, "warn")
        self.assertIn("차단 목록", result.reason)
        self.assertTrue(any("/itg/ln/" in detail.detail for detail in result.bot_details))
        self.assertTrue(any(detail.summary == "광고 랜딩 경로 접근 불가" for detail in result.bot_details))

    def test_wildcard_landing_path_disallow_warns(self) -> None:
        result = evaluate_robots_txt(
            normalized("https://example.com/itg/ln/page"),
            "User-agent: *\nAllow: /\nDisallow: /*/ln/*\n",
        )
        self.assertEqual(result.verdict, "warn")

    def test_specific_bots_only_warns(self) -> None:
        result = evaluate_robots_txt(
            normalized("https://example.com/landing"),
            "User-agent: Googlebot\nAllow: /\n",
        )
        self.assertEqual(result.verdict, "warn")
        self.assertTrue(all(detail.status == "warn" for detail in result.bot_details))
        self.assertTrue(all("명시 허용" in detail.detail for detail in result.bot_details))

    def test_invalid_url_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_url("bad url")


class CheckerFirewallHintTests(unittest.IsolatedAsyncioTestCase):
    async def test_cloudflare_header_adds_hint_without_blocking(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"server": "cloudflare", "cf-ray": "abc123-ICN"},
                text="User-agent: *\nAllow: /\n",
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await check_url("https://kr.jellycat.com/", client)

        self.assertEqual(result.verdict, "allow")
        self.assertTrue(result.firewall_hint)
        self.assertEqual(result.firewall_badge, "방화벽 뒤 — 추가 확인 권장")
        self.assertIn("실제 광고 로봇이 막힐 수 있음", result.reason)

    async def test_access_denied_robots_explains_each_oai_bot_is_unknown(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403,
                text=(
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    "<Error><Code>AccessDenied</Code><Message>Access Denied</Message></Error>"
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await check_url("https://s.wink.co.kr/marketing/page.html", client)

        self.assertEqual(result.verdict, "warn")
        self.assertIn("HTTP 403", result.reason)
        self.assertTrue(any(detail.label == "robots.txt 접근" for detail in result.bot_details))
        self.assertTrue(
            all(
                detail.status == "warn"
                for detail in result.bot_details
                if detail.label in {"OAI-AdsBot", "OAI-SearchBot"}
            )
        )
        self.assertTrue(any("허용 여부를 아직 판정할 수 없습니다" in detail.detail for detail in result.bot_details))


if __name__ == "__main__":
    unittest.main()
