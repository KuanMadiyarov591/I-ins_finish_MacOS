from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from iins_underwriter_app.auth import hash_password
from iins_underwriter_app.config import ROOT, SHARED_DATASETS
from iins_underwriter_app.models import UnderwritingCase, User
from iins_underwriter_app.services import risk_service as risk

FIRST_NAMES = [
    "Айгерим", "Данияр", "Мария", "Алексей", "Сауле", "Иван", "Алина", "Ерлан",
    "Ольга", "Нурлан", "Камила", "Сергей", "Жанна", "Тимур", "Анна",
]
LAST_NAMES = [
    "Касымова", "Омаров", "Иванова", "Петров", "Нурланова", "Смирнов", "Абдуллаева",
    "Сериков", "Козлова", "Жумабеков", "Бекова", "Морозов", "Ахметова", "Ли", "Ким",
]

CSV_SPECS = [
    ("auto", "02_underwriter_01_car_insurance_claim.csv", 24),
    ("fraud", "02_underwriter_27_insurance_claims_fraud.csv", 22),
    ("motor", "02_underwriter_motor_011_fe.csv", 24),
]


def _resolve_csv(name: str) -> Path | None:
    for base in (SHARED_DATASETS, ROOT / "data", ROOT / "data" / "raw"):
        p = base / name
        if p.is_file():
            return p
    return None


def _row_to_features(row: pd.Series, cols: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in cols:
        v = row.get(c)
        if pd.isna(v):
            continue
        if hasattr(v, "item"):
            try:
                v = v.item()
            except Exception:  # noqa: BLE001
                v = str(v)
        out[c] = v
    return out


def _summary_auto(f: dict[str, Any], name: str) -> tuple[str, str]:
    title = f"Личное авто · {name}"
    parts = [
        f"Возраст: {f.get('AGE', '—')}",
        f"Опыт: {f.get('DRIVING_EXPERIENCE', '—')}",
        f"ТС: {f.get('VEHICLE_TYPE', '—')} / {f.get('VEHICLE_YEAR', '—')}",
        f"Нарушения: {f.get('SPEEDING_VIOLATIONS', 0)}, нетрезвое: {f.get('DUIS', 0)}, ДТП: {f.get('PAST_ACCIDENTS', 0)}",
        f"Кредит: {f.get('CREDIT_SCORE', '—')}",
    ]
    return title, " · ".join(str(p) for p in parts)


def _summary_fraud(f: dict[str, Any], name: str) -> tuple[str, str]:
    title = f"Мошенничество · {name}"
    parts = [
        f"Возраст: {f.get('age', '—')}",
        f"Инцидент: {f.get('incident_type', '—')}",
        f"Тяжесть: {f.get('incident_severity', '—')}",
        f"Мошенничество: {f.get('fraud_reported', '—')}",
        f"Премия: {f.get('policy_annual_premium', '—')}",
        f"Клиент мес.: {f.get('months_as_customer', '—')}",
    ]
    return title, " · ".join(str(p) for p in parts)


def _summary_motor(f: dict[str, Any], name: str) -> tuple[str, str]:
    make = f.get("MAKE", "—")
    vtype = f.get("TYPE_VEHICLE", "—")
    title = f"Парк ТС · {make} {vtype}"
    parts = [
        f"Заявитель: {name}",
        f"Использование: {f.get('USAGE', '—')}",
        f"Премия: {f.get('PREMIUM', '—')}",
        f"Сумма: {f.get('INSURED_VALUE', '—')}",
        f"Убыток: {f.get('has_claim', 0)}",
        f"Возраст ТС: {f.get('vehicle_age', '—')}",
    ]
    return title, " · ".join(str(p) for p in parts)


def _status_for(n: int, rec: str) -> str:
    # Mix of open / closed demo statuses
    cycle = n % 7
    if cycle == 0:
        return "in_review"
    if cycle == 1:
        return "referred"
    if cycle == 2 and rec == "approve":
        return "approved"
    if cycle == 3 and rec == "decline":
        return "declined"
    return "new"


def seed_if_empty(db: Session) -> None:
    if db.query(User).count() == 0:
        db.add_all(
            [
                User(
                    username="admin",
                    password_hash=hash_password("admin123"),
                    full_name="Админ Underwriter Desk",
                    role="admin",
                ),
                User(
                    username="underwriter",
                    password_hash=hash_password("uw123"),
                    full_name="Андеррайтер Айгуль",
                    role="underwriter",
                ),
            ]
        )
        db.commit()

    if db.query(UnderwritingCase).count() > 0:
        return

    cases: list[UnderwritingCase] = []
    n = 0
    for line, filename, take in CSV_SPECS:
        path = _resolve_csv(filename)
        if path is None:
            # Synthetic fallback so demo still boots
            for i in range(min(8, take)):
                features = _synthetic(line, i)
                cases.append(_build_case(line, features, n))
                n += 1
            continue

        # Read enough rows to mix risk / non-risk examples
        df = pd.read_csv(path, nrows=4000)
        sample = df
        half = max(1, take // 2)
        if line == "fraud" and "fraud_reported" in sample.columns:
            mask = sample["fraud_reported"].astype(str).isin(["1", "1.0", "True", "true"])
            fraud_pos = sample[mask].head(half)
            fraud_neg = sample[~mask].head(take - len(fraud_pos))
            sample = pd.concat([fraud_pos, fraud_neg]).head(take)
        elif line == "auto" and "OUTCOME" in sample.columns:
            mask = sample["OUTCOME"].astype(float) >= 1
            bad = sample[mask].head(half)
            good = sample[~mask].head(take - len(bad))
            sample = pd.concat([bad, good]).head(take)
        elif line == "motor" and "has_claim" in sample.columns:
            mask = sample["has_claim"].astype(str).isin(["1", "1.0"])
            claims = sample[mask].head(half)
            rest = sample[~mask].head(take - len(claims))
            sample = pd.concat([claims, rest]).head(take)
        else:
            sample = sample.head(take)

        cols = list(sample.columns)
        for _, row in sample.iterrows():
            features = _row_to_features(row, cols)
            cases.append(_build_case(line, features, n))
            n += 1

    db.add_all(cases)
    db.commit()


def _synthetic(line: str, i: int) -> dict[str, Any]:
    if line == "fraud":
        return {
            "age": 30 + i,
            "months_as_customer": 6 + i * 3,
            "fraud_reported": 1 if i % 3 == 0 else 0,
            "incident_severity": "Major Damage" if i % 2 == 0 else "Minor Damage",
            "police_report_available": "NO" if i % 2 == 0 else "YES",
            "property_damage": "YES",
            "witnesses": i % 3,
            "number_of_vehicles_involved": 1 + (i % 3),
            "bodily_injuries": i % 2,
            "umbrella_limit": 0,
            "policy_annual_premium": 1200 + i * 50,
            "incident_type": "Single Vehicle Collision",
        }
    if line == "motor":
        return {
            "MAKE": "HYUNDAI",
            "TYPE_VEHICLE": "Automobile",
            "USAGE": "Private" if i % 2 else "Taxi",
            "PREMIUM": 3000 + i * 200,
            "INSURED_VALUE": 200000,
            "has_claim": 1 if i % 4 == 0 else 0,
            "CLAIM_PAID": 50000 if i % 4 == 0 else 0,
            "vehicle_age": 5 + i,
            "SEATS_NUM": 4,
            "CCM_TON": 1600,
        }
    return {
        "AGE": "16-25" if i % 4 == 0 else "26-39",
        "DRIVING_EXPERIENCE": "0-9y",
        "VEHICLE_TYPE": "sedan",
        "VEHICLE_YEAR": "before 2015" if i % 3 == 0 else "after 2015",
        "SPEEDING_VIOLATIONS": i % 4,
        "DUIS": 1 if i % 5 == 0 else 0,
        "PAST_ACCIDENTS": i % 3,
        "CREDIT_SCORE": 0.3 + (i % 5) * 0.1,
        "ANNUAL_MILEAGE": 10000 + i * 1500,
        "VEHICLE_OWNERSHIP": 1.0,
        "OUTCOME": 1.0 if i % 3 == 0 else 0.0,
    }


def _build_case(line: str, features: dict[str, Any], n: int) -> UnderwritingCase:
    name = f"{FIRST_NAMES[n % len(FIRST_NAMES)]} {LAST_NAMES[n % len(LAST_NAMES)]}"
    result = risk.evaluate(line, features)
    if line == "fraud":
        title, summary = _summary_fraud(features, name)
    elif line == "motor":
        title, summary = _summary_motor(features, name)
    else:
        title, summary = _summary_auto(features, name)

    # Keep raw features compact
    keep_keys = list(features.keys())[:18]
    raw = {k: features[k] for k in keep_keys}

    return UnderwritingCase(
        external_id=f"UW-{line[:3].upper()}-{n:04d}",
        line=line,
        title=title,
        applicant_summary=summary,
        risk_score=float(result["risk_score"]),
        recommendation=str(result["recommendation"]),
        decision_status=_status_for(n, str(result["recommendation"])),
        fraud_signal=bool(result.get("fraud_signal")),
        key_factors=json.dumps(result.get("reasons") or [], ensure_ascii=False),
        raw_features=json.dumps(raw, ensure_ascii=False, default=str),
        notes="",
        decision_by="system" if _status_for(n, str(result["recommendation"])) in {"approved", "declined"} else "",
    )
