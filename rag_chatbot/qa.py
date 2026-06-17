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
            "공식 자료 기준, OpenAI 직접 광고 문구는 제목 최대 50자(16~24자 권장), "
            "설명문 최대 100자(32~48자 권장)입니다. 크리테오 경유 한글 자수는 내부운영 기준을 별도로 확인하세요."
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
            "title": "OpenAI/크리테오 확정 회신(2026-06-17)",
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
            "title": "확인 대기 항목",
            "source_url": "internal://pending/openai-ads-beta-items",
        }
    ]


def _official_text_limits_source_payload() -> list[dict[str, Any]]:
    return [
        {
            "collection": "official",
            "score": 1.0,
            "source_tier": "official",
            "title": "Create Ads for ChatGPT",
            "source_url": "https://help.openai.com/en/articles/20001212-create-ads-for-chatgpt",
            "source_updated_at": "2026-06-17",
            "source_updated_at_is_fallback": True,
            "lang": "en",
        }
    ]


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _is_general_text_limit_query(question: str) -> bool:
    lowered = question.lower()
    if not _contains_any(lowered, ("글자", "자수", "문구", "제목", "설명")):
        return False
    if _contains_any(lowered, ("최소 집행", "최소 예산", "금액")):
        return False
    if _contains_any(lowered, ("한글", "국문", "크리테오", "criteo")):
        return False
    return True


def _kr_ops_confirmed_answer(question: str) -> str | None:
    lowered = question.lower()
    is_criteo = is_criteo_query(question)
    is_direct = any(term in lowered for term in ("openai 직접", "openai", "cbt", "직접"))
    is_both_route = is_criteo and is_direct

    if "슬라이드" in lowered and _contains_any(lowered, ("최소 집행", "최소 예산", "금액")):
        return '광고주 전달용 슬라이드에는 "최소 집행 약정 400만원 / 상세 조건은 영업 담당 안내" 톤으로 표기합니다. 크리테오 1,000만원 조건은 슬라이드에 직접 박지 않고 내부 영업 안내로 처리합니다.'

    if _contains_any(lowered, ("최소 집행", "최소 예산", "minimum spend")):
        if is_both_route:
            return (
                "최소 집행금액은 경로별로 다릅니다. OpenAI 직접(CBT)은 400만원 Net 기준이며 "
                "기간 제한 없이 광고비 소진 시까지 운영됩니다. 크리테오 경유는 1,000만원 Net 기준, "
                "월 단위 구좌제로 1개월 무제한 노출 조건입니다."
            )
        if is_criteo:
            return (
                "크리테오 경유 최소 집행금액은 1,000만원 Net 기준입니다. "
                "월 단위 구좌제로 운영되며 1개월 무제한 노출 조건입니다."
            )
        if is_direct:
            return (
                "OpenAI 직접(CBT) 최소 집행금액은 400만원 Net 기준입니다. "
                "기간 제한은 없고 광고비 소진 시까지 운영됩니다."
            )
        return (
            "최소 집행금액은 경로별로 다릅니다. OpenAI 직접(CBT)은 400만원 Net 기준이며 "
            "기간 제한 없이 광고비 소진 시까지 운영됩니다. 크리테오 경유는 1,000만원 Net 기준, "
            "월 단위 구좌제로 1개월 무제한 노출 조건입니다."
        )

    if _contains_any(lowered, ("vat", "부가세", "세금", "세금id", "tax", "brn", "사업자등록")):
        return "VAT는 한국 사업자등록번호(BRN)/세금ID 제공 시 0%, 미제공 시 10%로 적용됩니다."

    if _contains_any(lowered, ("트래커", "트래킹", "픽셀", "tracker", "전환 추적", "conversion")):
        return (
            "전환 추적(트래커)은 노출/클릭 캠페인에서는 필수는 아니지만 강력 권장됩니다. "
            "향후 전환 최적화 캠페인은 전환 추적 설정이 필요합니다."
        )

    if _contains_any(lowered, ("수수료", "마크업", "fee", "commission", "호스팅", "카페24", "메이크샵")):
        return (
            "OpenAI CBT와 크리테오 경유 모두 마크업 진행이 필요합니다. "
            "크리테오는 호스팅사(카페24, 메이크샵 등) 연동 운영 시 호스팅 fee 5%가 발생합니다."
        )

    if _contains_any(lowered, ("10%", "10％", "10퍼", "십프로", "노출 제한")):
        return (
            "CBT·런칭 초기에는 한국 유저(Free&Go) 10%에게 노출 후 점진 확대됩니다. "
            "크리테오 경유도 동일하게 적용되며 예외는 없습니다."
        )

    if _contains_any(lowered, ("인벤토리", "inventory", "유저 풀", "풀 공유")):
        return (
            "OpenAI 직접과 크리테오 경유는 동일 인벤토리·유저 풀을 공유합니다. "
            "경로 간 별도 분리나 할당은 아닙니다."
        )

    if _contains_any(lowered, ("입찰", "과금", "cpc", "cpm", "bid", "billing")):
        if is_both_route:
            return (
                "입찰/과금 방식은 OpenAI CBT는 CPC·CPM 선택 가능하고 최대 입찰가 조정도 가능합니다. "
                "크리테오 경유는 CPM만 가능하며 입찰 조정은 불가합니다. 입찰 단위는 KRW입니다."
            )
        if is_criteo:
            return (
                "크리테오 경유는 CPM만 가능하며 입찰 조정은 불가합니다. 입찰 단위는 KRW입니다."
            )
        if is_direct:
            return (
                "OpenAI CBT는 CPC와 CPM을 선택할 수 있고 최대 입찰가(CPM·CPC) 조정이 가능합니다. "
                "캠페인 레벨은 예산(총액/일), 광고그룹 레벨은 CPM/CPC 최대 입찰가 단위이며 입찰 단위는 KRW입니다. "
                "최대 입찰가 상향은 노출 개선에 도움될 수 있지만 relevance-weighted, second-price auction 구조상 노출량 증가나 보장은 아닙니다."
            )
        return (
            "입찰/과금 방식은 OpenAI CBT는 CPC·CPM 선택 가능하고 최대 입찰가 조정도 가능합니다. "
            "크리테오 경유는 CPM만 가능하며 입찰 조정은 불가합니다. 입찰 단위는 KRW입니다. "
            "최대 입찰가 상향은 노출 개선에 도움될 수 있지만 노출량 증가나 보장은 아닙니다."
        )

    if _contains_any(lowered, ("인보이스", "invoice", "청구", "정산")):
        if is_criteo:
            return (
                "크리테오 인보이스 방식은 기존 크리테오 광고 상품 정산과 동일 방식 예정입니다. "
                "단, 추후 변경될 수 있습니다. 미집행 계정 페널티는 없고 실제 집행분만 청구됩니다."
            )
        return (
            "OpenAI 인보이스는 나스미디어가 광고 계정 전체를 통합해 단일 인보이스를 발행하고, "
            "인보이스 내 광고주별 집행금액을 개별 표기합니다. 실제 집행분 기준 익월 첫 영업일 7일 이내 발행되며, "
            "미집행 계정 페널티는 없고 실제 집행분만 청구됩니다."
        )

    if _contains_any(lowered, ("예산 한도", "cap", "캡", "예산 변경", "한도 변경")):
        return (
            "예산 한도(Cap)는 변경 가능하지만 OpenAI 측 별도 요청이 필요하고 시간이 소요됩니다. "
            "운영 중 확대 가능성이 있으면 사전 요청을 권장합니다."
        )

    if _contains_any(lowered, ("랜딩", "외부몰", "자사몰", "스마트스토어", "브랜드스토어", "쿠팡", "올리브영")):
        return (
            "랜딩 페이지는 자사몰과 외부몰(네이버 브랜드스토어·스마트스토어, 쿠팡, 올리브영 등) 제품 페이지 모두 허용됩니다. "
            "단, OpenAI 크롤러가 접근 가능해야 합니다. 트래커 advertiser URL은 정책 심사용으로 공식 홈페이지를 권장합니다."
        )

    if _contains_any(lowered, ("불가 업종", "제한 업종", "금융", "건강", "의료", "보험", "카드", "대출", "의약품", "건기식")):
        return (
            "금융·건강/의료는 불가 업종이나 협의 후 진행 가능한 케이스가 있어 매체 측 재확인을 권장합니다. "
            "금융은 예금/계좌, 신용카드, 보험, 자동차 대출/리스, 주택담보 대출, 투자/증권/로보어드바이저가 허용 세부 범위입니다. "
            "건강/의료는 일반의약품(OTC), 건강기능식품/영양제가 허용 세부 범위입니다."
        )

    if _contains_any(lowered, ("차이", "다른", "비교", "셀프서브", "소재 세팅", "소재세팅", "세팅", "운영 방식")) and (
        is_criteo or is_direct or "openai" in lowered
    ):
        return (
            "OpenAI 직접은 광고계정에 접근해 셀프서브로 세팅·운영하는 방식입니다. 글로벌 소통 구조라 이슈 발생 시 커뮤니케이션 시간이 오래 걸릴 수 있습니다. "
            "크리테오 경유는 캠페인 브리프와 소재를 전달하면 크리테오가 직접 세팅해 안정적으로 운영할 수 있습니다."
        )

    if _contains_any(lowered, ("문제", "이슈", "문의", "헬프센터", "support", "지원")):
        if is_criteo:
            return "크리테오 경유 운영 중 개별 이슈는 크리테오 코리아 담당자 측과 확인해 처리합니다."
        return "OpenAI 직접 운영 문제는 ChatGPT Ads 헬프센터를 참고하거나 ads-support@openai.com으로 문의합니다. 단, 글로벌 소통 구조라 시간이 소요될 수 있습니다."

    if _contains_any(lowered, ("런칭", "런칭일", "일정", "오픈", "출시", "정식")):
        return (
            "한국 런칭은 2026년 6월 18일 확정입니다. 시차로 계정별 실제 적용 시점은 다를 수 있습니다. "
            "정식 오픈은 7월 중순 예정(셀프서브)이며, 크리테오는 2026년 6월 18일 정식 런칭으로 CBT 개념은 아닙니다."
        )

    if _contains_any(lowered, ("벤치마크", "레퍼런스", "공개 사례", "평균 성과", "표준 벤치마크")):
        return "글로벌·한국 모두 초기 단계라 현재 공개 사례나 표준 벤치마크는 없습니다. 업데이트 시 추가 안내 예정입니다."

    if _contains_any(lowered, ("자수", "글자", "문자", "제목", "설명")) and (
        "한글" in lowered or "국문" in lowered or is_criteo
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

    if is_criteo:
        return (
            "크리테오 경유 확정 운영값 기준으로, 최소 집행금액은 1,000만원 Net이며 월 단위 구좌제(1개월 무제한 노출)입니다. "
            "과금은 CPM만 가능하고 입찰 조정은 불가합니다. 캠페인 브리프와 소재를 전달하면 크리테오가 직접 세팅하며, "
            "운영 중 개별 이슈는 크리테오 코리아 담당자 확인이 필요합니다."
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

    if _is_general_text_limit_query(normalized):
        return {
            "answer": (
                "공식 자료 기준, OpenAI 직접 광고 문구는 제목 최대 50자(16~24자 권장), "
                "설명문 최대 100자(32~48자 권장)입니다. 크리테오 경유 한글 자수는 내부운영 기준을 별도로 확인하세요."
            ),
            "sources": _official_text_limits_source_payload(),
        }

    confirmed_answer = _kr_ops_confirmed_answer(normalized)
    if confirmed_answer:
        return {
            "answer": confirmed_answer,
            "sources": _kr_ops_confirmed_source_payload(),
        }

    if is_criteo_query(normalized):
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
