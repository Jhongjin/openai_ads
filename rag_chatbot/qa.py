from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openai import OpenAI

from .config import load_settings, require_openai_key
from .prompting import (
    SYSTEM_PROMPT,
    criteo_route_answer,
    format_context,
    is_criteo_query,
    is_no_data_query,
    is_pending_query,
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


def _official_template_answer(
    question: str,
    documents: list["RetrievedDocument"],
) -> str | None:
    if not any(item.source_tier == "official" for item in documents):
        return None

    lowered = question.lower()
    if "노출" in lowered and any(term in lowered for term in ("위치", "어디", "영역")):
        return (
            "공식 자료 기준, ChatGPT 광고는 관련 ChatGPT 대화 아래 영역에 노출됩니다. "
            "베타 단계이므로 실제 노출 가능 영역과 정책은 최신 공식 페이지 및 담당자 확인이 필요합니다."
        )
    if any(term in lowered for term in ("구성요소", "구성 요소", "포함", "구성")):
        return (
            "공식 자료 기준, 광고 구성요소는 광고주명, 파비콘/로고, 제목, 설명문, "
            "랜딩 페이지, 이미지 소재입니다. 베타 단계이므로 최신 공식 페이지 재확인이 필요합니다."
        )
    if "랜딩" in lowered and any(term in lowered for term in ("url", "요건", "조건", "페이지")):
        return (
            "공식 자료 기준, 랜딩 URL은 유효하고 접근 가능해야 하며, 광고 내용과 관련성이 높아야 합니다. "
            "또한 OAI-AdsBot/OAI-SearchBot 등 OpenAI 광고·검색 로봇을 차단하면 안 됩니다. "
            "UTM 같은 추적 파라미터는 목적지 URL에 직접 붙일 수 있습니다."
        )
    if "이미지" in lowered and any(term in lowered for term in ("규격", "요건", "사이즈", "크기")):
        return (
            "공식 자료 기준, 광고 이미지 URL은 공개적으로 접근 가능한 직접 PNG 또는 JPG 링크여야 하고, "
            "정사각형이며 최대 1200×1200 조건을 따릅니다. 파비콘/로고는 광고주 계정 설정에 필요한 준비물입니다."
        )
    if any(term in lowered for term in ("글자", "자수", "문구")):
        return (
            "공식 자료 기준, 광고 제목은 16~24자 권장, 최대 50자입니다. "
            "광고 설명문은 32~48자 권장, 최대 100자입니다. "
            "한글 최대 자수 환산 기준은 현재 OpenAI 확인 대기 항목입니다."
        )
    return None


def _route_source_payload() -> list[dict[str, Any]]:
    return [
        {
            "collection": "policy",
            "score": 1.0,
            "source_tier": "kr_ops",
            "title": "사내 라우팅 규칙",
            "source_url": "internal://routing/criteo",
        }
    ]


def _pending_route_source_payload() -> list[dict[str, Any]]:
    return [
        {
            "collection": "pending",
            "score": 1.0,
            "source_tier": "pending",
            "title": "확인 대기 6항목",
            "source_url": "internal://pending/openai-ads-beta-items",
        }
    ]


def answer_question(question: str, *, config_path: str | None = None) -> dict[str, Any]:
    normalized = question.strip()
    if not normalized:
        return {"answer": "질문을 입력해 주세요.", "sources": []}

    if is_criteo_query(normalized):
        return {"answer": criteo_route_answer(), "sources": _route_source_payload()}

    if is_pending_query(normalized):
        return {
            "answer": pending_only_answer([]),
            "sources": _pending_route_source_payload(),
        }

    if is_no_data_query(normalized):
        return {"answer": no_data_answer(), "sources": []}

    from .retrieval import retrieve

    documents = retrieve(normalized, config_path=config_path)
    if not documents:
        return {"answer": no_data_answer(), "sources": []}

    template_answer = _official_template_answer(normalized, documents)
    if template_answer:
        official_documents = [item for item in documents if item.source_tier == "official"]
        return {
            "answer": template_answer,
            "sources": _source_payload(official_documents or documents),
        }

    if _pending_is_best_match(documents):
        return {
            "answer": pending_only_answer(documents),
            "sources": _source_payload(documents),
        }

    settings = load_settings()
    if not settings.openai_api_key:
        return {"answer": no_data_answer(), "sources": _source_payload(documents)}
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
