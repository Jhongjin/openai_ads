from __future__ import annotations

from dataclasses import dataclass
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


def retrieve(
    query: str,
    *,
    config_path: str | None = None,
) -> list[RetrievedDocument]:
    settings = load_settings()
    require_openai_key(settings)
    require_supabase_db_url(settings)
    config = load_config(config_path)
    retrieval = config.get("retrieval") or {}
    top_k = int(retrieval.get("top_k_per_collection", 4))
    min_score = float(retrieval.get("min_relevance_score", 0.25))
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
        except psycopg.errors.UndefinedTable:
            continue

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

    return sorted(
        results,
        key=lambda item: (
            SOURCE_TIER_PRIORITY.get(item.source_tier, 99),
            -item.score,
            item.title,
        ),
    )
