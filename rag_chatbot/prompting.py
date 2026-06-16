from __future__ import annotations

from .config import SOURCE_TIER_LABELS
from .retrieval import RetrievedDocument


SYSTEM_PROMPT = """당신은 나스미디어 영업팀을 위한 사내 RAG 챗봇입니다.

목표:
- ChatGPT 광고 상품 관련 질문에 검색 근거 안에서만 답합니다.
- 정확성, 출처 표기, 미확정 항목 가드레일이 자연스러운 문장보다 우선입니다.

답변 규칙:
1. 검색 근거에 없는 내용은 추측하지 말고 "자료에 없음"이라고 답합니다.
2. 모든 핵심 주장에는 근거 출처 ID와 신뢰등급을 함께 표시합니다.
3. source_tier="official"은 ✅공식, source_tier="kr_ops"는 🟡국내운영, source_tier="pending"은 ⚠️확인대기입니다.
4. source_tier="pending" 근거는 절대 확정 정보처럼 단정하지 않습니다. 해당 항목은 "현재 OpenAI 확인 대기 중입니다"라고 답합니다.
5. 크리테오 경유 세부 질문은 "크리테오 코리아 확인 필요"로 라우팅합니다.
6. 공식 문서와 국내 운영 가이드가 충돌하는 소재 스펙/운영값은 "공식 최대값 + 국내 권장값"을 함께 답합니다.
7. 답변 말미에 반드시 "베타 단계 — 최신은 공식 페이지 재확인"을 포함합니다.
8. 한국어로 간결하게 답합니다.
"""


CRITEO_TERMS = ("크리테오", "criteo")


def tier_label(source_tier: str) -> str:
    return SOURCE_TIER_LABELS.get(source_tier, source_tier)


def is_criteo_query(question: str) -> bool:
    lowered = question.lower()
    return any(term in lowered for term in CRITEO_TERMS)


def format_context(documents: list[RetrievedDocument]) -> str:
    blocks: list[str] = []
    for index, item in enumerate(documents, start=1):
        metadata = item.document.metadata
        source_tier = item.source_tier
        blocks.append(
            "\n".join(
                [
                    f"[S{index}]",
                    f"source_tier: {source_tier}",
                    f"trust_label: {tier_label(source_tier)}",
                    f"title: {item.title}",
                    f"source_url: {item.source_url}",
                    f"crawled_at: {metadata.get('crawled_at', '')}",
                    f"relevance_score: {item.score:.4f}",
                    "content:",
                    item.document.page_content,
                ]
            )
        )
    return "\n\n---\n\n".join(blocks)


def format_source_list(documents: list[RetrievedDocument], limit: int = 6) -> str:
    lines: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for item in documents:
        key = (item.source_tier, item.title, item.source_url)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {tier_label(item.source_tier)} {item.title}: {item.source_url}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def no_data_answer() -> str:
    return (
        "자료에 없음.\n\n"
        "근거 출처와 신뢰등급: 검색된 근거 없음\n\n"
        "베타 단계 — 최신은 공식 페이지 재확인"
    )


def criteo_route_answer() -> str:
    return (
        "크리테오 경유 세부 질문은 크리테오 코리아 확인 필요합니다.\n\n"
        "근거 출처와 신뢰등급:\n"
        "- ⚠️확인대기 사내 라우팅 규칙\n\n"
        "베타 단계 — 최신은 공식 페이지 재확인"
    )


def pending_only_answer(documents: list[RetrievedDocument]) -> str:
    sources = format_source_list(documents)
    return (
        "질문하신 항목은 현재 OpenAI 확인 대기 중입니다. "
        "확정 회신 전에는 광고주 안내나 제안서에서 확정값처럼 사용하지 마세요.\n\n"
        f"근거 출처와 신뢰등급:\n{sources}\n\n"
        "베타 단계 — 최신은 공식 페이지 재확인"
    )
