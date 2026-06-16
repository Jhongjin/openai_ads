create schema if not exists extensions;

create extension if not exists vector with schema extensions;

create schema if not exists openai_ads_rag;

comment on schema openai_ads_rag is
  'Isolated schema for the internal ChatGPT ads RAG chatbot.';

set search_path to openai_ads_rag, public, extensions;

create table if not exists openai_ads_rag.documents (
  id uuid primary key,
  collection text not null,
  source_tier text not null,
  source_url text not null,
  title text not null,
  content text not null,
  chunk_index integer not null,
  crawled_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  embedding vector(1536) not null,
  created_at timestamptz not null default now(),
  constraint documents_collection_check
    check (collection in ('official', 'kr_ops', 'pending')),
  constraint documents_source_tier_check
    check (source_tier in ('official', 'kr_ops', 'pending'))
);

create index if not exists documents_collection_idx
  on openai_ads_rag.documents (collection);

create index if not exists documents_source_tier_idx
  on openai_ads_rag.documents (source_tier);

create index if not exists documents_embedding_hnsw_idx
  on openai_ads_rag.documents
  using hnsw (embedding vector_cosine_ops);
