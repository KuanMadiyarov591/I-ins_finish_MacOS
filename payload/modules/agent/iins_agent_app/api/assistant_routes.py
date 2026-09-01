from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from iins_agent_app.auth import require_agent
from iins_agent_app.config import get_settings
from iins_agent_app.db import get_db
from iins_agent_app.models import Application, Client, PolicyProduct, User
from iins_agent_app.services import assistant_service, coach_service, rag_service
from iins_agent_app.services.priority_service import PRIORITY_SHORT

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class AssistantAskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    top_k: int = Field(default=4, ge=1, le=8)
    lang: str = Field(default="ru", pattern="^(ru|kk|en)$")
    mode: str = Field(default="auto", pattern="^(auto|extractive|ollama|qwen|gigachat)$")
    client_id: Optional[int] = None
    policy_hint: str = ""


class CoachIn(BaseModel):
    action: str = Field(pattern="^(call_prep|email_draft|objection|follow_up|client_brief)$")
    client_id: int
    objection: str = Field(default="", max_length=500)
    lang: str = Field(default="ru", pattern="^(ru|kk|en)$")
    mode: str = Field(default="auto", pattern="^(auto|extractive|ollama|qwen|gigachat)$")


def _client_context(db: Session, client_id: int) -> str:
    client = (
        db.query(Client)
        .options(joinedload(Client.tags))
        .filter(Client.id == client_id)
        .first()
    )
    if not client:
        return ""
    tags = ", ".join(t.name for t in (client.tags or [])) or "—"
    open_apps = (
        db.query(Application)
        .filter(
            Application.client_id == client_id,
            Application.status.in_(["draft", "checklist", "submitted"]),
        )
        .count()
    )
    return (
        f"Контекст CRM клиента: {client.full_name} ({client.external_id}); "
        f"{PRIORITY_SHORT.get(client.priority, client.priority)}; статус {client.status}; "
        f"теги [{tags}]; open_apps={open_apps}; "
        f"travel_propensity={client.buy_probability}; tier={client.propensity_tier}."
    )


@router.get("/client/{client_id}")
def assistant_client_summary(
    client_id: int,
    lang: str = "ru",
    db: Session = Depends(get_db),
    _: User = Depends(require_agent),
) -> Dict[str, Any]:
    client = (
        db.query(Client)
        .options(joinedload(Client.tags), joinedload(Client.applications))
        .filter(Client.id == client_id)
        .first()
    )
    if not client:
        raise HTTPException(404, "Клиент не найден")
    apps = (
        db.query(Application)
        .options(joinedload(Application.product))
        .filter(Application.client_id == client_id)
        .all()
    )
    products = db.query(PolicyProduct).all()
    return assistant_service.client_summary(client, apps, products, lang=lang)


@router.get("/rag/status")
def assistant_rag_status(_: User = Depends(require_agent)) -> Dict[str, Any]:
    return rag_service.status_payload()


@router.post("/ask")
def assistant_ask(
    body: AssistantAskIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_agent),
) -> Dict[str, Any]:
    hint = body.policy_hint.strip()
    if body.client_id:
        ctx = _client_context(db, body.client_id)
        if ctx:
            hint = f"{hint} {ctx}".strip()
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


@router.get("/rag/document/{source}")
def assistant_rag_document(source: str, _: User = Depends(require_agent)) -> FileResponse:
    safe_name = Path(source).name
    if safe_name != source or not safe_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Недопустимое имя документа")
    store = rag_service.get_vector_store()
    if store is None or safe_name not in store.sources:
        raise HTTPException(status_code=404, detail="Документ отсутствует в активной базе знаний")
    path = get_settings().rag_vector_db_path.parent.parent / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Файл документа не найден")
    return FileResponse(path, media_type="application/pdf", filename=safe_name, content_disposition_type="inline")


@router.post("/coach")
def assistant_coach(
    body: CoachIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_agent),
) -> Dict[str, Any]:
    try:
        return coach_service.run_coach(
            db,
            action=body.action,
            client_id=body.client_id,
            objection=body.objection,
            lang=body.lang,
            mode=body.mode,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Ошибка coach: {exc}") from exc


@router.post("/rag/reload")
def assistant_rag_reload(_: User = Depends(require_agent)) -> Dict[str, Any]:
    idx = rag_service.reload_index()
    return {"ok": True, "chunks": len(idx.chunks)}
