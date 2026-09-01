from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from iins_legal_app.auth import hash_password
from iins_legal_app.config import ROOT, SHARED_DATASETS
from iins_legal_app.models import LegalCase, User
from iins_legal_app.services import case_eval as evalsvc

FIRST_NAMES = [
    "Айгерим", "Данияр", "Мария", "Алексей", "Сауле", "Иван", "Алина", "Ерлан",
    "Ольга", "Нурлан", "Камила", "Сергей", "Жанна", "Тимур", "Анна",
]
LAST_NAMES = [
    "Касымова", "Омаров", "Иванова", "Петров", "Нурланова", "Смирнов", "Абдуллаева",
    "Сериков", "Козлова", "Жумабеков", "Бекова", "Морозов", "Ахметова", "Ли", "Ким",
]

CSV_SPECS = [
    ("pi", "04_lawyer_30_personal_injury_verdicts.csv", 36),
    ("imr", "04_lawyer_31_imr_health_appeals.csv", 36),
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


def _summary_pi(f: dict[str, Any], name: str) -> tuple[str, str]:
    injury = f.get("injuryType") or f.get("injury_type") or "injury"
    practice = f.get("practiceArea") or f.get("practice_area") or "PI"
    title = f"Телесный вред · {name}"
    parts = [
        f"Клиент: {name}",
        f"Практика: {practice}",
        f"Травма: {injury}",
        f"Штат: {f.get('state', '—')}",
        f"Год: {f.get('year', '—')}",
        f"Исход: {f.get('resultType', '—')}",
        f"Сумма: {f.get('amount', '—')}",
        f"Вердикт: {f.get('is_verdict', '—')}",
    ]
    return title, " · ".join(str(p) for p in parts)


def _summary_imr(f: dict[str, Any], name: str) -> tuple[str, str]:
    appeal = f.get("appeal_type") or "IMR"
    title = f"Апелляция IMR · {name}"
    text = str(f.get("text") or "")[:180].replace("\n", " ")
    parts = [
        f"Клиент: {name}",
        f"Тип: {appeal}",
        f"Решение: {f.get('decision', '—')}",
        f"Overturn: {f.get('y_overturn', '—')}",
        f"Фрагмент: {text}…",
    ]
    return title, " · ".join(str(p) for p in parts)


def _status_for(n: int, rec: str) -> str:
    cycle = n % 7
    if cycle == 0:
        return "in_review"
    if cycle == 1:
        return "escalated"
    if cycle == 2 and rec == "accept":
        return "accepted"
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
                    full_name="Админ Legal Hub",
                    role="admin",
                ),
                User(
                    username="lawyer",
                    password_hash=hash_password("lawyer123"),
                    full_name="Юрист Айгуль",
                    role="lawyer",
                ),
            ]
        )
        db.commit()

    if db.query(LegalCase).count() > 0:
        return

    cases: list[LegalCase] = []
    n = 0
    for line, filename, take in CSV_SPECS:
        path = _resolve_csv(filename)
        if path is None:
            for i in range(min(8, take)):
                features = _synthetic(line, i)
                cases.append(_build_case(line, features, n))
                n += 1
            continue

        df = pd.read_csv(path, nrows=4000)
        sample = df
        half = max(1, take // 2)
        if line == "pi" and "is_verdict" in sample.columns:
            mask = sample["is_verdict"].astype(str).isin(["1", "1.0", "True", "true"])
            pos = sample[mask].head(half)
            neg = sample[~mask].head(take - len(pos))
            sample = pd.concat([pos, neg]).head(take)
        elif line == "imr" and "y_overturn" in sample.columns:
            mask = sample["y_overturn"].astype(str).isin(["1", "1.0", "True", "true"])
            pos = sample[mask].head(half)
            neg = sample[~mask].head(take - len(pos))
            sample = pd.concat([pos, neg]).head(take)
        else:
            sample = sample.head(take)

        cols = list(sample.columns)
        for _, row in sample.iterrows():
            features = _row_to_features(row, cols)
            # Keep IMR text truncated in raw storage
            if line == "imr" and "text" in features:
                features["text"] = str(features["text"])[:2500]
                features["text_len"] = len(str(row.get("text") or ""))
            cases.append(_build_case(line, features, n))
            n += 1

    db.add_all(cases)
    db.commit()


def _synthetic(line: str, i: int) -> dict[str, Any]:
    if line == "imr":
        return {
            "text": "Patient appeal regarding denied authorization for specialist therapy. " * (3 + i % 4),
            "appeal_type": ["Pharmacy", "Surgery", "Imaging", "Experimental"][i % 4],
            "decision": "overturned" if i % 3 == 0 else "upheld",
            "y_overturn": 1 if i % 3 == 0 else 0,
            "text_len": 400 + i * 120,
        }
    return {
        "state": "Illinois",
        "year": 2020 + (i % 6),
        "practiceArea": "Medical Malpractice" if i % 2 == 0 else "Personal Injury",
        "injuryType": "Wrongful Death" if i % 4 == 0 else "Other",
        "resultType": "verdict" if i % 3 == 0 else "settlement",
        "amount": 500_000 * (1 + i),
        "is_verdict": 1 if i % 3 == 0 else 0,
        "log_amount": 12.5 + i * 0.3,
        "description": f"Synthetic PI case #{i} with alleged damages.",
    }


def _build_case(line: str, features: dict[str, Any], n: int) -> LegalCase:
    name = f"{FIRST_NAMES[n % len(FIRST_NAMES)]} {LAST_NAMES[n % len(LAST_NAMES)]}"
    result = evalsvc.evaluate(line, features)
    if line == "imr":
        title, summary = _summary_imr(features, name)
    else:
        title, summary = _summary_pi(features, name)

    keep_keys = list(features.keys())[:20]
    raw = {k: features[k] for k in keep_keys}
    status = _status_for(n, str(result["recommendation"]))

    return LegalCase(
        external_id=f"LH-{line.upper()}-{n:04d}",
        line=line,
        title=title,
        applicant_summary=summary,
        risk_score=float(result["risk_score"]),
        recommendation=str(result["recommendation"]),
        decision_status=status,
        urgency_signal=bool(result.get("urgency_signal")),
        key_factors=json.dumps(result.get("reasons") or [], ensure_ascii=False),
        raw_features=json.dumps(raw, ensure_ascii=False, default=str),
        notes="",
        decision_by="system" if status in {"accepted", "declined"} else "",
    )
