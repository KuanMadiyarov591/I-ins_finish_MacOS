from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from iins_agent_app.auth import require_agent
from iins_agent_app.db import get_db
from iins_agent_app.models import Client, PolicyProduct, User
from iins_agent_app.services import recommend_service

router = APIRouter(prefix="/api/recommend", tags=["recommend"])


@router.get("/client/{client_id}")
def recommend_client(
    client_id: int,
    top_k: int = Query(5, ge=1, le=10),
    lang: str = Query("ru", pattern="^(ru|kk|en)$"),
    db: Session = Depends(get_db),
    _: User = Depends(require_agent),
) -> Dict[str, Any]:
    client = (
        db.query(Client)
        .options(joinedload(Client.tags))
        .filter(Client.id == client_id)
        .first()
    )
    if not client:
        raise HTTPException(404, "Клиент не найден")
    products = db.query(PolicyProduct).filter(PolicyProduct.is_active.is_(True)).all()
    return recommend_service.recommend_for_client(client, products, top_k=top_k, lang=lang)


@router.get("/status")
def recommend_status(_: User = Depends(require_agent)) -> Dict[str, Any]:
    from iins_agent_app.services import lead_scoring_service as scoring

    st = scoring.status()
    return {
        "ready": st.get("ready"),
        "models": st.get("models"),
        "relevant": ["travel_propensity"],
        "excluded": ["auto_claim_risk", "fraud", "actuary"],
        "metrics": st.get("metrics"),
    }
