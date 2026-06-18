from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

from rag_chatbot.config import load_settings


KST = timezone(timedelta(hours=9))


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
    "source_label": "OpenAI Ads Guide 기준으로 하루 2회 최신 정보를 자동 확인·업데이트합니다.",
    "source_url": "https://help.openai.com/en/collections/20001223-chatgpt-ads",
    "enabled": True,
}


_memory_notice = DEFAULT_NOTICE.copy()
_memory_visits: dict[str, dict[str, Any]] = {}
_db_ready = False


def _today_kst() -> str:
    return datetime.now(KST).date().isoformat()


def _quote_ident(value: str) -> str:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value):
        raise ValueError("Invalid Supabase schema name.")
    return f'"{value}"'


def _storage_info(mode: str, error: str | None = None) -> dict[str, str]:
    info = {"storage": mode}
    if error:
        info["storage_error"] = error
    return info


def _connect():
    settings = load_settings()
    if not settings.supabase_db_url:
        raise RuntimeError("SUPABASE_DB_URL is not configured.")
    return psycopg.connect(settings.supabase_db_url)


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
                    source_label text NOT NULL,
                    source_url text NOT NULL,
                    enabled boolean NOT NULL DEFAULT true,
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
                INSERT INTO {schema}.admin_notice
                    (id, title, updated_at, bullets, source_label, source_url, enabled)
                VALUES
                    ('main', %s, %s, %s::jsonb, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    DEFAULT_NOTICE["title"],
                    DEFAULT_NOTICE["updated_at"],
                    json.dumps(DEFAULT_NOTICE["bullets"], ensure_ascii=False),
                    DEFAULT_NOTICE["source_label"],
                    DEFAULT_NOTICE["source_url"],
                    DEFAULT_NOTICE["enabled"],
                ),
            )
    _db_ready = True


def get_notice_config() -> dict[str, Any]:
    try:
        _ensure_tables()
        schema = _schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT title, updated_at, bullets, source_label, source_url, enabled
                    FROM {schema}.admin_notice
                    WHERE id = 'main'
                    """
                )
                row = cur.fetchone()
        if not row:
            return {**DEFAULT_NOTICE, **_storage_info("memory")}
        title, updated_at, bullets, source_label, source_url, enabled = row
        return {
            "title": title,
            "updated_at": updated_at,
            "bullets": bullets or [],
            "source_label": source_label,
            "source_url": source_url,
            "enabled": bool(enabled),
            **_storage_info("supabase"),
        }
    except Exception as exc:
        return {**_memory_notice, **_storage_info("memory", str(exc))}


def save_notice_config(payload: dict[str, Any]) -> dict[str, Any]:
    notice = {
        "title": str(payload.get("title") or DEFAULT_NOTICE["title"]).strip(),
        "updated_at": str(payload.get("updated_at") or _today_kst()).strip(),
        "bullets": [
            str(item).strip()
            for item in payload.get("bullets", [])
            if str(item).strip()
        ],
        "source_label": str(payload.get("source_label") or DEFAULT_NOTICE["source_label"]).strip(),
        "source_url": str(payload.get("source_url") or DEFAULT_NOTICE["source_url"]).strip(),
        "enabled": bool(payload.get("enabled", True)),
    }
    if not notice["bullets"]:
        notice["bullets"] = list(DEFAULT_NOTICE["bullets"])

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
                        (id, title, updated_at, bullets, source_label, source_url, enabled, updated_at_utc)
                    VALUES
                        ('main', %s, %s, %s::jsonb, %s, %s, %s, now())
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        updated_at = EXCLUDED.updated_at,
                        bullets = EXCLUDED.bullets,
                        source_label = EXCLUDED.source_label,
                        source_url = EXCLUDED.source_url,
                        enabled = EXCLUDED.enabled,
                        updated_at_utc = now()
                    """,
                    (
                        notice["title"],
                        notice["updated_at"],
                        json.dumps(notice["bullets"], ensure_ascii=False),
                        notice["source_label"],
                        notice["source_url"],
                        notice["enabled"],
                    ),
                )
        return {**notice, **_storage_info("supabase")}
    except Exception as exc:
        return {**notice, **_storage_info("memory", str(exc))}


def record_page_visit(page: str, page_label: str) -> dict[str, Any]:
    page = (page or "unknown")[:80]
    page_label = (page_label or page)[:120]
    today = _today_kst()

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
        return {**current, **_storage_info("memory", str(exc))}


def get_visit_analytics() -> dict[str, Any]:
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
        items = [
            {
                "page": row[0],
                "page_label": row[1],
                "total_count": row[2],
                "today_count": row[3],
                "today_date": row[4],
                "last_seen_at": row[5].isoformat() if row[5] else "",
            }
            for row in rows
        ]
        return {"items": items, **_storage_info("supabase")}
    except Exception as exc:
        items = sorted(
            _memory_visits.values(),
            key=lambda item: (-int(item.get("total_count", 0)), item.get("page_label", "")),
        )
        return {"items": items, **_storage_info("memory", str(exc))}
