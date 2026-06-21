from __future__ import annotations

import json
import os
import re
import uuid
from html import escape as html_escape
from html import unescape as html_unescape
from html.parser import HTMLParser
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import psycopg
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from psycopg.rows import dict_row

from rag_chatbot.config import load_settings
from rag_chatbot.db import delete_source_documents, ensure_database, insert_documents
from rag_chatbot.embeddings import embed_texts
from rag_chatbot.help_center import content_hash
from rag_chatbot.official_changes import summarize_official_document_change


KST = timezone(timedelta(hours=9))
GUIDE_LAYOUT_VERSION = 5
GUIDE_LAYOUT_FINGERPRINT = "production-guide-decks-20260620-v2"
MANUAL_RAG_COLLECTION = "kr_ops"
MANUAL_RAG_SOURCE_PREFIX = "manual-rag:"
MANUAL_RAG_SOURCE_URL_PREFIX = "internal://manual-rag/"
MANUAL_RAG_CATEGORIES = (
    "계정·런칭",
    "입찰·예산",
    "청구·세금",
    "롤아웃·인벤토리",
    "랜딩·크롤러",
    "정책·제한업종",
    "전환·권한",
    "플랫폼·지원",
)
FAQ_REFRESH_INTERVAL_HOURS = int(os.getenv("FAQ_REFRESH_INTERVAL_HOURS", "24") or "24")
FAQ_CATEGORIES: tuple[dict[str, str], ...] = (
    {"id": "account", "label": "계정·런칭"},
    {"id": "bid", "label": "입찰·예산"},
    {"id": "billing", "label": "청구·세금"},
    {"id": "rollout", "label": "롤아웃·인벤토리"},
    {"id": "landing", "label": "랜딩·크롤러"},
    {"id": "policy", "label": "정책·제한업종"},
    {"id": "measurement", "label": "전환·권한"},
    {"id": "support", "label": "플랫폼·지원"},
)
FAQ_CATEGORY_BY_LABEL = {item["label"]: item["id"] for item in FAQ_CATEGORIES}
FAQ_CATEGORY_LABELS = {item["id"]: item["label"] for item in FAQ_CATEGORIES}
QUESTION_TO_FAQ_CATEGORY = {
    "budget": "bid",
    "creative": "policy",
    "landing": "landing",
    "measurement": "measurement",
    "campaign_setup": "account",
    "policy": "policy",
    "ops": "support",
    "general": "support",
}
FAQ_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "account": ("계정", "런칭", "launch", "order form", "terms", "provision", "접근", "권한", "캠페인 생성", "campaign setup"),
    "bid": ("입찰", "예산", "bid", "budget", "spend", "cpc", "cpm", "금액", "최소 집행"),
    "billing": ("청구", "세금", "invoice", "billing", "vat", "brn", "정산", "인보이스"),
    "rollout": ("롤아웃", "인벤토리", "inventory", "criteo", "10%", "국가", "출시", "타겟"),
    "landing": ("랜딩", "url", "crawler", "크롤러", "robots", "oai-adsbot", "oai-searchbot", "방화벽", "allowlist"),
    "policy": ("정책", "제한", "업종", "심사", "승인", "거절", "소재", "이미지", "카피", "creative", "policy"),
    "measurement": ("전환", "권한", "픽셀", "pixel", "conversion", "event", "gtm", "측정", "api"),
    "support": ("지원", "플랫폼", "문의", "troubleshooting", "faq", "error", "문제", "담당자", "support", "sso", "scim"),
}
DEFAULT_OPERATING_FAQS: dict[str, list[dict[str, str]]] = {
    "account": [
        {
            "question": "Order Form 서명 후 Ads Manager 계정은 언제 접근 가능한가요?",
            "answer": "Order Form 서명 완료 후 OpenAI가 광고주 계정을 프로비저닝하고 이메일에 접근 권한을 부여합니다. 런칭 전에도 계정 접속과 캠페인 세팅은 가능하지만 실제 광고 노출은 한국 런칭일부터 시작됩니다.",
        },
        {
            "question": "트래커에 광고주를 제출하면 집행 의무가 생기나요?",
            "answer": "아닙니다. 현 단계 트래커 제출은 광고주 검토, Order Form 준비, Ads Manager 계정 생성 목적이며 상업적 집행 의무는 Order Form 프로세스를 통해 별도로 처리됩니다.",
        },
        {
            "question": "추가 광고주는 언제든 신청할 수 있나요?",
            "answer": "초기 마감 이후에도 rolling basis로 추가 제출과 검토가 가능합니다. 트래커 시트에 광고주를 추가하고 이메일로 OpenAI에 알려 계정 생성을 요청합니다.",
        },
        {
            "question": "Terms Signed 칸을 나스미디어가 직접 체크해야 하나요?",
            "answer": "별도 조치는 필요 없습니다. OpenAI가 Order Form 서명을 확인한 뒤 프로비저닝을 시작하며, Terms Signed 항목은 OpenAI 내부 확인용으로 운영됩니다.",
        },
    ],
    "bid": [
        {
            "question": "입찰가는 캠페인 단위인가요, 광고그룹 단위인가요?",
            "answer": "캠페인 단위에서는 총예산 또는 일예산을 설정하고, 광고그룹 단위에서 최대 CPC 또는 최대 CPM 입찰가를 설정합니다. 한국 계정의 입찰 통화는 KRW입니다.",
        },
        {
            "question": "CPM 최대 입찰가는 고정인가요?",
            "answer": "고정이 아닙니다. OpenAI 담당자 회신 기준 CPM 최대 입찰가는 필요에 따라 직접 조정할 수 있습니다.",
        },
        {
            "question": "입찰가를 올리면 딜리버리가 좋아지나요?",
            "answer": "최대 입찰가 상향은 딜리버리 개선에 도움이 될 수 있습니다. 다만 경매는 관련성 가중 2차가 방식이므로 노출량 증가를 보장하는 의미는 아닙니다.",
        },
        {
            "question": "Account Spend Cap은 월 기준 한도인가요?",
            "answer": "월 기준이 아니라 광고주 계정의 lifetime 지출 한도입니다. 한국 파일럿 계정은 KRW 40,000,000이 적용되며, 초과 한도는 요청 시 케이스별 검토가 필요합니다.",
        },
    ],
    "billing": [
        {
            "question": "인보이스는 언제 발행되나요?",
            "answer": "월별 실제 집행 기준으로 발행되며, 다음 달 영업일 기준 7일 이내에 발행됩니다.",
        },
        {
            "question": "미집행 광고주에게도 최소 집행금액이 청구되나요?",
            "answer": "아닙니다. 실제 집행된 금액만 청구되며, 캠페인 미집행 계정에 대한 패널티는 없습니다.",
        },
        {
            "question": "한국 세금계산서가 발행되나요?",
            "answer": "OpenAI OpCo 명의의 표준 PDF 인보이스가 발행되며, 한국 세금계산서는 아닙니다. VAT 처리는 Order Form 및 청구 프로세스 기준으로 확인합니다.",
        },
    ],
    "rollout": [
        {
            "question": "초기 10% 롤아웃은 어떤 의미인가요?",
            "answer": "한국 내 광고 노출 가능한 Free 및 Go 이용자 풀의 10%부터 시작해 단계적으로 확대한다는 의미입니다.",
        },
        {
            "question": "Criteo 경유 캠페인은 10% 제한에서 제외되나요?",
            "answer": "아닙니다. 10% 롤아웃은 Criteo 경유를 포함한 시장 내 모든 광고주에게 동일하게 적용됩니다.",
        },
    ],
    "landing": [
        {
            "question": "트래커 URL은 꼭 공식 홈페이지여야 하나요?",
            "answer": "정책 검토 용도이므로 광고주 공식 홈페이지가 이상적입니다. Ads Manager의 개별 광고 랜딩 URL은 별도로 지정할 수 있습니다.",
        },
        {
            "question": "크롤러 접근이 안 되면 어떻게 되나요?",
            "answer": "URL 설정 자체는 가능할 수 있지만, OpenAI 크롤러가 랜딩 URL에 접근할 수 있어야 광고 게재가 가능합니다. 접근 실패 시 집행이 제한됩니다.",
        },
    ],
    "policy": [
        {
            "question": "금융 서비스는 모두 제한인가요?",
            "answer": "초기 파일럿 기준 예금계좌, 신용카드, 보험, 자동차 대출/리스, 모기지, 투자/증권/로보어드바이저 등은 승인 가능 세부 카테고리로 안내되었습니다.",
        },
        {
            "question": "트래커에 등록된 광고주는 모두 승인된 건가요?",
            "answer": "아닙니다. 실제 정책 검토는 계정 프로비저닝 단계에서 진행되며, 문제가 생기면 OpenAI가 별도로 안내합니다.",
        },
    ],
    "measurement": [
        {
            "question": "Click 또는 Reach 목적에서도 전환 트래킹이 필수인가요?",
            "answer": "필수는 아니지만 강력히 권장됩니다. 향후 Conversion 최적화 캠페인은 전환 트래킹 설정이 필수입니다.",
        },
        {
            "question": "한 광고 계정에 어드민을 몇 명까지 부여할 수 있나요?",
            "answer": "제한은 없습니다. 트래커에 기재된 이메일 주소 각각에 어드민 권한을 부여할 수 있습니다.",
        },
    ],
    "support": [
        {
            "question": "집행 데이터는 실시간으로 반영되나요?",
            "answer": "현재는 3~5시간 간격으로 업데이트됩니다. OpenAI는 더 자주 업데이트되도록 개선 중입니다.",
        },
        {
            "question": "지원 문의는 어디로 보내야 하나요?",
            "answer": "ads-support@openai.com으로 문의하고 ads-korea@openai.com을 CC에 포함합니다. 광고주 측 마케터의 직접 문의도 가능합니다.",
        },
    ],
}
CAMPAIGN_INTAKE_STATUSES = {
    "ready": "대기",
    "in_progress": "진행중",
    "done": "완료",
    "canceled": "취소",
}


DEFAULT_NOTICE: dict[str, Any] = {
    "title": "📢 OpenAI 광고 집행 의뢰 안내",
    "updated_at": "2026-06-17",
    "bullets": [
        "글자수 — 제목 24자 / 설명 48자 최대, 권장 제목 16~18자 / 설명 32~36자, 크리테오 경유 제목 30자 / 설명 60자",
        "이미지 — 1:1 정사각형, 640×640~1200×1200, PNG/JPG, 공개 직접접근 링크, 로고를 메인 비주얼로 쓰지 말 것",
        "랜딩 — OpenAI 크롤러(OAI-AdsBot) 접근 허용 필수, 차단 시 노출 제한 가능",
        "청구 — 청구 통화 KRW 고정 / 시간대 Asia/Seoul",
        "문의 — 케이티나스미디어 미디어채널실 openai@nasmedia.co.kr",
    ],
    "body_html": """
<ul>
  <li><strong>글자수</strong> — 제목 24자 / 설명 48자 최대, 권장 제목 16~18자 / 설명 32~36자, 크리테오 경유 제목 30자 / 설명 60자</li>
  <li><strong>이미지</strong> — 1:1 정사각형, 640×640~1200×1200, PNG/JPG, 공개 직접접근 링크, 로고를 메인 비주얼로 쓰지 말 것</li>
  <li><strong>랜딩</strong> — OpenAI 크롤러(OAI-AdsBot) 접근 허용 필수, 차단 시 노출 제한 가능</li>
  <li><strong>청구</strong> — 청구 통화 KRW 고정 / 시간대 Asia/Seoul</li>
  <li><strong>문의</strong> — 케이티나스미디어 미디어채널실 openai@nasmedia.co.kr</li>
</ul>
""".strip(),
    "modal_background": "#ffffff",
    "source_label": "OpenAI Ads Guide 기준으로 하루 2회 최신 정보를 자동 확인·업데이트합니다.",
    "source_url": "https://help.openai.com/en/collections/20001223-chatgpt-ads",
    "enabled": True,
}

DEFAULT_SLIDE_CONTENT: dict[str, Any] = {
    "updated_at": "2026-06-17",
    "layout": {
        "version": GUIDE_LAYOUT_VERSION,
        "fingerprint": GUIDE_LAYOUT_FINGERPRINT,
        "decks": {},
    },
    "items": [
        {
            "key": "advertiser.hero.title",
            "deck": "advertiser",
            "label": "광고주 안내자료 표지 제목",
            "default": "ChatGPT 광고 집행 준비 안내",
            "value": "ChatGPT 광고 집행 준비 안내",
            "multiline": False,
        },
        {
            "key": "advertiser.hero.subtitle",
            "deck": "advertiser",
            "label": "광고주 안내자료 표지 부제",
            "default": "광고주님께서 준비해주실 항목",
            "value": "광고주님께서 준비해주실 항목",
            "multiline": False,
        },
        {
            "key": "advertiser.material.title",
            "deck": "advertiser",
            "label": "소재 준비물 슬라이드 제목",
            "default": "광고 소재 준비물",
            "value": "광고 소재 준비물",
            "multiline": False,
        },
        {
            "key": "advertiser.material.image",
            "deck": "advertiser",
            "label": "이미지 준비 기준",
            "default": "PNG/JPG, 1:1 정사각형, 최대 1200×1200, 공개 직접 접근 링크. 로고를 메인 비주얼로 쓰지 말 것",
            "value": "PNG/JPG, 1:1 정사각형, 최대 1200×1200, 공개 직접 접근 링크. 로고를 메인 비주얼로 쓰지 말 것",
            "multiline": True,
        },
        {
            "key": "advertiser.condition.minimum",
            "deck": "advertiser",
            "label": "최소 집행 약정 공개 문구",
            "default": "400만원 / 상세 조건은 영업 담당 안내",
            "value": "400만원 / 상세 조건은 영업 담당 안내",
            "multiline": False,
        },
        {
            "key": "advertiser.footer.contact",
            "deck": "advertiser",
            "label": "광고주 안내자료 문의처",
            "default": "문의처: 케이티나스미디어 미디어채널실 openai@nasmedia.co.kr",
            "value": "문의처: 케이티나스미디어 미디어채널실 openai@nasmedia.co.kr",
            "multiline": False,
        },
        {
            "key": "setup.hero.title",
            "deck": "setup",
            "label": "캠페인 세팅 가이드 표지 제목",
            "default": "광고 캠페인 세팅 가이드",
            "value": "광고 캠페인 세팅 가이드",
            "multiline": False,
        },
        {
            "key": "setup.step1.title",
            "deck": "setup",
            "label": "캠페인 만들기 슬라이드 제목",
            "default": "캠페인 만들기",
            "value": "캠페인 만들기",
            "multiline": False,
        },
        {
            "key": "setup.step2.title",
            "deck": "setup",
            "label": "광고그룹 만들기 슬라이드 제목",
            "default": "광고그룹 만들기",
            "value": "광고그룹 만들기",
            "multiline": False,
        },
        {
            "key": "setup.step3.title",
            "deck": "setup",
            "label": "광고 만들기 슬라이드 제목",
            "default": "광고 만들기",
            "value": "광고 만들기",
            "multiline": False,
        },
        {
            "key": "pixel.hero.title",
            "deck": "pixel",
            "label": "픽셀 설치 가이드 표지 제목",
            "default": "픽셀 설치 가이드",
            "value": "픽셀 설치 가이드",
            "multiline": False,
        },
        {
            "key": "pixel.head.title",
            "deck": "pixel",
            "label": "공통 설치 코드 슬라이드 제목",
            "default": "웹사이트 head에 설치",
            "value": "웹사이트 head에 설치",
            "multiline": False,
        },
        {
            "key": "pixel.gtm.title",
            "deck": "pixel",
            "label": "GTM 슬라이드 제목",
            "default": "GTM 삽입 방법",
            "value": "GTM 삽입 방법",
            "multiline": False,
        },
        {
            "key": "pixel.footer.support",
            "deck": "pixel",
            "label": "픽셀 지원 문의 문구",
            "default": "나스미디어는 GTM 기반 OpenAI Pixel 세팅을 지원합니다. 관련 문의: adso@nasmedia.co.kr",
            "value": "나스미디어는 GTM 기반 OpenAI Pixel 세팅을 지원합니다. 관련 문의: adso@nasmedia.co.kr",
            "multiline": False,
        },
    ],
    "images": [
        {"key": "campaign_step1", "deck": "setup", "label": "캠페인 만들기 화면", "default": "/images/guide/campaign_step1.png", "value": "/images/guide/campaign_step1.png"},
        {"key": "campaign_step2", "deck": "setup", "label": "광고그룹 만들기 화면", "default": "/images/guide/campaign_step2.png", "value": "/images/guide/campaign_step2.png"},
        {"key": "campaign_step3", "deck": "setup", "label": "광고 만들기 화면", "default": "/images/guide/campaign_step3.png", "value": "/images/guide/campaign_step3.png"},
        {"key": "campaign_preview", "deck": "setup", "label": "광고 소재 미리보기", "default": "/images/guide/campaign_preview.png", "value": "/images/guide/campaign_preview.png"},
        {"key": "pixel_step1_conversion_home", "deck": "pixel", "label": "전환 데이터 소스 탭", "default": "/images/guide/pixel_step1_conversion_home.png", "value": "/images/guide/pixel_step1_conversion_home.png"},
        {"key": "pixel_step2_create_source", "deck": "pixel", "label": "새 데이터 소스 모달", "default": "/images/guide/pixel_step2_create_source.png", "value": "/images/guide/pixel_step2_create_source.png"},
        {"key": "pixel_step3_setup_code", "deck": "pixel", "label": "픽셀 설정 코드", "default": "/images/guide/pixel_step3_setup_code.png", "value": "/images/guide/pixel_step3_setup_code.png"},
        {"key": "pixel_step4_create_event", "deck": "pixel", "label": "전환 이벤트 만들기", "default": "/images/guide/pixel_step4_create_event.png", "value": "/images/guide/pixel_step4_create_event.png"},
        {"key": "pixel_step5_event_code", "deck": "pixel", "label": "이벤트 코드", "default": "/images/guide/pixel_step5_event_code.png", "value": "/images/guide/pixel_step5_event_code.png"},
        {"key": "pixel_step6_event_list", "deck": "pixel", "label": "전환 이벤트 목록", "default": "/images/guide/pixel_step6_event_list.png", "value": "/images/guide/pixel_step6_event_list.png"},
        {"key": "pixel_step7_gtm_workspace", "deck": "pixel", "label": "GTM 작업공간", "default": "/images/guide/pixel_step7_gtm_workspace.png", "value": "/images/guide/pixel_step7_gtm_workspace.png"},
    ],
}


_memory_notice = DEFAULT_NOTICE.copy()
_memory_slide_content = json.loads(json.dumps(DEFAULT_SLIDE_CONTENT, ensure_ascii=False))
_memory_visits: dict[str, dict[str, Any]] = {}
_memory_visit_days: dict[str, int] = {}
_memory_visit_events: list[dict[str, Any]] = []
_memory_chat_questions: list[dict[str, Any]] = []
_memory_ads_api_keys: dict[str, dict[str, Any]] = {}
_memory_campaign_intake_ops: dict[str, dict[str, Any]] = {}
_memory_operating_faq_items: dict[str, dict[str, Any]] = {}
_memory_operating_faq_refreshed_at = ""
_db_ready = False
_faq_db_ready = False


def _is_analytics_event(page: str) -> bool:
    return str(page or "").startswith(("download:", "action:", "guide-pdf:", "dev:guide-pdf:"))


def _visit_event_type(page: str, page_label: str = "") -> str:
    page_value = str(page or "")
    label_value = str(page_label or "")
    lower_page = page_value.lower()
    download_tokens = (
        "download:",
        "action:",
        "guide-pdf:",
        "dev:guide-pdf:",
    )
    label_tokens = (
        "다운로드",
        "pdf 저장",
        "이미지 저장",
        "csv",
        "xlsx",
        "인쇄",
    )
    if lower_page.startswith(download_tokens) or any(token in label_value.lower() for token in label_tokens):
        return "download"
    return "page"


QUESTION_CATEGORY_RULES: tuple[dict[str, Any], ...] = (
    {
        "category": "budget",
        "label": "예산·입찰",
        "keywords": (
            "예산",
            "최소 집행",
            "약정",
            "spend cap",
            "account spend",
            "입찰",
            "bid",
            "cpc",
            "cpm",
            "금액",
            "청구",
        ),
    },
    {
        "category": "creative",
        "label": "소재·이미지",
        "keywords": (
            "제목",
            "설명",
            "카피",
            "이미지",
            "로고",
            "파비콘",
            "favicon",
            "문구",
            "글자",
            "사이즈",
            "규격",
        ),
    },
    {
        "category": "landing",
        "label": "랜딩·크롤러",
        "keywords": (
            "랜딩",
            "url",
            "robots",
            "crawler",
            "크롤러",
            "oai-adsbot",
            "접근",
            "차단",
            "방화벽",
        ),
    },
    {
        "category": "measurement",
        "label": "픽셀·전환",
        "keywords": (
            "픽셀",
            "pixel",
            "전환",
            "conversion",
            "gtm",
            "태그",
            "추적",
            "이벤트",
        ),
    },
    {
        "category": "campaign_setup",
        "label": "캠페인 세팅",
        "keywords": (
            "캠페인",
            "광고그룹",
            "광고 그룹",
            "소재",
            "objective",
            "목표",
            "국가",
            "위치",
            "bulk",
            "xlsx",
            "벌크",
        ),
    },
    {
        "category": "policy",
        "label": "정책·심사",
        "keywords": (
            "정책",
            "심사",
            "승인",
            "거절",
            "제한",
            "금지",
            "의료",
            "금융",
            "주류",
            "광고주",
        ),
    },
    {
        "category": "ops",
        "label": "운영·문의",
        "keywords": (
            "문의",
            "담당자",
            "계정",
            "권한",
            "정산",
            "메일",
            "요청",
            "준비",
            "운영",
        ),
    },
)


def categorize_chat_question(question: str, answer: str = "") -> dict[str, str]:
    text = f"{question or ''} {answer or ''}".lower()
    for rule in QUESTION_CATEGORY_RULES:
        if any(str(keyword).lower() in text for keyword in rule["keywords"]):
            return {"category": rule["category"], "label": rule["label"]}
    return {"category": "general", "label": "기타"}


def _faq_category_for_text(*values: Any) -> str:
    text = " ".join(str(value or "") for value in values).lower()
    scores = {
        category: sum(1 for keyword in keywords if keyword.lower() in text)
        for category, keywords in FAQ_CATEGORY_KEYWORDS.items()
    }
    category, score = max(scores.items(), key=lambda item: item[1])
    return category if score > 0 else "support"


def _faq_category_from_manual(value: Any, fallback_text: str = "") -> str:
    category_text = str(value or "").strip()
    if category_text in FAQ_CATEGORY_LABELS:
        return category_text
    if category_text in FAQ_CATEGORY_BY_LABEL:
        return FAQ_CATEGORY_BY_LABEL[category_text]
    return _faq_category_for_text(category_text, fallback_text)


def _clean_faq_text(value: Any, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit].rstrip()


def _faq_question_key(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[\[\]{}()<>\"'`~!@#$%^&*_+=|\\:;,.?/·ㆍ，。！？]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:180] or f"faq-{uuid.uuid4().hex[:12]}"


def _faq_tokens(value: Any) -> set[str]:
    tokens = re.findall(r"[가-힣A-Za-z0-9]+", str(value or "").lower())
    return {token for token in tokens if len(token) >= 2}


def _faq_similarity(left: Any, right: Any) -> float:
    left_tokens = _faq_tokens(left)
    right_tokens = _faq_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))


def _faq_datetime(value: Any = None) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _seed_faq_updated_at() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _public_faq_categories(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {item["id"]: [] for item in FAQ_CATEGORIES}
    for row in rows:
        category = str(row.get("category") or "support")
        if category not in grouped:
            category = "support"
        question = _clean_faq_text(row.get("question"), 300)
        answer = _clean_faq_text(row.get("answer"), 1200)
        if not question or not answer:
            continue
        grouped[category].append(
            {
                "q": question,
                "a": answer,
                "source_type": str(row.get("source_type") or "seed"),
                "source_summary": str(row.get("source_summary") or "").strip(),
                "updated_at": _iso_value(row.get("updated_at_utc") or row.get("source_updated_at")),
                "frequency": int(row.get("frequency") or 1),
            }
        )

    categories: list[dict[str, Any]] = []
    for category in FAQ_CATEGORIES:
        items = grouped.get(category["id"], [])[:10]
        categories.append({"id": category["id"], "label": category["label"], "items": items})
    return categories


def _default_faq_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seed_time = _seed_faq_updated_at().isoformat()
    for category in FAQ_CATEGORIES:
        category_id = category["id"]
        for index, item in enumerate(DEFAULT_OPERATING_FAQS.get(category_id, [])):
            question = item["question"]
            rows.append(
                {
                    "id": f"seed-{category_id}-{index + 1}",
                    "category": category_id,
                    "category_label": category["label"],
                    "question_key": _faq_question_key(question),
                    "question": question,
                    "answer": item["answer"],
                    "source_type": "seed",
                    "source_ref": "internal://default-operating-faq",
                    "source_summary": "기본 운영 FAQ",
                    "frequency": 1,
                    "status": "active",
                    "source_updated_at": seed_time,
                    "updated_at_utc": seed_time,
                }
            )
    return rows


def _default_faq_response(storage: dict[str, str] | None = None) -> dict[str, Any]:
    rows = list(_memory_operating_faq_items.values()) or _default_faq_rows()
    return {
        "ok": True,
        "categories": _public_faq_categories(rows),
        "updated_at": _memory_operating_faq_refreshed_at,
        "refresh_interval_hours": FAQ_REFRESH_INTERVAL_HOURS,
        **(storage or _storage_info("memory")),
    }


def _faq_candidate(
    *,
    category: str,
    question: str,
    answer: str,
    source_type: str,
    source_ref: str,
    source_summary: str = "",
    frequency: int = 1,
    source_updated_at: Any = None,
) -> dict[str, Any] | None:
    question = _clean_faq_text(question, 300)
    answer = _clean_faq_text(answer, 1200)
    if not question or not answer:
        return None
    if category not in FAQ_CATEGORY_LABELS:
        category = _faq_category_for_text(question, answer)
    updated_at = _faq_datetime(source_updated_at)
    identity = f"{category}|{question}|{source_ref}"
    return {
        "id": f"{source_type}-{content_hash('operating-faq', identity)[:16]}",
        "category": category,
        "category_label": FAQ_CATEGORY_LABELS.get(category, FAQ_CATEGORY_LABELS["support"]),
        "question_key": _faq_question_key(question),
        "question": question,
        "answer": answer,
        "source_type": source_type,
        "source_ref": str(source_ref or "")[:500],
        "source_summary": str(source_summary or "")[:500],
        "frequency": max(1, int(frequency or 1)),
        "status": "active",
        "source_updated_at": updated_at,
        "updated_at_utc": updated_at,
    }


def _short_official_title(value: Any) -> str:
    title = re.sub(r"\s*\|\s*OpenAI.*$", "", str(value or "공식 문서")).strip()
    return title[:80] or "공식 문서"


def _manual_question(title: str) -> str:
    title = _clean_faq_text(title, 180)
    if title.endswith("?") or title.endswith("나요") or title.endswith("까요"):
        return title
    return f"{title} 기준은 어떻게 적용하나요?"


def _memory_seed_operating_faqs() -> None:
    if _memory_operating_faq_items:
        return
    for row in _default_faq_rows():
        _memory_operating_faq_items[row["id"]] = row


def _memory_refresh_operating_faqs(force: bool = False) -> dict[str, Any]:
    global _memory_operating_faq_refreshed_at
    _memory_seed_operating_faqs()
    now = datetime.now(timezone.utc)
    if _memory_operating_faq_refreshed_at and not force:
        last = _faq_datetime(_memory_operating_faq_refreshed_at)
        if now - last < timedelta(hours=FAQ_REFRESH_INTERVAL_HOURS):
            return {"ok": True, "refreshed": False, "updated_at": _memory_operating_faq_refreshed_at}

    candidates: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _memory_chat_questions:
        mapped_category = QUESTION_TO_FAQ_CATEGORY.get(str(row.get("category") or "general"), "support")
        question = str(row.get("question") or "")
        key = (mapped_category, _faq_question_key(question))
        bucket = grouped.setdefault(
            key,
            {
                "category": mapped_category,
                "question": question,
                "answer": str(row.get("answer_excerpt") or ""),
                "frequency": 0,
                "latest_at": row.get("created_at") or datetime.now(timezone.utc).isoformat(),
            },
        )
        bucket["frequency"] += 1
        latest_at = _iso_value(row.get("created_at"))
        if latest_at >= str(bucket.get("latest_at") or ""):
            bucket["latest_at"] = latest_at
            bucket["answer"] = str(row.get("answer_excerpt") or bucket["answer"])

    for item in grouped.values():
        if int(item.get("frequency") or 0) < 2:
            continue
        candidate = _faq_candidate(
            category=item["category"],
            question=item["question"],
            answer=item["answer"],
            source_type="user_question",
            source_ref="memory://chat-question",
            source_summary=f"사용자 Q&A {item['frequency']}회 문의",
            frequency=int(item["frequency"]),
            source_updated_at=item.get("latest_at"),
        )
        if candidate:
            candidates.append(candidate)

    for candidate in candidates:
        existing_key = None
        for item_id, existing in _memory_operating_faq_items.items():
            if existing.get("category") != candidate["category"]:
                continue
            if existing.get("question_key") == candidate["question_key"] or _faq_similarity(existing.get("question"), candidate["question"]) >= 0.58:
                existing_key = item_id
                break
        if existing_key:
            _memory_operating_faq_items[existing_key].update(candidate, id=existing_key)
        else:
            _memory_operating_faq_items[candidate["id"]] = candidate

    _memory_operating_faq_refreshed_at = now.isoformat()
    return {"ok": True, "refreshed": True, "candidate_count": len(candidates), "updated_at": _memory_operating_faq_refreshed_at}


MAIL_REVIEW_STATUSES = {
    "needs_review": "검토 필요",
    "approved_for_rag": "RAG 반영 승인",
    "hold": "보류",
    "rejected": "제외",
    "superseded": "이전 내용 대체",
}

_SAFE_STYLE_NAMES = {"color", "background-color", "font-size"}
_SAFE_CLASSES = {"ql-size-small", "ql-size-large", "ql-size-huge"}
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")
_RGB_COLOR_RE = re.compile(
    r"^rgba?\(\s*(?:25[0-5]|2[0-4]\d|1?\d?\d)\s*,\s*"
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)\s*,\s*"
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"
    r"(?:\s*,\s*(?:0|1|0?\.\d+))?\s*\)$"
)
_FONT_SIZE_RE = re.compile(r"^(?:1[0-9]|2[0-8])px$")


def _is_safe_css_color(value: str) -> bool:
    stripped = str(value or "").strip()
    return bool(_HEX_COLOR_RE.match(stripped) or _RGB_COLOR_RE.match(stripped))


def _sanitize_inline_style(value: str | None) -> str:
    safe: list[str] = []
    for item in str(value or "").split(";"):
        if ":" not in item:
            continue
        name, raw = item.split(":", 1)
        name = name.strip().lower()
        raw = raw.strip()
        if name not in _SAFE_STYLE_NAMES:
            continue
        if name in {"color", "background-color"} and not _is_safe_css_color(raw):
            continue
        if name == "font-size" and not _FONT_SIZE_RE.match(raw):
            continue
        safe.append(f"{name}: {raw}")
    return "; ".join(safe)


def _sanitize_hex_color(value: Any, fallback: str = "#ffffff") -> str:
    raw = str(value or "").strip()
    return raw if _HEX_COLOR_RE.match(raw) else fallback


class _NoticeHtmlSanitizer(HTMLParser):
    _allowed_tags = {
        "p",
        "br",
        "hr",
        "strong",
        "b",
        "em",
        "i",
        "u",
        "s",
        "strike",
        "ul",
        "ol",
        "li",
        "a",
        "span",
        "h2",
        "blockquote",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in self._allowed_tags:
            return
        if tag in {"br", "hr"}:
            self.parts.append(f"<{tag}>")
            return
        safe_attrs: list[str] = []
        for name, value in attrs:
            attr_name = name.lower()
            if attr_name == "class" and value:
                classes = [item for item in str(value).split() if item in _SAFE_CLASSES]
                if classes:
                    safe_attrs.append(f'class="{html_escape(" ".join(classes), quote=True)}"')
            elif attr_name == "style" and value:
                style = _sanitize_inline_style(value)
                if style:
                    safe_attrs.append(f'style="{html_escape(style, quote=True)}"')
        attr_text = (" " + " ".join(safe_attrs)) if safe_attrs else ""
        if tag == "a":
            href = ""
            for name, value in attrs:
                if name.lower() == "href" and value and re.match(r"^(https?://|mailto:)", value.strip(), re.I):
                    href = html_escape(value.strip(), quote=True)
                    break
            if href:
                self.parts.append(f'<a href="{href}" target="_blank" rel="noreferrer"{attr_text}>')
            else:
                self.parts.append(f"<a{attr_text}>")
            return
        self.parts.append(f"<{tag}{attr_text}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._allowed_tags and tag not in {"br", "hr"}:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(html_escape(data))

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")


def _sanitize_notice_html(value: str) -> str:
    parser = _NoticeHtmlSanitizer()
    parser.feed(value or "")
    html = "".join(parser.parts).strip()
    return html or DEFAULT_NOTICE["body_html"]


def _bullets_to_html(bullets: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{html_escape(item)}</li>" for item in bullets if item) + "</ul>"


def _html_to_lines(value: str) -> list[str]:
    text = re.sub(r"</(li|p)>", "\n", value or "", flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return [line.strip() for line in html_unescape(text).splitlines() if line.strip()]


def _today_kst() -> str:
    return datetime.now(KST).date().isoformat()


def _iso_value(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value or "")


def _clean_date_filter(value: Any) -> str:
    text = str(value or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return ""
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return ""
    return text


def _parse_mail_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    normalized = re.sub(r"\sKST$", "+09:00", normalized)
    normalized = re.sub(r"\sUTC$", "+00:00", normalized)
    if re.match(r"^\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}[+-]\d{2}:?\d{2}$", normalized):
        normalized = normalized.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)
    except ValueError:
        pass
    for pattern in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed.replace(tzinfo=KST)
        except ValueError:
            continue
    return None


def _mail_row_recent(row: dict[str, Any], *, cutoff: datetime) -> bool:
    parsed = _parse_mail_datetime(row.get("received_at") or row.get("collected_at_kst") or row.get("approved_at"))
    if parsed is None:
        return True
    return parsed.astimezone(KST) >= cutoff


def _quote_ident(value: str) -> str:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value):
        raise ValueError("Invalid Supabase schema name.")
    return f'"{value}"'


def _storage_info(mode: str, error: str | None = None) -> dict[str, str]:
    info = {"storage": mode}
    if error:
        info["storage_error"] = error
    return info


def _analytics_period(period: str | int | None) -> dict[str, Any]:
    raw_value = str(period or "30").strip().lower()
    today = datetime.now(KST).date()
    if raw_value in {"all", "전체"}:
        return {
            "value": "all",
            "label": "전체 기간",
            "days": None,
            "start_date": "0001-01-01",
            "end_date": today.isoformat(),
        }

    try:
        days = int(raw_value)
    except ValueError:
        days = 30
    days = max(1, min(days, 365))
    start_date = today - timedelta(days=days - 1)
    return {
        "value": str(days),
        "label": f"최근 {days}일",
        "days": days,
        "start_date": start_date.isoformat(),
        "end_date": today.isoformat(),
    }


def _public_visit_item(item: dict[str, Any]) -> dict[str, Any]:
    page = str(item.get("page") or "")
    page_label = str(item.get("page_label") or page)
    event_type = str(item.get("event_type") or _visit_event_type(page, page_label))
    return {
        "page": page,
        "page_label": page_label,
        "event_type": event_type,
        "total_count": int(item.get("total_count") or item.get("period_count") or 0),
        "today_count": int(item.get("today_count") or 0),
        "today_date": str(item.get("today_date") or _today_kst()),
        "last_seen_at": _iso_value(item.get("last_seen_at")),
    }


def _split_visit_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    public_items = [_public_visit_item(item) for item in items]
    page_items = [item for item in public_items if item["event_type"] != "download"]
    download_items = [item for item in public_items if item["event_type"] == "download"]
    return page_items, download_items


def _visit_pie_items(page_items: list[dict[str, Any]], download_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    combined = sorted(
        page_items + download_items,
        key=lambda item: (-int(item.get("total_count") or 0), item.get("page_label", "")),
    )[:10]
    return [
        {
            "name": item.get("page_label") or item.get("page") or "-",
            "value": int(item.get("total_count") or 0),
            "event_type": item.get("event_type") or "page",
        }
        for item in combined
        if int(item.get("total_count") or 0) > 0
    ]


def _source_summary(sources: Any) -> str:
    if not isinstance(sources, list):
        return ""
    labels: list[str] = []
    for source in sources[:3]:
        if isinstance(source, dict):
            label = (
                source.get("title")
                or source.get("source")
                or source.get("source_label")
                or source.get("url")
                or source.get("name")
            )
        else:
            label = str(source)
        label = str(label or "").strip()
        if label:
            labels.append(label)
    return " / ".join(labels)[:300]


def _aggregate_question_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    categories: dict[str, dict[str, Any]] = {}
    for row in rows:
        category = str(row.get("category") or "general")
        category_label = str(row.get("category_label") or "기타")
        bucket = categories.setdefault(
            category,
            {
                "category": category,
                "label": category_label,
                "count": 0,
                "latest_at": "",
                "questions": {},
            },
        )
        question = re.sub(r"\s+", " ", str(row.get("question") or "")).strip()
        if not question:
            continue
        latest_at = _iso_value(row.get("created_at"))
        key = question[:180]
        item = bucket["questions"].setdefault(
            key,
            {
                "question": question,
                "count": 0,
                "latest_at": latest_at,
                "answer_excerpt": str(row.get("answer_excerpt") or ""),
                "source_summary": str(row.get("source_summary") or ""),
            },
        )
        item["count"] += 1
        if latest_at and latest_at > str(item.get("latest_at") or ""):
            item["latest_at"] = latest_at
            item["answer_excerpt"] = str(row.get("answer_excerpt") or "")
            item["source_summary"] = str(row.get("source_summary") or "")
        bucket["count"] += 1
        if latest_at and latest_at > str(bucket.get("latest_at") or ""):
            bucket["latest_at"] = latest_at

    ordered_categories = []
    for bucket in categories.values():
        questions = sorted(
            bucket["questions"].values(),
            key=lambda item: (int(item.get("count") or 0), str(item.get("latest_at") or "")),
            reverse=True,
        )[:10]
        ordered_categories.append(
            {
                "category": bucket["category"],
                "label": bucket["label"],
                "count": bucket["count"],
                "latest_at": bucket["latest_at"],
                "questions": questions,
            }
        )
    ordered_categories.sort(key=lambda item: (-int(item.get("count") or 0), str(item.get("label") or "")))
    return {"total": sum(int(item.get("count") or 0) for item in ordered_categories), "categories": ordered_categories}


def _connect():
    settings = load_settings()
    if not settings.supabase_db_url:
        raise RuntimeError("SUPABASE_DB_URL is not configured.")
    return psycopg.connect(
        settings.supabase_db_url,
        prepare_threshold=None,
        connect_timeout=5,
        options="-c statement_timeout=5000",
    )


def _mail_webhook_config() -> tuple[str, str]:
    webhook_url = os.getenv("MAIL_COLLECTOR_SHEETS_WEBHOOK_URL", "").strip()
    webhook_secret = (
        os.getenv("MAIL_COLLECTOR_SHEETS_SHARED_SECRET")
        or os.getenv("SHEETS_SHARED_SECRET")
        or ""
    ).strip()
    if not webhook_url or not webhook_secret:
        raise RuntimeError(
            "MAIL_COLLECTOR_SHEETS_WEBHOOK_URL/MAIL_COLLECTOR_SHEETS_SHARED_SECRET is not configured."
        )
    return webhook_url, webhook_secret


def _post_mail_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    webhook_url, webhook_secret = _mail_webhook_config()
    response = httpx.post(
        webhook_url,
        json={"secret": webhook_secret, **payload},
        timeout=30,
        follow_redirects=True,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("메일 검토 시트 응답 형식이 올바르지 않습니다.")
    return data


def _intake_webhook_config() -> tuple[str, str]:
    webhook_url = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
    webhook_secret = os.getenv("SHEETS_SHARED_SECRET", "").strip()
    if not webhook_url or not webhook_secret:
        raise RuntimeError("GOOGLE_SHEETS_WEBHOOK_URL/SHEETS_SHARED_SECRET is not configured.")
    return webhook_url, webhook_secret


def _post_intake_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    webhook_url, webhook_secret = _intake_webhook_config()
    response = httpx.post(
        webhook_url,
        json={"secret": webhook_secret, **payload},
        timeout=30,
        follow_redirects=True,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("접수 시트 응답 형식이 올바르지 않습니다.")
    return data


def _schema() -> str:
    return _quote_ident(load_settings().supabase_schema)


def _ensure_tables() -> None:
    global _db_ready
    if _db_ready:
        return

    schema = _schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.admin_notice (
                    id text PRIMARY KEY,
                    title text NOT NULL,
                    updated_at text NOT NULL,
                    bullets jsonb NOT NULL DEFAULT '[]'::jsonb,
                    body_html text NOT NULL DEFAULT '',
                    modal_background text NOT NULL DEFAULT '#ffffff',
                    source_label text NOT NULL,
                    source_url text NOT NULL,
                    enabled boolean NOT NULL DEFAULT true,
                    updated_at_utc timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(f"ALTER TABLE {schema}.admin_notice ADD COLUMN IF NOT EXISTS body_html text NOT NULL DEFAULT ''")
            cur.execute(
                f"ALTER TABLE {schema}.admin_notice ADD COLUMN IF NOT EXISTS modal_background text NOT NULL DEFAULT '#ffffff'"
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.admin_slide_content (
                    id text PRIMARY KEY,
                    updated_at text NOT NULL,
                    content jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                    updated_at_utc timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.page_visits (
                    page text PRIMARY KEY,
                    page_label text NOT NULL,
                    total_count bigint NOT NULL DEFAULT 0,
                    today_date text NOT NULL,
                    today_count bigint NOT NULL DEFAULT 0,
                    last_seen_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.page_visit_days (
                    visit_date text PRIMARY KEY,
                    total_count bigint NOT NULL DEFAULT 0,
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.page_visit_events (
                    id bigserial PRIMARY KEY,
                    page text NOT NULL,
                    page_label text NOT NULL,
                    event_type text NOT NULL DEFAULT 'page',
                    event_date text NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS page_visit_events_date_idx
                ON {schema}.page_visit_events (event_date DESC)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS page_visit_events_type_date_idx
                ON {schema}.page_visit_events (event_type, event_date DESC)
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.chat_question_logs (
                    id bigserial PRIMARY KEY,
                    question text NOT NULL,
                    answer_excerpt text NOT NULL DEFAULT '',
                    category text NOT NULL,
                    category_label text NOT NULL,
                    source_summary text NOT NULL DEFAULT '',
                    asked_date text NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS chat_question_logs_date_idx
                ON {schema}.chat_question_logs (asked_date DESC)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS chat_question_logs_category_date_idx
                ON {schema}.chat_question_logs (category, asked_date DESC)
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.operating_faq_items (
                    id text PRIMARY KEY,
                    category text NOT NULL,
                    category_label text NOT NULL,
                    question_key text NOT NULL,
                    question text NOT NULL,
                    answer text NOT NULL,
                    source_type text NOT NULL DEFAULT 'seed',
                    source_ref text NOT NULL DEFAULT '',
                    source_summary text NOT NULL DEFAULT '',
                    frequency integer NOT NULL DEFAULT 1,
                    status text NOT NULL DEFAULT 'active',
                    source_updated_at timestamptz NOT NULL DEFAULT now(),
                    created_at_utc timestamptz NOT NULL DEFAULT now(),
                    updated_at_utc timestamptz NOT NULL DEFAULT now(),
                    CONSTRAINT operating_faq_items_status_check
                        CHECK (status IN ('active', 'deleted')),
                    CONSTRAINT operating_faq_items_category_key_unique
                        UNIQUE (category, question_key)
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS operating_faq_items_category_updated_idx
                ON {schema}.operating_faq_items (category, status, updated_at_utc DESC)
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.operating_faq_refresh_state (
                    id text PRIMARY KEY,
                    refreshed_at_utc timestamptz NOT NULL DEFAULT now(),
                    source_summary text NOT NULL DEFAULT ''
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.official_guide_changes (
                    id bigserial PRIMARY KEY,
                    source_identity text NOT NULL,
                    article_id text,
                    lang text,
                    title text NOT NULL,
                    source_url text NOT NULL,
                    change_type text NOT NULL,
                    previous_hash text,
                    current_hash text NOT NULL,
                    previous_source_updated_at date,
                    current_source_updated_at date,
                    detected_at timestamptz NOT NULL DEFAULT now(),
                    summary text NOT NULL DEFAULT '',
                    metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                    CONSTRAINT official_guide_changes_type_check
                        CHECK (change_type IN ('new', 'updated')),
                    CONSTRAINT official_guide_changes_identity_hash_unique
                        UNIQUE (source_identity, current_hash)
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS official_guide_changes_detected_idx
                ON {schema}.official_guide_changes (detected_at DESC)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS official_guide_changes_article_lang_idx
                ON {schema}.official_guide_changes (article_id, lang)
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.admin_manual_rag_items (
                    id text PRIMARY KEY,
                    title text NOT NULL,
                    category text NOT NULL DEFAULT '',
                    source_note text NOT NULL DEFAULT '',
                    content text NOT NULL DEFAULT '',
                    status text NOT NULL DEFAULT 'active',
                    rag_source_identity text NOT NULL,
                    rag_source_url text NOT NULL,
                    created_at_utc timestamptz NOT NULL DEFAULT now(),
                    updated_at_utc timestamptz NOT NULL DEFAULT now(),
                    last_indexed_at_utc timestamptz,
                    deleted_at_utc timestamptz,
                    CONSTRAINT admin_manual_rag_status_check
                        CHECK (status IN ('active', 'deleted'))
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS admin_manual_rag_items_status_updated_idx
                ON {schema}.admin_manual_rag_items (status, updated_at_utc DESC)
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.campaign_intake_ops (
                    receipt_number text PRIMARY KEY,
                    operator_name text NOT NULL DEFAULT '',
                    status text NOT NULL DEFAULT 'ready',
                    memo text NOT NULL DEFAULT '',
                    created_at_utc timestamptz NOT NULL DEFAULT now(),
                    updated_at_utc timestamptz NOT NULL DEFAULT now(),
                    CONSTRAINT campaign_intake_ops_status_check
                        CHECK (status IN ('ready', 'in_progress', 'done', 'canceled'))
                )
                """
            )
            cur.execute(
                f"""
                ALTER TABLE {schema}.campaign_intake_ops
                DROP CONSTRAINT IF EXISTS campaign_intake_ops_status_check
                """
            )
            cur.execute(
                f"""
                ALTER TABLE {schema}.campaign_intake_ops
                ADD CONSTRAINT campaign_intake_ops_status_check
                CHECK (status IN ('ready', 'in_progress', 'done', 'canceled'))
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS campaign_intake_ops_status_updated_idx
                ON {schema}.campaign_intake_ops (status, updated_at_utc DESC)
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.ads_api_keys (
                    advertiser_name text PRIMARY KEY,
                    ads_api_key text NOT NULL DEFAULT '',
                    conversion_api_key text NOT NULL DEFAULT '',
                    enabled boolean NOT NULL DEFAULT true,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                f"""
                INSERT INTO {schema}.admin_notice
                    (id, title, updated_at, bullets, body_html, modal_background, source_label, source_url, enabled)
                VALUES
                    ('main', %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    DEFAULT_NOTICE["title"],
                    DEFAULT_NOTICE["updated_at"],
                    json.dumps(DEFAULT_NOTICE["bullets"], ensure_ascii=False),
                    DEFAULT_NOTICE["body_html"],
                    DEFAULT_NOTICE["modal_background"],
                    DEFAULT_NOTICE["source_label"],
                    DEFAULT_NOTICE["source_url"],
                    DEFAULT_NOTICE["enabled"],
                ),
            )
            cur.execute(
                f"""
                UPDATE {schema}.admin_notice
                SET body_html = %s
                WHERE id = 'main' AND COALESCE(body_html, '') = ''
                """,
                (DEFAULT_NOTICE["body_html"],),
            )
            cur.execute(
                f"""
                INSERT INTO {schema}.admin_slide_content
                    (id, updated_at, content)
                VALUES
                    ('main', %s, %s::jsonb)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    DEFAULT_SLIDE_CONTENT["updated_at"],
                    json.dumps(DEFAULT_SLIDE_CONTENT, ensure_ascii=False),
                ),
            )
    _db_ready = True


def _ensure_faq_tables() -> None:
    global _faq_db_ready
    if _faq_db_ready:
        return

    schema = _schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.operating_faq_items (
                    id text PRIMARY KEY,
                    category text NOT NULL,
                    category_label text NOT NULL,
                    question_key text NOT NULL,
                    question text NOT NULL,
                    answer text NOT NULL,
                    source_type text NOT NULL DEFAULT 'seed',
                    source_ref text NOT NULL DEFAULT '',
                    source_summary text NOT NULL DEFAULT '',
                    frequency integer NOT NULL DEFAULT 1,
                    status text NOT NULL DEFAULT 'active',
                    source_updated_at timestamptz NOT NULL DEFAULT now(),
                    created_at_utc timestamptz NOT NULL DEFAULT now(),
                    updated_at_utc timestamptz NOT NULL DEFAULT now(),
                    CONSTRAINT operating_faq_items_status_check
                        CHECK (status IN ('active', 'deleted')),
                    CONSTRAINT operating_faq_items_category_key_unique
                        UNIQUE (category, question_key)
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS operating_faq_items_category_updated_idx
                ON {schema}.operating_faq_items (category, status, updated_at_utc DESC)
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.operating_faq_refresh_state (
                    id text PRIMARY KEY,
                    refreshed_at_utc timestamptz NOT NULL DEFAULT now(),
                    source_summary text NOT NULL DEFAULT ''
                )
                """
            )
    _faq_db_ready = True


def get_notice_config() -> dict[str, Any]:
    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT title, updated_at, bullets, body_html, modal_background, source_label, source_url, enabled
                    FROM {schema}.admin_notice
                    WHERE id = 'main'
                    """
                )
                row = cur.fetchone()
        if not row:
            return {**DEFAULT_NOTICE, **_storage_info("memory")}
        title, updated_at, bullets, body_html, modal_background, source_label, source_url, enabled = row
        return {
            "title": title,
            "updated_at": updated_at,
            "bullets": bullets or [],
            "body_html": body_html or _bullets_to_html(bullets or []),
            "modal_background": modal_background or DEFAULT_NOTICE["modal_background"],
            "source_label": source_label,
            "source_url": source_url,
            "enabled": bool(enabled),
            **_storage_info("supabase"),
        }
    except Exception as exc:
        return {**_memory_notice, **_storage_info("memory", str(exc))}


def save_notice_config(payload: dict[str, Any]) -> dict[str, Any]:
    bullets = [
        str(item).strip()
        for item in payload.get("bullets", [])
        if str(item).strip()
    ]
    body_html = _sanitize_notice_html(str(payload.get("body_html") or ""))
    modal_background = _sanitize_hex_color(payload.get("modal_background"), DEFAULT_NOTICE["modal_background"])
    if not bullets:
        bullets = _html_to_lines(body_html) or list(DEFAULT_NOTICE["bullets"])
    notice = {
        "title": str(payload.get("title") or DEFAULT_NOTICE["title"]).strip(),
        "updated_at": _today_kst(),
        "bullets": bullets,
        "body_html": body_html,
        "modal_background": modal_background,
        "source_label": str(payload.get("source_label") or DEFAULT_NOTICE["source_label"]).strip(),
        "source_url": str(payload.get("source_url") or DEFAULT_NOTICE["source_url"]).strip(),
        "enabled": bool(payload.get("enabled", True)),
    }

    global _memory_notice
    _memory_notice = notice.copy()

    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {schema}.admin_notice
                        (id, title, updated_at, bullets, body_html, modal_background, source_label, source_url, enabled, updated_at_utc)
                    VALUES
                        ('main', %s, %s, %s::jsonb, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        updated_at = EXCLUDED.updated_at,
                        bullets = EXCLUDED.bullets,
                        body_html = EXCLUDED.body_html,
                        modal_background = EXCLUDED.modal_background,
                        source_label = EXCLUDED.source_label,
                        source_url = EXCLUDED.source_url,
                        enabled = EXCLUDED.enabled,
                        updated_at_utc = now()
                    """,
                    (
                        notice["title"],
                        notice["updated_at"],
                        json.dumps(notice["bullets"], ensure_ascii=False),
                        notice["body_html"],
                        notice["modal_background"],
                        notice["source_label"],
                        notice["source_url"],
                        notice["enabled"],
                    ),
                )
        return {**notice, **_storage_info("supabase")}
    except Exception as exc:
        return {**notice, **_storage_info("memory", str(exc))}


def _clean_slide_text(value: Any, *, multiline: bool = False, fallback: str = "") -> str:
    text = str(value if value is not None else fallback).strip()
    if multiline:
        text = re.sub(r"\r\n?", "\n", text)
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)[:1200] or fallback
    return re.sub(r"\s+", " ", text)[:300] or fallback


def _clean_slide_image_url(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if text.startswith("/images/") or re.match(r"^https?://[^\s]+$", text, re.I):
        return text[:500]
    return fallback


def _clean_slide_key(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_.:-]", "", str(value or "")).strip()[:120]


def _clean_slide_cards(value: Any) -> list[list[str]]:
    cards: list[list[str]] = []
    if not isinstance(value, list):
        return cards
    for raw_card in value[:24]:
        if not isinstance(raw_card, list):
            continue
        title = _clean_slide_text(raw_card[0] if len(raw_card) > 0 else "", fallback="새 박스 제목")[:300]
        body = _clean_slide_text(raw_card[1] if len(raw_card) > 1 else "", multiline=True, fallback="내용을 입력해 주세요.")[:1200]
        body_key = _clean_slide_key(raw_card[2] if len(raw_card) > 2 else "")
        title_key = _clean_slide_key(raw_card[3] if len(raw_card) > 3 else "")
        pills = _clean_slide_string_list(raw_card[4] if len(raw_card) > 4 else [], max_items=6)
        class_name = re.sub(r"[^a-zA-Z0-9_ -]", "", str(raw_card[5] if len(raw_card) > 5 else "")).strip()[:80]
        card_code = _clean_slide_text(raw_card[6] if len(raw_card) > 6 else "", multiline=True, fallback="")[:1600]
        cards.append([title, body, body_key, title_key, pills, class_name, card_code])
    return cards


def _clean_slide_pairs(value: Any, *, max_items: int = 32) -> list[list[str]]:
    rows: list[list[str]] = []
    if not isinstance(value, list):
        return rows
    for raw_row in value[:max_items]:
        if not isinstance(raw_row, list) or len(raw_row) < 2:
            continue
        rows.append(
            [
                _clean_slide_text(raw_row[0], fallback="")[:300],
                _clean_slide_text(raw_row[1], multiline=True, fallback="")[:1200],
            ]
        )
    return [row for row in rows if row[0] or row[1]]


def _clean_slide_string_list(value: Any, *, max_items: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        text
        for text in (_clean_slide_text(item, multiline=True, fallback="")[:800] for item in value[:max_items])
        if text
    ]


def _clean_slide_images(value: Any) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    if not isinstance(value, list):
        return images
    for raw_image in value[:12]:
        if not isinstance(raw_image, dict):
            continue
        key = _clean_slide_key(raw_image.get("key"))
        if not key:
            continue
        image: dict[str, str] = {"key": key}
        caption = _clean_slide_text(raw_image.get("caption"), fallback="")
        class_name = re.sub(r"[^a-zA-Z0-9_ -]", "", str(raw_image.get("className") or "")).strip()[:80]
        if caption:
            image["caption"] = caption
        if class_name:
            image["className"] = class_name
        images.append(image)
    return images


def _clean_slide_overview(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    columns = []
    raw_columns = value.get("columns")
    if isinstance(raw_columns, list):
        for raw_column in raw_columns[:4]:
            column = _clean_slide_string_list(raw_column, max_items=12)
            if column:
                columns.append(column)
    if not columns:
        return {}
    return {
        "title": _clean_slide_text(value.get("title"), fallback="핵심 정보"),
        "columns": columns,
    }


def _clean_slide_copy_guide(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    rows = []
    raw_rows = value.get("rows")
    if isinstance(raw_rows, list):
        for raw_row in raw_rows[:20]:
            if isinstance(raw_row, list):
                row = [_clean_slide_text(cell, multiline=True, fallback="")[:600] for cell in raw_row[:4]]
                if any(row):
                    rows.append(row)
    if not rows:
        return {}
    columns = _clean_slide_string_list(value.get("columns"), max_items=4) or ["구분", "좋은 예", "아쉬운 예"]
    return {
        "title": _clean_slide_text(value.get("title"), fallback="가이드"),
        "columns": columns,
        "rows": rows,
    }


def _clean_slide_code_blocks(value: Any) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    if not isinstance(value, list):
        return blocks
    for raw_block in value[:8]:
        if not isinstance(raw_block, dict):
            continue
        code = _clean_slide_text(raw_block.get("code"), multiline=True, fallback="")[:3000]
        if not code:
            continue
        blocks.append(
            {
                "title": _clean_slide_text(raw_block.get("title"), fallback="코드"),
                "code": code,
            }
        )
    return blocks


def _clean_slide_layout(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"version": 0, "decks": {}}
    try:
        version = int(value.get("version") or 0)
    except (TypeError, ValueError):
        version = 0
    fingerprint = re.sub(r"[^a-zA-Z0-9_.:-]", "", str(value.get("fingerprint") or "")).strip()[:120]
    raw_decks = value.get("decks", {})
    if not isinstance(raw_decks, dict):
        return {"version": version, "fingerprint": fingerprint, "decks": {}}
    decks: dict[str, Any] = {}
    for deck_key in ("advertiser", "setup", "pixel"):
        raw_deck = raw_decks.get(deck_key, {})
        if not isinstance(raw_deck, dict):
            continue
        raw_slides = raw_deck.get("slides", [])
        if not isinstance(raw_slides, list):
            continue
        slides: list[dict[str, Any]] = []
        for raw_slide in raw_slides[:40]:
            if not isinstance(raw_slide, dict):
                continue
            slide = {
                "kicker": _clean_slide_text(raw_slide.get("kicker"), fallback=""),
                "kickerKey": _clean_slide_key(raw_slide.get("kickerKey")),
                "title": _clean_slide_text(raw_slide.get("title"), fallback="새 슬라이드 제목"),
                "titleKey": _clean_slide_key(raw_slide.get("titleKey")),
                "subtitle": _clean_slide_text(raw_slide.get("subtitle"), multiline=True, fallback=""),
                "subtitleKey": _clean_slide_key(raw_slide.get("subtitleKey")),
                "callout": _clean_slide_text(raw_slide.get("callout"), multiline=True, fallback=""),
                "calloutKey": _clean_slide_key(raw_slide.get("calloutKey")),
                "footer": _clean_slide_text(raw_slide.get("footer"), fallback=""),
                "code": _clean_slide_text(raw_slide.get("code"), multiline=True, fallback="")[:1200],
                "codeKey": _clean_slide_key(raw_slide.get("codeKey")),
                "imageKey": _clean_slide_key(raw_slide.get("imageKey")),
                "imageCaption": _clean_slide_text(raw_slide.get("imageCaption"), fallback=""),
                "imageFrameClass": re.sub(r"[^a-zA-Z0-9_ -]", "", str(raw_slide.get("imageFrameClass") or "")).strip()[:80],
                "gridClass": re.sub(r"[^a-zA-Z0-9_ -]", "", str(raw_slide.get("gridClass") or "")).strip()[:80],
                "channelNote": _clean_slide_text(raw_slide.get("channelNote"), multiline=True, fallback=""),
                "note": _clean_slide_text(raw_slide.get("note"), multiline=True, fallback=""),
                "sourceNote": _clean_slide_text(raw_slide.get("sourceNote"), multiline=True, fallback=""),
                "fieldRows": _clean_slide_pairs(raw_slide.get("fieldRows")),
                "processCards": _clean_slide_pairs(raw_slide.get("processCards")),
                "eventCards": _clean_slide_pairs(raw_slide.get("eventCards")),
                "listItems": _clean_slide_string_list(raw_slide.get("listItems")),
                "images": _clean_slide_images(raw_slide.get("images")),
                "overview": _clean_slide_overview(raw_slide.get("overview")),
                "copyGuide": _clean_slide_copy_guide(raw_slide.get("copyGuide")),
                "codeBlocks": _clean_slide_code_blocks(raw_slide.get("codeBlocks")),
                "cards": _clean_slide_cards(raw_slide.get("cards")),
            }
            slides.append({key: val for key, val in slide.items() if val not in ("", [], None)})
        decks[deck_key] = {"slides": slides}
    return {"version": version, "fingerprint": fingerprint, "decks": decks}


def _merged_slide_content(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    source = payload or {}
    base = json.loads(json.dumps(DEFAULT_SLIDE_CONTENT, ensure_ascii=False))
    layout = _clean_slide_layout(source.get("layout"))
    is_current_layout = (
        layout.get("version") == GUIDE_LAYOUT_VERSION
        and layout.get("fingerprint") == GUIDE_LAYOUT_FINGERPRINT
    )
    base["layout"] = layout if is_current_layout else json.loads(
        json.dumps(DEFAULT_SLIDE_CONTENT["layout"], ensure_ascii=False)
    )
    incoming_items = {
        str(item.get("key") or ""): item
        for item in (source.get("items", []) if is_current_layout else [])
        if isinstance(item, dict)
    }
    incoming_images = {
        str(item.get("key") or ""): item
        for item in (source.get("images", []) if is_current_layout else [])
        if isinstance(item, dict)
    }

    for item in base["items"]:
        incoming = incoming_items.get(item["key"], {})
        item["value"] = _clean_slide_text(
            incoming.get("value", item.get("value")),
            multiline=bool(item.get("multiline")),
            fallback=item["default"],
        )

    base_item_keys = {str(item.get("key") or "") for item in base["items"]}
    for key, incoming in incoming_items.items():
        clean_key = re.sub(r"[^a-zA-Z0-9_.:-]", "", key).strip()[:120]
        if not clean_key or clean_key in base_item_keys:
            continue
        deck = _clean_slide_text(incoming.get("deck"), fallback="custom")[:40]
        label = _clean_slide_text(incoming.get("label"), fallback=clean_key)[:200]
        default = _clean_slide_text(incoming.get("default"), multiline=True, fallback="")[:1200]
        multiline = bool(incoming.get("multiline", False))
        base["items"].append(
            {
                "key": clean_key,
                "deck": deck,
                "label": label,
                "default": default,
                "value": _clean_slide_text(
                    incoming.get("value"),
                    multiline=multiline,
                    fallback=default,
                ),
                "multiline": multiline,
            }
        )
        base_item_keys.add(clean_key)

    for item in base["images"]:
        incoming = incoming_images.get(item["key"], {})
        item["value"] = _clean_slide_image_url(incoming.get("value", item.get("value")), item["default"])
        item["alt"] = _clean_slide_text(incoming.get("alt", item.get("alt", item["label"])), fallback=item["label"])
        item["caption"] = _clean_slide_text(
            incoming.get("caption", item.get("caption", item["label"])),
            fallback=item["label"],
        )

    base_image_keys = {str(item.get("key") or "") for item in base["images"]}
    for key, incoming in incoming_images.items():
        clean_key = re.sub(r"[^a-zA-Z0-9_.:-]", "", key).strip()[:120]
        if not clean_key or clean_key in base_image_keys:
            continue
        deck = _clean_slide_text(incoming.get("deck"), fallback="custom")[:40]
        label = _clean_slide_text(incoming.get("label"), fallback=clean_key)[:200]
        default = _clean_slide_image_url(incoming.get("default"), "")
        value = _clean_slide_image_url(incoming.get("value"), default)
        base["images"].append(
            {
                "key": clean_key,
                "deck": deck,
                "label": label,
                "default": default,
                "value": value,
                "alt": _clean_slide_text(incoming.get("alt"), fallback=label),
                "caption": _clean_slide_text(incoming.get("caption"), fallback=label),
            }
        )
        base_image_keys.add(clean_key)

    base["updated_at"] = _clean_slide_text(source.get("updated_at"), fallback=_today_kst())
    return base


def get_slide_content() -> dict[str, Any]:
    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT content, updated_at
                    FROM {schema}.admin_slide_content
                    WHERE id = 'main'
                    """
                )
                row = cur.fetchone()
        if not row:
            return {**_merged_slide_content(DEFAULT_SLIDE_CONTENT), **_storage_info("memory")}
        content, updated_at = row
        merged = _merged_slide_content(content or {})
        merged["updated_at"] = str(updated_at or merged["updated_at"])
        return {**merged, **_storage_info("supabase")}
    except Exception as exc:
        return {**_merged_slide_content(_memory_slide_content), **_storage_info("memory", str(exc))}


def save_slide_content(payload: dict[str, Any]) -> dict[str, Any]:
    content = _merged_slide_content({**payload, "updated_at": _today_kst()})

    global _memory_slide_content
    _memory_slide_content = json.loads(json.dumps(content, ensure_ascii=False))

    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {schema}.admin_slide_content
                        (id, updated_at, content, updated_at_utc)
                    VALUES
                        ('main', %s, %s::jsonb, now())
                    ON CONFLICT (id) DO UPDATE SET
                        updated_at = EXCLUDED.updated_at,
                        content = EXCLUDED.content,
                        updated_at_utc = now()
                    """,
                    (
                        content["updated_at"],
                        json.dumps(content, ensure_ascii=False),
                    ),
                )
        return {**content, **_storage_info("supabase")}
    except Exception as exc:
        return {**content, **_storage_info("memory", str(exc))}


def record_page_visit(page: str, page_label: str) -> dict[str, Any]:
    page = (page or "unknown")[:80]
    page_label = (page_label or page)[:120]
    today = _today_kst()
    event_type = _visit_event_type(page, page_label)

    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {schema}.page_visits
                        (page, page_label, total_count, today_date, today_count, last_seen_at)
                    VALUES
                        (%s, %s, 1, %s, 1, now())
                    ON CONFLICT (page) DO UPDATE SET
                        page_label = EXCLUDED.page_label,
                        total_count = {schema}.page_visits.total_count + 1,
                        today_count = CASE
                            WHEN {schema}.page_visits.today_date = EXCLUDED.today_date
                            THEN {schema}.page_visits.today_count + 1
                            ELSE 1
                        END,
                        today_date = EXCLUDED.today_date,
                        last_seen_at = now()
                    RETURNING page, page_label, total_count, today_count, today_date, last_seen_at
                    """,
                    (page, page_label, today),
                )
                row = cur.fetchone()
                cur.execute(
                    f"""
                    INSERT INTO {schema}.page_visit_events
                        (page, page_label, event_type, event_date, created_at)
                    VALUES
                        (%s, %s, %s, %s, now())
                    """,
                    (page, page_label, event_type, today),
                )
                if event_type != "download":
                    cur.execute(
                        f"""
                        INSERT INTO {schema}.page_visit_days
                            (visit_date, total_count, updated_at)
                        VALUES
                            (%s, 1, now())
                        ON CONFLICT (visit_date) DO UPDATE SET
                            total_count = {schema}.page_visit_days.total_count + 1,
                            updated_at = now()
                        """,
                        (today,),
                    )
        return {
            "page": row[0],
            "page_label": row[1],
            "total_count": row[2],
            "today_count": row[3],
            "today_date": row[4],
            "last_seen_at": row[5].isoformat() if row[5] else "",
            **_storage_info("supabase"),
        }
    except Exception as exc:
        current = _memory_visits.setdefault(
            page,
            {
                "page": page,
                "page_label": page_label,
                "total_count": 0,
                "today_count": 0,
                "today_date": today,
                "last_seen_at": "",
            },
        )
        current["page_label"] = page_label
        current["total_count"] += 1
        current["today_count"] = current["today_count"] + 1 if current["today_date"] == today else 1
        current["today_date"] = today
        current["last_seen_at"] = datetime.now(KST).isoformat()
        _memory_visit_events.append(
            {
                "page": page,
                "page_label": page_label,
                "event_type": event_type,
                "event_date": today,
                "created_at": current["last_seen_at"],
            }
        )
        del _memory_visit_events[:-5000]
        if event_type != "download":
            _memory_visit_days[today] = _memory_visit_days.get(today, 0) + 1
        return {**current, **_storage_info("memory", str(exc))}


def record_chat_question(question: str, answer: str = "", sources: Any = None) -> dict[str, Any]:
    question_text = re.sub(r"\s+", " ", str(question or "")).strip()[:500]
    if not question_text:
        return {"recorded": False, "reason": "empty_question"}
    answer_excerpt = re.sub(r"\s+", " ", str(answer or "")).strip()[:700]
    category = categorize_chat_question(question_text, answer_excerpt)
    source_summary = _source_summary(sources)
    today = _today_kst()
    created_at = datetime.now(KST).isoformat()
    record = {
        "question": question_text,
        "answer_excerpt": answer_excerpt,
        "category": category["category"],
        "category_label": category["label"],
        "source_summary": source_summary,
        "asked_date": today,
        "created_at": created_at,
    }

    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {schema}.chat_question_logs
                        (question, answer_excerpt, category, category_label, source_summary, asked_date, created_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, now())
                    """,
                    (
                        question_text,
                        answer_excerpt,
                        category["category"],
                        category["label"],
                        source_summary,
                        today,
                    ),
                )
        return {"recorded": True, **category, **_storage_info("supabase")}
    except Exception as exc:
        _memory_chat_questions.append(record)
        del _memory_chat_questions[:-1000]
        return {"recorded": True, **category, **_storage_info("memory", str(exc))}


def get_visit_analytics(period: str | int | None = "30") -> dict[str, Any]:
    period_info = _analytics_period(period)
    start_date = period_info["start_date"]
    end_date = period_info["end_date"]
    today = _today_kst()

    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT page, page_label, total_count, today_count, today_date, last_seen_at
                    FROM {schema}.page_visits
                    ORDER BY total_count DESC, page_label ASC
                    """
                )
                rows = cur.fetchall()
                cur.execute(
                    f"""
                    SELECT page, page_label, event_type, COUNT(*)::bigint AS period_count,
                        SUM(CASE WHEN event_date = %s THEN 1 ELSE 0 END)::bigint AS today_count,
                        MAX(created_at) AS last_seen_at
                    FROM {schema}.page_visit_events
                    WHERE event_date BETWEEN %s AND %s
                    GROUP BY page, page_label, event_type
                    ORDER BY period_count DESC, page_label ASC
                    """,
                    (today, start_date, end_date),
                )
                event_rows = cur.fetchall()
                cur.execute(
                    f"""
                    SELECT event_date, COUNT(*)::bigint
                    FROM {schema}.page_visit_events
                    WHERE event_type <> 'download'
                        AND event_date BETWEEN %s AND %s
                    GROUP BY event_date
                    ORDER BY event_date DESC
                    LIMIT 365
                    """,
                    (start_date, end_date),
                )
                event_series_rows = cur.fetchall()
                cur.execute(
                    f"""
                    SELECT visit_date, total_count
                    FROM {schema}.page_visit_days
                    ORDER BY visit_date DESC
                    LIMIT 365
                    """
                )
                series_rows = cur.fetchall()
                cur.execute(
                    f"""
                    SELECT category, category_label, question, answer_excerpt, source_summary, created_at
                    FROM {schema}.chat_question_logs
                    WHERE asked_date BETWEEN %s AND %s
                    ORDER BY created_at DESC
                    LIMIT 500
                    """,
                    (start_date, end_date),
                )
                question_rows = cur.fetchall()
        items = [
            {
                "page": row[0],
                "page_label": row[1],
                "event_type": _visit_event_type(row[0], row[1]),
                "total_count": row[2],
                "today_count": row[3],
                "today_date": row[4],
                "last_seen_at": row[5].isoformat() if row[5] else "",
            }
            for row in rows
        ]
        event_items = [
            {
                "page": row[0],
                "page_label": row[1],
                "event_type": row[2],
                "total_count": row[3],
                "today_count": row[4],
                "today_date": today,
                "last_seen_at": row[5].isoformat() if row[5] else "",
            }
            for row in event_rows
        ]
        if not event_items:
            event_items = items
        page_items, download_items = _split_visit_items(event_items)
        selected_series_rows = event_series_rows or series_rows
        series = [
            {"date": row[0], "total_count": row[1]}
            for row in reversed(selected_series_rows)
        ]
        question_items = [
            {
                "category": row[0],
                "category_label": row[1],
                "question": row[2],
                "answer_excerpt": row[3],
                "source_summary": row[4],
                "created_at": row[5],
            }
            for row in question_rows
        ]
        return {
            "items": items,
            "page_items": page_items,
            "download_items": download_items,
            "pie_items": _visit_pie_items(page_items, download_items),
            "series": series,
            "period": period_info,
            "questions": _aggregate_question_rows(question_items),
            **_storage_info("supabase"),
        }
    except Exception as exc:
        items = sorted(
            [_public_visit_item(item) for item in _memory_visits.values()],
            key=lambda item: (-int(item.get("total_count", 0)), item.get("page_label", "")),
        )
        period_events = [
            item
            for item in _memory_visit_events
            if start_date <= str(item.get("event_date") or "") <= end_date
        ]
        event_counts: dict[tuple[str, str, str], dict[str, Any]] = {}
        for event in period_events:
            key = (
                str(event.get("page") or ""),
                str(event.get("page_label") or ""),
                str(event.get("event_type") or _visit_event_type(event.get("page"), event.get("page_label"))),
            )
            bucket = event_counts.setdefault(
                key,
                {
                    "page": key[0],
                    "page_label": key[1],
                    "event_type": key[2],
                    "total_count": 0,
                    "today_count": 0,
                    "today_date": today,
                    "last_seen_at": "",
                },
            )
            bucket["total_count"] += 1
            if event.get("event_date") == today:
                bucket["today_count"] += 1
            created_at = str(event.get("created_at") or "")
            if created_at > str(bucket.get("last_seen_at") or ""):
                bucket["last_seen_at"] = created_at
        event_items = sorted(
            event_counts.values() or items,
            key=lambda item: (-int(item.get("total_count", 0)), item.get("page_label", "")),
        )
        page_items, download_items = _split_visit_items(event_items)
        series = [
            {"date": date, "total_count": count}
            for date, count in sorted(_memory_visit_days.items())
            if start_date <= date <= end_date
        ]
        question_items = [
            item
            for item in _memory_chat_questions
            if start_date <= str(item.get("asked_date") or "") <= end_date
        ]
        return {
            "items": items,
            "page_items": page_items,
            "download_items": download_items,
            "pie_items": _visit_pie_items(page_items, download_items),
            "series": series,
            "period": period_info,
            "questions": _aggregate_question_rows(question_items),
            **_storage_info("memory", str(exc)),
        }


def _mask_secret(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    if len(value) <= 10:
        return f"{value[:2]}...{value[-2:]}"
    return f"{value[:8]}...{value[-4:]}"


def _public_ads_api_key_row(row: dict[str, Any]) -> dict[str, Any]:
    ads_api_key = str(row.get("ads_api_key") or "")
    conversion_api_key = str(row.get("conversion_api_key") or "")
    return {
        "advertiser_name": str(row.get("advertiser_name") or ""),
        "has_ads_api_key": bool(ads_api_key),
        "masked_ads_api_key": _mask_secret(ads_api_key),
        "has_conversion_api_key": bool(conversion_api_key),
        "masked_conversion_api_key": _mask_secret(conversion_api_key),
        "enabled": bool(row.get("enabled", True)),
        "created_at": _iso_value(row.get("created_at")),
        "updated_at": _iso_value(row.get("updated_at")),
    }


def list_ads_api_keys() -> dict[str, Any]:
    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT advertiser_name, ads_api_key, conversion_api_key, enabled, created_at, updated_at
                    FROM {schema}.ads_api_keys
                    ORDER BY advertiser_name ASC
                    """
                )
                rows = cur.fetchall()
        return {
            "ok": True,
            "items": [_public_ads_api_key_row(dict(row)) for row in rows],
            **_storage_info("supabase"),
        }
    except Exception as exc:
        return {
            "ok": True,
            "items": [
                _public_ads_api_key_row(row)
                for row in sorted(_memory_ads_api_keys.values(), key=lambda item: item.get("advertiser_name", ""))
            ],
            **_storage_info("memory", str(exc)),
        }


def get_ads_api_key(advertiser_name: str) -> str:
    advertiser_name = str(advertiser_name or "").strip()
    if not advertiser_name:
        return ""
    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT ads_api_key
                    FROM {schema}.ads_api_keys
                    WHERE advertiser_name = %s AND enabled = true
                    """,
                    (advertiser_name,),
                )
                row = cur.fetchone()
        return str(row["ads_api_key"] or "") if row else ""
    except Exception:
        row = _memory_ads_api_keys.get(advertiser_name) or {}
        return str(row.get("ads_api_key") or "") if row.get("enabled", True) else ""


def upsert_ads_api_key(payload: dict[str, Any]) -> dict[str, Any]:
    advertiser_name = str(payload.get("advertiser_name") or "").strip()
    new_ads_api_key = str(payload.get("ads_api_key") or "").strip()
    new_conversion_api_key = str(payload.get("conversion_api_key") or "").strip()
    enabled = bool(payload.get("enabled", True))
    if not advertiser_name:
        raise ValueError("광고주명이 필요합니다.")

    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT advertiser_name, ads_api_key, conversion_api_key, enabled, created_at, updated_at
                    FROM {schema}.ads_api_keys
                    WHERE advertiser_name = %s
                    """,
                    (advertiser_name,),
                )
                existing = cur.fetchone()
                ads_api_key = new_ads_api_key or (existing["ads_api_key"] if existing else "")
                conversion_api_key = new_conversion_api_key or (existing["conversion_api_key"] if existing else "")
                if not ads_api_key:
                    raise ValueError("Ads API Key가 필요합니다.")
                cur.execute(
                    f"""
                    INSERT INTO {schema}.ads_api_keys
                        (advertiser_name, ads_api_key, conversion_api_key, enabled, created_at, updated_at)
                    VALUES
                        (%s, %s, %s, %s, COALESCE(%s, now()), now())
                    ON CONFLICT (advertiser_name) DO UPDATE SET
                        ads_api_key = EXCLUDED.ads_api_key,
                        conversion_api_key = EXCLUDED.conversion_api_key,
                        enabled = EXCLUDED.enabled,
                        updated_at = now()
                    RETURNING advertiser_name, ads_api_key, conversion_api_key, enabled, created_at, updated_at
                    """,
                    (
                        advertiser_name,
                        ads_api_key,
                        conversion_api_key,
                        enabled,
                        existing["created_at"] if existing else None,
                    ),
                )
                row = cur.fetchone()
        return {
            "ok": True,
            "item": _public_ads_api_key_row(dict(row)),
            **_storage_info("supabase"),
        }
    except ValueError:
        raise
    except Exception as exc:
        existing = _memory_ads_api_keys.get(advertiser_name) or {}
        ads_api_key = new_ads_api_key or str(existing.get("ads_api_key") or "")
        conversion_api_key = new_conversion_api_key or str(existing.get("conversion_api_key") or "")
        if not ads_api_key:
            raise ValueError("Ads API Key가 필요합니다.") from exc
        now = datetime.now(KST).isoformat()
        row = {
            "advertiser_name": advertiser_name,
            "ads_api_key": ads_api_key,
            "conversion_api_key": conversion_api_key,
            "enabled": enabled,
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
        }
        _memory_ads_api_keys[advertiser_name] = row
        return {
            "ok": True,
            "item": _public_ads_api_key_row(row),
            **_storage_info("memory", str(exc)),
        }


def delete_ads_api_key(advertiser_name: str) -> dict[str, Any]:
    advertiser_name = str(advertiser_name or "").strip()
    if not advertiser_name:
        raise ValueError("광고주명이 필요합니다.")
    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {schema}.ads_api_keys WHERE advertiser_name = %s",
                    (advertiser_name,),
                )
        return {"ok": True, **_storage_info("supabase")}
    except Exception as exc:
        _memory_ads_api_keys.pop(advertiser_name, None)
        return {"ok": True, **_storage_info("memory", str(exc))}


def list_official_guide_changes(
    *,
    limit: int = 15,
    page: int = 1,
    start_date: str = "",
    end_date: str = "",
) -> dict[str, Any]:
    limit = max(1, min(int(limit or 15), 15))
    try:
        page = int(page or 1)
    except (TypeError, ValueError):
        page = 1
    page = max(1, page)
    start_date = _clean_date_filter(start_date)
    end_date = _clean_date_filter(end_date)
    filters: list[str] = []
    params: list[Any] = []
    if start_date:
        filters.append("c.detected_at >= %s::date")
        params.append(start_date)
    if end_date:
        filters.append("c.detected_at < (%s::date + interval '1 day')")
        params.append(end_date)
    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    DELETE FROM {schema}.official_guide_changes older
                    USING {schema}.official_guide_changes newer
                    WHERE older.id < newer.id
                      AND (
                        (older.source_url <> '' AND older.source_url = newer.source_url)
                        OR older.source_identity = newer.source_identity
                      )
                    """
                )
                cur.execute(
                    f"""
                    SELECT COUNT(*) AS total_count
                    FROM {schema}.official_guide_changes c
                    {where_sql}
                    """,
                    tuple(params),
                )
                count_row = cur.fetchone() or {}
                total_count = int(count_row.get("total_count") or 0)
                total_pages = max(1, (total_count + limit - 1) // limit)
                page = min(page, total_pages)
                offset = (page - 1) * limit
                cur.execute(
                    f"""
                    SELECT
                        c.id,
                        c.source_identity,
                        c.article_id,
                        c.lang,
                        c.title,
                        c.source_url,
                        c.change_type,
                        c.previous_hash,
                        c.current_hash,
                        c.previous_source_updated_at,
                        c.current_source_updated_at,
                        c.detected_at,
                        c.summary,
                        (
                            SELECT d.content
                            FROM {schema}.documents d
                            WHERE d.collection = 'official'
                              AND (
                                d.metadata->>'source_identity' = c.source_identity
                                OR d.source_url = c.source_url
                              )
                            ORDER BY d.chunk_index ASC
                            LIMIT 1
                        ) AS document_content
                    FROM {schema}.official_guide_changes c
                    {where_sql}
                    ORDER BY c.detected_at DESC, c.id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (*params, limit, offset),
                )
                rows = cur.fetchall()
        items = []
        for row in rows:
            summary = summarize_official_document_change(
                title=row["title"],
                content=row.get("document_content") or "",
                change_type=row["change_type"],
            )
            items.append(
                {
                    "id": row["id"],
                    "source_identity": row["source_identity"],
                    "article_id": row["article_id"] or "",
                    "lang": (row["lang"] or "").upper(),
                    "title": row["title"],
                    "source_url": row["source_url"],
                    "change_type": row["change_type"],
                    "previous_hash": row["previous_hash"] or "",
                    "current_hash": row["current_hash"],
                    "previous_source_updated_at": _iso_value(row["previous_source_updated_at"]),
                    "current_source_updated_at": _iso_value(row["current_source_updated_at"]),
                    "detected_at": _iso_value(row["detected_at"]),
                    "summary": summary,
                }
            )
        return {
            "ok": True,
            "items": items,
            "limit": limit,
            "page": page,
            "page_size": limit,
            "total_count": total_count,
            "total_pages": total_pages,
            "has_previous": page > 1,
            "has_next": page < total_pages,
            "filters": {"start_date": start_date, "end_date": end_date},
            **_storage_info("supabase"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "items": [],
            "error": str(exc),
            **_storage_info("memory", str(exc)),
        }


def _faq_needs_refresh(cur: Any, schema: str) -> bool:
    cur.execute(
        f"""
        SELECT refreshed_at_utc
        FROM {schema}.operating_faq_refresh_state
        WHERE id = 'main'
        """
    )
    row = cur.fetchone()
    if not row:
        return True
    refreshed_at = row["refreshed_at_utc"] if isinstance(row, dict) else row[0]
    return datetime.now(timezone.utc) - _faq_datetime(refreshed_at) >= timedelta(hours=FAQ_REFRESH_INTERVAL_HOURS)


def _seed_operating_faqs(cur: Any, schema: str) -> int:
    count = 0
    for row in _default_faq_rows():
        cur.execute(
            f"""
            INSERT INTO {schema}.operating_faq_items
                (id, category, category_label, question_key, question, answer, source_type,
                 source_ref, source_summary, frequency, status, source_updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s)
            ON CONFLICT (category, question_key) DO NOTHING
            """,
            (
                row["id"],
                row["category"],
                row["category_label"],
                row["question_key"],
                row["question"],
                row["answer"],
                row["source_type"],
                row["source_ref"],
                row["source_summary"],
                row["frequency"],
                _faq_datetime(row["source_updated_at"]),
            ),
        )
        count += int(cur.rowcount or 0)
    return count


def _official_faq_candidates(cur: Any, schema: str) -> list[dict[str, Any]]:
    cur.execute(
        f"""
        SELECT
            c.id,
            c.title,
            c.source_url,
            c.change_type,
            c.detected_at,
            c.summary
        FROM {schema}.official_guide_changes c
        ORDER BY c.detected_at DESC, c.id DESC
        LIMIT 40
        """
    )
    candidates: list[dict[str, Any]] = []
    for row in cur.fetchall():
        row = dict(row)
        title = _short_official_title(row.get("title"))
        summary = str(row.get("summary") or "").strip()
        if not summary:
            summary = summarize_official_document_change(
                title=title,
                content=title,
                change_type=str(row.get("change_type") or "updated"),
            )
        category = _faq_category_for_text(title, summary)
        candidate = _faq_candidate(
            category=category,
            question=f"{title} 문서에서 {FAQ_CATEGORY_LABELS[category]} 관련 확인할 점은 무엇인가요?",
            answer=summary,
            source_type="official",
            source_ref=str(row.get("source_url") or f"official-change:{row.get('id')}"),
            source_summary=f"공식 문서 변경 로그 · {title}",
            frequency=1,
            source_updated_at=row.get("detected_at"),
        )
        if candidate:
            candidates.append(candidate)
    return candidates


def _manual_rag_faq_candidates(cur: Any, schema: str) -> list[dict[str, Any]]:
    cur.execute(
        f"""
        SELECT id, title, category, source_note, content, updated_at_utc
        FROM {schema}.admin_manual_rag_items
        WHERE status = 'active'
        ORDER BY updated_at_utc DESC
        LIMIT 80
        """
    )
    candidates: list[dict[str, Any]] = []
    for row in cur.fetchall():
        row = dict(row)
        title = _clean_faq_text(row.get("title"), 220)
        content = _clean_faq_text(row.get("content"), 1100)
        if not title or not content:
            continue
        category = _faq_category_from_manual(row.get("category"), f"{title} {content}")
        candidate = _faq_candidate(
            category=category,
            question=_manual_question(title),
            answer=content,
            source_type="manual_rag",
            source_ref=f"manual-rag:{row.get('id')}",
            source_summary=str(row.get("source_note") or "관리자 직접 입력 지식"),
            frequency=1,
            source_updated_at=row.get("updated_at_utc"),
        )
        if candidate:
            candidates.append(candidate)
    return candidates


def _chat_faq_candidates(cur: Any, schema: str) -> list[dict[str, Any]]:
    cur.execute(
        f"""
        SELECT category, category_label, question, answer_excerpt, source_summary, created_at
        FROM {schema}.chat_question_logs
        WHERE created_at >= now() - interval '90 days'
        ORDER BY created_at DESC
        LIMIT 300
        """
    )
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in cur.fetchall():
        row = dict(row)
        category = QUESTION_TO_FAQ_CATEGORY.get(str(row.get("category") or "general"), "support")
        question = _clean_faq_text(row.get("question"), 300)
        if not question:
            continue
        key = (category, _faq_question_key(question))
        bucket = grouped.setdefault(
            key,
            {
                "category": category,
                "question": question,
                "answer": str(row.get("answer_excerpt") or ""),
                "source_summary": str(row.get("source_summary") or ""),
                "frequency": 0,
                "latest_at": row.get("created_at"),
            },
        )
        bucket["frequency"] += 1
        if _faq_datetime(row.get("created_at")) >= _faq_datetime(bucket.get("latest_at")):
            bucket["latest_at"] = row.get("created_at")
            bucket["answer"] = str(row.get("answer_excerpt") or bucket["answer"])
            bucket["source_summary"] = str(row.get("source_summary") or bucket["source_summary"])

    candidates: list[dict[str, Any]] = []
    for item in grouped.values():
        if int(item.get("frequency") or 0) < 2:
            continue
        answer = _clean_faq_text(item.get("answer"), 1100)
        if not answer:
            continue
        candidate = _faq_candidate(
            category=item["category"],
            question=item["question"],
            answer=answer,
            source_type="user_question",
            source_ref=f"chat-question:{_faq_question_key(item['question'])}",
            source_summary=f"사용자 Q&A {item['frequency']}회 문의 · {item.get('source_summary') or '답변 로그 기준'}",
            frequency=int(item["frequency"]),
            source_updated_at=item.get("latest_at"),
        )
        if candidate:
            candidates.append(candidate)
    return candidates


def _apply_faq_candidates(cur: Any, schema: str, candidates: list[dict[str, Any]]) -> int:
    cur.execute(
        f"""
        SELECT id, category, question_key, question, source_updated_at
        FROM {schema}.operating_faq_items
        WHERE status = 'active'
        """
    )
    existing = [dict(row) for row in cur.fetchall()]
    updated = 0
    for candidate in candidates:
        matched_id = ""
        for row in existing:
            if row.get("category") != candidate["category"]:
                continue
            if row.get("question_key") == candidate["question_key"] or _faq_similarity(row.get("question"), candidate["question"]) >= 0.58:
                matched_id = str(row.get("id") or "")
                candidate["question_key"] = str(row.get("question_key") or candidate["question_key"])
                break
        row_id = matched_id or candidate["id"]
        cur.execute(
            f"""
            INSERT INTO {schema}.operating_faq_items AS faq
                (id, category, category_label, question_key, question, answer, source_type,
                 source_ref, source_summary, frequency, status, source_updated_at, updated_at_utc)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, now())
            ON CONFLICT (category, question_key) DO UPDATE SET
                question = CASE
                    WHEN faq.source_updated_at <= EXCLUDED.source_updated_at
                         OR faq.source_type = 'seed'
                    THEN EXCLUDED.question
                    ELSE faq.question
                END,
                answer = CASE
                    WHEN faq.source_updated_at <= EXCLUDED.source_updated_at
                         OR faq.source_type = 'seed'
                    THEN EXCLUDED.answer
                    ELSE faq.answer
                END,
                source_type = EXCLUDED.source_type,
                source_ref = EXCLUDED.source_ref,
                source_summary = EXCLUDED.source_summary,
                frequency = GREATEST(faq.frequency, EXCLUDED.frequency),
                source_updated_at = GREATEST(faq.source_updated_at, EXCLUDED.source_updated_at),
                updated_at_utc = now(),
                status = 'active'
            """,
            (
                row_id,
                candidate["category"],
                candidate["category_label"],
                candidate["question_key"],
                candidate["question"],
                candidate["answer"],
                candidate["source_type"],
                candidate["source_ref"],
                candidate["source_summary"],
                candidate["frequency"],
                _faq_datetime(candidate["source_updated_at"]),
            ),
        )
        updated += 1
    return updated


def refresh_operating_faqs(*, force: bool = False) -> dict[str, Any]:
    try:
        _ensure_faq_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                if not force and not _faq_needs_refresh(cur, schema):
                    return {"ok": True, "refreshed": False, **_storage_info("supabase")}
                seeded = _seed_operating_faqs(cur, schema)
                candidates = [
                    *_official_faq_candidates(cur, schema),
                    *_manual_rag_faq_candidates(cur, schema),
                    *_chat_faq_candidates(cur, schema),
                ]
                applied = _apply_faq_candidates(cur, schema, candidates)
                summary = (
                    f"seed={seeded}, official/manual/question candidates={len(candidates)}, "
                    f"applied={applied}"
                )
                cur.execute(
                    f"""
                    INSERT INTO {schema}.operating_faq_refresh_state
                        (id, refreshed_at_utc, source_summary)
                    VALUES ('main', now(), %s)
                    ON CONFLICT (id) DO UPDATE SET
                        refreshed_at_utc = now(),
                        source_summary = EXCLUDED.source_summary
                    """,
                    (summary,),
                )
        return {
            "ok": True,
            "refreshed": True,
            "candidate_count": len(candidates),
            "applied_count": applied,
            **_storage_info("supabase"),
        }
    except Exception as exc:
        fallback = _memory_refresh_operating_faqs(force=force)
        return {**fallback, **_storage_info("memory", str(exc))}


def list_operating_faqs(*, auto_refresh: bool = True) -> dict[str, Any]:
    if auto_refresh:
        refresh_operating_faqs(force=False)
    try:
        schema = _schema()
        with _connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT id, category, category_label, question, answer, source_type,
                           source_summary, frequency, source_updated_at, updated_at_utc
                    FROM {schema}.operating_faq_items
                    WHERE status = 'active'
                    ORDER BY
                        category,
                        CASE source_type
                            WHEN 'official' THEN 1
                            WHEN 'manual_rag' THEN 2
                            WHEN 'user_question' THEN 3
                            ELSE 4
                        END,
                        source_updated_at DESC,
                        updated_at_utc DESC
                    """
                )
                rows = [dict(row) for row in cur.fetchall()]
                cur.execute(
                    f"""
                    SELECT refreshed_at_utc
                    FROM {schema}.operating_faq_refresh_state
                    WHERE id = 'main'
                    """
                )
                state = cur.fetchone()
        return {
            "ok": True,
            "categories": _public_faq_categories(rows),
            "updated_at": _iso_value(state["refreshed_at_utc"]) if state else "",
            "refresh_interval_hours": FAQ_REFRESH_INTERVAL_HOURS,
            **_storage_info("supabase"),
        }
    except Exception as exc:
        _memory_refresh_operating_faqs(force=False)
        return _default_faq_response(_storage_info("memory", str(exc)))


def _normalize_sheet_key(value: Any) -> str:
    return re.sub(r"[\s_\-]+", "", str(value or "").strip().lower())


def _sheet_value(row: dict[str, Any], *keys: str) -> str:
    if not isinstance(row, dict):
        return ""
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return str(row[key]).strip()
    normalized = {_normalize_sheet_key(key): value for key, value in row.items()}
    for key in keys:
        value = normalized.get(_normalize_sheet_key(key))
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _sheet_rows(payload: dict[str, Any], sheet_name: str) -> list[dict[str, Any]]:
    raw_sheets = payload.get("sheets") if isinstance(payload, dict) else {}
    rows = raw_sheets.get(sheet_name) if isinstance(raw_sheets, dict) else None
    if rows is None:
        rows = payload.get(sheet_name) if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _receipt_from_row(row: dict[str, Any]) -> str:
    return _sheet_value(row, "receipt_number", "접수번호", "receiptNumber")


def _campaign_intake_status_item(row: dict[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    status = str(row.get("status") or "ready").strip()
    if status not in CAMPAIGN_INTAKE_STATUSES:
        status = "ready"
    return {
        "operator_name": str(row.get("operator_name") or "").strip(),
        "status": status,
        "status_label": CAMPAIGN_INTAKE_STATUSES[status],
        "memo": str(row.get("memo") or "").strip(),
        "updated_at_utc": _iso_value(row.get("updated_at_utc")),
    }


def _campaign_intake_sort_value(item: dict[str, Any]) -> tuple[str, str]:
    submitted_at = str(item.get("submitted_at_kst") or item.get("submitted_at") or "")
    parsed = _parse_mail_datetime(submitted_at)
    sortable_date = parsed.astimezone(KST).isoformat() if parsed else submitted_at
    return (sortable_date, str(item.get("receipt_number") or ""))


def _public_campaign_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "campaign_name": _sheet_value(row, "campaign_name"),
        "budget_max": _sheet_value(row, "budget_max"),
        "budget_type": _sheet_value(row, "budget_type"),
        "launch_date": _sheet_value(row, "launch_date"),
        "end_date": _sheet_value(row, "end_date"),
        "objective": _sheet_value(row, "objective"),
        "target_countries": _sheet_value(row, "target_countries"),
    }


def _public_adgroup_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "campaign_name": _sheet_value(row, "campaign_name"),
        "adgroup_name": _sheet_value(row, "adgroup_name"),
        "max_bid": _sheet_value(row, "max_bid"),
        "keywords": _sheet_value(row, "keywords"),
        "ads": [],
    }


def _public_ad_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "adgroup_name": _sheet_value(row, "adgroup_name"),
        "ad_name": _sheet_value(row, "ad_name"),
        "title": _sheet_value(row, "title"),
        "copy": _sheet_value(row, "copy"),
        "link": _sheet_value(row, "link"),
        "image_link": _sheet_value(row, "image_link"),
    }


def _build_campaign_intake_items(
    payload: dict[str, Any],
    ops_state: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    ops_state = ops_state or {}
    campaigns_by_receipt: dict[str, list[dict[str, Any]]] = {}
    adgroups_by_receipt: dict[str, list[dict[str, Any]]] = {}
    ads_by_receipt: dict[str, list[dict[str, Any]]] = {}
    meta_by_receipt: dict[str, dict[str, Any]] = {}
    receipts: set[str] = set()

    for row in _sheet_rows(payload, "campaigns"):
        receipt = _receipt_from_row(row)
        if not receipt:
            continue
        receipts.add(receipt)
        campaigns_by_receipt.setdefault(receipt, []).append(_public_campaign_row(row))

    for row in _sheet_rows(payload, "adgroups"):
        receipt = _receipt_from_row(row)
        if not receipt:
            continue
        receipts.add(receipt)
        adgroups_by_receipt.setdefault(receipt, []).append(_public_adgroup_row(row))

    for row in _sheet_rows(payload, "ads"):
        receipt = _receipt_from_row(row)
        if not receipt:
            continue
        receipts.add(receipt)
        ads_by_receipt.setdefault(receipt, []).append(_public_ad_row(row))

    for row in _sheet_rows(payload, "ops_meta"):
        receipt = _receipt_from_row(row)
        if not receipt:
            continue
        receipts.add(receipt)
        meta_by_receipt[receipt] = {
            "receipt_number": receipt,
            "submitted_at_kst": _sheet_value(row, "submitted_at_kst", "제출시각"),
            "advertiser_name": _sheet_value(row, "advertiser_name", "광고주명"),
            "brand_name": _sheet_value(row, "brand_name", "브랜드명"),
            "sales_owner": _sheet_value(row, "sales_owner", "담당자명"),
            "sales_owner_email": _sheet_value(row, "sales_owner_email", "담당자 이메일"),
            "owner_headquarters": _sheet_value(row, "owner_headquarters", "본부"),
            "owner_office": _sheet_value(row, "owner_office", "실"),
            "owner_team": _sheet_value(row, "owner_team", "팀"),
            "note": _sheet_value(row, "note", "비고"),
        }

    items: list[dict[str, Any]] = []
    for receipt in sorted(receipts):
        campaigns = campaigns_by_receipt.get(receipt, [])
        adgroups = adgroups_by_receipt.get(receipt, [])
        ads = ads_by_receipt.get(receipt, [])
        ads_by_adgroup: dict[str, list[dict[str, str]]] = {}
        for ad in ads:
            ads_by_adgroup.setdefault(ad["adgroup_name"], []).append(ad)

        grouped_campaigns: list[dict[str, Any]] = []
        for campaign in campaigns:
            campaign_adgroups = [
                dict(adgroup, ads=ads_by_adgroup.get(adgroup["adgroup_name"], []))
                for adgroup in adgroups
                if adgroup["campaign_name"] == campaign["campaign_name"]
            ]
            grouped_campaigns.append({**campaign, "adgroups": campaign_adgroups})

        assigned_adgroups = {
            adgroup["adgroup_name"]
            for campaign in grouped_campaigns
            for adgroup in campaign["adgroups"]
        }
        orphan_adgroups = [
            dict(adgroup, ads=ads_by_adgroup.get(adgroup["adgroup_name"], []))
            for adgroup in adgroups
            if adgroup["adgroup_name"] not in assigned_adgroups
        ]
        if orphan_adgroups and len(grouped_campaigns) == 1:
            grouped_campaigns[0]["adgroups"].extend(orphan_adgroups)
        elif orphan_adgroups:
            grouped_campaigns.append(
                {
                    "campaign_name": "캠페인 미지정",
                    "budget_max": "",
                    "budget_type": "",
                    "launch_date": "",
                    "end_date": "",
                    "objective": "",
                    "target_countries": "",
                    "adgroups": orphan_adgroups,
                }
            )

        meta = meta_by_receipt.get(receipt, {"receipt_number": receipt})
        status_item = _campaign_intake_status_item(ops_state.get(receipt))
        items.append(
            {
                **meta,
                **status_item,
                "campaign_count": len(campaigns),
                "adgroup_count": len(adgroups),
                "ad_count": len(ads),
                "campaigns": grouped_campaigns,
            }
        )

    items.sort(key=_campaign_intake_sort_value, reverse=True)
    return items


def _load_campaign_intake_ops(receipts: set[str]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    if not receipts:
        return {}, _storage_info("supabase")
    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT receipt_number, operator_name, status, memo, updated_at_utc
                    FROM {schema}.campaign_intake_ops
                    WHERE receipt_number = ANY(%s)
                    """,
                    (list(receipts),),
                )
                rows = {str(row["receipt_number"]): dict(row) for row in cur.fetchall()}
        return rows, _storage_info("supabase")
    except Exception as exc:
        rows = {receipt: _memory_campaign_intake_ops[receipt] for receipt in receipts if receipt in _memory_campaign_intake_ops}
        return rows, _storage_info("memory", str(exc))


def list_campaign_intake_items() -> dict[str, Any]:
    try:
        payload = _post_intake_webhook({"action": "campaign_intake_list"})
        if payload.get("ok") is False:
            error_message = str(payload.get("error") or "접수 시트 목록을 가져오지 못했습니다.")
            if "campaigns is required" in error_message:
                error_message = (
                    "접수 시트 Apps Script가 아직 목록 조회 액션을 지원하지 않습니다. "
                    "apps_script/intake_webhook.gs 최신 코드를 Apps Script에 붙여넣고 새 버전으로 배포해 주세요."
                )
            raise RuntimeError(error_message)
        receipts = {
            _receipt_from_row(row)
            for sheet_name in ("campaigns", "adgroups", "ads", "ops_meta")
            for row in _sheet_rows(payload, sheet_name)
        }
        receipts.discard("")
        ops_state, storage = _load_campaign_intake_ops(receipts)
        items = _build_campaign_intake_items(payload, ops_state)
        return {
            "ok": True,
            "items": items,
            "total_count": len(items),
            "statusLabels": CAMPAIGN_INTAKE_STATUSES,
            **storage,
        }
    except Exception as exc:
        return {
            "ok": False,
            "items": [],
            "total_count": 0,
            "statusLabels": CAMPAIGN_INTAKE_STATUSES,
            "error": str(exc),
            **_storage_info("memory", str(exc)),
        }


def update_campaign_intake_ops(payload: dict[str, Any]) -> dict[str, Any]:
    receipt_number = str(payload.get("receipt_number") or "").strip()[:80]
    operator_name = str(payload.get("operator_name") or "").strip()[:80]
    status = str(payload.get("status") or "ready").strip()
    memo = str(payload.get("memo") or "").strip()[:1000]
    if not receipt_number:
        raise ValueError("접수번호가 필요합니다.")
    if status not in CAMPAIGN_INTAKE_STATUSES:
        raise ValueError("지원하지 않는 상태입니다.")

    row = {
        "receipt_number": receipt_number,
        "operator_name": operator_name,
        "status": status,
        "memo": memo,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {schema}.campaign_intake_ops
                        (receipt_number, operator_name, status, memo)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (receipt_number) DO UPDATE SET
                        operator_name = EXCLUDED.operator_name,
                        status = EXCLUDED.status,
                        memo = EXCLUDED.memo,
                        updated_at_utc = now()
                    RETURNING receipt_number, operator_name, status, memo, updated_at_utc
                    """,
                    (receipt_number, operator_name, status, memo),
                )
                row = dict(cur.fetchone())
        return {"ok": True, "item": {"receipt_number": receipt_number, **_campaign_intake_status_item(row)}, **_storage_info("supabase")}
    except Exception as exc:
        _memory_campaign_intake_ops[receipt_number] = row
        return {
            "ok": True,
            "item": {"receipt_number": receipt_number, **_campaign_intake_status_item(row)},
            **_storage_info("memory", str(exc)),
        }


def list_mail_review_rows(*, status_filter: str = "", limit: int = 10, page: int = 1) -> dict[str, Any]:
    status_filter = (status_filter or "").strip()
    if status_filter and status_filter not in MAIL_REVIEW_STATUSES and status_filter != "all":
        status_filter = ""
    limit = max(1, min(int(limit or 10), 10))
    page = max(1, int(page or 1))
    retention_days = 14
    cutoff = datetime.now(KST) - timedelta(days=retention_days)

    try:
        payload = _post_mail_webhook(
            {
                "action": "review_list",
                "status": status_filter,
                "limit": 300,
                "retention_days": retention_days,
            }
        )
        source_rows = payload.get("rows") or []
        if not isinstance(source_rows, list):
            source_rows = []
        recent_rows = [
            row for row in source_rows
            if isinstance(row, dict) and _mail_row_recent(row, cutoff=cutoff)
        ]
        total_count = len(recent_rows)
        total_pages = max(1, (total_count + limit - 1) // limit)
        if page > total_pages:
            page = total_pages
        start = (page - 1) * limit
        payload["rows"] = recent_rows[start : start + limit]
        payload["page"] = page
        payload["page_size"] = limit
        payload["total_count"] = total_count
        payload["total_pages"] = total_pages
        payload["has_previous"] = page > 1
        payload["has_next"] = page < total_pages
        payload["retention_days"] = retention_days
        payload["filtered_out_old"] = max(0, len(source_rows) - total_count)
        payload.setdefault("statusLabels", MAIL_REVIEW_STATUSES)
        return payload
    except Exception as exc:
        return {
            "ok": False,
            "rows": [],
            "stats": {},
            "statusLabels": MAIL_REVIEW_STATUSES,
            "page": page,
            "page_size": limit,
            "total_count": 0,
            "total_pages": 1,
            "has_previous": False,
            "has_next": False,
            "retention_days": retention_days,
            "error": str(exc),
        }


def update_mail_review_row(payload: dict[str, Any]) -> dict[str, Any]:
    duplicate_hash = str(payload.get("duplicate_hash") or "").strip()
    review_status = str(payload.get("review_status") or "").strip()
    if not duplicate_hash:
        raise ValueError("duplicate_hash가 필요합니다.")
    if review_status not in MAIL_REVIEW_STATUSES:
        raise ValueError("지원하지 않는 검토 상태입니다.")

    clean_payload = {
        "action": "review_update",
        "duplicate_hash": duplicate_hash,
        "review_status": review_status,
        "review_note": str(payload.get("review_note") or "").strip()[:2000],
        "approved_title": str(payload.get("approved_title") or "").strip()[:300],
        "approved_summary": str(payload.get("approved_summary") or "").strip()[:8000],
        "approved_by": str(payload.get("approved_by") or "").strip()[:80],
        "supersedes_duplicate_hash": str(payload.get("supersedes_duplicate_hash") or "").strip()[:128],
    }
    if review_status == "approved_for_rag" and not clean_payload["approved_summary"]:
        raise ValueError("RAG 반영 승인에는 승인 요약이 필요합니다.")

    response = _post_mail_webhook(clean_payload)
    response.setdefault("statusLabels", MAIL_REVIEW_STATUSES)
    return response


def _manual_rag_identity(item_id: str) -> str:
    return f"{MANUAL_RAG_SOURCE_PREFIX}{item_id}"


def _manual_rag_source_url(item_id: str) -> str:
    return f"{MANUAL_RAG_SOURCE_URL_PREFIX}{item_id}"


def _normalize_manual_rag_category(value: str) -> str:
    text = str(value or "").strip()
    return text if text in MANUAL_RAG_CATEGORIES else MANUAL_RAG_CATEGORIES[0]


def _manual_rag_content(*, title: str, category: str, source_note: str, content: str) -> str:
    parts = [
        "# 관리자 직접 입력 RAG",
        f"제목: {title}",
        f"분류: {category or '운영 커뮤니케이션'}",
    ]
    if source_note:
        parts.append(f"출처 메모: {source_note}")
    parts.extend(["", content.strip()])
    return "\n".join(parts).strip()


def _index_manual_rag_item(
    *,
    item_id: str,
    title: str,
    category: str,
    source_note: str,
    content: str,
) -> None:
    clean_content = content.strip()
    if not clean_content:
        raise ValueError("RAG 반영 내용이 필요합니다.")

    settings = load_settings()
    ensure_database(settings)
    source_identity = _manual_rag_identity(item_id)
    source_url = _manual_rag_source_url(item_id)
    delete_source_documents(
        collection_name=MANUAL_RAG_COLLECTION,
        source_identity=source_identity,
        source_url=source_url,
        settings=settings,
    )

    now_utc = datetime.now(timezone.utc)
    page_content = _manual_rag_content(
        title=title,
        category=category,
        source_note=source_note,
        content=clean_content,
    )
    document = Document(
        page_content=page_content,
        metadata={
            "source_tier": MANUAL_RAG_COLLECTION,
            "source_url": source_url,
            "source_identity": source_identity,
            "title": title,
            "category": category or "운영 커뮤니케이션",
            "source_note": source_note,
            "content_hash": content_hash(title, page_content),
            "lang": "ko",
            "article_id": item_id,
            "source_updated_at": now_utc.date().isoformat(),
            "crawled_at": now_utc.isoformat(),
            "manual_admin_entry": True,
        },
    )
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=700,
        chunk_overlap=100,
        add_start_index=True,
    )
    chunks = splitter.split_documents([document])
    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = index
    embeddings = embed_texts([chunk.page_content for chunk in chunks], settings)
    insert_documents(
        collection_name=MANUAL_RAG_COLLECTION,
        chunks=chunks,
        embeddings=embeddings,
        settings=settings,
    )


def _public_manual_rag_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "title": str(row.get("title") or ""),
        "category": str(row.get("category") or ""),
        "source_note": str(row.get("source_note") or ""),
        "content": str(row.get("content") or ""),
        "status": str(row.get("status") or "active"),
        "rag_source_identity": str(row.get("rag_source_identity") or ""),
        "rag_source_url": str(row.get("rag_source_url") or ""),
        "created_at": _iso_value(row.get("created_at_utc")),
        "updated_at": _iso_value(row.get("updated_at_utc")),
        "last_indexed_at": _iso_value(row.get("last_indexed_at_utc")),
        "deleted_at": _iso_value(row.get("deleted_at_utc")),
    }


def list_manual_rag_items(*, include_deleted: bool = False, limit: int = 200) -> dict[str, Any]:
    try:
        _ensure_tables()
        schema = _schema()
        limit = max(1, min(int(limit or 200), 500))
        where = "" if include_deleted else "WHERE status <> 'deleted'"
        with _connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT *
                    FROM {schema}.admin_manual_rag_items
                    {where}
                    ORDER BY updated_at_utc DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = [_public_manual_rag_item(dict(row)) for row in cur.fetchall()]
        return {"ok": True, "items": rows, **_storage_info("supabase")}
    except Exception as exc:
        return {
            "ok": False,
            "items": [],
            "error": str(exc),
            **_storage_info("memory", str(exc)),
        }


def create_manual_rag_item(payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "").strip()[:300]
    category = _normalize_manual_rag_category(str(payload.get("category") or "").strip()[:120])
    source_note = str(payload.get("source_note") or "").strip()[:1000]
    content = str(payload.get("content") or "").strip()
    if len(title) < 2:
        raise ValueError("제목을 2자 이상 입력해 주세요.")
    if not content:
        raise ValueError("RAG 반영 내용이 필요합니다.")

    _ensure_tables()
    item_id = uuid.uuid4().hex
    source_identity = _manual_rag_identity(item_id)
    source_url = _manual_rag_source_url(item_id)
    schema = _schema()
    with _connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                INSERT INTO {schema}.admin_manual_rag_items
                    (id, title, category, source_note, content, status, rag_source_identity, rag_source_url)
                VALUES (%s, %s, %s, %s, %s, 'active', %s, %s)
                RETURNING *
                """,
                (item_id, title, category, source_note, content, source_identity, source_url),
            )
            row = dict(cur.fetchone())

    _index_manual_rag_item(
        item_id=item_id,
        title=title,
        category=category,
        source_note=source_note,
        content=content,
    )
    with _connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                UPDATE {schema}.admin_manual_rag_items
                SET last_indexed_at_utc = now(), updated_at_utc = now()
                WHERE id = %s
                RETURNING *
                """,
                (item_id,),
            )
            row = dict(cur.fetchone())
    return {"ok": True, "item": _public_manual_rag_item(row), **_storage_info("supabase")}


def update_manual_rag_item(item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    item_id = str(item_id or "").strip()
    title = str(payload.get("title") or "").strip()[:300]
    category = _normalize_manual_rag_category(str(payload.get("category") or "").strip()[:120])
    source_note = str(payload.get("source_note") or "").strip()[:1000]
    content = str(payload.get("content") or "").strip()
    if not item_id:
        raise ValueError("관리 항목 ID가 필요합니다.")
    if len(title) < 2:
        raise ValueError("제목을 2자 이상 입력해 주세요.")
    if not content:
        raise ValueError("RAG 반영 내용이 필요합니다.")

    _ensure_tables()
    schema = _schema()
    with _connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                UPDATE {schema}.admin_manual_rag_items
                SET title = %s,
                    category = %s,
                    source_note = %s,
                    content = %s,
                    status = 'active',
                    deleted_at_utc = NULL,
                    updated_at_utc = now()
                WHERE id = %s
                RETURNING *
                """,
                (title, category, source_note, content, item_id),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("수정할 직접 입력 RAG 항목을 찾지 못했습니다.")

    _index_manual_rag_item(
        item_id=item_id,
        title=title,
        category=category,
        source_note=source_note,
        content=content,
    )
    with _connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                UPDATE {schema}.admin_manual_rag_items
                SET last_indexed_at_utc = now(), updated_at_utc = now()
                WHERE id = %s
                RETURNING *
                """,
                (item_id,),
            )
            row = dict(cur.fetchone())
    return {"ok": True, "item": _public_manual_rag_item(row), **_storage_info("supabase")}


def delete_manual_rag_item(item_id: str) -> dict[str, Any]:
    item_id = str(item_id or "").strip()
    if not item_id:
        raise ValueError("삭제할 직접 입력 RAG 항목 ID가 필요합니다.")
    _ensure_tables()
    schema = _schema()
    source_identity = _manual_rag_identity(item_id)
    source_url = _manual_rag_source_url(item_id)
    settings = load_settings()
    ensure_database(settings)
    delete_source_documents(
        collection_name=MANUAL_RAG_COLLECTION,
        source_identity=source_identity,
        source_url=source_url,
        settings=settings,
    )
    with _connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                UPDATE {schema}.admin_manual_rag_items
                SET status = 'deleted',
                    deleted_at_utc = now(),
                    updated_at_utc = now()
                WHERE id = %s
                RETURNING *
                """,
                (item_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("삭제할 직접 입력 RAG 항목을 찾지 못했습니다.")
    return {"ok": True, "item": _public_manual_rag_item(dict(row)), **_storage_info("supabase")}
