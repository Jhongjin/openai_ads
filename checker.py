from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, replace
from typing import Literal
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx


TARGET_BOTS = ("OAI-AdsBot", "OAI-SearchBot")
TARGET_BOTS_LOWER = tuple(bot.lower() for bot in TARGET_BOTS)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
ROBOTS_TIMEOUT_SECONDS = 10
MAX_ROBOTS_TEXT_CHARS = 50000
FIREWALL_HINT_BADGE = "방화벽 뒤 — 추가 확인 권장"
FIREWALL_HINT_REASON = (
    "CDN/방화벽(Cloudflare 등) 뒤에 있어, 사이트의 크롤러 허용 설정(robots.txt)은 "
    "통과해도 실제 광고 로봇이 막힐 수 있음"
)


Verdict = Literal["allow", "warn", "block"]


@dataclass(frozen=True)
class RobotsRule:
    directive: Literal["allow", "disallow"]
    value: str


@dataclass(frozen=True)
class RobotsGroup:
    agents: tuple[str, ...]
    rules: tuple[RobotsRule, ...]


@dataclass(frozen=True)
class CheckResult:
    input_url: str
    normalized_url: str
    origin: str
    path: str
    robots_url: str
    verdict: Verdict
    badge: str
    reason: str
    action: str
    http_status: int | None
    robots_txt: str
    firewall_hint: bool = False
    firewall_badge: str | None = None

    def to_dict(self) -> dict:
        return {
            "input_url": self.input_url,
            "normalized_url": self.normalized_url,
            "origin": self.origin,
            "path": self.path,
            "robots_url": self.robots_url,
            "verdict": self.verdict,
            "badge": self.badge,
            "reason": self.reason,
            "action": self.action,
            "http_status": self.http_status,
            "robots_txt": self.robots_txt,
            "firewall_hint": self.firewall_hint,
            "firewall_badge": self.firewall_badge,
        }


@dataclass(frozen=True)
class NormalizedUrl:
    input_url: str
    normalized_url: str
    origin: str
    path: str
    robots_url: str


def normalize_url(raw_url: str) -> NormalizedUrl:
    value = raw_url.strip()
    if not value:
        raise ValueError("빈 URL")
    if re.search(r"\s", value):
        raise ValueError("URL 형식 오류")
    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL 형식 오류")

    path = parsed.path or "/"
    normalized = urlunparse(
        (parsed.scheme, parsed.netloc, path, "", parsed.query, "")
    )
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return NormalizedUrl(
        input_url=raw_url,
        normalized_url=normalized,
        origin=origin,
        path=path,
        robots_url=f"{origin}/robots.txt",
    )


def parse_robots_txt(text: str) -> list[RobotsGroup]:
    groups: list[RobotsGroup] = []
    agents: list[str] = []
    rules: list[RobotsRule] = []
    saw_rule = False

    def flush() -> None:
        nonlocal agents, rules, saw_rule
        if agents or rules:
            groups.append(
                RobotsGroup(
                    agents=tuple(agent.lower() for agent in agents),
                    rules=tuple(rules),
                )
            )
        agents = []
        rules = []
        saw_rule = False

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            flush()
            continue
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()

        if key == "user-agent":
            if agents and saw_rule:
                flush()
            agents.append(value)
        elif key in {"allow", "disallow"} and agents:
            rules.append(RobotsRule(key, value))  # type: ignore[arg-type]
            saw_rule = True

    flush()
    return groups


def _oai_groups(groups: list[RobotsGroup]) -> list[RobotsGroup]:
    return [
        group
        for group in groups
        if any(agent in TARGET_BOTS_LOWER for agent in group.agents)
    ]


def _star_groups(groups: list[RobotsGroup]) -> list[RobotsGroup]:
    return [group for group in groups if "*" in group.agents]


def _rules(groups: list[RobotsGroup]) -> list[RobotsRule]:
    return [rule for group in groups for rule in group.rules]


def _has_root_disallow(groups: list[RobotsGroup]) -> bool:
    return any(
        rule.directive == "disallow" and rule.value.strip() in {"/", "/*"}
        for rule in _rules(groups)
    )


def _has_explicit_allow(groups: list[RobotsGroup]) -> bool:
    return any(
        rule.directive == "allow" or (rule.directive == "disallow" and rule.value == "")
        for rule in _rules(groups)
    )


def _has_star_allow(groups: list[RobotsGroup]) -> bool:
    return any(
        (rule.directive == "allow" and rule.value.strip() == "/")
        or (rule.directive == "disallow" and rule.value == "")
        for rule in _rules(groups)
    )


def _rule_matches_path(pattern: str, path: str) -> bool:
    if not pattern:
        return False
    if not path.startswith("/"):
        path = f"/{path}"

    if "*" not in pattern and "$" not in pattern:
        return path.startswith(pattern)

    anchored_end = pattern.endswith("$")
    raw_pattern = pattern[:-1] if anchored_end else pattern
    regex = "^" + re.escape(raw_pattern).replace(r"\*", ".*")
    if anchored_end:
        regex += "$"
    return re.match(regex, path) is not None


def _matching_disallow(groups: list[RobotsGroup], path: str) -> str | None:
    for rule in _rules(groups):
        if rule.directive == "disallow" and _rule_matches_path(rule.value, path):
            return rule.value
    return None


def _standard_robotparser_allows(text: str, url: str) -> bool:
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    return all(parser.can_fetch(bot, url) for bot in TARGET_BOTS)


def _badge(verdict: Verdict) -> str:
    return {"allow": "✅", "warn": "⚠️", "block": "🚫"}[verdict]


def _detect_firewall_hint(headers: httpx.Headers, body: str) -> bool:
    body_lower = body[:10000].lower()
    if any(
        token in body_lower
        for token in (
            "cloudflare",
            "challenge",
            "just a moment",
            "cf-browser-verification",
        )
    ):
        return True

    for key, value in headers.items():
        key_lower = key.lower()
        value_lower = value.lower()
        if key_lower.startswith("cf-") or key_lower.startswith("x-akamai-"):
            return True
        if "cloudflare" in key_lower or "akamai" in key_lower:
            return True
        if "cloudflare" in value_lower or "akamai" in value_lower:
            return True
    return False


def _with_firewall_hint(result: CheckResult, has_hint: bool) -> CheckResult:
    if not has_hint or result.verdict != "allow":
        return result
    reason = result.reason
    if FIREWALL_HINT_REASON not in reason:
        reason = f"{reason}; {FIREWALL_HINT_REASON}" if reason else FIREWALL_HINT_REASON
    return replace(
        result,
        reason=reason,
        firewall_hint=True,
        firewall_badge=FIREWALL_HINT_BADGE,
    )


def _result(
    normalized: NormalizedUrl,
    *,
    verdict: Verdict,
    reason: str,
    action: str,
    http_status: int | None,
    robots_txt: str,
) -> CheckResult:
    return CheckResult(
        input_url=normalized.input_url,
        normalized_url=normalized.normalized_url,
        origin=normalized.origin,
        path=normalized.path,
        robots_url=normalized.robots_url,
        verdict=verdict,
        badge=_badge(verdict),
        reason=reason,
        action=action,
        http_status=http_status,
        robots_txt=robots_txt[:MAX_ROBOTS_TEXT_CHARS],
    )


def evaluate_robots_txt(
    normalized: NormalizedUrl,
    robots_txt: str,
    *,
    http_status: int = 200,
) -> CheckResult:
    groups = parse_robots_txt(robots_txt)
    oai_groups = _oai_groups(groups)
    star_groups = _star_groups(groups)
    applied_groups: list[RobotsGroup] = []

    if oai_groups:
        applied_groups = oai_groups
        if _has_root_disallow(oai_groups):
            return _result(
                normalized,
                verdict="block",
                reason="OpenAI 광고 로봇의 사이트 접근이 막혀 있음",
                action="사이트 설정에서 OpenAI 광고 로봇 접근을 허용해 주세요",
                http_status=http_status,
                robots_txt=robots_txt,
            )
        base_reason = (
            "OpenAI 광고 로봇 접근이 허용된 것으로 보임"
            if _has_explicit_allow(oai_groups)
            else "OpenAI 광고 로봇 설정이 있으며 전체 차단은 없음"
        )
    elif star_groups:
        applied_groups = star_groups
        if _has_root_disallow(star_groups):
            return _result(
                normalized,
                verdict="block",
                reason="모든 광고/검색 로봇의 사이트 접근이 막혀 있어 OpenAI 광고 로봇도 접근할 수 없음",
                action="사이트 설정에서 OpenAI 광고 로봇 접근 예외를 허용해 주세요",
                http_status=http_status,
                robots_txt=robots_txt,
            )
        base_reason = (
            "사이트 접근이 허용된 것으로 보임"
            if _has_star_allow(star_groups)
            else "전체 로봇 설정이 있으며 전체 차단은 없음"
        )
    elif groups:
        return _result(
            normalized,
            verdict="warn",
            reason="일부 검색 로봇만 허용돼 있어, OpenAI 광고 로봇 허용 여부가 불명확 — 개발팀 확인 권장",
            action="광고주 개발팀에 OpenAI 광고 로봇 허용 설정을 명시해 달라고 요청하세요",
            http_status=http_status,
            robots_txt=robots_txt,
        )
    else:
        base_reason = "별도 차단 설정이 없어 접근 가능으로 보임"

    if applied_groups:
        matched_disallow = _matching_disallow(applied_groups, normalized.path)
        if matched_disallow:
            return _result(
                normalized,
                verdict="warn",
                reason="광고가 연결될 페이지 주소가 차단 목록에 포함됨 — 다른 랜딩 페이지 필요",
                action="다른 랜딩 페이지를 쓰거나, 개발팀에 해당 페이지 차단 해제를 요청하세요",
                http_status=http_status,
                robots_txt=robots_txt,
            )

    if not _standard_robotparser_allows(robots_txt, normalized.normalized_url):
        return _result(
            normalized,
            verdict="warn",
            reason="광고가 연결될 페이지 주소가 차단될 수 있음 — 개발팀 확인 필요",
            action="사이트의 크롤러 허용 설정(robots.txt)을 개발팀에서 확인해 주세요",
            http_status=http_status,
            robots_txt=robots_txt,
        )

    return _result(
        normalized,
        verdict="allow",
        reason=base_reason,
        action="광고주 개발팀에 실제 OpenAI 광고 로봇 접근 테스트로 최종 확인을 요청하세요",
        http_status=http_status,
        robots_txt=robots_txt,
    )


def _http_error_result(
    normalized: NormalizedUrl,
    status_code: int,
    body: str,
) -> CheckResult:
    if status_code == 404:
        return _result(
            normalized,
            verdict="allow",
            reason="별도 차단 설정이 없어 접근 가능으로 보임",
            action="방화벽/안티봇 차단 여부는 실제 OpenAI 광고 로봇 접근 테스트로 확인하세요",
            http_status=status_code,
            robots_txt=body or "사이트의 크롤러 허용 설정(robots.txt) 없음 (HTTP 404)",
        )

    body_lower = body.lower()
    if status_code == 403 and any(
        token in body_lower for token in ("cloudflare", "challenge", "just a moment")
    ):
        return _result(
            normalized,
            verdict="block",
            reason="방화벽이 먼저 막고 있음 — 광고 로봇 접근 허용 등록 필요",
            action="Cloudflare 등 방화벽에서 OpenAI 광고 로봇 접근을 허용해 주세요",
            http_status=status_code,
            robots_txt=body,
        )

    return _result(
        normalized,
        verdict="warn",
        reason=f"사이트의 크롤러 허용 설정(robots.txt)을 확인할 수 없음(HTTP {status_code}) — 개발팀 확인 필요",
        action="서버 응답 코드와 방화벽/안티봇 정책을 개발팀에서 확인해 주세요",
        http_status=status_code,
        robots_txt=body,
    )


async def check_url(raw_url: str, client: httpx.AsyncClient) -> CheckResult:
    try:
        normalized = normalize_url(raw_url)
    except ValueError as exc:
        fallback = NormalizedUrl(
            input_url=raw_url,
            normalized_url=raw_url,
            origin="",
            path="",
            robots_url="",
        )
        return _result(
            fallback,
            verdict="warn",
            reason=f"{exc} — 올바른 URL을 입력해 주세요",
            action="https://example.com/path 형식으로 다시 입력",
            http_status=None,
            robots_txt="",
        )

    try:
        response = await client.get(normalized.robots_url)
    except httpx.TimeoutException:
        return _result(
            normalized,
            verdict="warn",
            reason="사이트가 응답하지 않음 — 잠시 후 재시도 또는 개발팀 확인",
            action="잠시 후 다시 점검하고, 반복되면 광고주 개발팀에 확인을 요청하세요",
            http_status=None,
            robots_txt="",
        )
    except httpx.RequestError:
        return _result(
            normalized,
            verdict="warn",
            reason="사이트가 응답하지 않음 — 잠시 후 재시도 또는 개발팀 확인",
            action="잠시 후 다시 점검하고, 반복되면 광고주 개발팀에 확인을 요청하세요",
            http_status=None,
            robots_txt="",
        )

    body = response.text[:MAX_ROBOTS_TEXT_CHARS]
    if response.status_code == 200:
        result = evaluate_robots_txt(normalized, body, http_status=response.status_code)
        return _with_firewall_hint(
            result,
            _detect_firewall_hint(response.headers, body),
        )
    return _http_error_result(normalized, response.status_code, body)


async def check_urls(urls: list[str]) -> list[CheckResult]:
    unique_urls = [url.strip() for url in urls if url.strip()]
    timeout = httpx.Timeout(ROBOTS_TIMEOUT_SECONDS)
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    async with httpx.AsyncClient(
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
    ) as client:
        return await asyncio.gather(*(check_url(url, client) for url in unique_urls))
