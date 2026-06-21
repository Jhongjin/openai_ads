from __future__ import annotations

import re
from typing import Any


GENERIC_UPDATED_SUMMARY = (
    "OpenAI 공식 문서 내용이 변경되어 official 컬렉션에 재인덱싱되었습니다. 원문을 열어 변경 내용을 확인해 주세요."
)
GENERIC_NEW_SUMMARY = "새 OpenAI 공식 문서가 수집되어 official 컬렉션에 인덱싱되었습니다."


_KOREAN_TOPIC_RULES: list[tuple[tuple[str, ...], str, str, str]] = [
    (
        ("testing ads", "ads in chatgpt"),
        "ChatGPT 광고 테스트 기준",
        "광고가 ChatGPT 이용 경험에 어떤 방식으로 노출되고, 답변 품질과 무료 이용 지원에 어떤 영향을 주지 않는지 확인해야 합니다.",
        "광고주 안내 문구에서 테스트 노출 범위, 사용자 경험 영향, 베타 운영 전제 설명이 최신 기준과 맞는지 확인하세요.",
    ),
    (
        ("sso", "scim", "single sign-on"),
        "Ads Manager SSO/SCIM 설정 기준",
        "조직 인증, 사용자 프로비저닝, 권한 역할, 로그인 오류 대응 절차를 확인해야 합니다.",
        "계정 생성·초대·권한 부여 안내와 로그인 오류 대응 문구가 변경된 조직/역할 매핑 기준과 맞는지 확인하세요.",
    ),
    (
        ("product feed", "product feeds", "feed id"),
        "제품 피드 캠페인 생성 기준",
        "제품 피드 업로드, 피드 ID, 상품 필터, 동적 소재 필드 설정 기준을 확인해야 합니다.",
        "표준 캠페인 입력 기준과 제품 피드 캠페인 입력 기준이 섞이지 않도록 피드 ID, 필터, 동적 제목·이미지 필드 안내를 분리해 검토하세요.",
    ),
    (
        ("web crawler", "crawler", "robots.txt", "oai-adsbot", "oai-searchbot"),
        "OpenAI 웹 크롤러 접근 허용 기준",
        "OAI-AdsBot과 OAI-SearchBot 접근 허용, robots.txt, 방화벽 allowlist, 랜딩 차단 여부를 확인해야 합니다.",
        "랜딩 점검 결과의 robots.txt, WAF, CAPTCHA, 봇 차단 안내가 최신 user-agent 기준과 일치하는지 확인하세요.",
    ),
    (
        ("bulk upload", "schema", "spreadsheet", "workbook"),
        "벌크 업로드 스키마 점검 기준",
        "campaigns, adgroups, ads 시트의 필드명, 필수값, JSON 형식, 업로드 오류 기준을 확인해야 합니다.",
        "소재 접수 XLSX 생성 로직의 국가, 입찰가, 날짜, JSON 배열 변환 규칙이 공식 스키마와 맞는지 확인하세요.",
    ),
    (
        ("quickstart", "launch your first campaign", "create campaign"),
        "첫 캠페인 생성 절차",
        "캠페인 목표, 위치, 예산, 일정, 광고그룹, 소재 등록 흐름을 확인해야 합니다.",
        "소재 접수 화면과 수동 세팅 가이드의 캠페인→광고그룹→소재 순서, 필수 입력값, 화면 용어가 Ads Manager와 맞는지 확인하세요.",
    ),
    (
        ("frequently asked questions", "faq"),
        "Ads 운영 FAQ",
        "집행 가능 국가, 예산, 과금, 소재, 랜딩, 계정 권한 관련 운영 답변 기준을 확인해야 합니다.",
        "사용자 Q&A 답변 근거와 관리자 FAQ의 정책·운영 표현이 서로 충돌하지 않는지 확인하세요.",
    ),
    (
        ("troubleshooting", "common issues", "error"),
        "Ads Manager 문제 해결 기준",
        "캠페인 생성, 벌크 업로드, 소재 승인, 접근 권한, 추적 설정에서 발생하는 오류 대응을 확인해야 합니다.",
        "오류 메시지별 권장 조치, 담당자 확인 필요 항목, 재시도 가능 여부를 운영 안내에 반영할지 검토하세요.",
    ),
    (
        ("pixel", "event", "conversion", "measurement"),
        "픽셀과 전환 측정 기준",
        "픽셀 설치, 데이터 소스, 이벤트 코드, GTM 연동, 전환 측정 방식 변경 여부를 확인해야 합니다.",
        "픽셀 설치 가이드의 Pixel ID, head 설치 코드, 표준 이벤트·맞춤 이벤트 예시가 최신 측정 기준과 맞는지 확인하세요.",
    ),
    (
        ("api", "authentication", "endpoint"),
        "Ads API 연동 기준",
        "API 키, 인증, 요청과 응답 처리, 오류 대응, 권한 범위 변경 여부를 확인해야 합니다.",
        "관리자 API 키 관리와 성과 대시보드 호출이 변경된 인증·권한·엔드포인트 기준에 맞는지 확인하세요.",
    ),
]


_HEADING_TRANSLATIONS: list[tuple[str, str]] = [
    ("before you begin", "시작 전 준비"),
    ("how ads roles work", "Ads 권한 구조"),
    ("set up sso", "SSO 설정"),
    ("troubleshoot", "문제 해결"),
    ("campaign setup", "캠페인 설정"),
    ("ad group setup", "광고그룹 설정"),
    ("creative setup", "소재 설정"),
    ("campaign", "캠페인"),
    ("ad group", "광고그룹"),
    ("creative", "소재"),
    ("budget", "예산"),
    ("billing", "정산"),
    ("product feed", "제품 피드"),
    ("upload", "업로드"),
    ("schema", "스키마"),
    ("crawler", "크롤러 접근"),
    ("robots", "robots.txt"),
    ("faq", "FAQ"),
    ("pixel", "픽셀"),
    ("events", "이벤트"),
    ("conversion", "전환"),
]


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


def _infer_korean_topic(title: str, content: Any) -> tuple[str, str, str]:
    haystack = f"{title} {content or ''}".lower()
    for keywords, topic, detail, operations_check in _KOREAN_TOPIC_RULES:
        if any(keyword in haystack for keyword in keywords):
            return topic, detail, operations_check
    return (
        "OpenAI 공식 문서 운영 기준",
        "공식 문서의 설정 절차, 정책 기준, 운영자가 확인해야 할 변경 항목을 재검토해야 합니다.",
        "원문에서 변경된 필수 입력값, 정책 제한, 계정 권한, 운영 안내 문구가 현재 서비스 화면과 충돌하지 않는지 확인하세요.",
    )


def _translate_heading_to_korean(value: str) -> str:
    heading = _clean_line(value)
    normalized = heading.lower()
    for pattern, translated in _HEADING_TRANSLATIONS:
        if pattern in normalized:
            return translated
    if re.fullmatch(r"[A-Za-z0-9 /&:._-]+", heading):
        return "세부 설정 항목"
    return heading


def _summarize_headings_korean(headings: list[str]) -> str:
    translated: list[str] = []
    for heading in headings:
        korean = _translate_heading_to_korean(heading)
        if korean and korean not in translated:
            translated.append(korean)
        if len(translated) >= 3:
            break
    return ", ".join(translated)


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

    prefix = "신규 문서 수집" if change_type == "new" else "문서 변경 감지"
    topic, detail, operations_check = _infer_korean_topic(clean_title, content)
    heading_summary = _summarize_headings_korean(headings)
    summary = f"{prefix}: {topic}. {detail} 운영 확인: {operations_check}"
    if heading_summary:
        summary = f"{summary} 주요 확인 항목: {heading_summary}."
    return summary[:620]
