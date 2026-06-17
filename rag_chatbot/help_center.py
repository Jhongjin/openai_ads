from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import time
from typing import Iterable
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from langchain_core.documents import Document
from markdownify import markdownify as to_markdown

from .crawler import (
    can_fetch,
    fetch_page,
    fetch_reader_page,
    reader_fallback_enabled,
    reader_markdown_to_content,
)


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
    if (
        re.search(r"\b(an?|one)\s+day\s+ago\b", lowered)
        or "yesterday" in lowered
        or "하루 전" in lowered
        or "어제" in lowered
    ):
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


def _extract_markdown_links(markdown: str, base_url: str, lang: str) -> tuple[set[str], set[str]]:
    article_urls: set[str] = set()
    collection_urls: set[str] = set()
    for raw_url in re.findall(r"https?://help\.openai\.com/[^\s)\]\"]+", markdown):
        url = _normalize_help_link(base_url, raw_url.rstrip(".,;:"))
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


def _data_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path
    if not path.endswith(".data"):
        path = f"{path.rstrip('/')}.data"
    return urlunparse(parsed._replace(path=path, query="", fragment=""))


def _strings_from_router_data(text: str) -> list[str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, str)]


def _ids_from_router_data(text: str) -> set[str]:
    return set(re.findall(r"\b200012\d+\b", text))


def _looks_like_article_data(strings: list[str], article_id: str) -> bool:
    return "routes/articles" in strings and "article" in strings and article_id in strings


def _textual_router_strings(strings: list[str]) -> list[str]:
    ignored = {
        "root",
        "routes/lang-root",
        "routes/articles",
        "routes/collections",
        "data",
        "article",
        "collection",
        "breadcrumbs",
        "content",
        "updatedAt",
        "contentfulEntryId",
        "routeLanguage",
        "countryCode",
        "href",
        "label",
        "id",
        "description",
        "defaultMessage",
        "messageDescriptor",
        "usingFallbackLocale",
    }
    seen: set[str] = set()
    selected: list[str] = []
    for raw in strings:
        text = _clean_text(raw)
        if not text or text in ignored:
            continue
        if re.fullmatch(r"200012\d+", text):
            continue
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*Z", text):
            continue
        if text.startswith(("/", "http://", "https://")):
            continue
        if len(text) < 8:
            continue
        if not re.search(r"[A-Za-z가-힣]", text):
            continue
        if text in seen:
            continue
        seen.add(text)
        selected.append(text)
    return selected


def _title_from_router_strings(strings: list[str], article_id: str, fallback: str) -> str:
    ignored = {
        "title",
        "slug",
        "subtitle",
        "seoTitle",
        "description",
        "content",
        "updatedAt",
        "contentfulEntryId",
    }
    try:
        start = strings.index(article_id) + 1
    except ValueError:
        start = 0
    for text in strings[start : start + 8]:
        cleaned = _clean_text(text)
        if (
            len(cleaned) >= 4
            and cleaned not in ignored
            and not re.fullmatch(r"200012\d+", cleaned)
        ):
            return cleaned
    for text in _textual_router_strings(strings):
        if len(text) < 80:
            return text
    return fallback


def _article_document_from_router_data(
    text: str,
    source_url: str,
    lang: str,
    crawled_at: datetime,
) -> Document | None:
    strings = _strings_from_router_data(text)
    article_id = _article_id(source_url)
    if not _looks_like_article_data(strings, article_id):
        return None
    title = _title_from_router_strings(strings, article_id, source_url)
    content_parts = _textual_router_strings(strings)
    content = "\n\n".join([title, *content_parts]).strip()
    if not content:
        return None

    updated_at = _date_string(crawled_at)
    identity = f"help:{article_id}:{lang}"
    return Document(
        page_content=content,
        metadata={
            "source_tier": "official",
            "source_url": source_url,
            "title": title,
            "crawled_at": crawled_at.isoformat(),
            "source_updated_at": updated_at,
            "source_updated_at_is_fallback": True,
            "lang": lang,
            "article_id": article_id,
            "content_hash": content_hash(title, content),
            "source_identity": identity,
            "loader_data_fallback": True,
        },
    )


def _article_url_from_id(start_url: str, article_id: str, lang: str) -> str:
    parsed = urlparse(start_url)
    locale = "ko-kr" if lang == "ko" else "en"
    return f"{parsed.scheme}://{parsed.netloc}/{locale}/articles/{article_id}"


def _collection_url_from_id(start_url: str, collection_id: str, lang: str) -> str:
    parsed = urlparse(start_url)
    locale = "ko-kr" if lang == "ko" else "en"
    return f"{parsed.scheme}://{parsed.netloc}/{locale}/collections/{collection_id}"


def _crawl_help_center_loader_data(
    start_url: str,
    *,
    lang: str,
    user_agent: str,
    timeout_seconds: int,
    respect_robots_txt: bool,
) -> tuple[list[Document], list[str]]:
    errors: list[str] = []
    documents: list[Document] = []
    seen_collections: set[str] = set()
    seen_articles: set[str] = set()
    article_ids: set[str] = set()
    collection_queue: deque[str] = deque([start_url])

    while collection_queue:
        collection_url = collection_queue.popleft()
        collection_id = re.search(r"/collections/(\d+)", urlparse(collection_url).path)
        collection_key = collection_id.group(1) if collection_id else collection_url
        if collection_key in seen_collections:
            continue
        seen_collections.add(collection_key)
        try:
            if respect_robots_txt and not can_fetch(collection_url, user_agent):
                raise PermissionError(f"Blocked by robots.txt: {collection_url}")
            page = fetch_page(
                _data_url(collection_url),
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
                respect_robots_txt=False,
            )
            ids = _ids_from_router_data(page.text)
            article_ids.update(ids)
            for candidate in ids:
                if candidate not in seen_collections:
                    collection_queue.append(_collection_url_from_id(start_url, candidate, lang))
        except Exception:
            continue

    for article_id in sorted(article_ids):
        if article_id in seen_articles:
            continue
        seen_articles.add(article_id)
        article_url = _article_url_from_id(start_url, article_id, lang)
        try:
            if respect_robots_txt and not can_fetch(article_url, user_agent):
                raise PermissionError(f"Blocked by robots.txt: {article_url}")
            crawled_at = datetime.now(timezone.utc)
            page = fetch_page(
                _data_url(article_url),
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
                respect_robots_txt=False,
            )
            document = _article_document_from_router_data(
                page.text,
                article_url,
                lang,
                crawled_at,
            )
            if document is not None:
                documents.append(document)
        except Exception as exc:
            if "HTTP 404" not in str(exc):
                errors.append(f"{article_url} -> {exc}")
    return documents, errors


def _article_document_from_reader_markdown(
    text: str,
    source_url: str,
    lang: str,
    crawled_at: datetime,
) -> Document | None:
    title, markdown = reader_markdown_to_content(text)
    article_id = _article_id(source_url)
    title = title or source_url
    markdown = markdown.strip()
    if not markdown:
        return None

    updated_at, is_fallback = relative_updated_date(markdown[:1200], crawled_at) or (
        _date_string(crawled_at),
        True,
    )
    identity = f"help:{article_id}:{lang}"
    return Document(
        page_content=markdown,
        metadata={
            "source_tier": "official",
            "source_url": source_url,
            "title": title,
            "crawled_at": crawled_at.isoformat(),
            "source_updated_at": updated_at,
            "source_updated_at_is_fallback": is_fallback,
            "lang": lang,
            "article_id": article_id,
            "content_hash": content_hash(title, markdown),
            "source_identity": identity,
            "reader_fallback": True,
        },
    )


def _reader_delay() -> None:
    delay = float(os.getenv("READER_FALLBACK_DELAY_SECONDS", "0.8") or 0)
    if delay > 0:
        time.sleep(delay)


def _crawl_help_center_reader(
    start_url: str,
    *,
    lang: str,
    user_agent: str,
    timeout_seconds: int,
    respect_robots_txt: bool,
) -> tuple[list[Document], list[str]]:
    errors: list[str] = []
    documents: list[Document] = []
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
            _reader_delay()
            page = fetch_reader_page(
                collection_url,
                timeout_seconds=timeout_seconds,
                user_agent=user_agent,
            )
            found_articles, found_collections = _extract_markdown_links(
                page.text,
                page.final_url,
                lang,
            )
            article_urls.update(found_articles)
            for found in sorted(found_collections):
                if found not in visited_collections:
                    queue.append(found)
        except Exception as exc:
            errors.append(f"{collection_url} -> {exc}")

    for article_url in sorted(article_urls):
        try:
            if respect_robots_txt and not can_fetch(article_url, user_agent):
                raise PermissionError(f"Blocked by robots.txt: {article_url}")
            crawled_at = datetime.now(timezone.utc)
            _reader_delay()
            page = fetch_reader_page(
                article_url,
                timeout_seconds=timeout_seconds,
                user_agent=user_agent,
            )
            final_url = page.final_url
            article_lang = _language_from_url(final_url, lang)
            document = _article_document_from_reader_markdown(
                page.text,
                final_url,
                article_lang,
                crawled_at,
            )
            if document is not None:
                documents.append(document)
        except Exception as exc:
            errors.append(f"{article_url} -> {exc}")

    return documents, errors


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
    crawl_mode = os.getenv("HELP_CENTER_CRAWL_MODE", "auto").lower()

    for configured_lang, start_url in starts.items():
        lang = "ko" if configured_lang.lower().startswith("ko") else "en"
        if crawl_mode != "reader":
            data_documents, data_errors = _crawl_help_center_loader_data(
                start_url,
                lang=lang,
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
                respect_robots_txt=respect_robots_txt,
            )
            min_loader_articles = (
                int(os.getenv("HELP_CENTER_MIN_LOADER_ARTICLES_PER_LANG", "10") or 0)
                if reader_fallback_enabled() and crawl_mode == "auto"
                else 1
            )
            if data_documents and (
                len(data_documents) >= min_loader_articles or crawl_mode == "loader"
            ):
                documents.extend(data_documents)
                if lang == "ko":
                    stats["help_center_ko_articles"] += len(data_documents)
                elif lang == "en":
                    stats["help_center_en_articles"] += len(data_documents)
                errors.extend(data_errors)
                stats["help_center_failed"] += len(data_errors)
                continue
            if data_documents:
                errors.append(
                    f"{start_url} -> loader data returned only "
                    f"{len(data_documents)} article(s); trying reader fallback"
                )
            errors.extend(data_errors)
            if crawl_mode == "loader":
                continue

        if reader_fallback_enabled() and crawl_mode != "loader":
            reader_documents, reader_errors = _crawl_help_center_reader(
                start_url,
                lang=lang,
                user_agent=str(user_agent),
                timeout_seconds=timeout_seconds,
                respect_robots_txt=respect_robots_txt,
            )
            if reader_documents:
                documents.extend(reader_documents)
                if lang == "ko":
                    stats["help_center_ko_articles"] += len(reader_documents)
                elif lang == "en":
                    stats["help_center_en_articles"] += len(reader_documents)
                stats["help_center_failed"] += len(reader_errors)
                stats["help_center_reader_articles"] = (
                    stats.get("help_center_reader_articles", 0) + len(reader_documents)
                )
                errors.extend(reader_errors)
                continue
            errors.extend(reader_errors)
            if crawl_mode == "reader":
                continue

        visited_collections: set[str] = set()
        article_urls: set[str] = set()
        queue: deque[str] = deque([start_url])

        while queue:
            collection_url = queue.popleft()
            if collection_url in visited_collections:
                continue
            visited_collections.add(collection_url)
            try:
                page = fetch_page(
                    collection_url,
                    user_agent=user_agent,
                    timeout_seconds=timeout_seconds,
                    respect_robots_txt=respect_robots_txt,
                )
                found_articles, found_collections = _extract_links(
                    page.text,
                    page.final_url,
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
                page = fetch_page(
                    article_url,
                    user_agent=user_agent,
                    timeout_seconds=timeout_seconds,
                    respect_robots_txt=False,
                )
                final_url = page.final_url
                article_lang = _language_from_url(final_url, lang)
                document = _article_to_document(
                    page.text,
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
