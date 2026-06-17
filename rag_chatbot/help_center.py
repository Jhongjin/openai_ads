from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from langchain_core.documents import Document
from markdownify import markdownify as to_markdown

from .crawler import can_fetch


ARTICLE_RE = re.compile(r"/articles/(\d+)")
COLLECTION_RE = re.compile(r"/collections/\d+")
HELP_HOST = "help.openai.com"


def _clean_text(text: str) -> str:
    return " ".join(text.split())


def _date_string(value: datetime) -> str:
    return value.astimezone(timezone.utc).date().isoformat()


def relative_updated_date(
    text: str,
    crawled_at: datetime,
) -> tuple[str, bool] | None:
    """Return (YYYY-MM-DD, is_fallback) from Help Center relative date text."""

    lowered = _clean_text(text).lower()
    if not lowered:
        return None

    days = 0
    if re.search(r"\b(an?|one)\s+day\s+ago\b", lowered) or "하루 전" in lowered or "어제" in lowered:
        days = 1
    elif match := re.search(r"\b(\d+)\s+days?\s+ago\b", lowered):
        days = int(match.group(1))
    elif match := re.search(r"(\d+)\s*일\s*전", lowered):
        days = int(match.group(1))
    elif re.search(r"\b(an?|one)\s+week\s+ago\b", lowered) or "일주일 전" in lowered:
        days = 7
    elif match := re.search(r"\b(\d+)\s+weeks?\s+ago\b", lowered):
        days = int(match.group(1)) * 7
    elif match := re.search(r"(\d+)\s*주\s*전", lowered):
        days = int(match.group(1)) * 7
    elif re.search(r"\b(an?|one)\s+month\s+ago\b", lowered) or "한 달 전" in lowered:
        days = 30
    elif match := re.search(r"\b(\d+)\s+months?\s+ago\b", lowered):
        days = int(match.group(1)) * 30
    elif match := re.search(r"(\d+)\s*개월\s*전", lowered):
        days = int(match.group(1)) * 30
    elif any(
        marker in lowered
        for marker in (
            "hour ago",
            "hours ago",
            "minute ago",
            "minutes ago",
            "just now",
            "today",
            "시간 전",
            "분 전",
            "방금",
            "오늘",
        )
    ):
        days = 0
    elif "updated" not in lowered and "업데이트" not in lowered and "수정" not in lowered:
        return None
    else:
        return (_date_string(crawled_at), True)

    return (_date_string(crawled_at - timedelta(days=days)), False)


def parse_help_center_updated_at(
    soup: BeautifulSoup,
    crawled_at: datetime,
) -> tuple[str, bool]:
    candidates: list[str] = []
    for tag in soup.find_all(class_=lambda value: value and "text-tertiary" in str(value)):
        text = _clean_text(tag.get_text(" ", strip=True))
        if text:
            candidates.append(text)
    candidates.extend(_clean_text(text) for text in soup.stripped_strings if "Updated" in text)

    for candidate in candidates:
        parsed = relative_updated_date(candidate, crawled_at)
        if parsed:
            return parsed
    return (_date_string(crawled_at), True)


def content_hash(title: str, content: str) -> str:
    return hashlib.sha256(f"{title}\n\n{content}".encode("utf-8")).hexdigest()


def _language_from_url(url: str, fallback: str) -> str:
    path = urlparse(url).path
    if path.startswith("/ko-kr/"):
        return "ko"
    if path.startswith("/en/"):
        return "en"
    return fallback


def _locale_matches(url: str, lang: str) -> bool:
    path = urlparse(url).path
    if lang == "ko":
        return path.startswith("/ko-kr/")
    if lang == "en":
        return path.startswith("/en/")
    return True


def _is_help_center_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc == HELP_HOST or parsed.netloc.endswith(f".{HELP_HOST}")


def _normalize_help_link(base_url: str, href: str) -> str | None:
    if not href or href.startswith(("mailto:", "tel:", "#")):
        return None
    url = urljoin(base_url, href)
    parsed = urlparse(url)
    if not _is_help_center_url(url):
        return None
    return parsed._replace(fragment="").geturl()


def _extract_links(html: str, base_url: str, lang: str) -> tuple[set[str], set[str]]:
    soup = BeautifulSoup(html, "html.parser")
    article_urls: set[str] = set()
    collection_urls: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        url = _normalize_help_link(base_url, str(anchor.get("href") or ""))
        if not url or not _locale_matches(url, lang):
            continue
        path = urlparse(url).path
        if ARTICLE_RE.search(path):
            article_urls.add(url)
        elif COLLECTION_RE.search(path):
            collection_urls.add(url)
    return article_urls, collection_urls


def _article_id(url: str) -> str:
    match = ARTICLE_RE.search(urlparse(url).path)
    return match.group(1) if match else ""


def _article_to_document(html: str, final_url: str, lang: str, crawled_at: datetime) -> Document:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "form"]):
        tag.decompose()

    title_tag = soup.find("h1") or soup.title
    title = _clean_text(title_tag.get_text(" ", strip=True) if title_tag else "") or final_url
    updated_at, is_fallback = parse_help_center_updated_at(soup, crawled_at)
    for tag in soup.find_all(class_=lambda value: value and "text-tertiary" in str(value)):
        tag.decompose()
    content_root = soup.find("article") or soup.find("main") or soup.body or soup
    markdown = to_markdown(str(content_root), heading_style="ATX")
    markdown = "\n".join(line.rstrip() for line in markdown.splitlines())
    markdown = "\n".join(line for line in markdown.splitlines() if line.strip()).strip()
    article_id = _article_id(final_url)
    identity = f"help:{article_id}:{lang}"

    return Document(
        page_content=markdown,
        metadata={
            "source_tier": "official",
            "source_url": final_url,
            "title": title,
            "crawled_at": crawled_at.isoformat(),
            "source_updated_at": updated_at,
            "source_updated_at_is_fallback": is_fallback,
            "lang": lang,
            "article_id": article_id,
            "content_hash": content_hash(title, markdown),
            "source_identity": identity,
        },
    )


def crawl_help_center_collections(
    start_urls_by_lang: dict[str, str] | Iterable[tuple[str, str]],
    *,
    user_agent: str,
    timeout_seconds: int,
    respect_robots_txt: bool,
) -> tuple[list[Document], list[str], dict[str, int]]:
    starts = dict(start_urls_by_lang)
    documents: list[Document] = []
    errors: list[str] = []
    stats = {
        "help_center_ko_articles": 0,
        "help_center_en_articles": 0,
        "help_center_failed": 0,
    }

    headers = {"User-Agent": user_agent}
    with httpx.Client(headers=headers, follow_redirects=True, timeout=timeout_seconds) as client:
        for configured_lang, start_url in starts.items():
            lang = "ko" if configured_lang.lower().startswith("ko") else "en"
            visited_collections: set[str] = set()
            article_urls: set[str] = set()
            queue: deque[str] = deque([start_url])

            while queue:
                collection_url = queue.popleft()
                if collection_url in visited_collections:
                    continue
                visited_collections.add(collection_url)
                try:
                    if respect_robots_txt and not can_fetch(collection_url, user_agent):
                        raise PermissionError(f"Blocked by robots.txt: {collection_url}")
                    response = client.get(collection_url)
                    response.raise_for_status()
                    found_articles, found_collections = _extract_links(
                        response.text,
                        str(response.url),
                        lang,
                    )
                    article_urls.update(found_articles)
                    for found in sorted(found_collections):
                        if found not in visited_collections:
                            queue.append(found)
                except Exception as exc:
                    stats["help_center_failed"] += 1
                    errors.append(f"{collection_url} -> {exc}")

            for article_url in sorted(article_urls):
                try:
                    if respect_robots_txt and not can_fetch(article_url, user_agent):
                        raise PermissionError(f"Blocked by robots.txt: {article_url}")
                    crawled_at = datetime.now(timezone.utc)
                    response = client.get(article_url)
                    response.raise_for_status()
                    final_url = str(response.url)
                    article_lang = _language_from_url(final_url, lang)
                    document = _article_to_document(
                        response.text,
                        final_url,
                        article_lang,
                        crawled_at,
                    )
                    if document.page_content:
                        documents.append(document)
                        if article_lang == "ko":
                            stats["help_center_ko_articles"] += 1
                        elif article_lang == "en":
                            stats["help_center_en_articles"] += 1
                except Exception as exc:
                    stats["help_center_failed"] += 1
                    errors.append(f"{article_url} -> {exc}")

    return documents, errors, stats
