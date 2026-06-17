from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlparse

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import (
    COLLECTION_ORDER,
    load_config,
    load_settings,
    require_openai_key,
    require_supabase_db_url,
)
from .crawler import crawl_urls
from .db import (
    delete_legacy_documents,
    delete_source_documents,
    delete_source_identity_prefix,
    ensure_database,
    insert_documents,
    reset_collection,
    source_hash_exists,
)
from .embeddings import embed_texts
from .help_center import content_hash, crawl_help_center_collections
from .local_docs import load_inline_documents, load_local_documents


def _collection_config(config: dict, name: str) -> dict:
    return (config.get("collections") or {}).get(name, {})


def _chunk_documents(documents: list[Document], config: dict) -> list[Document]:
    chunking = config.get("chunking") or {}
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=int(chunking.get("chunk_size_tokens", 700)),
        chunk_overlap=int(chunking.get("chunk_overlap_tokens", 100)),
        add_start_index=True,
    )
    chunks = splitter.split_documents(documents)
    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = index
    return chunks


def _batched(items: list[Document], batch_size: int) -> Iterable[list[Document]]:
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def _index_chunks(chunks: list[Document], *, collection_name: str) -> None:
    settings = load_settings()
    reset_collection(collection_name, settings)
    _insert_chunk_batches(chunks, collection_name=collection_name, settings=settings)


def _index_chunks_without_reset(chunks: list[Document], *, collection_name: str) -> None:
    settings = load_settings()
    _insert_chunk_batches(chunks, collection_name=collection_name, settings=settings)


def _insert_chunk_batches(
    chunks: list[Document],
    *,
    collection_name: str,
    settings,
) -> None:
    if not chunks:
        return

    batch_size = max(1, int(settings.embedding_batch_size))
    for batch in _batched(chunks, batch_size):
        vectors = embed_texts([chunk.page_content for chunk in batch], settings)
        insert_documents(
            collection_name=collection_name,
            chunks=batch,
            embeddings=vectors,
            settings=settings,
        )


def _identity_from_url(source_url: str) -> str:
    parsed = urlparse(source_url)
    normalized = parsed._replace(fragment="").geturl()
    return f"url:{normalized}"


def _ensure_incremental_metadata(document: Document) -> Document:
    metadata = document.metadata
    title = str(metadata.get("title") or "Untitled")
    source_url = str(metadata.get("source_url") or "")
    if not metadata.get("source_updated_at"):
        crawled_at = str(metadata.get("crawled_at") or "")
        if len(crawled_at) >= 10:
            metadata["source_updated_at"] = crawled_at[:10]
        else:
            metadata["source_updated_at"] = datetime.now(timezone.utc).date().isoformat()
        metadata["source_updated_at_is_fallback"] = True
    if not metadata.get("content_hash"):
        metadata["content_hash"] = content_hash(title, document.page_content)
    if not metadata.get("source_identity"):
        article_id = str(metadata.get("article_id") or "").strip()
        lang = str(metadata.get("lang") or "").strip()
        metadata["source_identity"] = (
            f"help:{article_id}:{lang}" if article_id and lang else _identity_from_url(source_url)
        )
    return document


def _official_documents(config: dict) -> tuple[list[Document], list[str], dict[str, int]]:
    collection = _collection_config(config, "official")
    crawler = config.get("crawler") or {}
    stats: dict[str, int] = {
        "official_documents": 0,
        "official_changed_documents": 0,
        "official_unchanged_documents": 0,
        "official_legacy_deleted": 0,
        "official_stale_inline_deleted": 0,
        "help_center_ko_articles": 0,
        "help_center_en_articles": 0,
        "help_center_failed": 0,
    }

    documents: list[Document] = []
    errors: list[str] = []

    help_center_collections = collection.get("help_center_collections") or {}
    if help_center_collections:
        help_documents, help_errors, help_stats = crawl_help_center_collections(
            help_center_collections,
            user_agent=str(crawler.get("user_agent", "nasmedia-rag-poc/0.1")),
            timeout_seconds=int(crawler.get("request_timeout_seconds", 30)),
            respect_robots_txt=bool(crawler.get("respect_robots_txt", True)),
        )
        documents.extend(help_documents)
        errors.extend(help_errors)
        stats.update(help_stats)

    urls = collection.get("urls") or []
    url_documents, url_errors = crawl_urls(
        urls,
        user_agent=str(crawler.get("user_agent", "nasmedia-rag-poc/0.1")),
        timeout_seconds=int(crawler.get("request_timeout_seconds", 30)),
        respect_robots_txt=bool(crawler.get("respect_robots_txt", True)),
    )
    documents.extend(url_documents)
    errors.extend(url_errors)

    seen_urls = {str(item.metadata.get("source_url") or "") for item in documents}
    has_help_center_documents = any(
        str(item.metadata.get("article_id") or "") for item in documents
    )
    inline_documents = [
        item
        for item in load_inline_documents(collection.get("documents") or [], source_tier="official")
        if str(item.metadata.get("source_url") or "") not in seen_urls
        and not (
            has_help_center_documents
            and urlparse(str(item.metadata.get("source_url") or "")).netloc == "help.openai.com"
        )
    ]
    documents.extend(inline_documents)

    prepared = [_ensure_incremental_metadata(document) for document in documents]
    stats["official_documents"] = len(prepared)
    return prepared, errors, stats


def _local_documents(config: dict, collection_name: str) -> list[Document]:
    collection = _collection_config(config, collection_name)
    documents = load_local_documents(
        collection.get("paths") or [],
        source_tier=collection_name,
        ignore_patterns=config.get("ignored_local_patterns") or [],
    )
    documents.extend(
        load_inline_documents(collection.get("documents") or [], source_tier=collection_name)
    )
    return documents


def _changed_official_documents(documents: list[Document]) -> tuple[list[Document], int]:
    settings = load_settings()
    changed: list[Document] = []
    unchanged = 0
    for document in documents:
        metadata = document.metadata
        source_identity = str(metadata.get("source_identity") or "")
        hash_value = str(metadata.get("content_hash") or "")
        source_url = str(metadata.get("source_url") or "")
        if source_identity and hash_value and source_hash_exists(
            collection_name="official",
            source_identity=source_identity,
            content_hash=hash_value,
            settings=settings,
        ):
            unchanged += 1
            continue
        if source_identity:
            delete_source_documents(
                collection_name="official",
                source_identity=source_identity,
                source_url=source_url,
                settings=settings,
            )
        changed.append(document)
    return changed, unchanged


def ingest_collections(
    collections: Iterable[str] | None = None,
    *,
    config_path: str | None = None,
) -> dict[str, int]:
    settings = load_settings()
    require_openai_key(settings)
    require_supabase_db_url(settings)
    config = load_config(config_path)
    selected = tuple(collections or COLLECTION_ORDER)
    ensure_database(settings)

    counts: dict[str, int] = {}
    for collection_name in selected:
        if collection_name not in COLLECTION_ORDER:
            raise ValueError(f"Unknown collection: {collection_name}")

        if collection_name == "official":
            documents, errors, official_stats = _official_documents(config)
            for error in errors:
                print(f"[warn] {error}")
            min_help_articles = int(os.getenv("REQUIRE_HELP_CENTER_MIN_ARTICLES", "0") or 0)
            if min_help_articles:
                help_articles = int(official_stats.get("help_center_ko_articles", 0)) + int(
                    official_stats.get("help_center_en_articles", 0)
                )
                if help_articles < min_help_articles:
                    raise RuntimeError(
                        "Help Center reindex fetched too few articles: "
                        f"{help_articles} < {min_help_articles}. "
                        "Check GitHub Actions network access or reader fallback."
                    )
            official_stats["official_legacy_deleted"] = delete_legacy_documents(
                collection_name="official",
                settings=settings,
            )
            if any(str(item.metadata.get("article_id") or "") for item in documents):
                official_stats["official_stale_inline_deleted"] = delete_source_identity_prefix(
                    collection_name="official",
                    source_identity_prefix="inline:official:https://help.openai.com/",
                    settings=settings,
                )
            documents, unchanged = _changed_official_documents(documents)
            official_stats["official_changed_documents"] = len(documents)
            official_stats["official_unchanged_documents"] = unchanged
        else:
            documents = _local_documents(config, collection_name)
            official_stats = {}

        chunks = _chunk_documents(documents, config)
        if collection_name == "official":
            _index_chunks_without_reset(chunks, collection_name=collection_name)
        else:
            _index_chunks(chunks, collection_name=collection_name)
        counts[collection_name] = len(chunks)
        counts[f"{collection_name}_chunks"] = len(chunks)
        for key, value in official_stats.items():
            counts[key] = int(value)
        print(f"[ok] {collection_name}: {len(documents)} docs, {len(chunks)} chunks")
        if official_stats:
            print(f"[stats] {collection_name}: {json.dumps(official_stats, ensure_ascii=False)}")

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl and index RAG documents.")
    parser.add_argument("--config", help="Path to config YAML. Defaults to RAG_CONFIG_PATH.")
    parser.add_argument(
        "--collection",
        action="append",
        choices=COLLECTION_ORDER,
        help="Collection to reindex. Can be passed multiple times.",
    )
    args = parser.parse_args()
    ingest_collections(args.collection, config_path=args.config)


if __name__ == "__main__":
    main()
