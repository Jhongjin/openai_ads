from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


COLLECTION_ORDER = ("official", "kr_ops", "pending")
SOURCE_TIER_LABELS = {
    "official": "✅공식",
    "kr_ops": "🟡국내운영",
    "pending": "⚠️확인대기",
}
SOURCE_TIER_PRIORITY = {
    "official": 0,
    "kr_ops": 1,
    "pending": 2,
}


class RuntimeSettings(BaseSettings):
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL"
    )
    openai_embedding_dimensions: int = Field(
        default=1536, alias="OPENAI_EMBEDDING_DIMENSIONS"
    )
    openai_chat_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_CHAT_MODEL")
    supabase_url: str | None = Field(default=None, alias="SUPABASE_URL")
    supabase_db_url: str | None = Field(default=None, alias="SUPABASE_DB_URL")
    supabase_schema: str = Field(default="openai_ads_rag", alias="SUPABASE_SCHEMA")
    embedding_batch_size: int = Field(default=96, alias="EMBEDDING_BATCH_SIZE")
    rag_config_path: str = Field(default="config.yaml", alias="RAG_CONFIG_PATH")
    chat_api_base_url: str = Field(
        default="http://localhost:8000", alias="CHAT_API_BASE_URL"
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_settings() -> RuntimeSettings:
    root = project_root()
    load_dotenv(root / ".env", override=False)
    load_dotenv(root / ".env.local", override=False)
    return RuntimeSettings()


def resolve_path(path_value: str | Path, base_dir: Path | None = None) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (base_dir or project_root()) / path


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    settings = load_settings()
    requested = config_path or os.getenv("RAG_CONFIG_PATH") or settings.rag_config_path
    path = resolve_path(requested)
    if not path.exists():
        path = project_root() / "config.example.yaml"
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    config["_config_path"] = str(path)
    return config


def require_openai_key(settings: RuntimeSettings | None = None) -> None:
    settings = settings or load_settings()
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add a key."
        )


def require_supabase_db_url(settings: RuntimeSettings | None = None) -> None:
    settings = settings or load_settings()
    if not settings.supabase_db_url:
        raise RuntimeError(
            "SUPABASE_DB_URL is not set. Add the Supabase pooled Postgres connection "
            "string to .env or the Vercel environment variables."
        )
