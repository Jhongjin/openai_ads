from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openai import OpenAI

from .config import load_settings, require_openai_key
from .prompting import (
    SYSTEM_PROMPT,
    criteo_route_answer,
    format_context,
    is_criteo_confirmed_query,
    is_criteo_pending_query,
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
            "글자수 제한은 경로별로 다릅니다. OpenAI 직접은 제목 최대 50자(16~24자 권장), "
            "설명 최대 100자(32~48자 권장)입니다. 크리테오 경유는 제목 30자, 설명 60자이며 국문 띄어쓰기를 포함합니다."
        )
    if any(term in lowered for term in ("모범", "best practice", "베스트", "잘 만들", "작성 팁")):
        return (
            "공식 자료 기준, ChatGPT 광고는 대화 맥락과 자연스럽게 맞아야 합니다. "
            "제목과 설명은 명확하고 구체적이며 유용하고 정확하게 작성하고, "
            "랜딩 페이지는 광고 내용과 가장 관련성 높은 목적지로 연결하세요. "
            "이미지는 광고 메시지를 뒷받침하는 단순하고 관련성 높은 소재를 권장합니다."
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
            "source_updated_at": "2026-06-17",
            "source_updated_at_is_fallback": False,
        }
    ]


def _kr_ops_confirmed_source_payload() -> list[dict[str, Any]]:
    return [
        {
            "collection": "kr_ops",
            "score": 1.0,
            "source_tier": "kr_ops",
            "title": "OpenAI·크리테오 확정 운영 회신",
            "source_url": "internal://kr_ops/openai-criteo-confirmed-2026-06",
            "source_updated_at": "2026-06-17",
            "source_updated_at_is_fallback": False,
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


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _kr_ops_confirmed_answer(question: str) -> str | None:
    lowered = question.lower()
    is_criteo = is_criteo_query(question)
    is_direct = any(term in lowered for term in ("openai 직접", "openai", "cbt", "직접"))
    is_both_route = is_criteo and is_direct

    if _contains_any(lowered, ("최소 집행", "최소 예산", "minimum spend")):
        if is_both_route:
            return (
                "최소 집행금액은 경로별로 다릅니다. OpenAI 직접(CBT)은 400만원 Net 기준이고, "
                "크리테오 경유는 캠페인별 월 기준 2,500만원입니다. "
                "크리테오 세부 수수료 등은 크리테오 코리아 확인이 필요합니다."
            )
        if is_criteo:
            return (
                "크리테오 경유 최소 집행금액은 캠페인별 월 기준 2,500만원입니다. "
                "세부 수수료 등은 크리테오 코리아 확인이 필요합니다."
            )
        if is_direct:
            return "OpenAI 직접(CBT) 최소 집행금액은 400만원이며 Net 기준입니다."
        return (
            "최소 집행금액은 경로별로 다릅니다. OpenAI 직접(CBT)은 400만원 Net 기준이고, "
            "크리테오 경유는 캠페인별 월 기준 2,500만원입니다. "
            "크리테오 세부 수수료 등은 크리테오 코리아 확인이 필요합니다."
        )

    if _contains_any(lowered, ("10%", "10％", "10퍼", "십프로", "노출 제한")):
        return (
            "한국 런칭 초기에는 전체 광고 자격 유저의 10%에게 노출 후 점진 확대됩니다. "
            "크리테오 경유 캠페인도 동일하게 적용되며 예외는 없습니다."
        )

    if _contains_any(lowered, ("인벤토리", "inventory", "유저 풀", "풀 공유")):
        return (
            "OpenAI 직접과 크리테오 경유는 동일 인벤토리·유저 풀을 공유합니다. "
            "경로 간 별도 분리나 할당은 아닙니다."
        )

    if _contains_any(lowered, ("입찰", "과금", "cpc", "cpm", "bid", "billing")):
        if is_both_route:
            return "입찰/과금 방식은 OpenAI CBT는 CPC·CPM 모두 가능하고, 크리테오 경유는 CPM만 가능합니다."
        if is_criteo:
            return (
                "크리테오 경유는 CPM만 가능합니다. "
                "세부 수수료 등은 크리테오 코리아 확인이 필요합니다."
            )
        if is_direct:
            return "OpenAI CBT는 CPC와 CPM 모두 가능합니다."
        return "입찰/과금 방식은 OpenAI CBT는 CPC·CPM 모두 가능하고, 크리테오 경유는 CPM만 가능합니다."

    if _contains_any(lowered, ("인보이스", "invoice", "청구", "정산")):
        if is_criteo:
            return (
                "크리테오 인보이스 방식은 기존 크리테오 광고 상품 정산과 동일 방식 예정입니다. "
                "단, 추후 변경될 수 있습니다. 세부 수수료 등은 크리테오 코리아 확인이 필요합니다."
            )
        return (
            "OpenAI 인보이스는 나스미디어가 광고 계정 전체를 통합해 단일 인보이스를 발행하고, "
            "인보이스 내 광고주별 집행금액을 개별 표기합니다."
        )

    if _contains_any(
        lowered,
        ("자수", "글자", "문자", "제목", "설명"),
    ):
        if is_both_route:
            return (
                "한글 소재 최대 자수는 경로별로 다릅니다. OpenAI 직접은 제목 최대 50자(16~24자 권장), "
                "설명 최대 100자(32~48자 권장)입니다. 크리테오 경유는 제목 30자, 설명 60자이며 국문 띄어쓰기를 포함합니다."
            )
        if is_criteo:
            return "크리테오 경유 한글 소재 최대 자수는 제목 30자, 설명 60자이며 국문 띄어쓰기를 포함합니다."
        if is_direct:
            return "OpenAI 직접 한글 소재는 제목 최대 50자(16~24자 권장), 설명 최대 100자(32~48자 권장)입니다."
        return (
            "한글 소재 최대 자수는 경로별로 다릅니다. OpenAI 직접은 제목 최대 50자(16~24자 권장), "
            "설명 최대 100자(32~48자 권장)입니다. 크리테오 경유는 제목 30자, 설명 60자이며 국문 띄어쓰기를 포함합니다."
        )

    return None


def answer_question(question: str, *, config_path: str | None = None) -> dict[str, Any]:
    normalized = question.strip()
    if not normalized:
        return {"answer": "질문을 입력해 주세요.", "sources": []}

    if is_pending_query(normalized):
        return {
            "answer": pending_only_answer([]),
            "sources": _pending_route_source_payload(),
        }

    if is_criteo_pending_query(normalized):
        return {
            "answer": pending_only_answer([]),
            "sources": _pending_route_source_payload(),
        }

    if is_no_data_query(normalized):
        return {"answer": no_data_answer(), "sources": []}

    confirmed_answer = _kr_ops_confirmed_answer(normalized)
    if confirmed_answer:
        return {
            "answer": confirmed_answer,
            "sources": _kr_ops_confirmed_source_payload(),
        }

    if is_criteo_query(normalized):
        if is_criteo_confirmed_query(normalized):
            return {
                "answer": criteo_route_answer(),
                "sources": _route_source_payload(),
            }
        return {"answer": criteo_route_answer(), "sources": _route_source_payload()}

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
        return {"answer": no_data_answer(), "sources": []}
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
