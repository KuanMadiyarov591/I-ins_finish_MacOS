from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from iins_actuary_app.auth import hash_password
from iins_actuary_app.config import ROOT, SHARED_DATASETS
from iins_actuary_app.models import CgrDefinition, PremiumCase, TerritoryDefinition, User

PREMIUM_CSV = "03_actuary_03_cgr-premiums-table.csv"
CGR_CSV = "03_actuary_04_cgr-definitions-table.csv"
TERR_CSV = "03_actuary_06_territory-definitions-table.csv"
SEED_PREMIUMS = 100
SEED_CGR = 80
SEED_TERR = 80
REF_YEAR = 2024


def _resolve_csv(name: str) -> Path | None:
    for base in (SHARED_DATASETS, ROOT / "data", ROOT / "data" / "raw"):
        p = base / name
        if p.is_file():
            return p
    return None


def _to_native(v: Any) -> Any:
    if pd.isna(v):
        return None
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:  # noqa: BLE001
            return str(v)
    return v


def _age_from_birthdate(raw: Any, ref_year: int = REF_YEAR) -> float:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return 40.0
    ts = pd.to_datetime(raw, errors="coerce")
    if pd.isna(ts):
        return 40.0
    age = float(ref_year - int(ts.year))
    return max(16.0, min(100.0, age))


def seed_if_empty(db: Session) -> None:
    if db.query(User).count() == 0:
        db.add_all(
            [
                User(
                    username="admin",
                    password_hash=hash_password("admin123"),
                    full_name="Админ Actuary Desk",
                    role="admin",
                ),
                User(
                    username="actuary",
                    password_hash=hash_password("actuary123"),
                    full_name="Актуарий Айгуль",
                    role="actuary",
                ),
            ]
        )
        db.commit()

    if db.query(PremiumCase).count() == 0:
        _seed_premiums(db)

    if db.query(CgrDefinition).count() == 0:
        _seed_cgr(db)

    if db.query(TerritoryDefinition).count() == 0:
        _seed_territories(db)


def _seed_premiums(db: Session) -> None:
    path = _resolve_csv(PREMIUM_CSV)
    cases: list[PremiumCase] = []
    if path is None:
        for i in range(SEED_PREMIUMS):
            cases.append(_synthetic_premium(i))
    else:
        df = pd.read_csv(path, nrows=8000)
        # diversify by territory/gender
        sample = df.sample(n=min(SEED_PREMIUMS, len(df)), random_state=42)
        for n, (_, row) in enumerate(sample.iterrows()):
            cases.append(_row_to_premium(row, n))
    db.add_all(cases)
    db.commit()


def _seed_cgr(db: Session) -> None:
    path = _resolve_csv(CGR_CSV)
    rows: list[CgrDefinition] = []
    if path is None:
        for i in range(min(20, SEED_CGR)):
            code = f"X{i:02d}"
            rows.append(
                CgrDefinition(
                    cgr=code,
                    aa=0.1 + i * 0.001,
                    bb=0.1,
                    cc=0.1,
                    va=0.1,
                    dd=0.1,
                    hh=0.1,
                    ss=0.1,
                    payload=json.dumps({"cgr": code}, ensure_ascii=False),
                )
            )
    else:
        df = pd.read_csv(path, nrows=SEED_CGR)
        for _, row in df.iterrows():
            payload = {c: _to_native(row.get(c)) for c in df.columns}
            rows.append(
                CgrDefinition(
                    cgr=str(_to_native(row.get("cgr")) or ""),
                    aa=float(_to_native(row.get("aa")) or 0),
                    bb=float(_to_native(row.get("bb")) or 0),
                    cc=float(_to_native(row.get("cc")) or 0),
                    va=float(_to_native(row.get("va")) or 0),
                    dd=float(_to_native(row.get("dd")) or 0),
                    hh=float(_to_native(row.get("hh")) or 0),
                    ss=float(_to_native(row.get("ss")) or 0),
                    payload=json.dumps(payload, ensure_ascii=False, default=str),
                )
            )
    db.add_all(rows)
    db.commit()


def _seed_territories(db: Session) -> None:
    path = _resolve_csv(TERR_CSV)
    rows: list[TerritoryDefinition] = []
    if path is None:
        for i in range(min(20, SEED_TERR)):
            terr = str(600 + i)
            rows.append(
                TerritoryDefinition(
                    county="DEMO",
                    county_code=str(i),
                    territory=terr,
                    zipcode=f"20{i:03d}",
                    town=f"Town {i}",
                    area=str(100 + i),
                    payload=json.dumps({"territory": terr}, ensure_ascii=False),
                )
            )
    else:
        df = pd.read_csv(path, nrows=SEED_TERR)
        for _, row in df.iterrows():
            payload = {c: _to_native(row.get(c)) for c in df.columns}
            rows.append(
                TerritoryDefinition(
                    county=str(_to_native(row.get("county")) or ""),
                    county_code=str(_to_native(row.get("county_code")) or ""),
                    territory=str(_to_native(row.get("territory")) or ""),
                    zipcode=str(_to_native(row.get("zipcode")) or ""),
                    town=str(_to_native(row.get("town")) or ""),
                    area=str(_to_native(row.get("area")) or ""),
                    payload=json.dumps(payload, ensure_ascii=False, default=str),
                )
            )
    db.add_all(rows)
    db.commit()


def _row_to_premium(row: pd.Series, n: int) -> PremiumCase:
    birth = _to_native(row.get("birthdate"))
    age = _age_from_birthdate(birth)
    features = {
        "territory": str(_to_native(row.get("territory")) or ""),
        "gender": str(_to_native(row.get("gender")) or ""),
        "birthdate": str(birth or ""),
        "age": age,
        "ypc": float(_to_native(row.get("ypc")) or 0),
        "indicated_premium": float(_to_native(row.get("indicated_premium")) or 0),
        "selected_premium": float(_to_native(row.get("selected_premium")) or 0),
        "fixed_expenses": float(_to_native(row.get("fixed_expenses")) or 0),
        "cgr": str(_to_native(row.get("cgr")) or ""),
        "cgr_factor": float(_to_native(row.get("cgr_factor")) or 1),
        # leakage — display only
        "current_premium": float(_to_native(row.get("current_premium")) or 0),
    }
    return PremiumCase(
        external_id=f"AD-PREM-{n:04d}",
        territory=features["territory"],
        gender=features["gender"],
        birthdate=features["birthdate"],
        age=age,
        ypc=features["ypc"],
        indicated_premium=features["indicated_premium"],
        selected_premium=features["selected_premium"],
        fixed_expenses=features["fixed_expenses"],
        cgr=features["cgr"],
        cgr_factor=features["cgr_factor"],
        current_premium=features["current_premium"],
        underlying_premium=float(_to_native(row.get("underlying_premium")) or 0),
        raw_features=json.dumps(features, ensure_ascii=False, default=str),
    )


def _synthetic_premium(i: int) -> PremiumCase:
    gender = "M" if i % 2 == 0 else "F"
    age = 25.0 + (i % 50)
    indicated = 600.0 + i * 12.5
    selected = indicated * (0.95 + (i % 7) * 0.01)
    features = {
        "territory": str(601 + (i % 20)),
        "gender": gender,
        "birthdate": f"1/1/{int(REF_YEAR - age)}",
        "age": age,
        "ypc": float(i % 6),
        "indicated_premium": indicated,
        "selected_premium": selected,
        "fixed_expenses": 150.0 + (i % 5) * 5,
        "cgr": f"C{i % 12:02d}",
        "cgr_factor": 1.0,
        "current_premium": indicated * 0.98,
    }
    return PremiumCase(
        external_id=f"AD-PREM-{i:04d}",
        territory=features["territory"],
        gender=gender,
        birthdate=features["birthdate"],
        age=age,
        ypc=features["ypc"],
        indicated_premium=indicated,
        selected_premium=selected,
        fixed_expenses=features["fixed_expenses"],
        cgr=features["cgr"],
        cgr_factor=1.0,
        current_premium=features["current_premium"],
        underlying_premium=indicated * 0.85,
        raw_features=json.dumps(features, ensure_ascii=False),
    )
