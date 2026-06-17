from __future__ import annotations

import argparse
import base64
import hashlib
import html
import imaplib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime, parseaddr
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

from .config import project_root


DEFAULT_TARGET_SENDERS = (
    "michaelcho@openai.com",
    "harrisonk@openai.com",
    "ads-korea@openai.com",
    "nigel@openai.com",
)
DEFAULT_TARGET_RECIPIENTS = ("openai@nasmedia.co.kr",)
DEFAULT_RAG_DOC_PATH = "data/kr_ops/openai_email_confirmations.md"
DEFAULT_APPROVED_RAG_DOC_PATH = "data/kr_ops/openai_email_approved_updates.md"
KST = ZoneInfo("Asia/Seoul")
MAX_SHEET_CELL_CHARS = 45_000


@dataclass(frozen=True)
class MailCollectorSettings:
    host: str
    port: int
    secure: bool
    user: str
    password: str
    folder: str
    top: int
    target_senders: tuple[str, ...]
    target_recipients: tuple[str, ...]
    webhook_url: str
    webhook_secret: str
    body_max_chars: int = 12_000
    trim_quoted_replies: bool = True

    @classmethod
    def from_env(cls, *, top_override: int | None = None) -> "MailCollectorSettings":
        root = project_root()
        load_dotenv(root / ".env", override=False)
        load_dotenv(root / ".env.local", override=False)
        host = os.getenv("MAIL_COLLECTOR_HOST", "imap.daum.net").strip()
        user = os.getenv("MAIL_COLLECTOR_USER", "").strip()
        password = os.getenv("MAIL_COLLECTOR_PASSWORD", "").strip()
        missing = [
            name
            for name, value in (
                ("MAIL_COLLECTOR_HOST", host),
                ("MAIL_COLLECTOR_USER", user),
                ("MAIL_COLLECTOR_PASSWORD", password),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing mail collector environment variables: {', '.join(missing)}")

        top = top_override or int(os.getenv("MAIL_COLLECTOR_TOP", "50") or "50")
        return cls(
            host=host,
            port=int(os.getenv("MAIL_COLLECTOR_PORT", "993") or "993"),
            secure=_bool_env("MAIL_COLLECTOR_SECURE", True),
            user=user,
            password=password,
            folder=os.getenv("MAIL_COLLECTOR_FOLDER", "INBOX").strip() or "INBOX",
            top=max(1, top),
            target_senders=_split_email_list(
                os.getenv("MAIL_COLLECTOR_TARGET_SENDERS"),
                DEFAULT_TARGET_SENDERS,
            ),
            target_recipients=_split_email_list(
                os.getenv("MAIL_COLLECTOR_TARGET_RECIPIENTS"),
                DEFAULT_TARGET_RECIPIENTS,
            ),
            webhook_url=os.getenv("MAIL_COLLECTOR_SHEETS_WEBHOOK_URL", "").strip(),
            webhook_secret=(
                os.getenv("MAIL_COLLECTOR_SHEETS_SHARED_SECRET")
                or os.getenv("SHEETS_SHARED_SECRET")
                or ""
            ).strip(),
            body_max_chars=max(500, int(os.getenv("MAIL_COLLECTOR_BODY_MAX_CHARS", "12000") or "12000")),
            trim_quoted_replies=_bool_env("MAIL_COLLECTOR_TRIM_QUOTES", True),
        )


@dataclass
class MailDiagnostics:
    mailbox_total: int = 0
    inspected_messages: int = 0
    fetched_messages: int = 0
    parsed_messages: int = 0
    fetch_failures: int = 0
    empty_fetches: int = 0
    matched_messages: int = 0
    target_sender_matches: int = 0
    target_recipient_matches: int = 0
    both_target_sender_and_recipient: int = 0
    from_openai_domain: int = 0
    to_cc_openai_domain: int = 0
    to_cc_nasmedia_domain: int = 0
    to_cc_openai_nasmedia_exact: int = 0
    missing_to_cc_headers: int = 0

    def to_safe_dict(self) -> dict[str, int]:
        return {
            "mailbox_total": self.mailbox_total,
            "inspected_messages": self.inspected_messages,
            "fetched_messages": self.fetched_messages,
            "parsed_messages": self.parsed_messages,
            "fetch_failures": self.fetch_failures,
            "empty_fetches": self.empty_fetches,
            "matched_messages": self.matched_messages,
            "target_sender_matches": self.target_sender_matches,
            "target_recipient_matches": self.target_recipient_matches,
            "both_target_sender_and_recipient": self.both_target_sender_and_recipient,
            "from_openai_domain": self.from_openai_domain,
            "to_cc_openai_domain": self.to_cc_openai_domain,
            "to_cc_nasmedia_domain": self.to_cc_nasmedia_domain,
            "to_cc_openai_nasmedia_exact": self.to_cc_openai_nasmedia_exact,
            "missing_to_cc_headers": self.missing_to_cc_headers,
        }


@dataclass(frozen=True)
class CollectedMail:
    collected_at_kst: str
    received_at: str
    uid: str
    message_id: str
    from_name: str
    from_email: str
    to: str
    cc: str
    subject: str
    body_summary: str
    body_text: str
    attachment_names: str
    attachment_text: str
    tags: str
    rag_document_id: str
    duplicate_hash: str
    status: str
    last_embedded_at: str

    def to_sheet_row(self) -> dict[str, str]:
        return {
            "collected_at_kst": self.collected_at_kst,
            "received_at": self.received_at,
            "uid": self.uid,
            "message_id": self.message_id,
            "from_name": self.from_name,
            "from_email": self.from_email,
            "to": self.to,
            "cc": self.cc,
            "subject": self.subject,
            "body_summary": self.body_summary,
            "body_text": _clamp(self.body_text, MAX_SHEET_CELL_CHARS),
            "attachment_names": self.attachment_names,
            "attachment_text": _clamp(self.attachment_text, MAX_SHEET_CELL_CHARS),
            "tags": self.tags,
            "rag_document_id": self.rag_document_id,
            "duplicate_hash": self.duplicate_hash,
            "status": self.status,
            "last_embedded_at": self.last_embedded_at,
            "review_status": self.status,
            "review_note": "",
            "approved_title": "",
            "approved_summary": "",
            "approved_by": "",
            "approved_at": "",
            "supersedes_duplicate_hash": "",
            "rag_ingested_at": "",
        }


def collect_matching_messages(
    settings: MailCollectorSettings,
    diagnostics: MailDiagnostics | None = None,
) -> list[CollectedMail]:
    client: imaplib.IMAP4
    if settings.secure:
        client = imaplib.IMAP4_SSL(settings.host, settings.port)
    else:
        client = imaplib.IMAP4(settings.host, settings.port)

    try:
        client.login(settings.user, settings.password)
        status, _ = client.select(_quote_mailbox(settings.folder), readonly=True)
        if status != "OK":
            raise RuntimeError(f"Could not open IMAP folder: {settings.folder}")

        status, data = client.uid("search", None, "ALL")
        if status != "OK" or not data or not data[0]:
            return []
        uids = data[0].split()
        selected_uids = list(reversed(uids[-settings.top :]))
        if diagnostics:
            diagnostics.mailbox_total = len(uids)
            diagnostics.inspected_messages = len(selected_uids)

        collected: list[CollectedMail] = []
        for uid_bytes in selected_uids:
            uid = uid_bytes.decode("ascii", errors="ignore")
            status, fetched = client.uid("fetch", uid_bytes, "(RFC822)")
            if status != "OK":
                if diagnostics:
                    diagnostics.fetch_failures += 1
                continue
            raw = _raw_message_from_fetch(fetched)
            if not raw:
                if diagnostics:
                    diagnostics.empty_fetches += 1
                continue
            if diagnostics:
                diagnostics.fetched_messages += 1
            message = BytesParser(policy=policy.default).parsebytes(raw)
            if diagnostics:
                record_message_diagnostics(message, settings, diagnostics)
            item = parse_message(uid, message, settings)
            if item:
                if diagnostics:
                    diagnostics.matched_messages += 1
                collected.append(item)
        return collected
    finally:
        try:
            client.logout()
        except Exception:
            pass


def record_message_diagnostics(
    message: EmailMessage | Message,
    settings: MailCollectorSettings,
    diagnostics: MailDiagnostics,
) -> None:
    diagnostics.parsed_messages += 1
    _, from_email = _single_address(message.get("From", ""))
    to_addresses = _addresses_for_header(message, "To")
    cc_addresses = _addresses_for_header(message, "Cc")
    recipients = {email for _, email in [*to_addresses, *cc_addresses]}

    sender_match = from_email in set(settings.target_senders)
    recipient_match = bool(recipients.intersection(settings.target_recipients))

    if sender_match:
        diagnostics.target_sender_matches += 1
    if recipient_match:
        diagnostics.target_recipient_matches += 1
    if sender_match and recipient_match:
        diagnostics.both_target_sender_and_recipient += 1
    if from_email.endswith("@openai.com"):
        diagnostics.from_openai_domain += 1
    if any(email.endswith("@openai.com") for email in recipients):
        diagnostics.to_cc_openai_domain += 1
    if any(email.endswith("@nasmedia.co.kr") for email in recipients):
        diagnostics.to_cc_nasmedia_domain += 1
    if "openai@nasmedia.co.kr" in recipients:
        diagnostics.to_cc_openai_nasmedia_exact += 1
    if not recipients:
        diagnostics.missing_to_cc_headers += 1


def parse_message(
    uid: str,
    message: EmailMessage | Message,
    settings: MailCollectorSettings,
) -> CollectedMail | None:
    from_name, from_email = _single_address(message.get("From", ""))
    to_addresses = _addresses_for_header(message, "To")
    cc_addresses = _addresses_for_header(message, "Cc")
    to_value = _format_addresses(to_addresses)
    cc_value = _format_addresses(cc_addresses)

    if not _matches_filters(
        from_email=from_email,
        to_addresses=to_addresses,
        cc_addresses=cc_addresses,
        target_senders=settings.target_senders,
        target_recipients=settings.target_recipients,
    ):
        return None

    subject = _decode_mime_header(message.get("Subject", "")).strip() or "(제목 없음)"
    body_text, attachment_names, attachment_text = _extract_message_text(message)
    if settings.trim_quoted_replies:
        body_text = _trim_quoted_reply(body_text)
    body_text = _normalize_text(body_text)
    attachment_text = _normalize_text(attachment_text)
    body_text = _clamp(body_text, settings.body_max_chars)
    attachment_text = _clamp(attachment_text, settings.body_max_chars)

    received_at = _message_date(message)
    collected_at_kst = _now_kst()
    message_id = str(message.get("Message-ID", "") or "").strip()
    duplicate_hash = _duplicate_hash(message_id, subject, from_email, received_at, body_text)
    rag_document_id = f"openai-mail-{duplicate_hash[:16]}"
    tags = _mail_tags(subject, body_text, from_email, to_addresses, cc_addresses, settings)

    return CollectedMail(
        collected_at_kst=collected_at_kst,
        received_at=received_at,
        uid=uid,
        message_id=message_id,
        from_name=from_name,
        from_email=from_email,
        to=to_value,
        cc=cc_value,
        subject=subject,
        body_summary=_summary(body_text),
        body_text=body_text,
        attachment_names=", ".join(attachment_names),
        attachment_text=attachment_text,
        tags=", ".join(tags),
        rag_document_id=rag_document_id,
        duplicate_hash=duplicate_hash,
        status="needs_review",
        last_embedded_at="",
    )


def render_mail_markdown(messages: Iterable[CollectedMail]) -> str:
    items = list(messages)
    generated_at = _now_kst()
    lines = [
        "# OpenAI 담당자 이메일 회신 수집 문서",
        "",
        "출처 등급: 나스미디어 내부 자료",
        "출처명: OpenAI 담당자 이메일 회신",
        f"문서 생성일시(KST): {generated_at}",
        "",
        "이 문서는 Daum IMAP에서 읽기 전용으로 수집한 OpenAI 광고 담당자 관련 메일 중",
        "지정 발신자 또는 수신/참조 조건에 맞는 메일만 RAG 인덱싱용으로 정리한 문서입니다.",
        "메일 원문 맥락 확인이 필요한 운영 중 개별 이슈는 담당자 확인을 우선합니다.",
        "",
    ]
    for index, item in enumerate(items, start=1):
        lines.extend(
            [
                f"## {index}. {item.subject}",
                "",
                f"- RAG 문서 ID: {item.rag_document_id}",
                f"- 메일 수신일시: {item.received_at}",
                f"- 발신자: {item.from_name} <{item.from_email}>",
                f"- 수신자: {item.to or '-'}",
                f"- 참조: {item.cc or '-'}",
                f"- Message-ID: {item.message_id or '-'}",
                f"- 중복 해시: {item.duplicate_hash}",
                f"- 태그: {item.tags}",
                "",
                "### 본문",
                "",
                item.body_text or "(본문 텍스트를 추출하지 못했습니다.)",
                "",
            ]
        )
        if item.attachment_names or item.attachment_text:
            lines.extend(
                [
                    "### 첨부",
                    "",
                    f"- 첨부파일명: {item.attachment_names or '-'}",
                    "",
                    item.attachment_text or "(텍스트 첨부 추출 내용 없음)",
                    "",
                ]
            )
    return "\n".join(lines).strip() + "\n"


def write_mail_markdown(messages: Iterable[CollectedMail], path_value: str | Path) -> Path | None:
    messages = list(messages)
    path = Path(path_value)
    if not path.is_absolute():
        path = project_root() / path
    if not messages:
        if path.exists():
            path.unlink()
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_mail_markdown(messages), encoding="utf-8")
    return path


def post_rows_to_sheet(messages: Iterable[CollectedMail], settings: MailCollectorSettings) -> dict:
    rows = [message.to_sheet_row() for message in messages]
    if not rows:
        return {"ok": True, "posted": 0, "skipped": "no_rows"}
    if not settings.webhook_url or not settings.webhook_secret:
        return {"ok": False, "posted": 0, "error": "MAIL_COLLECTOR_SHEETS_WEBHOOK_URL/SECRET not set"}
    response = httpx.post(
        settings.webhook_url,
        json={"secret": settings.webhook_secret, "data": {"rows": rows}},
        timeout=30,
        follow_redirects=True,
    )
    response.raise_for_status()
    try:
        return response.json()
    except json.JSONDecodeError:
        return {"ok": True, "posted": len(rows), "response": response.text[:500]}


def fetch_approved_rows_from_sheet(settings: MailCollectorSettings) -> dict:
    if not settings.webhook_url or not settings.webhook_secret:
        return {
            "ok": False,
            "rows": [],
            "error": "MAIL_COLLECTOR_SHEETS_WEBHOOK_URL/SECRET not set",
        }
    response = httpx.post(
        settings.webhook_url,
        json={"secret": settings.webhook_secret, "action": "approved_for_rag"},
        timeout=30,
        follow_redirects=True,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return {"ok": False, "rows": [], "error": "Unexpected approved rows response"}
    rows = payload.get("rows") or []
    if not isinstance(rows, list):
        return {"ok": False, "rows": [], "error": "Approved rows response did not include rows[]"}
    payload["rows"] = rows
    return payload


def render_approved_mail_markdown(rows: Iterable[dict]) -> str:
    approved_rows = [
        row for row in rows if str(row.get("approved_summary") or "").strip()
    ]
    generated_at = _now_kst()
    lines = [
        "# 승인된 OpenAI 담당자 이메일 확정사항",
        "",
        "출처 등급: 나스미디어 내부 자료",
        "출처명: OpenAI 담당자 이메일 회신 승인본",
        f"문서 생성일시(KST): {generated_at}",
        "",
        "이 문서는 Google Sheet에 영구 누적된 OpenAI 광고 관련 메일 중",
        "관리자가 `review_status=approved_for_rag`로 승인하고 `approved_summary`를 작성한 행만 RAG에 반영한다.",
        "원문 메일 전체를 자동 인덱싱하지 않으며, 이전 내용이 변경된 경우 기존 행은 `superseded` 처리하거나",
        "새 행의 `supersedes_duplicate_hash`에 이전 중복 해시를 기입한다.",
        "",
    ]
    for index, row in enumerate(approved_rows, start=1):
        summary = _normalize_text(str(row.get("approved_summary") or ""))
        title = str(row.get("approved_title") or "").strip() or f"OpenAI 담당자 이메일 승인 사항 {index}"
        duplicate_hash = str(row.get("duplicate_hash") or "").strip()
        source_id = str(row.get("rag_document_id") or "").strip() or (
            f"openai-mail-{duplicate_hash[:16]}" if duplicate_hash else f"openai-mail-approved-{index}"
        )
        lines.extend(
            [
                f"## {index}. {title}",
                "",
                f"- RAG 문서 ID: {source_id}",
                f"- 메일 수신일시: {row.get('received_at') or '-'}",
                f"- 발신자: {row.get('from_name') or '-'} <{row.get('from_email') or '-'}>",
                f"- Message-ID: {row.get('message_id') or '-'}",
                f"- 중복 해시: {duplicate_hash or '-'}",
                f"- 승인자: {row.get('approved_by') or '-'}",
                f"- 승인일시: {row.get('approved_at') or '-'}",
                f"- 대체한 이전 해시: {row.get('supersedes_duplicate_hash') or '-'}",
                "",
                "### 승인 요약",
                "",
                summary,
                "",
            ]
        )
        note = _normalize_text(str(row.get("review_note") or ""))
        if note:
            lines.extend(["### 검토 메모", "", note, ""])
    return "\n".join(lines).strip() + "\n"


def write_approved_mail_markdown(rows: Iterable[dict], path_value: str | Path) -> Path | None:
    rows = [row for row in rows if str(row.get("approved_summary") or "").strip()]
    path = Path(path_value)
    if not path.is_absolute():
        path = project_root() / path
    if not rows:
        if path.exists():
            path.unlink()
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_approved_mail_markdown(rows), encoding="utf-8")
    return path


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _split_email_list(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    raw_items = (value.split(",") if value else list(default))
    normalized = tuple(
        item.strip().lower()
        for item in raw_items
        if item and item.strip()
    )
    return normalized or default


def _raw_message_from_fetch(fetched: list) -> bytes | None:
    for item in fetched:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return None


def _decode_mime_header(value: object) -> str:
    if value is None:
        return ""
    try:
        return str(make_header(decode_header(str(value))))
    except Exception:
        return str(value)


def _single_address(value: object) -> tuple[str, str]:
    decoded = _decode_mime_header(value)
    name, email = parseaddr(decoded)
    return name.strip(), email.strip().lower()


def _addresses_for_header(message: EmailMessage | Message, header_name: str) -> list[tuple[str, str]]:
    headers = [_decode_mime_header(value) for value in message.get_all(header_name, [])]
    addresses: list[tuple[str, str]] = []
    for name, email in getaddresses(headers):
        email = email.strip().lower()
        if email:
            addresses.append((name.strip(), email))
    return addresses


def _format_addresses(addresses: Iterable[tuple[str, str]]) -> str:
    return ", ".join(
        f"{name} <{email}>" if name else email
        for name, email in addresses
    )


def _matches_filters(
    *,
    from_email: str,
    to_addresses: Iterable[tuple[str, str]],
    cc_addresses: Iterable[tuple[str, str]],
    target_senders: tuple[str, ...],
    target_recipients: tuple[str, ...],
) -> bool:
    recipients = {email for _, email in [*to_addresses, *cc_addresses]}
    return from_email in set(target_senders) or bool(recipients.intersection(target_recipients))


def _extract_message_text(message: EmailMessage | Message) -> tuple[str, list[str], str]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachment_names: list[str] = []
    attachment_parts: list[str] = []

    parts = list(message.walk()) if message.is_multipart() else [message]
    for part in parts:
        if part.is_multipart():
            continue
        content_type = part.get_content_type()
        disposition = (part.get_content_disposition() or "").lower()
        filename = _decode_mime_header(part.get_filename() or "").strip()
        is_attachment = disposition == "attachment" or bool(filename)

        if is_attachment:
            if filename:
                attachment_names.append(filename)
            if content_type.startswith("text/"):
                text = _part_text(part)
                if text:
                    attachment_parts.append(f"[{filename or content_type}]\n{text}")
            continue

        text = _part_text(part)
        if not text:
            continue
        if content_type == "text/plain":
            plain_parts.append(text)
        elif content_type == "text/html":
            html_parts.append(_html_to_text(text))

    body_text = "\n\n".join(plain_parts or html_parts)
    attachment_text = "\n\n".join(attachment_parts)
    return body_text, attachment_names, attachment_text


def _part_text(part: Message) -> str:
    try:
        content = part.get_content()
        if isinstance(content, bytes):
            return content.decode(part.get_content_charset() or "utf-8", errors="replace")
        return str(content)
    except Exception:
        payload = part.get_payload(decode=True)
        if not payload:
            return ""
        return payload.decode(part.get_content_charset() or "utf-8", errors="replace")


def _html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</p>", "\n\n", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return html.unescape(value)


def _normalize_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")]
    value = "\n".join(lines)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _trim_quoted_reply(value: str) -> str:
    markers = re.compile(
        r"^(-----Original Message-----|From:|Sent:|To:|Subject:|보낸 사람:|보낸 날짜:|받는 사람:|제목:|On .+ wrote:)",
        re.IGNORECASE,
    )
    kept: list[str] = []
    for line in value.splitlines():
        if kept and markers.match(line.strip()):
            break
        kept.append(line)
    return "\n".join(kept).strip() or value


def _message_date(message: EmailMessage | Message) -> str:
    raw = str(message.get("Date", "") or "").strip()
    if not raw:
        return ""
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            return parsed.isoformat()
        return parsed.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return raw


def _now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def _summary(value: str, *, limit: int = 500) -> str:
    return _clamp(re.sub(r"\s+", " ", value).strip(), limit)


def _clamp(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 15)].rstrip() + "\n...[truncated]"


def _duplicate_hash(
    message_id: str,
    subject: str,
    from_email: str,
    received_at: str,
    body_text: str,
) -> str:
    source = "\n".join([message_id, subject, from_email, received_at, body_text])
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _mail_tags(
    subject: str,
    body_text: str,
    from_email: str,
    to_addresses: Iterable[tuple[str, str]],
    cc_addresses: Iterable[tuple[str, str]],
    settings: MailCollectorSettings,
) -> list[str]:
    tags = ["openai_email"]
    if from_email in settings.target_senders:
        tags.append("official_sender")
    recipients = {email for _, email in [*to_addresses, *cc_addresses]}
    if recipients.intersection(settings.target_recipients):
        tags.append("openai_nasmedia_thread")
    content = f"{subject}\n{body_text}".lower()
    if any(keyword in content for keyword in ("확정", "confirmed", "confirm", "final", "approved")):
        tags.append("confirmation_candidate")
    return tags


def _imap_utf7_encode(value: str) -> str:
    result: list[str] = []
    buffer: list[str] = []

    def flush_buffer() -> None:
        if not buffer:
            return
        raw = "".join(buffer).encode("utf-16-be")
        encoded = base64.b64encode(raw).decode("ascii").rstrip("=").replace("/", ",")
        result.append(f"&{encoded}-")
        buffer.clear()

    for char in value:
        codepoint = ord(char)
        if 0x20 <= codepoint <= 0x7E:
            flush_buffer()
            result.append("&-" if char == "&" else char)
        else:
            buffer.append(char)
    flush_buffer()
    return "".join(result)


def _quote_mailbox(value: str) -> str:
    encoded = _imap_utf7_encode(value)
    if encoded.startswith('"') and encoded.endswith('"'):
        return encoded
    return '"' + encoded.replace('"', '\\"') + '"'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect OpenAI manager emails from Daum IMAP.")
    parser.add_argument("--top", type=int, help="How many recent IMAP messages to inspect.")
    parser.add_argument(
        "--write-rag-doc",
        nargs="?",
        const=DEFAULT_RAG_DOC_PATH,
        help="Legacy/unsafe: write raw matching emails to a temporary kr_ops markdown file.",
    )
    parser.add_argument(
        "--write-approved-rag-doc",
        nargs="?",
        const=DEFAULT_APPROVED_RAG_DOC_PATH,
        help="Fetch manager-approved mail summaries from Google Sheet and write only those to kr_ops.",
    )
    parser.add_argument(
        "--require-approved-summary",
        action="store_true",
        help="Fail approved RAG sync if approved rows exist without approved_summary.",
    )
    parser.add_argument("--post-sheet", action="store_true", help="Post matching rows to Google Sheets webhook.")
    parser.add_argument("--require-sheet", action="store_true", help="Fail if sheet posting is requested but not configured.")
    parser.add_argument("--diagnostics", action="store_true", help="Print safe header-only match counters.")
    parser.add_argument("--verbose-matches", action="store_true", help="Print matched message subjects. Avoid in shared logs.")
    parser.add_argument("--dry-run", action="store_true", help="Print matched subjects without side effects.")
    args = parser.parse_args(argv)

    settings = MailCollectorSettings.from_env(top_override=args.top)

    if args.write_approved_rag_doc:
        approved_payload = fetch_approved_rows_from_sheet(settings)
        if not approved_payload.get("ok"):
            raise RuntimeError(str(approved_payload.get("error") or approved_payload))
        rows = list(approved_payload.get("rows") or [])
        missing_summary = int(approved_payload.get("skippedMissingSummary") or 0)
        if args.require_approved_summary and missing_summary:
            raise RuntimeError(
                f"{missing_summary} approved mail rows are missing approved_summary. "
                "Fill approved_summary or change review_status before RAG sync."
            )
        written = write_approved_mail_markdown(rows, args.write_approved_rag_doc)
        if written:
            print(f"[ok] wrote approved RAG mail document: {written}")
        else:
            print("[ok] no approved mail RAG document written")
        print(
            "[approved-sheet] "
            + json.dumps(
                {
                    "approvedRows": len(rows),
                    "skippedMissingSummary": missing_summary,
                    "supersededRows": int(approved_payload.get("supersededRows") or 0),
                },
                ensure_ascii=False,
            )
        )
        return 0

    diagnostics = MailDiagnostics() if args.diagnostics else None
    messages = collect_matching_messages(settings, diagnostics=diagnostics)
    print(f"[ok] matched OpenAI mail messages: {len(messages)}")
    if diagnostics:
        print(f"[diag] mail scan counters: {json.dumps(diagnostics.to_safe_dict(), ensure_ascii=False)}")
    if args.verbose_matches:
        for item in messages[:10]:
            print(f"- {item.received_at} | {item.from_email} | {item.subject}")

    if args.dry_run:
        return 0

    if args.write_rag_doc:
        written = write_mail_markdown(messages, args.write_rag_doc)
        if written:
            print(f"[ok] wrote RAG mail document: {written}")
        else:
            print("[ok] no matching mail document written")

    should_post = args.post_sheet or bool(settings.webhook_url)
    if should_post:
        result = post_rows_to_sheet(messages, settings)
        if not result.get("ok") and args.require_sheet:
            raise RuntimeError(str(result.get("error") or result))
        print(f"[sheet] {json.dumps(result, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
