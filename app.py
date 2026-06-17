from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from rag_chatbot.config import project_root


app = FastAPI(title="Nasmedia ChatGPT Ads RAG", version="0.1.0")
app.mount(
    "/images",
    StaticFiles(directory=project_root() / "public" / "images", check_dir=False),
    name="images",
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


@app.get("/slides", include_in_schema=False)
def slides_page() -> FileResponse:
    return _index_file()


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    try:
        from rag_chatbot.qa import answer_question

        result = answer_question(request.question)
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return IntakeResponse(**result)


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
