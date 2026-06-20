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
from .official_changes import summarize_official_document_change


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
    kwargs = {"prepare_threshold": None}
    if row_factory is not None:
        kwargs["row_factory"] = row_factory
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
                    lang text,
                    article_id text,
                    content_hash text,
                    source_updated_at date,
                    source_updated_at_is_fallback boolean not null default false,
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
                "alter table {}.documents add column if not exists lang text"
            ).format(sql.Identifier(schema))
        )
        conn.execute(
            sql.SQL(
                "alter table {}.documents add column if not exists article_id text"
            ).format(sql.Identifier(schema))
        )
        conn.execute(
            sql.SQL(
                "alter table {}.documents add column if not exists content_hash text"
            ).format(sql.Identifier(schema))
        )
        conn.execute(
            sql.SQL(
                "alter table {}.documents add column if not exists source_updated_at date"
            ).format(sql.Identifier(schema))
        )
        conn.execute(
            sql.SQL(
                "alter table {}.documents add column if not exists source_updated_at_is_fallback "
                "boolean not null default false"
            ).format(sql.Identifier(schema))
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
        conn.execute(
            sql.SQL(
                "create index if not exists documents_source_identity_idx "
                "on {}.documents ((metadata->>'source_identity'))"
            ).format(sql.Identifier(schema))
        )
        conn.execute(
            sql.SQL(
                "create index if not exists documents_article_lang_idx "
                "on {}.documents (article_id, lang)"
            ).format(sql.Identifier(schema))
        )
        conn.execute(
            sql.SQL(
                """
                create table if not exists {}.official_guide_changes (
                    id bigserial primary key,
                    source_identity text not null,
                    article_id text,
                    lang text,
                    title text not null,
                    source_url text not null,
                    change_type text not null,
                    previous_hash text,
                    current_hash text not null,
                    previous_source_updated_at date,
                    current_source_updated_at date,
                    detected_at timestamptz not null default now(),
                    summary text not null default '',
                    metadata jsonb not null default '{{}}'::jsonb,
                    constraint official_guide_changes_type_check
                        check (change_type in ('new', 'updated')),
                    constraint official_guide_changes_identity_hash_unique
                        unique (source_identity, current_hash)
                )
                """
            ).format(sql.Identifier(schema))
        )
        conn.execute(
            sql.SQL(
                "create index if not exists official_guide_changes_detected_idx "
                "on {}.official_guide_changes (detected_at desc)"
            ).format(sql.Identifier(schema))
        )
        conn.execute(
            sql.SQL(
                "create index if not exists official_guide_changes_article_lang_idx "
                "on {}.official_guide_changes (article_id, lang)"
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


def source_hash_exists(
    *,
    collection_name: str,
    source_identity: str,
    content_hash: str,
    settings: RuntimeSettings | None = None,
) -> bool:
    settings = settings or load_settings()
    schema = _validate_schema_name(settings.supabase_schema)
    with db_connection(settings, row_factory=dict_row) as conn:
        cursor = conn.execute(
            sql.SQL(
                """
                select 1
                from {}.documents
                where collection = %s
                  and metadata->>'source_identity' = %s
                  and metadata->>'content_hash' = %s
                limit 1
                """
            ).format(sql.Identifier(schema)),
            (collection_name, source_identity, content_hash),
        )
        return cursor.fetchone() is not None


def fetch_official_source_snapshot(
    *,
    source_identity: str,
    settings: RuntimeSettings | None = None,
) -> dict[str, Any] | None:
    settings = settings or load_settings()
    schema = _validate_schema_name(settings.supabase_schema)
    with db_connection(settings, row_factory=dict_row) as conn:
        cursor = conn.execute(
            sql.SQL(
                """
                select
                    source_url,
                    title,
                    lang,
                    article_id,
                    content_hash,
                    source_updated_at,
                    metadata
                from {}.documents
                where collection = 'official'
                  and metadata->>'source_identity' = %s
                order by chunk_index asc
                limit 1
                """
            ).format(sql.Identifier(schema)),
            (source_identity,),
        )
        row = cursor.fetchone()
    return dict(row) if row else None


def record_official_guide_change(
    *,
    document: Document,
    previous: dict[str, Any] | None,
    settings: RuntimeSettings | None = None,
) -> bool:
    settings = settings or load_settings()
    schema = _validate_schema_name(settings.supabase_schema)
    metadata = dict(document.metadata)
    source_identity = str(metadata.get("source_identity") or "")
    current_hash = str(metadata.get("content_hash") or "")
    if not source_identity or not current_hash:
        return False

    change_type = "updated" if previous else "new"
    summary = summarize_official_document_change(
        title=metadata.get("title") or "Untitled",
        content=document.page_content,
        change_type=change_type,
    )
    previous_hash = previous.get("content_hash") if previous else None
    previous_updated_at = previous.get("source_updated_at") if previous else None

    with db_connection(settings) as conn:
        conn.execute(
            sql.SQL(
                """
                delete from {}.official_guide_changes
                where (%s <> '' and source_url = %s)
                   or source_identity = %s
                """
            ).format(sql.Identifier(schema)),
            (
                str(metadata.get("source_url") or ""),
                str(metadata.get("source_url") or ""),
                source_identity,
            ),
        )
        cursor = conn.execute(
            sql.SQL(
                """
                insert into {}.official_guide_changes (
                    source_identity,
                    article_id,
                    lang,
                    title,
                    source_url,
                    change_type,
                    previous_hash,
                    current_hash,
                    previous_source_updated_at,
                    current_source_updated_at,
                    summary,
                    metadata
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                on conflict (source_identity, current_hash) do nothing
                """
            ).format(sql.Identifier(schema)),
            (
                source_identity,
                metadata.get("article_id") or None,
                metadata.get("lang") or None,
                str(metadata.get("title") or "Untitled"),
                str(metadata.get("source_url") or ""),
                change_type,
                previous_hash,
                current_hash,
                previous_updated_at,
                metadata.get("source_updated_at") or None,
                summary,
                Jsonb(metadata),
            ),
        )
        return int(cursor.rowcount or 0) > 0


def delete_source_documents(
    *,
    collection_name: str,
    source_identity: str,
    source_url: str,
    settings: RuntimeSettings | None = None,
) -> None:
    settings = settings or load_settings()
    schema = _validate_schema_name(settings.supabase_schema)
    with db_connection(settings) as conn:
        conn.execute(
            sql.SQL(
                """
                delete from {}.documents
                where collection = %s
                  and (
                    metadata->>'source_identity' = %s
                    or source_url = %s
                  )
                """
            ).format(sql.Identifier(schema)),
            (collection_name, source_identity, source_url),
        )


def delete_legacy_documents(
    *,
    collection_name: str,
    settings: RuntimeSettings | None = None,
) -> int:
    settings = settings or load_settings()
    schema = _validate_schema_name(settings.supabase_schema)
    with db_connection(settings) as conn:
        cursor = conn.execute(
            sql.SQL(
                """
                delete from {}.documents
                where collection = %s
                  and not (metadata ? 'source_identity')
                """
            ).format(sql.Identifier(schema)),
            (collection_name,),
        )
        return int(cursor.rowcount or 0)


def delete_source_identity_prefix(
    *,
    collection_name: str,
    source_identity_prefix: str,
    settings: RuntimeSettings | None = None,
) -> int:
    settings = settings or load_settings()
    schema = _validate_schema_name(settings.supabase_schema)
    with db_connection(settings) as conn:
        cursor = conn.execute(
            sql.SQL(
                """
                delete from {}.documents
                where collection = %s
                  and metadata->>'source_identity' like %s
                """
            ).format(sql.Identifier(schema)),
            (collection_name, f"{source_identity_prefix}%"),
        )
        return int(cursor.rowcount or 0)


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
        source_updated_at = metadata.get("source_updated_at") or None
        source_updated_at_is_fallback = bool(
            metadata.get("source_updated_at_is_fallback") or False
        )
        rows.append(
            (
                uuid.uuid4(),
                collection_name,
                str(metadata.get("source_tier") or collection_name),
                str(metadata.get("source_url") or ""),
                str(metadata.get("title") or "Untitled"),
                chunk.page_content,
                int(metadata.get("chunk_index") or 0),
                metadata.get("lang") or None,
                metadata.get("article_id") or None,
                metadata.get("content_hash") or None,
                source_updated_at,
                source_updated_at_is_fallback,
                crawled_at,
                Jsonb(metadata),
                vector_literal(embedding),
            )
        )

    if not rows:
        return

    with db_connection(settings) as conn:
        with conn.cursor() as cursor:
            cursor.executemany(
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
                        lang,
                        article_id,
                        content_hash,
                        source_updated_at,
                        source_updated_at_is_fallback,
                        crawled_at,
                        metadata,
                        embedding
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
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
