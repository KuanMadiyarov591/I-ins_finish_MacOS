"""Лёгкий блок оплаты/комиссии для заявки агента (не биллинг компании)."""

from __future__ import annotations

from typing import Optional

# Типовые агентские % по линейкам (демо)
COMMISSION_PCT = {
    "medical": 10.0,
    "life": 15.0,
    "auto": 8.0,
    "travel": 12.0,
    "home": 10.0,
    "funeral": 12.0,
}

PAYMENT_STATUSES = ("unpaid", "pending", "paid", "overdue")
PAYMENT_METHODS = ("", "card", "cash", "transfer", "installment")


def default_commission_pct(category: Optional[str]) -> float:
    return float(COMMISSION_PCT.get((category or "").lower(), 10.0))


def calc_commission(premium: Optional[int], pct: float) -> int:
    prem = int(premium or 0)
    return int(round(prem * float(pct) / 100.0))
