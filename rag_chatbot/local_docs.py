from __future__ import annotations

from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
import re
from typing import Iterable

from langchain_core.documents import Document

from .config import project_root, resolve_path


SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt"}


def _is_ignored(path: Path, patterns: Iterable[str]) -> bool:
    normalized = str(path).replace("\\", "/")
    name = path.name
    return any(fnmatch(name, pattern) or fnmatch(normalized, pattern) for pattern in patterns)


def _title_from_text(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
    return fallback


def iter_local_files(paths: Iterable[str], ignore_patterns: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for raw_path in paths:
        path = resolve_path(raw_path)
        if not path.exists():
            continue
        candidates = [path] if path.is_file() else list(path.rglob("*"))
        for candidate in candidates:
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            if _is_ignored(candidate, ignore_patterns):
                continue
            files.append(candidate)
    return sorted(files)


def load_local_documents(
    paths: Iterable[str],
    *,
    source_tier: str,
    ignore_patterns: Iterable[str],
) -> list[Document]:
    documents: list[Document] = []
    for path in iter_local_files(paths, ignore_patterns):
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            continue
        resolved = path.resolve()
        documents.append(
            Document(
                page_content=text.strip(),
                metadata={
                    "source_tier": source_tier,
                    "source_url": resolved.as_uri(),
                    "title": _title_from_text(text, path.stem),
                    "crawled_at": datetime.now(timezone.utc).isoformat(),
                    "local_path": str(resolved.relative_to(project_root()))
                    if resolved.is_relative_to(project_root())
                    else str(resolved),
                },
            )
        )
    return documents


def load_inline_documents(
    entries: Iterable[dict],
    *,
    source_tier: str,
) -> list[Document]:
    documents: list[Document] = []
    crawled_at = datetime.now(timezone.utc).isoformat()
    for index, entry in enumerate(entries, start=1):
        content = str(entry.get("content") or "").strip()
        if not content:
            continue
        title = str(entry.get("title") or f"{source_tier} inline document {index}")
        source_url = str(entry.get("source_url") or f"internal://{source_tier}/{index}")
        updated_at = str(entry.get("updated_at") or "").strip()
        metadata = {
            "source_tier": source_tier,
            "source_url": source_url,
            "title": title,
            "crawled_at": crawled_at,
            "inline_config": True,
            "source_identity": f"inline:{source_tier}:{source_url}",
        }
        if updated_at:
            metadata["source_updated_at"] = updated_at
            metadata["source_updated_at_is_fallback"] = False
        elif source_tier == "official":
            metadata["source_updated_at"] = crawled_at[:10]
            metadata["source_updated_at_is_fallback"] = True
        if source_tier == "official" and "help.openai.com" in source_url:
            if "/ko-kr/" in source_url:
                metadata["lang"] = "ko"
            elif "/en/" in source_url:
                metadata["lang"] = "en"
            if match := re.search(r"/articles/(\d+)", source_url):
                metadata["article_id"] = match.group(1)
        documents.append(
            Document(
                page_content=content,
                metadata=metadata,
            )
        )
    return documents
