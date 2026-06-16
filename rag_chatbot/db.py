from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any, Iterator, Sequence
import uuid

import psycopg
from langchain_core.documents import Document
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import RuntimeSettings, load_settings, require_supabase_db_url


_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_schema_name(schema: str) -> str:
    if not _SCHEMA_RE.match(schema):
        raise ValueError(
            "SUPABASE_SCHEMA must be a simple PostgreSQL identifier, for example "
            "'openai_ads_rag'."
        )
    return schema


def vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in values) + "]"


@contextmanager
def db_connection(
    settings: RuntimeSettings | None = None,
    *,
    row_factory: Any | None = None,
) -> Iterator[psycopg.Connection]:
    settings = settings or load_settings()
    require_supabase_db_url(settings)
    schema = _validate_schema_name(settings.supabase_schema)
    kwargs = {"row_factory": row_factory} if row_factory is not None else {}
    with psycopg.connect(settings.supabase_db_url, **kwargs) as conn:
        conn.execute(
            sql.SQL("set search_path to {}, public, extensions").format(
                sql.Identifier(schema)
            )
        )
        yield conn


def ensure_database(settings: RuntimeSettings | None = None) -> None:
    settings = settings or load_settings()
    schema = _validate_schema_name(settings.supabase_schema)
    dimensions = int(settings.openai_embedding_dimensions)
    if dimensions <= 0:
        raise ValueError("OPENAI_EMBEDDING_DIMENSIONS must be positive.")

    with db_connection(settings) as conn:
        conn.execute("create schema if not exists extensions")
        conn.execute("create extension if not exists vector with schema extensions")
        conn.execute(sql.SQL("create schema if not exists {}").format(sql.Identifier(schema)))
        conn.execute(
            sql.SQL("set search_path to {}, public, extensions").format(
                sql.Identifier(schema)
            )
        )
        conn.execute(
            sql.SQL(
                """
                create table if not exists {}.documents (
                    id uuid primary key,
                    collection text not null,
                    source_tier text not null,
                    source_url text not null,
                    title text not null,
                    content text not null,
                    chunk_index integer not null,
                    crawled_at timestamptz,
                    metadata jsonb not null default '{{}}'::jsonb,
                    embedding vector({}) not null,
                    created_at timestamptz not null default now(),
                    constraint documents_collection_check
                        check (collection in ('official', 'kr_ops', 'pending')),
                    constraint documents_source_tier_check
                        check (source_tier in ('official', 'kr_ops', 'pending'))
                )
                """
            ).format(sql.Identifier(schema), sql.SQL(str(dimensions)))
        )
        conn.execute(
            sql.SQL(
                "create index if not exists documents_collection_idx "
                "on {}.documents (collection)"
            ).format(sql.Identifier(schema))
        )
        conn.execute(
            sql.SQL(
                "create index if not exists documents_source_tier_idx "
                "on {}.documents (source_tier)"
            ).format(sql.Identifier(schema))
        )
        conn.execute(
            sql.SQL(
                "create index if not exists documents_embedding_hnsw_idx "
                "on {}.documents using hnsw (embedding vector_cosine_ops)"
            ).format(sql.Identifier(schema))
        )


def reset_collection(collection_name: str, settings: RuntimeSettings | None = None) -> None:
    settings = settings or load_settings()
    schema = _validate_schema_name(settings.supabase_schema)
    with db_connection(settings) as conn:
        conn.execute(
            sql.SQL("delete from {}.documents where collection = %s").format(
                sql.Identifier(schema)
            ),
            (collection_name,),
        )


def insert_documents(
    *,
    collection_name: str,
    chunks: list[Document],
    embeddings: list[list[float]],
    settings: RuntimeSettings | None = None,
) -> None:
    if len(chunks) != len(embeddings):
        raise ValueError("chunks and embeddings must have the same length.")

    settings = settings or load_settings()
    schema = _validate_schema_name(settings.supabase_schema)
    rows: list[tuple[Any, ...]] = []
    for chunk, embedding in zip(chunks, embeddings):
        metadata = dict(chunk.metadata)
        crawled_at = metadata.get("crawled_at")
        if crawled_at == "":
            crawled_at = None
        rows.append(
            (
                uuid.uuid4(),
                collection_name,
                str(metadata.get("source_tier") or collection_name),
                str(metadata.get("source_url") or ""),
                str(metadata.get("title") or "Untitled"),
                chunk.page_content,
                int(metadata.get("chunk_index") or 0),
                crawled_at,
                Jsonb(metadata),
                vector_literal(embedding),
            )
        )

    if not rows:
        return

    with db_connection(settings) as conn:
        conn.executemany(
            sql.SQL(
                """
                insert into {}.documents (
                    id,
                    collection,
                    source_tier,
                    source_url,
                    title,
                    content,
                    chunk_index,
                    crawled_at,
                    metadata,
                    embedding
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                """
            ).format(sql.Identifier(schema)),
            rows,
        )


def fetch_similar_documents(
    *,
    collection_name: str,
    query_embedding: Sequence[float],
    limit: int,
    settings: RuntimeSettings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or load_settings()
    schema = _validate_schema_name(settings.supabase_schema)
    embedding = vector_literal(query_embedding)
    with db_connection(settings, row_factory=dict_row) as conn:
        cursor = conn.execute(
            sql.SQL(
                """
                select
                    id::text,
                    collection,
                    source_tier,
                    source_url,
                    title,
                    content,
                    chunk_index,
                    crawled_at,
                    metadata,
                    1 - (embedding <=> %s::vector) as score
                from {}.documents
                where collection = %s
                order by embedding <=> %s::vector
                limit %s
                """
            ).format(sql.Identifier(schema)),
            (embedding, collection_name, embedding, limit),
        )
        return list(cursor.fetchall())
