from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from iins_agent_app.auth import hash_password
from iins_agent_app.config import ROOT, SHARED_DATASETS
from iins_agent_app.models import AgentProfile, Application, Client, PolicyProduct, Tag, User
from iins_agent_app.services import finance_service as finance
from iins_agent_app.services import priority_service as prio
from iins_agent_app.services import lead_scoring_service as scoring

FIRST_NAMES = [
    "Айгерим", "Данияр", "Мария", "Алексей", "Сауле", "Иван", "Алина", "Ерлан",
    "Ольга", "Нурлан", "Камила", "Сергей", "Жанна", "Тимур", "Анна",
]
LAST_NAMES = [
    "Касымова", "Омаров", "Иванова", "Петров", "Нурланова", "Смирнов", "Абдуллаева",
    "Сериков", "Козлова", "Жумабеков", "Бекова", "Морозов", "Ахметова", "Ли", "Ким",
]

PRODUCTS = [
    ("MED01", "МедСтандарт", "medical", 12000, 1000000, "Базовое медицинское покрытие"),
    ("LIFE01", "Жизнь Плюс", "life", 18000, 2000000, "Страхование жизни"),
    ("AUTO01", "АвтоКомфорт", "auto", 25000, 5000000, "Автострахование КАСКО/ОСАГО-демо"),
    ("TRAV01", "Турист Safe", "travel", 8500, 500000, "Туристическое страхование"),
    ("HOME01", "Дом и Квартира", "home", 15000, 8000000, "Имущественное страхование"),
    ("FUN01", "Забота+", "funeral", 9000, 300000, "Похоронное страхование"),
]

TAGS = ["vip", "follow-up", "coverage-change", "travel", "new", "funeral-interest"]


def _resolve_leads_csv() -> Path | None:
    names = [
        "01_agent_23_travel_company_new_clients.csv",
        "01_agent_23_travel_company_new_clients_scored.csv",
    ]
    for base in (ROOT / "data", SHARED_DATASETS):
        for name in names:
            p = base / name
            if p.is_file():
                return p
    return None


def seed_if_empty(db: Session) -> None:
    if db.query(User).count() == 0:
        admin = User(
            username="admin",
            password_hash=hash_password("admin123"),
            full_name="Админ Agent Desk",
            role="admin",
        )
        agent = User(
            username="agent",
            password_hash=hash_password("agent123"),
            full_name="Агент Иван",
            role="agent",
        )
        db.add_all([admin, agent])
        db.flush()
        db.add(
            AgentProfile(
                user_id=agent.id,
                display_name="Иван Агентов",
                phone="+7 700 000 00 01",
                email="agent@agentdesk.local",
                product_prefs="medical,travel,auto,home,life,funeral",
                sales_ready=True,
            )
        )
        db.commit()
    else:
        agent = db.query(User).filter(User.username == "agent").first()
        if agent and db.query(AgentProfile).filter(AgentProfile.user_id == agent.id).count() == 0:
            db.add(
                AgentProfile(
                    user_id=agent.id,
                    display_name=agent.full_name or "Агент",
                    phone="+7 700 000 00 01",
                    email="agent@agentdesk.local",
                )
            )
            db.commit()

    if db.query(PolicyProduct).count() == 0:
        for code, name, cat, prem, sum_a, desc in PRODUCTS:
            db.add(
                PolicyProduct(
                    code=code,
                    name=name,
                    category=cat,
                    premium=prem,
                    sum_assurance=sum_a,
                    description=desc,
                )
            )
        db.commit()
    else:
        # Унификация отображаемых имён (старые демо-БД)
        renamed = False
        for p in db.query(PolicyProduct).filter(PolicyProduct.code == "TRAV01").all():
            if p.name in ("Travel Safe", "TravelSafe", "Travel"):
                p.name = "Турист Safe"
                renamed = True
        if renamed:
            db.commit()

    if db.query(Tag).count() == 0:
        for t in TAGS:
            db.add(Tag(name=t))
        db.commit()

    if db.query(Client).count() > 0:
        _backfill_finance(db)
        return

    path = _resolve_leads_csv()
    tags = {t.name: t for t in db.query(Tag).all()}
    products = db.query(PolicyProduct).all()
    travel = next((p for p in products if p.category == "travel"), products[0])
    medical = next((p for p in products if p.category == "medical"), products[0])

    rows = []
    if path is not None:
        df = pd.read_csv(path).head(80)
        for i, r in df.iterrows():
            rows.append(
                {
                    "Age": int(r.get("Age", 35) or 35),
                    "AnnualIncome": float(r.get("AnnualIncome", 500000) or 500000),
                    "FamilyMembers": int(r.get("FamilyMembers", 2) or 2),
                    "ChronicDiseases": int(r.get("ChronicDiseases", 0) or 0),
                    "Employment Type": str(r.get("Employment Type", "Private Sector/Self Employed")),
                    "GraduateOrNot": str(r.get("GraduateOrNot", "Yes")),
                    "FrequentFlyer": str(r.get("FrequentFlyer", "No")),
                    "EverTravelledAbroad": str(r.get("EverTravelledAbroad", "No")),
                    "pred": float(r["pred_buy_proba"]) if "pred_buy_proba" in r and pd.notna(r.get("pred_buy_proba")) else None,
                    "idx": int(i),
                }
            )
    else:
        for i in range(20):
            rows.append(
                {
                    "Age": 30 + (i % 20),
                    "AnnualIncome": 400000 + i * 20000,
                    "FamilyMembers": 2 + (i % 3),
                    "ChronicDiseases": i % 2,
                    "Employment Type": "Private Sector/Self Employed",
                    "GraduateOrNot": "Yes",
                    "FrequentFlyer": "Yes" if i % 4 == 0 else "No",
                    "EverTravelledAbroad": "Yes" if i % 3 == 0 else "No",
                    "pred": None,
                    "idx": i,
                }
            )

    ready = scoring.status()["ready"]
    for n, row in enumerate(rows):
        fn = FIRST_NAMES[n % len(FIRST_NAMES)]
        ln = LAST_NAMES[n % len(LAST_NAMES)]
        ml = {}
        if row["pred"] is not None:
            ml = {"buy_probability": row["pred"], "propensity_tier": scoring.tier_for(row["pred"])}
        elif ready:
            ml = prio.enrich_client_ml(row)

        coverage_change = n % 11 == 0
        priority = prio.compute_priority(
            coverage_change=coverage_change,
            has_open_application=False,
            buy_probability=ml.get("buy_probability"),
            propensity_tier=ml.get("propensity_tier"),
        )

        client = Client(
            external_id=f"CLT-{row['idx']:05d}",
            full_name=f"{fn} {ln}",
            phone=f"+7701{1000000 + n:07d}",
            email=f"client{n}@example.kz" if n % 5 else "",
            age=row["Age"],
            employment_type=row["Employment Type"],
            graduate=row["GraduateOrNot"],
            annual_income=row["AnnualIncome"],
            family_members=row["FamilyMembers"],
            chronic_diseases=row["ChronicDiseases"],
            frequent_flyer=row["FrequentFlyer"],
            ever_travelled_abroad=row["EverTravelledAbroad"],
            status="prospect" if priority >= 4 else "active",
            priority=priority,
            coverage_change=coverage_change,
            notes="",
            buy_probability=ml.get("buy_probability"),
            propensity_tier=ml.get("propensity_tier"),
        )
        # tags
        client.tags.append(tags["new"])
        if coverage_change:
            client.tags.append(tags["coverage-change"])
        if row["FrequentFlyer"] == "Yes" or row["EverTravelledAbroad"] == "Yes":
            client.tags.append(tags["travel"])
        if priority <= 2:
            client.tags.append(tags["vip"])
        if n % 17 == 0:
            client.tags.append(tags["funeral-interest"])
        if priority == 3:
            client.tags.append(tags["follow-up"])

        db.add(client)
        db.flush()

        # пара демо-заявок
        if n % 9 == 0:
            pct = finance.default_commission_pct(travel.category)
            db.add(
                Application(
                    client_id=client.id,
                    product_id=travel.id,
                    status="draft",
                    quoted_premium=travel.premium,
                    payment_status="unpaid",
                    commission_pct=pct,
                    commission_amount=finance.calc_commission(travel.premium, pct),
                    notes="Черновик travel",
                )
            )
            client.priority = prio.compute_priority(
                coverage_change=client.coverage_change,
                has_open_application=True,
                buy_probability=client.buy_probability,
                propensity_tier=client.propensity_tier,
            )
        elif n % 13 == 0:
            pct = finance.default_commission_pct(medical.category)
            db.add(
                Application(
                    client_id=client.id,
                    product_id=medical.id,
                    status="submitted",
                    chk_contact_ok=True,
                    chk_consent_ok=True,
                    chk_docs_ok=True,
                    chk_prefs_ok=True,
                    quoted_premium=medical.premium,
                    payment_status="pending",
                    payment_method="card",
                    commission_pct=pct,
                    commission_amount=finance.calc_commission(medical.premium, pct),
                )
            )

    db.commit()
    _backfill_finance(db)


def _backfill_finance(db: Session) -> None:
    """Проставить оплату/комиссию у старых заявок."""
    changed = False
    apps = db.query(Application).all()
    products = {p.id: p for p in db.query(PolicyProduct).all()}
    for i, a in enumerate(apps):
        p = products.get(a.product_id)
        prem = a.quoted_premium if a.quoted_premium is not None else (p.premium if p else 0)
        if not a.payment_status:
            a.payment_status = "pending" if a.status == "submitted" else "unpaid"
            changed = True
        if a.commission_pct is None or float(a.commission_pct or 0) <= 0:
            a.commission_pct = finance.default_commission_pct(p.category if p else None)
            changed = True
        expected = finance.calc_commission(prem, float(a.commission_pct or 10))
        if a.commission_amount is None or a.commission_amount != expected:
            a.commission_amount = expected
            changed = True
        # Разнообразие демо-статусов оплаты
        if a.status == "submitted" and (a.payment_status or "unpaid") in ("unpaid", "pending"):
            if i % 5 == 0:
                a.payment_status = "paid"
                a.payment_method = a.payment_method or "transfer"
                changed = True
            elif i % 7 == 0:
                a.payment_status = "overdue"
                a.next_payment_date = a.next_payment_date or "2026-08-05"
                a.payment_method = a.payment_method or "installment"
                changed = True
    if changed:
        db.commit()