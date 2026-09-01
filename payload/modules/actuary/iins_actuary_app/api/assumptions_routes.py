from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from iins_actuary_app.auth import require_actuary
from iins_actuary_app.db import get_db
from iins_actuary_app.models import CgrDefinition, TerritoryDefinition, User

router = APIRouter(prefix="/api/assumptions", tags=["assumptions"])


@router.get("")
def assumptions_bundle(
    limit_cgr: int = Query(120, ge=1, le=500),
    limit_terr: int = Query(120, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_actuary),
) -> Dict[str, Any]:
    cgr_rows: List[CgrDefinition] = db.query(CgrDefinition).order_by(CgrDefinition.id).limit(limit_cgr).all()
    terr_rows: List[TerritoryDefinition] = (
        db.query(TerritoryDefinition).order_by(TerritoryDefinition.id).limit(limit_terr).all()
    )
    return {
        "cgr_definitions": [
            {
                "id": r.id,
                "cgr": r.cgr,
                "aa": r.aa,
                "bb": r.bb,
                "cc": r.cc,
                "va": r.va,
                "dd": r.dd,
                "hh": r.hh,
                "ss": r.ss,
            }
            for r in cgr_rows
        ],
        "territory_definitions": [
            {
                "id": r.id,
                "county": r.county,
                "county_code": r.county_code,
                "territory": r.territory,
                "zipcode": r.zipcode,
                "town": r.town,
                "area": r.area,
            }
            for r in terr_rows
        ],
        "counts": {
            "cgr": len(cgr_rows),
            "territory": len(terr_rows),
        },
    }
