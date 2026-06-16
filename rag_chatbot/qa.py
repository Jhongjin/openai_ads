from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openai import OpenAI

from .config import load_settings, require_openai_key
from .prompting import (
    SYSTEM_PROMPT,
    criteo_route_answer,
    format_context,
    is_criteo_query,
    no_data_answer,
    pending_only_answer,
)

if TYPE_CHECKING:
    from .retrieval import RetrievedDocument


def _source_payload(documents: list["RetrievedDocument"]) -> list[dict[str, Any]]:
    return [item.to_source_dict() for item in documents]


def _pending_is_best_match(documents: list["RetrievedDocument"]) -> bool:
    pending_scores = [item.score for item in documents if item.source_tier == "pending"]
    non_pending_scores = [item.score for item in documents if item.source_tier != "pending"]
    if not pending_scores:
        return False
    if not non_pending_scores:
        return True
    return max(pending_scores) > max(non_pending_scores)


def _route_source_payload() -> list[dict[str, Any]]:
    return [
        {
            "collection": "policy",
            "score": 1.0,
            "source_tier": "pending",
            "title": "사내 라우팅 규칙",
            "source_url": "internal://routing/criteo",
        }
    ]


def answer_question(question: str, *, config_path: str | None = None) -> dict[str, Any]:
    normalized = question.strip()
    if not normalized:
        return {"answer": "질문을 입력해 주세요.", "sources": []}

    if is_criteo_query(normalized):
        return {"answer": criteo_route_answer(), "sources": _route_source_payload()}

    from .retrieval import retrieve

    documents = retrieve(normalized, config_path=config_path)
    if not documents:
        return {"answer": no_data_answer(), "sources": []}

    if _pending_is_best_match(documents):
        return {
            "answer": pending_only_answer(documents),
            "sources": _source_payload(documents),
        }

    settings = load_settings()
    require_openai_key(settings)
    context = format_context(documents)
    user_prompt = f"""질문:
{normalized}

검색 근거:
{context}

위 검색 근거 안에서만 답하세요. 출처 ID(S1 등)와 신뢰등급을 핵심 주장마다 붙이세요."""

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=settings.openai_chat_model,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = response.choices[0].message.content or ""
    return {
        "answer": content,
        "sources": _source_payload(documents),
    }
