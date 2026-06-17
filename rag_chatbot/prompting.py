from __future__ import annotations

from .config import SOURCE_TIER_LABELS
from .retrieval import RetrievedDocument


SYSTEM_PROMPT = """당신은 나스미디어 영업팀을 위한 사내 RAG 챗봇입니다.

목표:
- ChatGPT 광고 상품 관련 질문에 검색 근거 안에서만 답합니다.
- 정확성, 출처 표기, 미확정 항목 가드레일이 자연스러운 문장보다 우선입니다.

답변 규칙:
1. 검색 근거에 없는 내용은 추측하지 말고 "제공된 자료에서 확인할 수 없습니다."라고 답합니다.
2. 모든 핵심 주장에는 근거 출처 ID와 신뢰등급을 함께 표시합니다.
3. source_tier="official"은 OpenAI 공식 문서, source_tier="kr_ops"는 나스미디어 내부 자료, source_tier="pending"은 확인 대기 (미확정)입니다.
4. source_tier="pending" 근거는 절대 확정 정보처럼 단정하지 않습니다. 해당 항목은 "현재 OpenAI 확인 대기 중입니다"라고 답합니다.
5. 크리테오 경유 세부 질문은 "크리테오 코리아 확인 필요"로 라우팅합니다.
6. 공식 문서와 국내 운영 가이드가 충돌하는 소재 스펙/운영값은 "공식 최대값 + 국내 권장값"을 함께 답합니다.
7. 베타 단계이므로 정책·수치가 변동될 수 있음을 간결히 알립니다.
8. 한국어로 간결하게 답합니다.
"""


CRITEO_TERMS = ("크리테오", "criteo")
PENDING_QUERY_TERMS = (
    "vat",
    "부가세",
    "트래커",
    "트래킹",
    "픽셀",
    "tracker",
)
CRITEO_PENDING_TERMS = ("수수료", "fee", "commission", "포함 여부", "포함되")
CRITEO_CONFIRMED_TERMS = (
    "최소 집행",
    "최소 예산",
    "minimum spend",
    "2500",
    "2,500",
    "입찰",
    "과금",
    "cpm",
    "cpc",
    "인보이스",
    "invoice",
)
NO_DATA_QUERY_TERMS = (
    "네이버",
    "환율",
    "원화",
    "환산",
)
CPM_PRICE_INTENT_TERMS = (
    "정확",
    "단가",
    "가격",
    "얼마",
    "비용",
    "금액",
    "요금",
    "원",
    "price",
    "cost",
    "rate",
)


def tier_label(source_tier: str) -> str:
    return SOURCE_TIER_LABELS.get(source_tier, source_tier)


def is_criteo_query(question: str) -> bool:
    lowered = question.lower()
    return any(term in lowered for term in CRITEO_TERMS)


def is_criteo_pending_query(question: str) -> bool:
    lowered = question.lower()
    return is_criteo_query(question) and any(term in lowered for term in CRITEO_PENDING_TERMS)


def is_criteo_confirmed_query(question: str) -> bool:
    lowered = question.lower()
    return is_criteo_query(question) and any(
        term in lowered for term in CRITEO_CONFIRMED_TERMS
    )


def is_pending_query(question: str) -> bool:
    lowered = question.lower()
    return any(term in lowered for term in PENDING_QUERY_TERMS)


def is_no_data_query(question: str) -> bool:
    lowered = question.lower()
    if any(term in lowered for term in NO_DATA_QUERY_TERMS):
        return True
    return "cpm" in lowered and any(term in lowered for term in CPM_PRICE_INTENT_TERMS)


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
                    f"source_updated_at: {metadata.get('source_updated_at', '')}",
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
    return "제공된 자료에서 확인할 수 없습니다."


def criteo_route_answer() -> str:
    return "크리테오 경유 세부사항은 크리테오 코리아에 확인이 필요합니다."


def pending_only_answer(documents: list[RetrievedDocument]) -> str:
    return "현재 OpenAI 확인 대기 중입니다. 확정 후 정확히 안내드리겠습니다."
