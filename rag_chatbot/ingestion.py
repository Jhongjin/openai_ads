from __future__ import annotations

import argparse
from typing import Iterable

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
from .db import ensure_database, insert_documents, reset_collection
from .embeddings import embed_texts
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


def _official_documents(config: dict) -> tuple[list[Document], list[str]]:
    collection = _collection_config(config, "official")
    crawler = config.get("crawler") or {}
    urls = collection.get("urls") or []
    documents, errors = crawl_urls(
        urls,
        user_agent=str(crawler.get("user_agent", "nasmedia-rag-poc/0.1")),
        timeout_seconds=int(crawler.get("request_timeout_seconds", 30)),
        respect_robots_txt=bool(crawler.get("respect_robots_txt", True)),
    )
    documents.extend(load_inline_documents(collection.get("documents") or [], source_tier="official"))
    return documents, errors


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
            documents, errors = _official_documents(config)
            for error in errors:
                print(f"[warn] {error}")
        else:
            documents = _local_documents(config, collection_name)

        chunks = _chunk_documents(documents, config)
        _index_chunks(chunks, collection_name=collection_name)
        counts[collection_name] = len(chunks)
        print(f"[ok] {collection_name}: {len(documents)} docs, {len(chunks)} chunks")

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
