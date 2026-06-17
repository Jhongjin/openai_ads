from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import psycopg
from langchain_core.documents import Document

from .config import (
    COLLECTION_ORDER,
    SOURCE_TIER_PRIORITY,
    load_config,
    load_settings,
    require_openai_key,
    require_supabase_db_url,
)
from .db import fetch_similar_documents
from .embeddings import embed_query
from .local_docs import load_inline_documents, load_local_documents


@dataclass(frozen=True)
class RetrievedDocument:
    document: Document
    score: float
    collection: str

    @property
    def source_tier(self) -> str:
        return str(self.document.metadata.get("source_tier") or self.collection)

    @property
    def title(self) -> str:
        return str(self.document.metadata.get("title") or "Untitled")

    @property
    def source_url(self) -> str:
        return str(self.document.metadata.get("source_url") or "")

    def to_source_dict(self) -> dict[str, Any]:
        metadata = dict(self.document.metadata)
        metadata.update(
            {
                "collection": self.collection,
                "score": round(float(self.score), 4),
                "source_tier": self.source_tier,
                "title": self.title,
                "source_url": self.source_url,
            }
        )
        return metadata


def _collection_config(config: dict, name: str) -> dict:
    return (config.get("collections") or {}).get(name, {})


def _fallback_documents(config: dict, collection_name: str) -> list[Document]:
    collection = _collection_config(config, collection_name)
    documents = load_inline_documents(
        collection.get("documents") or [],
        source_tier=collection_name,
    )
    if collection_name != "official":
        documents.extend(
            load_local_documents(
                collection.get("paths") or [],
                source_tier=collection_name,
                ignore_patterns=config.get("ignored_local_patterns") or [],
            )
        )
    return documents


def _tokens(text: str) -> set[str]:
    lowered = text.lower()
    raw_tokens = re.findall(r"[a-z0-9%+-]+|[가-힣]+", lowered)
    expanded = set(raw_tokens)
    for token in raw_tokens:
        if len(token) >= 4 and re.fullmatch(r"[가-힣]+", token):
            expanded.update(token[index : index + 2] for index in range(len(token) - 1))
            expanded.update(token[index : index + 3] for index in range(len(token) - 2))
    return {token for token in expanded if len(token) >= 2}


def _lexical_score(query_tokens: set[str], document: Document) -> float:
    if not query_tokens:
        return 0.0
    text = " ".join(
        [
            str(document.metadata.get("title") or ""),
            str(document.metadata.get("source_url") or ""),
            document.page_content,
        ]
    )
    doc_tokens = _tokens(text)
    if not doc_tokens:
        return 0.0
    overlap = query_tokens & doc_tokens
    return len(overlap) / max(4, len(query_tokens))


def _fallback_retrieve(query: str, config: dict, *, limit: int) -> list[RetrievedDocument]:
    query_tokens = _tokens(query)
    results: list[RetrievedDocument] = []
    for collection_name in COLLECTION_ORDER:
        for document in _fallback_documents(config, collection_name):
            score = _lexical_score(query_tokens, document)
            if score <= 0:
                continue
            results.append(
                RetrievedDocument(
                    document=document,
                    score=score,
                    collection=collection_name,
                )
            )
    return sorted(
        results,
        key=lambda item: (
            -item.score,
            SOURCE_TIER_PRIORITY.get(item.source_tier, 99),
            item.title,
        ),
    )[:limit]


def retrieve(
    query: str,
    *,
    config_path: str | None = None,
) -> list[RetrievedDocument]:
    settings = load_settings()
    config = load_config(config_path)
    retrieval = config.get("retrieval") or {}
    top_k = int(retrieval.get("top_k_per_collection", 4))
    min_score = float(retrieval.get("min_relevance_score", 0.25))

    if not settings.openai_api_key or not settings.supabase_db_url:
        return _fallback_retrieve(query, config, limit=top_k * len(COLLECTION_ORDER))

    require_openai_key(settings)
    require_supabase_db_url(settings)
    query_embedding = embed_query(query, settings)

    results: list[RetrievedDocument] = []
    for collection_name in COLLECTION_ORDER:
        try:
            rows = fetch_similar_documents(
                collection_name=collection_name,
                query_embedding=query_embedding,
                limit=top_k,
                settings=settings,
            )
        except (psycopg.Error, RuntimeError):
            return _fallback_retrieve(query, config, limit=top_k * len(COLLECTION_ORDER))

        for row in rows:
            score = float(row.get("score") or 0)
            if score < min_score:
                continue
            metadata = dict(row.get("metadata") or {})
            metadata.update(
                {
                    "id": row.get("id"),
                    "collection": row.get("collection"),
                    "source_tier": row.get("source_tier"),
                    "source_url": row.get("source_url"),
                    "title": row.get("title"),
                    "chunk_index": row.get("chunk_index"),
                    "crawled_at": str(row.get("crawled_at") or ""),
                }
            )
            results.append(
                RetrievedDocument(
                    document=Document(
                        page_content=str(row.get("content") or ""),
                        metadata=metadata,
                    ),
                    score=score,
                    collection=collection_name,
                )
            )

    sorted_results = sorted(
        results,
        key=lambda item: (
            SOURCE_TIER_PRIORITY.get(item.source_tier, 99),
            -item.score,
            item.title,
        ),
    )
    if not sorted_results:
        return _fallback_retrieve(query, config, limit=top_k * len(COLLECTION_ORDER))
    return sorted_results
