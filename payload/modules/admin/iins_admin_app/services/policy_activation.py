"""Активация полиса клиента при одобрении заявки."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session, joinedload

from iins_admin_app.models import (
    ClientDocument,
    CustomerPolicy,
    Notification,
    PolicyApplication,
    PremiumPayment,
)


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # 29 февраля
        return d.replace(month=2, day=28, year=d.year + years)


def _policy_number(application_id: int, customer_id: int) -> str:
    return f"ID-{customer_id:04d}-{application_id:05d}"


def activate_policy_on_approval(db: Session, application: PolicyApplication) -> CustomerPolicy | None:
    """Создаёт CustomerPolicy + график платежей + уведомление. Идемпотентно."""
    if application.status != "Approved":
        return None

    existing = (
        db.query(CustomerPolicy)
        .filter(CustomerPolicy.application_id == application.id)
        .first()
    )
    if existing:
        return existing

    app = (
        db.query(PolicyApplication)
        .options(joinedload(PolicyApplication.policy), joinedload(PolicyApplication.customer))
        .filter(PolicyApplication.id == application.id)
        .one()
    )
    catalog = app.policy
    start = date.today()
    years = max(1, int(catalog.tenure or 1))
    end = _add_years(start, years)

    cp = CustomerPolicy(
        customer_id=app.customer_id,
        catalog_policy_id=catalog.id,
        application_id=app.id,
        policy_number=_policy_number(app.id, app.customer_id),
        start_date=start,
        end_date=end,
        premium=catalog.premium,
        sum_assurance=catalog.sum_assurance,
        status="Active",
    )
    db.add(cp)
    db.flush()

    for i in range(years):
        due = _add_years(start, i)
        status = "Paid" if i == 0 else "Due"
        paid_at = datetime.utcnow() if i == 0 else None
        method = "demo-auto" if i == 0 else ""
        db.add(
            PremiumPayment(
                customer_policy_id=cp.id,
                customer_id=app.customer_id,
                amount=catalog.premium,
                due_date=due,
                paid_at=paid_at,
                status=status,
                method=method,
            )
        )

    db.add(
        ClientDocument(
            customer_id=app.customer_id,
            customer_policy_id=cp.id,
            title=f"Полис {cp.policy_number} — {catalog.name}",
            kind="policy",
            file_path=f"virtual://policies/{cp.policy_number}.pdf",
        )
    )

    db.add(
        Notification(
            user_id=app.customer_id,
            message=(
                f"Заявка одобрена. Оформлен полис {cp.policy_number} "
                f"«{catalog.name}» до {cp.end_date.isoformat()}."
            ),
            is_read=0,
        )
    )
    db.flush()
    return cp
