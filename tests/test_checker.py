from __future__ import annotations

import unittest

from checker import NormalizedUrl, evaluate_robots_txt, normalize_url


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
        self.assertIn("/itg/ln/page", result.reason)

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


if __name__ == "__main__":
    unittest.main()
