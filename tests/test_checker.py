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


if __name__ == "__main__":
    unittest.main()
