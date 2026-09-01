from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from iins_legal_app.auth import require_lawyer
from iins_legal_app.models import User
from iins_legal_app.services import guidelines_service as guidelines

router = APIRouter(prefix="/api", tags=["guidelines"])


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=3, ge=1, le=5)


@router.get("/guidelines")
def list_docs(user: User = Depends(require_lawyer)) -> Dict[str, Any]:
    return {"items": guidelines.list_guidelines(), "status": guidelines.status()}


@router.post("/guidelines/search")
def search_docs(body: SearchIn, user: User = Depends(require_lawyer)) -> Dict[str, Any]:
    return {"query": body.query, "hits": guidelines.search(body.query, top_k=body.top_k)}


@router.get("/guidelines/search/q")
def search_q(
    q: str = Query(..., min_length=1),
    top_k: int = Query(3, ge=1, le=5),
    user: User = Depends(require_lawyer),
) -> Dict[str, Any]:
    return {"query": q, "hits": guidelines.search(q, top_k=top_k)}


@router.get("/guidelines/{doc_id}")
def get_doc(doc_id: str, user: User = Depends(require_lawyer)) -> Dict[str, Any]:
    doc = guidelines.get_guideline(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")
    return doc
