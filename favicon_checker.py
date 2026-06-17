from __future__ import annotations

import asyncio
import io
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import httpx
from PIL import Image


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
FETCH_TIMEOUT_SECONDS = 10
MAX_IMAGE_BYTES = 8 * 1024 * 1024


Verdict = Literal["pass", "warn", "fail", "wait"]


@dataclass(frozen=True)
class FaviconCheckResult:
    input_url: str
    normalized_url: str
    verdict: Verdict
    badge: str
    size: str
    width: int | None
    height: int | None
    format: str
    background: str
    reason: str
    action: str
    http_status: int | None
    preview_url: str | None

    def to_dict(self) -> dict:
        return {
            "input_url": self.input_url,
            "normalized_url": self.normalized_url,
            "verdict": self.verdict,
            "badge": self.badge,
            "size": self.size,
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "background": self.background,
            "reason": self.reason,
            "action": self.action,
            "http_status": self.http_status,
            "preview_url": self.preview_url,
        }


def _badge(verdict: Verdict) -> str:
    return {"pass": "✅", "warn": "⚠️", "fail": "🚫", "wait": "⏳"}[verdict]


def _result(
    *,
    input_url: str,
    normalized_url: str = "",
    verdict: Verdict,
    size: str = "-",
    width: int | None = None,
    height: int | None = None,
    format: str = "-",
    background: str = "-",
    reason: str,
    action: str,
    http_status: int | None = None,
    preview_url: str | None = None,
) -> FaviconCheckResult:
    return FaviconCheckResult(
        input_url=input_url,
        normalized_url=normalized_url or input_url,
        verdict=verdict,
        badge=_badge(verdict),
        size=size,
        width=width,
        height=height,
        format=format,
        background=background,
        reason=reason,
        action=action,
        http_status=http_status,
        preview_url=preview_url,
    )


def split_favicon_inputs(values: list[str]) -> list[str]:
    inputs: list[str] = []
    for value in values:
        parts = re.split(r"[\n,]+", value)
        inputs.extend(part.strip() for part in parts)
    return inputs


def _is_waiting_value(value: str) -> bool:
    stripped = value.strip()
    return stripped == "" or stripped.upper() == "TBD"


def _normalize_url(raw_url: str) -> str:
    value = raw_url.strip()
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or re.search(r"\s", value):
        raise ValueError("URL 형식 오류")
    return value


def _looks_like_viewer_link(url: str) -> bool:
    lowered = url.lower()
    parsed = urlparse(url)
    return (
        "drive.google.com/file/" in lowered
        or "drive.google.com/drive/folders/" in lowered
        or "docs.google.com" in lowered
        or "usp=sharing" in parsed.query.lower()
        or parsed.path.lower().endswith("/view")
        or "/view/" in parsed.path.lower()
    )


def _filename_low_res_hint(url: str) -> str | None:
    lowered = url.lower()
    if re.search(r"(?:^|[-_])(?:16|32|48|64|128)x(?:16|32|48|64|128)(?:[-_.]|$)", lowered):
        return "파일명상 저해상도 의심"
    if re.search(r"(?:favicon[-_])(?:16|32|48|64|128)(?:[-_.]|$)", lowered):
        return "파일명상 저해상도 의심"
    return None


def _content_type_format(content_type: str, image_format: str | None = None) -> str:
    if image_format:
        return image_format.lower()
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type.startswith("image/"):
        return media_type.removeprefix("image/") or "-"
    return "-"


def _has_transparency(image: Image.Image) -> bool:
    if image.mode in {"RGBA", "LA"}:
        alpha = image.getchannel("A")
        extrema = alpha.getextrema()
        return bool(extrema and extrema[0] < 255)

    if image.mode == "P" and "transparency" in image.info:
        return True

    return False


def _select_largest_frame(image: Image.Image) -> Image.Image:
    if image.format == "ICO" and getattr(image, "ico", None):
        sizes = sorted(image.ico.sizes(), key=lambda item: item[0] * item[1], reverse=True)
        if sizes:
            return image.ico.getimage(sizes[0])

    best = image.copy()
    best_area = best.width * best.height
    frame_count = getattr(image, "n_frames", 1)
    for frame_index in range(frame_count):
        try:
            image.seek(frame_index)
        except EOFError:
            break
        frame = image.copy()
        area = frame.width * frame.height
        if area > best_area:
            best = frame
            best_area = area
    return best


def _inspect_image(
    raw_url: str,
    normalized_url: str,
    content: bytes,
    content_type: str,
    http_status: int,
) -> FaviconCheckResult:
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            selected = _select_largest_frame(image)
            selected.load()
            width, height = selected.size
            image_format = _content_type_format(content_type, image.format)
            transparent = _has_transparency(selected)
    except Exception:
        return _result(
            input_url=raw_url,
            normalized_url=normalized_url,
            verdict="fail",
            format=_content_type_format(content_type),
            reason="이미지 파일을 열 수 없음 — 링크 또는 파일 형식 확인 필요",
            action="공개 접근 가능한 PNG/ICO/WebP 직접 이미지 URL로 교체",
            http_status=http_status,
        )

    failures: list[str] = []
    warnings: list[str] = []
    hint = _filename_low_res_hint(normalized_url)
    if hint:
        warnings.append(hint)

    if width < 256 or height < 256:
        failures.append(f"{width}×{height} — 256 미달")
    if width != height:
        warnings.append("비정사각형 — 원형 크롭 시 왜곡 가능")
    if transparent:
        warnings.append("투명 배경 — 흰 배경 권장")

    background = "투명" if transparent else "불투명"
    size = f"{width}x{height}"

    if failures:
        reason = ", ".join(failures + warnings)
        return _result(
            input_url=raw_url,
            normalized_url=normalized_url,
            verdict="fail",
            size=size,
            width=width,
            height=height,
            format=image_format,
            background=background,
            reason=reason,
            action="256×256 이상 정사각형, 흰 배경 직접 이미지로 교체",
            http_status=http_status,
            preview_url=normalized_url,
        )

    if warnings:
        return _result(
            input_url=raw_url,
            normalized_url=normalized_url,
            verdict="warn",
            size=size,
            width=width,
            height=height,
            format=image_format,
            background=background,
            reason=", ".join(warnings),
            action="정사각형 흰 배경 이미지로 보정 후 OpenAI 광고팀 검수 권장",
            http_status=http_status,
            preview_url=normalized_url,
        )

    return _result(
        input_url=raw_url,
        normalized_url=normalized_url,
        verdict="pass",
        size=size,
        width=width,
        height=height,
        format=image_format,
        background=background,
        reason="직접 이미지 링크 + 256×256 이상 + 정사각형 + 불투명 배경",
        action="OpenAI 광고팀 최종 검수로 등록 가능 여부 확인",
        http_status=http_status,
        preview_url=normalized_url,
    )


def _http_error_result(
    raw_url: str,
    normalized_url: str,
    status_code: int,
    body: str,
) -> FaviconCheckResult:
    body_lower = body.lower()
    if status_code == 403 and any(
        token in body_lower for token in ("cloudflare", "challenge", "just a moment")
    ):
        return _result(
            input_url=raw_url,
            normalized_url=normalized_url,
            verdict="warn",
            reason="방화벽 차단 — 개발팀 확인",
            action="방화벽/안티봇 정책에서 공개 이미지 접근 허용 확인",
            http_status=status_code,
        )

    if 400 <= status_code < 500:
        return _result(
            input_url=raw_url,
            normalized_url=normalized_url,
            verdict="fail",
            reason="파비콘 없음/경로 오류 — URL 교체 필요",
            action="공개 접근 가능한 직접 이미지 URL로 교체",
            http_status=status_code,
        )

    if status_code >= 500:
        return _result(
            input_url=raw_url,
            normalized_url=normalized_url,
            verdict="warn",
            reason="서버 오류 — 재확인 필요",
            action="잠시 후 재시도하거나 광고주 개발팀 확인",
            http_status=status_code,
        )

    return _result(
        input_url=raw_url,
        normalized_url=normalized_url,
        verdict="warn",
        reason=f"확인 불가(HTTP {status_code}) — 개발팀 확인 필요",
        action="응답 코드와 이미지 URL 확인 필요",
        http_status=status_code,
    )


async def check_favicon_url(raw_url: str, client: httpx.AsyncClient) -> FaviconCheckResult:
    if _is_waiting_value(raw_url):
        return _result(
            input_url=raw_url,
            verdict="wait",
            reason="광고주 회신 대기",
            action="파비콘 직접 이미지 URL 수령 후 재검사",
        )

    try:
        normalized_url = _normalize_url(raw_url)
    except ValueError as exc:
        return _result(
            input_url=raw_url,
            verdict="fail",
            reason=f"{exc} — 링크 확인 필요",
            action="https://example.com/favicon.png 형식의 직접 이미지 URL 입력",
        )

    if _looks_like_viewer_link(normalized_url):
        return _result(
            input_url=raw_url,
            normalized_url=normalized_url,
            verdict="fail",
            reason="공유 뷰어 링크 — 직접 이미지 URL로 교체 필요",
            action="공개 접근 가능한 PNG/ICO/WebP 직접 이미지 URL 제공 요청",
        )

    try:
        response = await client.get(normalized_url)
    except httpx.TimeoutException:
        return _result(
            input_url=raw_url,
            normalized_url=normalized_url,
            verdict="warn",
            reason="접근 불가 — 재시도/개발팀 확인",
            action="잠시 후 재시도하거나 광고주 개발팀에 접근성 확인 요청",
        )
    except httpx.RequestError:
        return _result(
            input_url=raw_url,
            normalized_url=normalized_url,
            verdict="warn",
            reason="접근 불가 — 재시도/개발팀 확인",
            action="URL/DNS/방화벽 상태 확인 필요",
        )

    content_type = response.headers.get("content-type", "")
    body_preview = response.text[:5000] if "text" in content_type.lower() else ""

    if response.status_code != 200:
        return _http_error_result(
            raw_url,
            normalized_url,
            response.status_code,
            body_preview,
        )

    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type == "text/html":
        return _result(
            input_url=raw_url,
            normalized_url=normalized_url,
            verdict="fail",
            reason="공유 뷰어 링크 — 직접 이미지 URL로 교체 필요",
            action="이미지 파일 자체가 열리는 공개 직접 URL 제공 요청",
            http_status=response.status_code,
        )
    if not media_type.startswith("image/"):
        return _result(
            input_url=raw_url,
            normalized_url=normalized_url,
            verdict="fail",
            reason="이미지가 아닌 응답 — 링크 확인 필요",
            action="Content-Type이 image/*인 직접 이미지 URL로 교체",
            http_status=response.status_code,
        )

    return _inspect_image(
        raw_url,
        normalized_url,
        response.content[:MAX_IMAGE_BYTES],
        content_type,
        response.status_code,
    )


async def check_favicon_urls(urls: list[str]) -> list[FaviconCheckResult]:
    inputs = split_favicon_inputs(urls)
    if not inputs:
        inputs = [""]

    timeout = httpx.Timeout(FETCH_TIMEOUT_SECONDS)
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    async with httpx.AsyncClient(
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
    ) as client:
        return await asyncio.gather(
            *(check_favicon_url(value, client) for value in inputs)
        )
