from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from iins_client_app.auth import get_current_user
from iins_client_app.config import get_settings
from iins_client_app.models import User
from iins_client_app.schemas import RagAskIn, RagAskOut, RagStatusOut
from iins_client_app.services import rag_service

router = APIRouter(prefix="/api/rag", tags=["rag"])


@router.get("/status", response_model=RagStatusOut)
def rag_status(_: User = Depends(get_current_user)) -> RagStatusOut:
    data = rag_service.status_payload()
    return RagStatusOut(**data)


@router.post("/ask", response_model=RagAskOut)
def rag_ask(body: RagAskIn, _: User = Depends(get_current_user)) -> RagAskOut:
    try:
        result = rag_service.rag_query(
            body.question,
            top_k=body.top_k,
            policy_hint=body.policy_hint,
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
    return RagAskOut(**result)


@router.get("/document/{source}")
def rag_document(source: str, _: User = Depends(get_current_user)) -> FileResponse:
    """Return only a PDF that is registered in the active vector store."""
    safe_name = Path(source).name
    if safe_name != source or not safe_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Недопустимое имя документа")
    store = rag_service.get_vector_store()
    if store is None or safe_name not in store.sources:
        raise HTTPException(status_code=404, detail="Документ отсутствует в активной базе знаний")
    path = get_settings().rag_vector_db_path.parent.parent / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Файл документа не найден")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=safe_name,
        content_disposition_type="inline",
    )


@router.post("/reload")
def rag_reload(_: User = Depends(get_current_user)) -> dict:
    idx = rag_service.reload_index()
    return {"ok": True, "chunks": len(idx.chunks)}
