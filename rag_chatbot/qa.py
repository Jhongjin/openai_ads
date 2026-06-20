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
        },
        *_openai_cbt_email_source_payload(),
    ]


def _openai_cbt_email_source_payload() -> list[dict[str, Any]]:
    return [
        {
            "collection": "kr_ops",
            "score": 1.0,
            "source_tier": "kr_ops",
            "title": "OpenAI CBT 담당자 Q&A 승인 요약 (2026-06-12~2026-06-19)",
            "source_url": "internal://kr_ops/openai-cbt-email-approved-summary-2026-06-19",
            "source_updated_at": "2026-06-19",
            "source_updated_at_is_fallback": False,
            "source_tag": "openai_contact_summary",
            "trust_label": "OpenAI 담당자 커뮤니케이션 요약",
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


def _official_crawler_source_payload() -> list[dict[str, Any]]:
    return [
        {
            "collection": "official",
            "score": 1.0,
            "source_tier": "official",
            "title": "Overview of OpenAI Crawlers",
            "source_url": "https://developers.openai.com/api/docs/bots",
            "source_updated_at": "2026-06-17",
            "source_updated_at_is_fallback": True,
            "lang": "en",
        }
    ]


def _crawler_429_source_payload() -> list[dict[str, Any]]:
    return _official_crawler_source_payload() + _pending_route_source_payload()


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


def _is_crawler_429_query(question: str) -> bool:
    lowered = question.lower()
    return _contains_any(
        lowered,
        (
            "429",
            "too many requests",
            "rate limit",
            "레이트 리밋",
            "속도 제한",
        ),
    ) and _contains_any(lowered, ("크롤러", "crawler", "adsbot", "oai-adsbot", "에러", "오류", "코드"))


def _is_crawler_error_code_list_query(question: str) -> bool:
    lowered = question.lower()
    return _contains_any(
        lowered,
        ("에러코드", "에러 코드", "오류코드", "오류 코드", "상태코드", "error code", "http code"),
    ) and _contains_any(lowered, ("전체", "목록", "리스트", "종류", "전부", "모두"))


def _kr_ops_confirmed_answer(question: str) -> str | None:
    lowered = question.lower()
    is_criteo = is_criteo_query(question)
    is_direct = any(term in lowered for term in ("openai 직접", "openai", "cbt", "직접"))
    is_both_route = is_criteo and is_direct

    if _contains_any(lowered, ("account spend cap", "spend cap", "계정 spend cap", "계정 cap", "계정 캡", "계정 한도")):
        return (
            "Account Spend Cap은 계정 단위 lifetime spend cap입니다. OpenAI 팀이 설정하며 대행사나 광고주가 직접 설정할 수 없고, "
            "월 단위 cap도 아닙니다. OpenAI 담당자 커뮤니케이션 요약 기준 한국 파일럿 계정 전체에는 KRW 40,000,000이 적용됩니다. "
            "이를 초과하려는 광고주는 광고주명, 요청 한도, 캠페인 기간, 예상 집행 근거를 포함해 케이스별 검토를 요청해야 합니다. "
            "최소 집행 약정과는 별개 개념이며 베타 단계 운영값은 변동 가능성이 있습니다."
        )

    if _contains_any(lowered, ("추가 광고주", "광고주 추가", "계정 provisioning", "프로비저닝", "기존 27개사", "27개사", "tracker")):
        return (
            "기존 27개사 외 추가 광고주는 tracker에 기입한 뒤 이메일로 통보하면 OpenAI가 추가 Ads Manager 계정을 provisioning합니다."
        )

    if _contains_any(lowered, ("트래커 제출", "광고주를 트래커", "트래커에 광고주", "제출하면")) and _contains_any(
        lowered,
        ("집행 의무", "집행 필수", "의무", "필수"),
    ):
        return (
            "트래커에 광고주를 제출하는 것만으로 캠페인 집행 의무가 발생하지 않습니다. "
            "현 단계 트래커 제출은 광고주 검토, Order Form 준비, Ads Manager 계정 생성 목적이며, "
            "상업적 집행 의무는 Order Form 프로세스를 통해 별도로 처리됩니다."
        )

    if _contains_any(lowered, ("order form", "계정 접속", "계정 접근", "프로비저닝", "런칭 전", "세팅 가능")):
        return (
            "Order Form 서명 완료 후 OpenAI가 광고주 계정을 프로비저닝하고 이메일 접근 권한을 부여합니다. "
            "런칭 전에도 계정 접속과 캠페인 세팅은 가능하지만 실제 광고 노출은 한국 런칭일부터 시작됩니다."
        )

    if "슬라이드" in lowered and _contains_any(lowered, ("최소 집행", "최소 예산", "금액")):
        return '광고주 전달용 슬라이드에는 "최소 집행 약정 400만원 / 상세 조건은 영업 담당 안내" 톤으로 표기합니다. 크리테오 1,000만원 조건은 슬라이드에 직접 박지 않고 내부 영업 안내로 처리합니다.'

    if _contains_any(
        lowered,
        ("일 최소", "일예산 최소", "총예산 최소", "예산 최소값", "시스템 표기값", "krw 25,000", "25000", "25,000", "krw 1,000"),
    ):
        return (
            "Ads Manager에 보이는 예산 최소값은 일 최소 KRW 25,000 / 총예산 최소 KRW 1,000 표기값입니다. "
            "다만 OpenAI도 이 값이 의도된 정책값인지 아직 확정하지 못해 미확정으로 봐야 합니다. "
            "실무상 캠페인 예산은 이보다 훨씬 높게 설정하는 것을 권장하며, 표기값과 정책 확정 여부는 변동 가능성이 있습니다."
        )

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

    if _contains_any(lowered, ("트래킹", "픽셀", "tracker", "전환 추적", "conversion", "컨버전")):
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
            "OpenAI 인보이스는 월별 실제 집행 기준으로 다음 달 영업일 기준 7일 이내 발행됩니다. "
            "OpenAI OpCo 미국 법인 명의의 표준 PDF 인보이스이며 한국 세금계산서는 아닙니다. "
            "인보이스에는 광고주별 집행금액이 별도 라인 항목으로 포함되고, 미집행 계정에는 패널티 없이 실제 집행분만 청구됩니다."
        )

    if _contains_any(lowered, ("예산 한도", "캠페인 예산 제어", "campaign-level budget", "한도 변경")):
        return (
            "Account Spend Cap은 계정 단위 lifetime spend cap이며 OpenAI 팀이 설정합니다. 대행사·광고주가 직접 설정하는 월 단위 cap이 아닙니다. "
            "런칭 시 전 계정 한도를 상향 예정이고, 이후 캠페인 단위 예산 제어 도입 예정입니다. 상세는 추후 OpenAI 공지 대상이며 변동 가능성이 있습니다."
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

    if _contains_any(lowered, ("어드민", "관리자", "admin", "권한", "몇 명", "몇명")):
        return "한 광고 계정에 부여할 수 있는 어드민 계정 수 제한은 없습니다. 트래커에 기재된 이메일 주소 각각에 어드민 권한을 부여할 수 있습니다."

    if _contains_any(lowered, ("spend data", "집행 데이터", "실시간", "반영", "업데이트")):
        return "캠페인 라이브 후 spend data는 현재 3~5시간 간격으로 업데이트됩니다. OpenAI는 더 자주 업데이트되도록 개선 중입니다."

    if _contains_any(lowered, ("default ad url", "기본 광고 url", "기본 url")):
        return (
            "Default Ad URL은 광고그룹 레벨에서 새 광고의 랜딩 URL 기본값을 채우는 필드입니다. "
            "각 광고에서 개별 수정 가능하며, 실제 클릭 이동 URL은 개별 광고 소재에 저장된 URL입니다. 입력하지 않아도 캠페인 세팅은 진행됩니다."
        )

    if _contains_any(lowered, ("해외 타겟", "해외 타기팅", "해외 타겟팅", "locations", "국가 타겟")):
        return (
            "CBT 기간 중 한국 광고주도 해외 타겟팅 캠페인을 집행할 수 있습니다. 캠페인 레벨의 위치를 조정하면 되며, "
            "현재 광고 출시 국가는 미국, 캐나다, 호주, 뉴질랜드, 영국, 일본, 한국으로 한정됩니다."
        )

    if _contains_any(lowered, ("feed", "피드", "usd", "krw 선택", "통화")):
        return "Tools > Feed 메뉴에서 통화가 USD로만 표시되고 KRW 선택이 불가한 이슈는 현재 OpenAI 확인 요청 중인 미해결 항목입니다."

    if _contains_any(lowered, ("문제", "이슈", "문의", "헬프센터", "support", "지원", "ads-support", "ads-korea")):
        if is_criteo:
            return "크리테오 경유 운영 중 개별 이슈는 크리테오 코리아 담당자 측과 확인해 처리합니다."
        return "OpenAI 직접 운영 문제는 ChatGPT Ads 헬프센터를 참고하거나 ads-support@openai.com으로 문의하고 ads-korea@openai.com을 CC에 포함합니다. 글로벌 소통 구조라 시간이 소요될 수 있습니다."

    if _contains_any(lowered, ("런칭", "런칭일", "일정", "오픈", "출시", "정식")):
        return (
            "한국 롤아웃은 미국 PDT 기준 2026년 6월 18일 오후 1시에 시작됩니다. 시차로 계정별 실제 적용 시점은 다를 수 있습니다. "
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

    if _is_crawler_429_query(normalized):
        return {
            "answer": (
                "크롤러 응답 429는 Too Many Requests, 즉 rate limit에 걸렸다는 의미입니다. "
                "대량 업로드나 반복 검수 중 429가 발생하면 URL을 작은 배치로 나누어 분산 제출하고 시간을 두고 재시도하는 것을 권장합니다. "
                "다만 429 외 전체 크롤러 에러코드 목록은 현재 OpenAI 확인 중입니다."
            ),
            "sources": _crawler_429_source_payload(),
        }

    if _is_crawler_error_code_list_query(normalized):
        return {
            "answer": "크롤러 에러코드 전체 목록은 현재 OpenAI 확인 대기 중입니다. 확정 후 정확히 안내드리겠습니다.",
            "sources": _pending_route_source_payload(),
        }

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
