from __future__ import annotations

import re
from typing import Any


GENERIC_UPDATED_SUMMARY = (
    "OpenAI 공식 문서 내용이 변경되어 official 컬렉션에 재인덱싱되었습니다. 원문을 열어 변경 내용을 확인해 주세요."
)
GENERIC_NEW_SUMMARY = "새 OpenAI 공식 문서가 수집되어 official 컬렉션에 인덱싱되었습니다."


def is_generic_official_summary(value: Any) -> bool:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text in {GENERIC_UPDATED_SUMMARY, GENERIC_NEW_SUMMARY, ""}


def _clean_markdown_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text


def _clean_line(value: str) -> str:
    line = _clean_markdown_text(value)
    line = re.sub(r"^#{1,6}\s*", "", line)
    line = re.sub(r"^[-*+]\s+", "", line)
    line = re.sub(r"^\d+[.)]\s+", "", line)
    line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
    line = re.sub(r"[_*~|]+", " ", line)
    return re.sub(r"\s+", " ", line).strip(" -–—:·")


def _split_sentences(value: str) -> list[str]:
    text = _clean_markdown_text(value)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?。！？])\s+", text)
    return [_clean_line(part) for part in parts if len(_clean_line(part)) >= 24]


def summarize_official_document_change(
    *,
    title: Any,
    content: Any = "",
    change_type: str = "updated",
) -> str:
    clean_title = _clean_line(str(title or "OpenAI 공식 문서")) or "OpenAI 공식 문서"
    clean_title = re.sub(r"\s*\|\s*OpenAI.*$", "", clean_title).strip()
    clean_title = re.sub(r"\s+OpenAI Help Center$", "", clean_title).strip() or clean_title
    title_key = clean_title.lower()
    lines = [_clean_line(line) for line in str(content or "").splitlines()]
    lines = [line for line in lines if line and line.lower() not in {"markdown content", "title"}]

    headings: list[str] = []
    for raw_line in str(content or "").splitlines():
        if not re.match(r"^\s{0,3}#{1,4}\s+\S", raw_line):
            continue
        heading = _clean_line(raw_line)
        if heading and heading.lower() != title_key and not heading.lower().startswith(f"{title_key} ") and heading not in headings:
            headings.append(heading)
        if len(headings) >= 3:
            break

    candidates = [
        line
        for line in lines
        if len(line) >= 45
        and line.lower() != title_key
        and not line.lower().startswith(f"{title_key} ")
        and not line.lower().startswith(("updated ", "last updated", "table of contents"))
        and "opens in a new window" not in line.lower()
        and line.lower() not in {"foundation", "overview", "quickstart"}
    ]
    sentence = ""
    for candidate in candidates:
        sentence = (_split_sentences(candidate) or [candidate])[0]
        if sentence:
            break

    detail_parts: list[str] = []
    if sentence:
        detail_parts.append(sentence[:180])
    if headings:
        detail_parts.append(f"주요 섹션: {', '.join(headings[:3])}")

    if not detail_parts:
        detail_parts.append(f"{clean_title} 문서의 본문과 메타데이터를 기준으로 재인덱싱했습니다.")

    prefix = "신규 문서 수집" if change_type == "new" else "문서 변경 감지"
    summary = f"{prefix}: {clean_title} - {' / '.join(detail_parts)}"
    return summary[:420]
