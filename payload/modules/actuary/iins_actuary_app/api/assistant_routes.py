from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from iins_actuary_app.auth import require_actuary
from iins_actuary_app.config import get_settings
from iins_actuary_app.models import User
from iins_actuary_app.services import rag_service

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    top_k: int = Field(default=4, ge=1, le=8)
    lang: str = Field(default="ru", pattern="^(ru|kk|en)$")
    mode: str = Field(default="auto", pattern="^(auto|extractive|ollama|qwen|gigachat)$")
    policy_hint: str = ""
    case_id: Optional[int] = None


@router.get("/rag/status")
def rag_status(_: User = Depends(require_actuary)) -> Dict[str, Any]:
    return rag_service.status_payload()


@router.get("/rag/document/{source}")
def rag_document(source: str, _: User = Depends(require_actuary)) -> FileResponse:
    """Return an indexed PDF inline; filenames outside the RAG manifest are rejected."""
    if source != source.strip() or source != Path(source).name or not source.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Некорректное имя документа")
    store = rag_service.get_vector_store()
    if store is None or source not in store.sources:
        raise HTTPException(status_code=404, detail="Документ отсутствует в подключённой базе знаний")
    path = get_settings().rag_vector_db_path.parent.parent / source
    if not path.is_file():
        raise HTTPException(status_code=404, detail="PDF-файл не найден")
    return FileResponse(path, media_type="application/pdf", content_disposition_type="inline", filename=source)


@router.post("/ask")
def assistant_ask(body: AskIn, _: User = Depends(require_actuary)) -> Dict[str, Any]:
    hint = body.policy_hint.strip()
    if body.case_id:
        hint = f"{hint} case_id={body.case_id}".strip()
    try:
        return rag_service.rag_query(
            body.question,
            top_k=body.top_k,
            policy_hint=hint,
            lang=body.lang,
            mode=body.mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Ошибка RAG: {exc}") from exc


@router.post("/rag/reload")
def rag_reload(_: User = Depends(require_actuary)) -> Dict[str, Any]:
    rag_service.reload_index()
    return {"ok": True, **rag_service.status_payload()}
