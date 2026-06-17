from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import shutil
import subprocess
from typing import Iterable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from langchain_core.documents import Document
from markdownify import markdownify as to_markdown


_ROBOTS_CACHE: dict[str, RobotFileParser] = {}
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass(frozen=True)
class FetchedPage:
    final_url: str
    text: str
    status_code: int
    used_curl_fallback: bool = False


def _robots_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


def can_fetch(url: str, user_agent: str) -> bool:
    robots_url = _robots_url(url)
    parser = _ROBOTS_CACHE.get(robots_url)
    if parser is None:
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            response = httpx.get(
                robots_url,
                headers={"User-Agent": user_agent},
                follow_redirects=True,
                timeout=10,
            )
            if response.status_code == 404:
                parser.parse([])
            elif response.status_code >= 400:
                return False
            else:
                parser.parse(response.text.splitlines())
        except Exception:
            return False
        _ROBOTS_CACHE[robots_url] = parser
    return parser.can_fetch(user_agent, url)


def _is_cloudflare_challenge(response: httpx.Response) -> bool:
    return (
        response.status_code == 403
        and response.headers.get("cf-mitigated", "").lower() == "challenge"
    )


def _curl_binary() -> str | None:
    return shutil.which("curl") or shutil.which("curl.exe")


def _fetch_with_curl(url: str, timeout_seconds: int) -> FetchedPage:
    curl = _curl_binary()
    if not curl:
        raise RuntimeError("Cloudflare challenge received and curl fallback is unavailable.")

    marker = "\n__CURL_META__"
    command = [
        curl,
        "-L",
        "--silent",
        "--show-error",
        "--max-time",
        str(timeout_seconds),
        "-A",
        _BROWSER_USER_AGENT,
        "-H",
        "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "-H",
        "Accept-Language: ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "-w",
        marker + "%{http_code} %{url_effective}",
        url,
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds + 5,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"Curl fallback failed: {detail[:240]}")

    body, separator, meta = completed.stdout.rpartition(marker)
    if not separator:
        raise RuntimeError("Curl fallback returned an unexpected response.")
    parts = meta.strip().split(" ", 1)
    status_code = int(parts[0]) if parts and parts[0].isdigit() else 0
    final_url = parts[1] if len(parts) > 1 else url
    if status_code >= 400:
        raise RuntimeError(f"Curl fallback failed with HTTP {status_code}: {final_url}")
    return FetchedPage(
        final_url=final_url,
        text=body,
        status_code=status_code,
        used_curl_fallback=True,
    )


def _fetch_with_curl_cffi(url: str, timeout_seconds: int) -> FetchedPage:
    try:
        from curl_cffi import requests as curl_requests
    except ImportError as exc:
        raise RuntimeError("curl_cffi fallback is unavailable.") from exc

    response = curl_requests.get(
        url,
        impersonate="chrome120",
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        },
        timeout=timeout_seconds,
        allow_redirects=True,
    )
    final_url = str(response.url or url)
    if response.status_code >= 400:
        raise RuntimeError(
            f"curl_cffi fallback failed with HTTP {response.status_code}: {final_url}"
        )
    return FetchedPage(
        final_url=final_url,
        text=response.text,
        status_code=int(response.status_code),
        used_curl_fallback=True,
    )


def fetch_page(
    url: str,
    *,
    user_agent: str,
    timeout_seconds: int,
    respect_robots_txt: bool = True,
) -> FetchedPage:
    if respect_robots_txt and not can_fetch(url, user_agent):
        raise PermissionError(f"Blocked by robots.txt: {url}")

    headers = {"User-Agent": user_agent}
    with httpx.Client(headers=headers, follow_redirects=True, timeout=timeout_seconds) as client:
        response = client.get(url)
        if _is_cloudflare_challenge(response):
            try:
                return _fetch_with_curl_cffi(url, timeout_seconds)
            except Exception:
                return _fetch_with_curl(url, timeout_seconds)
        response.raise_for_status()
        return FetchedPage(
            final_url=str(response.url),
            text=response.text,
            status_code=response.status_code,
            used_curl_fallback=False,
        )


def html_to_markdown(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "form"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    content_root = soup.find("main") or soup.find("article") or soup.body or soup
    markdown = to_markdown(str(content_root), heading_style="ATX")
    markdown = "\n".join(line.rstrip() for line in markdown.splitlines())
    markdown = "\n".join(line for line in markdown.splitlines() if line.strip())
    return title, markdown.strip()


def fetch_url(
    url: str,
    *,
    user_agent: str,
    timeout_seconds: int,
    respect_robots_txt: bool = True,
) -> Document:
    page = fetch_page(
        url,
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
        respect_robots_txt=respect_robots_txt,
    )
    title, markdown = html_to_markdown(page.text)
    final_url = page.final_url
    if not markdown:
        raise ValueError(f"No indexable content found: {url}")

    return Document(
        page_content=markdown,
        metadata={
            "source_tier": "official",
            "source_url": final_url,
            "title": title or final_url,
            "crawled_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def crawl_urls(
    urls: Iterable[str],
    *,
    user_agent: str,
    timeout_seconds: int,
    respect_robots_txt: bool,
) -> tuple[list[Document], list[str]]:
    documents: list[Document] = []
    errors: list[str] = []
    for url in urls:
        try:
            documents.append(
                fetch_url(
                    url,
                    user_agent=user_agent,
                    timeout_seconds=timeout_seconds,
                    respect_robots_txt=respect_robots_txt,
                )
            )
        except Exception as exc:
            errors.append(f"{url} -> {exc}")
    return documents, errors


def normalize_link(base_url: str, href: str) -> str:
    return urljoin(base_url, href)
