from __future__ import annotations

import asyncio
from io import BytesIO
import os
from pathlib import Path
import re
from uuid import uuid4
from typing import Any

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from rag_chatbot.config import project_root


app = FastAPI(title="Nasmedia ChatGPT Ads RAG", version="0.1.0")
app.mount(
    "/images",
    StaticFiles(directory=project_root() / "public" / "images", check_dir=False),
    name="images",
)
app.mount(
    "/dev-assets",
    StaticFiles(directory=project_root() / "dev" / "assets", check_dir=False),
    name="dev-assets",
)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]]


class CheckRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, max_length=100)


class CheckResultResponse(BaseModel):
    input_url: str
    normalized_url: str
    origin: str
    path: str
    robots_url: str
    verdict: str
    badge: str
    reason: str
    action: str
    http_status: int | None
    robots_txt: str
    firewall_hint: bool = False
    firewall_badge: str | None = None
    bot_details: list[dict[str, str]] = Field(default_factory=list)


class FaviconCheckRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, max_length=100)


class FaviconCheckResultResponse(BaseModel):
    input_url: str
    normalized_url: str
    verdict: str
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


class IngestResponse(BaseModel):
    counts: dict[str, int]


class IntakeResponse(BaseModel):
    receipt_number: str
    submitted_at_kst: str
    mail_sent: bool | None = None
    mail_error: str | None = None
    mail_sender: str | None = None
    mail_recipient: str | None = None
    mail_cc: str | None = None
    mail_quota_remaining: int | None = None


class WorkbookInspectResponse(BaseModel):
    ok: bool
    sheets: dict[str, Any]
    errors: list[str]
    warnings: list[str] = Field(default_factory=list)
    data: dict[str, Any] | None = None


class ImageUploadResponse(BaseModel):
    image_url: str
    width: int
    height: int
    content_type: str


class NoticeConfigRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    body_html: str | None = Field(default=None, max_length=8000)
    modal_background: str | None = Field(default="#ffffff", max_length=20)
    bullets: list[str] = Field(default_factory=list, max_length=20)
    source_label: str = Field(..., min_length=1, max_length=200)
    source_url: str = Field(..., min_length=1, max_length=300)
    enabled: bool = True


class SlideContentItemRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=120)
    value: str = Field(default="", max_length=1200)
    deck: str | None = Field(default="", max_length=40)
    label: str | None = Field(default="", max_length=200)
    default: str | None = Field(default="", max_length=1200)
    multiline: bool | None = False
    alt: str | None = Field(default="", max_length=300)
    caption: str | None = Field(default="", max_length=300)


class SlideContentRequest(BaseModel):
    items: list[SlideContentItemRequest] = Field(default_factory=list, max_length=240)
    images: list[SlideContentItemRequest] = Field(default_factory=list, max_length=80)


class MailReviewUpdateRequest(BaseModel):
    duplicate_hash: str = Field(..., min_length=8, max_length=128)
    review_status: str = Field(..., min_length=1, max_length=40)
    review_note: str | None = Field(default="", max_length=2000)
    approved_title: str | None = Field(default="", max_length=300)
    approved_summary: str | None = Field(default="", max_length=8000)
    approved_by: str | None = Field(default="", max_length=80)
    supersedes_duplicate_hash: str | None = Field(default="", max_length=128)


class VisitRequest(BaseModel):
    page: str = Field(..., min_length=1, max_length=80)
    label: str | None = Field(default=None, max_length=120)


class AdsApiKeyRequest(BaseModel):
    advertiser_name: str = Field(..., min_length=1, max_length=120)
    ads_api_key: str | None = Field(default="", max_length=500)
    conversion_api_key: str | None = Field(default="", max_length=500)
    enabled: bool = True


PAGE_LABELS = {
    "root": "메인",
    "chat": "광고 Q&A",
    "crawler": "랜딩 URL 검사",
    "favicon": "파비콘 검사",
    "intake": "소재 업로드",
    "slides": "광고주 안내 자료",
    "setupGuide": "캠페인 세팅 가이드",
    "pixelGuide": "픽셀 설치 가이드",
}


def _admin_password() -> str:
    return os.getenv("ADMIN_PASSWORD") or "nas2026@"


def _require_admin(request: Request) -> None:
    provided = request.headers.get("x-admin-password", "")
    if provided != _admin_password():
        raise HTTPException(status_code=403, detail="관리자 비밀번호가 올바르지 않습니다.")


def _validation_error_details(exc: ValidationError) -> list[dict[str, Any]]:
    return exc.errors(include_url=False, include_input=False, include_context=False)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _index_file() -> FileResponse:
    return FileResponse(project_root() / "templates" / "index.html")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return _index_file()


@app.get("/checker", include_in_schema=False)
def checker_page() -> FileResponse:
    return _index_file()


@app.get("/rag", include_in_schema=False)
def rag_page() -> FileResponse:
    return _index_file()


@app.get("/intake", include_in_schema=False)
def intake_page() -> FileResponse:
    return _index_file()


@app.get("/creative-upload-draft", include_in_schema=False)
def creative_upload_draft_page() -> FileResponse:
    return FileResponse(project_root() / "templates" / "creative_upload_draft.html")


@app.get("/ads-api-draft", include_in_schema=False)
def ads_api_draft_page() -> FileResponse:
    return FileResponse(project_root() / "templates" / "ads_api_draft.html")


@app.get("/slides", include_in_schema=False)
def slides_page() -> FileResponse:
    return _index_file()


@app.get("/admin", include_in_schema=False)
def admin_page() -> FileResponse:
    return FileResponse(project_root() / "templates" / "admin.html")


@app.get("/dev", include_in_schema=False)
def dev_index_page() -> FileResponse:
    return FileResponse(project_root() / "dev" / "index.html")


@app.get("/dev/admin", include_in_schema=False)
def dev_admin_page() -> FileResponse:
    return FileResponse(project_root() / "dev" / "admin.html")


@app.get("/dev/creative-upload-draft", include_in_schema=False)
def dev_creative_upload_draft_page() -> FileResponse:
    return FileResponse(project_root() / "dev" / "creative_upload_draft.html")


@app.get("/api/notice", include_in_schema=False)
def public_notice() -> dict[str, Any]:
    from admin_store import get_notice_config

    return get_notice_config()


@app.post("/api/analytics/visit", include_in_schema=False)
def analytics_visit(request: VisitRequest) -> dict[str, Any]:
    from admin_store import record_page_visit

    raw_page = (request.page or "root").strip()
    page = raw_page[:80] or "root"
    label = (request.label or "").strip()[:120] or PAGE_LABELS.get(page, page)
    return record_page_visit(page, label)


@app.get("/api/admin/notice", include_in_schema=False)
def admin_notice(request: Request) -> dict[str, Any]:
    from admin_store import get_notice_config

    _require_admin(request)
    return get_notice_config()


@app.post("/api/admin/notice", include_in_schema=False)
def update_admin_notice(request: Request, notice: NoticeConfigRequest) -> dict[str, Any]:
    from admin_store import save_notice_config

    _require_admin(request)
    return save_notice_config(notice.model_dump())


@app.get("/api/guide-slides", include_in_schema=False)
def public_guide_slides() -> dict[str, Any]:
    from admin_store import get_slide_content

    return get_slide_content()


@app.get("/api/admin/guide-slides", include_in_schema=False)
def admin_guide_slides(request: Request) -> dict[str, Any]:
    from admin_store import get_slide_content

    _require_admin(request)
    return get_slide_content()


@app.post("/api/admin/guide-slides", include_in_schema=False)
def update_admin_guide_slides(request: Request, slides: SlideContentRequest) -> dict[str, Any]:
    from admin_store import save_slide_content

    _require_admin(request)
    return save_slide_content(slides.model_dump())


@app.post("/api/admin/guide-image", response_model=ImageUploadResponse, include_in_schema=False)
async def upload_admin_guide_image(request: Request, file: UploadFile = File(...)) -> ImageUploadResponse:
    _require_admin(request)

    supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "openai-ad-assets").strip()
    if not supabase_url or not service_role_key:
        raise HTTPException(
            status_code=503,
            detail="이미지 업로드 저장소가 아직 설정되지 않았습니다. 공개 직접 이미지 URL을 입력해 주세요.",
        )

    suffix_by_type = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }
    content_type = file.content_type or ""
    suffix = suffix_by_type.get(content_type)
    if not suffix:
        raise HTTPException(status_code=400, detail="PNG, JPG, WEBP 이미지만 업로드할 수 있습니다.")

    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="안내자료 이미지는 8MB 이하만 업로드할 수 있습니다.")

    try:
        from PIL import Image

        image = Image.open(BytesIO(data))
        width, height = image.size
    except Exception as exc:
        raise HTTPException(status_code=400, detail="이미지 파일을 열 수 없습니다.") from exc
    if width < 240 or height < 160 or width > 4096 or height > 4096:
        raise HTTPException(status_code=400, detail="안내자료 이미지는 240×160 이상, 4096×4096 이하만 업로드할 수 있습니다.")

    safe_stem = re.sub(r"[^0-9A-Za-z._-]+", "-", Path(file.filename or "guide-image").stem).strip("-")
    object_name = f"guide-slides/{uuid4().hex}-{safe_stem or 'guide-image'}{suffix}"
    upload_url = f"{supabase_url}/storage/v1/object/{bucket}/{object_name}"
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": content_type,
        "x-upsert": "false",
    }
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.post(upload_url, content=data, headers=headers)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Supabase Storage 업로드 실패(HTTP {response.status_code})")

    public_url = f"{supabase_url}/storage/v1/object/public/{bucket}/{object_name}"
    return ImageUploadResponse(
        image_url=public_url,
        width=width,
        height=height,
        content_type=content_type,
    )


@app.get("/api/admin/analytics", include_in_schema=False)
def admin_analytics(request: Request) -> dict[str, Any]:
    from admin_store import get_visit_analytics

    _require_admin(request)
    return get_visit_analytics(request.query_params.get("period", "30"))


@app.get("/api/admin/ads-api-keys", include_in_schema=False)
def admin_ads_api_keys(request: Request) -> dict[str, Any]:
    from admin_store import list_ads_api_keys

    _require_admin(request)
    return list_ads_api_keys()


@app.post("/api/admin/ads-api-keys", include_in_schema=False)
def admin_save_ads_api_key(request: Request, payload: AdsApiKeyRequest) -> dict[str, Any]:
    from admin_store import upsert_ads_api_key

    _require_admin(request)
    try:
        return upsert_ads_api_key(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/admin/ads-api-keys/{advertiser_name}", include_in_schema=False)
def admin_delete_ads_api_key(advertiser_name: str, request: Request) -> dict[str, Any]:
    from admin_store import delete_ads_api_key

    _require_admin(request)
    try:
        return delete_ads_api_key(advertiser_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/admin/ads-dashboard", include_in_schema=False)
async def admin_ads_dashboard(request: Request) -> dict[str, Any]:
    from rag_chatbot.ads_api import fetch_ads_dashboard

    _require_admin(request)
    start_date = str(request.query_params.get("start_date") or "") or None
    end_date = str(request.query_params.get("end_date") or "") or None
    detail_scope = str(request.query_params.get("detail_scope") or "") or None
    detail_id = str(request.query_params.get("detail_id") or "") or None
    advertiser_name = str(request.query_params.get("advertiser_name") or "").strip()
    api_key = None
    if advertiser_name:
        from admin_store import get_ads_api_key

        api_key = get_ads_api_key(advertiser_name)
        if not api_key:
            return {
                "ok": False,
                "configured": False,
                "advertiser_name": advertiser_name,
                "error": f"{advertiser_name} Ads API 키가 등록되어 있지 않거나 비활성 상태입니다.",
            }
    return await fetch_ads_dashboard(
        start_date=start_date,
        end_date=end_date,
        detail_scope=detail_scope,
        detail_id=detail_id,
        api_key=api_key,
        advertiser_name=advertiser_name,
    )


@app.get("/api/admin/official-changes", include_in_schema=False)
def admin_official_changes(request: Request) -> dict[str, Any]:
    from admin_store import list_official_guide_changes

    _require_admin(request)
    try:
        limit = int(str(request.query_params.get("limit") or "80"))
    except ValueError:
        limit = 80
    return list_official_guide_changes(limit=limit)


@app.get("/api/admin/mail-review", include_in_schema=False)
def admin_mail_review(request: Request) -> dict[str, Any]:
    from admin_store import list_mail_review_rows

    _require_admin(request)
    status_filter = str(request.query_params.get("status") or "")
    try:
        limit = int(str(request.query_params.get("limit") or "100"))
    except ValueError:
        limit = 100
    return list_mail_review_rows(status_filter=status_filter, limit=limit)


@app.post("/api/admin/mail-review/update", include_in_schema=False)
def admin_update_mail_review(request: Request, update: MailReviewUpdateRequest) -> dict[str, Any]:
    from admin_store import update_mail_review_row

    _require_admin(request)
    try:
        return update_mail_review_row(update.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    try:
        from rag_chatbot.qa import answer_question

        result = answer_question(request.question)
        try:
            from admin_store import record_chat_question

            record_chat_question(request.question, result.get("answer", ""), result.get("sources", []))
        except Exception:
            pass
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ChatResponse(**result)


@app.post("/check", response_model=list[CheckResultResponse])
async def check(request: CheckRequest) -> list[CheckResultResponse]:
    try:
        from checker import check_urls

        results = await check_urls(request.urls)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return [CheckResultResponse(**result.to_dict()) for result in results]


@app.post("/check-favicon", response_model=list[FaviconCheckResultResponse])
async def check_favicon(
    request: FaviconCheckRequest,
) -> list[FaviconCheckResultResponse]:
    try:
        from favicon_checker import check_favicon_urls

        results = await check_favicon_urls(request.urls)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return [FaviconCheckResultResponse(**result.to_dict()) for result in results]


@app.post("/intake", response_model=IntakeResponse)
async def intake(request: Request) -> IntakeResponse:
    try:
        from intake import IntakeSubmission, forward_intake_to_sheet

        payload = await request.json()
        submission = IntakeSubmission.model_validate(payload)
        client_key = request.client.host if request.client else "unknown"
        result = await forward_intake_to_sheet(submission, client_key=client_key)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=_validation_error_details(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return IntakeResponse(**result)


@app.post("/intake/workbook", include_in_schema=False)
async def intake_workbook(request: Request) -> StreamingResponse:
    try:
        from intake import IntakeSubmission, create_workbook_bytes

        payload = await request.json()
        submission = IntakeSubmission.model_validate(payload)
        workbook_bytes = create_workbook_bytes(submission)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=_validation_error_details(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    filename = "openai_ads_bulk_upload.xlsx"
    return StreamingResponse(
        BytesIO(workbook_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/intake/inspect-workbook", response_model=WorkbookInspectResponse, include_in_schema=False)
async def inspect_intake_workbook(file: UploadFile = File(...)) -> WorkbookInspectResponse:
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="xlsx 파일만 업로드할 수 있습니다.")
    try:
        from intake import inspect_workbook_bytes

        content = await file.read()
        if len(content) > 8 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="파일은 8MB 이하만 업로드할 수 있습니다.")
        result = inspect_workbook_bytes(content)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"워크북을 읽을 수 없습니다: {exc}") from exc
    return WorkbookInspectResponse(**result)


@app.post("/intake/upload-image", response_model=ImageUploadResponse, include_in_schema=False)
async def upload_intake_image(file: UploadFile = File(...)) -> ImageUploadResponse:
    supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "openai-ad-assets").strip()
    if not supabase_url or not service_role_key:
        raise HTTPException(
            status_code=503,
            detail="이미지 업로드 저장소가 아직 설정되지 않았습니다. 공개 직접 이미지 URL을 입력해 주세요.",
        )

    content_type = file.content_type or ""
    if content_type not in {"image/png", "image/jpeg"}:
        raise HTTPException(status_code=400, detail="PNG 또는 JPG 이미지만 첨부할 수 있습니다.")
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="이미지 파일은 5MB 이하만 첨부할 수 있습니다.")

    try:
        from PIL import Image

        image = Image.open(BytesIO(data))
        width, height = image.size
    except Exception as exc:
        raise HTTPException(status_code=400, detail="이미지 파일을 열 수 없습니다.") from exc
    if width != height:
        raise HTTPException(status_code=400, detail="이미지는 정사각형이어야 합니다.")
    if width < 640 or height < 640 or width > 1200 or height > 1200:
        raise HTTPException(status_code=400, detail="이미지는 640×640 이상, 1200×1200 이하이어야 합니다.")

    suffix = ".png" if content_type == "image/png" else ".jpg"
    safe_stem = re.sub(r"[^0-9A-Za-z._-]+", "-", Path(file.filename or "image").stem).strip("-")
    object_name = f"creative-upload/{uuid4().hex}-{safe_stem or 'image'}{suffix}"
    upload_url = f"{supabase_url}/storage/v1/object/{bucket}/{object_name}"
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": content_type,
        "x-upsert": "false",
    }
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.post(upload_url, content=data, headers=headers)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Supabase Storage 업로드 실패(HTTP {response.status_code})")

    public_url = f"{supabase_url}/storage/v1/object/public/{bucket}/{object_name}"
    return ImageUploadResponse(
        image_url=public_url,
        width=width,
        height=height,
        content_type=content_type,
    )


@app.post("/admin/reindex", response_model=IngestResponse, include_in_schema=False)
async def admin_reindex(request: Request) -> IngestResponse:
    token = os.getenv("INGEST_TOKEN")
    provided = request.headers.get("x-ingest-token")
    if not token or provided != token:
        raise HTTPException(status_code=404, detail="Not found")

    try:
        from rag_chatbot.ingestion import ingest_collections

        counts = await asyncio.to_thread(ingest_collections)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return IngestResponse(counts=counts)
