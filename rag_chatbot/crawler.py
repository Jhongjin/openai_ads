from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from langchain_core.documents import Document
from markdownify import markdownify as to_markdown


_ROBOTS_CACHE: dict[str, RobotFileParser] = {}


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
    if respect_robots_txt and not can_fetch(url, user_agent):
        raise PermissionError(f"Blocked by robots.txt: {url}")

    headers = {"User-Agent": user_agent}
    with httpx.Client(headers=headers, follow_redirects=True, timeout=timeout_seconds) as client:
        response = client.get(url)
        response.raise_for_status()

    title, markdown = html_to_markdown(response.text)
    final_url = str(response.url)
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
