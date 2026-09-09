"""Данные для вкладки «Анализ» в кабинете актуария.

Ползунки должны отзываться мгновенно, поэтому сервер не считает
распределение заново на каждое движение мыши. Он один раз отдаёт
совокупность значений и готовые срезы, а подгонка, правдоподобие
и чувствительность считаются уже на странице.

Совокупность берётся из исходной таблицы премий, если она на месте:
в базе кабинета лежит только витрина на сто строк, а для оценки
параметров этого мало. Если таблицы нет, работаем по базе.
"""

from __future__ import annotations

import csv
import math
import random
import statistics
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from iins_actuary_app.config import ROOT, SHARED_DATASETS
from iins_actuary_app.models import PremiumCase

PREMIUM_CSV = "03_actuary_03_cgr-premiums-table.csv"
MAX_ROWS = 4000
SCATTER_POINTS = 1200
REF_YEAR = 2024

# Подписи отдаём ключами: страница трёхъязычная, и русский текст
# с сервера ломал бы переключение языка.
FIELDS: List[Dict[str, str]] = [
    {"id": "selected", "key": "an_f_selected", "label": "Отобранная премия"},
    {"id": "indicated", "key": "an_f_indicated", "label": "Индикативная премия"},
    {"id": "current", "key": "an_f_current", "label": "Действующая премия"},
    {"id": "fixed", "key": "an_f_fixed", "label": "Фиксированные расходы"},
    {"id": "gap", "key": "an_f_gap", "label": "Разрыв: отобранная минус индикативная"},
]


# --------------------------------------------------------------- источник
def _csv_path() -> Optional[Path]:
    for base in (SHARED_DATASETS, ROOT / "data", ROOT / "data" / "raw"):
        p = base / PREMIUM_CSV
        if p.is_file():
            return p
    return None


def _num(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _age(raw: Any) -> Optional[float]:
    """Возраст на опорный год. В таблице дата записана как 10/5/1947."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    year = None
    for part in s.replace("-", "/").split("/"):
        if len(part) == 4 and part.isdigit():
            year = int(part)
    if year is None:
        return None
    age = float(REF_YEAR - year)
    if age < 16 or age > 100:
        return None
    return age


def _rows_from_csv(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader):
            if i >= MAX_ROWS * 8:
                break
            out.append(row)
    if len(out) > MAX_ROWS:
        rnd = random.Random(42)
        out = rnd.sample(out, MAX_ROWS)
    return out


def _records_from_csv(path: Path) -> List[Dict[str, Any]]:
    recs: List[Dict[str, Any]] = []
    for row in _rows_from_csv(path):
        sel = _num(row.get("selected_premium"))
        ind = _num(row.get("indicated_premium"))
        if sel is None or ind is None:
            continue
        recs.append({
            "territory": str(row.get("territory") or "").strip() or "—",
            "cgr": str(row.get("cgr") or "").strip() or "—",
            "gender": str(row.get("gender") or "").strip() or "—",
            "age": _age(row.get("birthdate")),
            "ypc": _num(row.get("ypc")),
            "selected": sel,
            "indicated": ind,
            "current": _num(row.get("current_premium")) or 0.0,
            "fixed": _num(row.get("fixed_expenses")) or 0.0,
            "cgr_factor": _num(row.get("cgr_factor")) or 1.0,
        })
    return recs


def _records_from_db(db: Session) -> List[Dict[str, Any]]:
    recs: List[Dict[str, Any]] = []
    for c in db.query(PremiumCase).all():
        sel = float(c.selected_premium or 0.0)
        ind = float(c.indicated_premium or 0.0)
        if sel <= 0 or ind <= 0:
            continue
        recs.append({
            "territory": c.territory or "—",
            "cgr": c.cgr or "—",
            "gender": c.gender or "—",
            "age": float(c.age) if c.age else None,
            "ypc": float(c.ypc or 0.0),
            "selected": sel,
            "indicated": ind,
            "current": float(c.current_premium or 0.0),
            "fixed": float(c.fixed_expenses or 0.0),
            "cgr_factor": float(c.cgr_factor or 1.0),
        })
    return recs


# ------------------------------------------------------------- статистика
def _summary(values: Sequence[float]) -> Dict[str, Any]:
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    n = len(clean)
    if n < 2:
        return {"n": n}
    mean = statistics.fmean(clean)
    sd = statistics.pstdev(clean)
    ordered = sorted(clean)
    positive = [v for v in clean if v > 0]
    log_mu = log_sd = None
    if len(positive) >= 2:
        logs = [math.log(v) for v in positive]
        log_mu = statistics.fmean(logs)
        log_sd = statistics.pstdev(logs)
    return {
        "n": n,
        "mean": mean,
        "sd": sd,
        "min": ordered[0],
        "max": ordered[-1],
        "median": ordered[n // 2],
        "log_mu": log_mu,
        "log_sd": log_sd,
        "positive_share": round(len(positive) / n, 4),
    }


def _group(recs: Sequence[Dict[str, Any]], key: str, limit: int = 14) -> List[Dict[str, Any]]:
    acc: Dict[str, Dict[str, float]] = {}
    for r in recs:
        k = str(r.get(key) or "—")
        a = acc.setdefault(k, {"n": 0.0, "sel": 0.0, "ind": 0.0, "fix": 0.0})
        a["n"] += 1
        a["sel"] += r["selected"]
        a["ind"] += r["indicated"]
        a["fix"] += r["fixed"]
    out = []
    for k, a in acc.items():
        n = a["n"] or 1.0
        out.append({
            "label": k,
            "n": int(a["n"]),
            "selected": round(a["sel"] / n, 2),
            "indicated": round(a["ind"] / n, 2),
            "fixed": round(a["fix"] / n, 2),
            "ratio": round(a["sel"] / a["ind"], 4) if a["ind"] else None,
            "sum_selected": round(a["sel"], 2),
            "sum_indicated": round(a["ind"], 2),
        })
    out.sort(key=lambda x: x["n"], reverse=True)
    return out[:limit]


def _by_age(recs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[int, Dict[str, float]] = {}
    for r in recs:
        age = r.get("age")
        if age is None:
            continue
        b = int(age // 5) * 5
        a = buckets.setdefault(b, {"n": 0.0, "sel": 0.0, "ind": 0.0})
        a["n"] += 1
        a["sel"] += r["selected"]
        a["ind"] += r["indicated"]
    out = []
    for b in sorted(buckets):
        a = buckets[b]
        n = a["n"] or 1.0
        out.append({
            "label": f"{b}–{b + 4}",
            "from": b,
            "n": int(a["n"]),
            "selected": round(a["sel"] / n, 2),
            "indicated": round(a["ind"] / n, 2),
        })
    return out


def _trend(points: Sequence[Tuple[float, float]]) -> Dict[str, Any]:
    """Обычная линейная регрессия: нужна только чтобы показать направление."""
    pts = [(float(x), float(y)) for x, y in points if x is not None and y is not None]
    n = len(pts)
    if n < 3:
        return {}
    mx = statistics.fmean([p[0] for p in pts])
    my = statistics.fmean([p[1] for p in pts])
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    if sxx <= 0:
        return {}
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    b = sxy / sxx
    a = my - b * mx
    syy = sum((p[1] - my) ** 2 for p in pts)
    r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else None
    return {"a": round(a, 4), "b": round(b, 4), "r2": round(r2, 4) if r2 is not None else None, "n": n}


# ------------------------------------------------------------------ пакет
def _build(recs: List[Dict[str, Any]], source_kind: str) -> Dict[str, Any]:
    for r in recs:
        r["gap"] = round(r["selected"] - r["indicated"], 2)

    samples = {
        f["id"]: [round(float(r[f["id"]]), 2) for r in recs]
        for f in FIELDS
    }
    summaries = {k: _summary(v) for k, v in samples.items()}

    scatter_src = [r for r in recs if r.get("age") is not None]
    if len(scatter_src) > SCATTER_POINTS:
        scatter_src = random.Random(7).sample(scatter_src, SCATTER_POINTS)
    scatter = [[r["age"], r["selected"]] for r in scatter_src]

    sum_sel = sum(r["selected"] for r in recs)
    sum_ind = sum(r["indicated"] for r in recs)
    sum_fix = sum(r["fixed"] for r in recs)

    return {
        "source_kind": source_kind,
        "source_rows": len(recs),
        "fields": FIELDS,
        "samples": samples,
        "summaries": summaries,
        "by_territory": _group(recs, "territory"),
        "by_cgr": _group(recs, "cgr"),
        "by_gender": _group(recs, "gender", limit=4),
        "by_age": _by_age(recs),
        "scatter": scatter,
        "scatter_trend": _trend([(p[0], p[1]) for p in scatter]),
        "totals": {
            "n": len(recs),
            "sum_selected": round(sum_sel, 2),
            "sum_indicated": round(sum_ind, 2),
            "sum_fixed": round(sum_fix, 2),
            "balance_gap": round(sum_sel - sum_ind, 2),
            "ratio": round(sum_sel / sum_ind, 4) if sum_ind else None,
            "avg_cgr_factor": round(statistics.fmean([r["cgr_factor"] for r in recs]), 4) if recs else None,
        },
    }


@lru_cache(maxsize=1)
def _cached_csv_package() -> Optional[Dict[str, Any]]:
    path = _csv_path()
    if path is None:
        return None
    recs = _records_from_csv(path)
    if len(recs) < 30:
        return None
    return _build(recs, "csv")


def package(db: Session) -> Dict[str, Any]:
    data = _cached_csv_package()
    if data is not None:
        return data
    recs = _records_from_db(db)
    if not recs:
        return {
            "source_kind": "none",
            "source_rows": 0,
            "fields": FIELDS,
            "samples": {f["id"]: [] for f in FIELDS},
            "summaries": {},
            "by_territory": [], "by_cgr": [], "by_gender": [], "by_age": [],
            "scatter": [], "scatter_trend": {},
            "totals": {"n": 0},
        }
    return _build(recs, "db")
