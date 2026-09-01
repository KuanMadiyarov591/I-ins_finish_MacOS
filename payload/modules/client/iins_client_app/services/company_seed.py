"""Seed company ER database with demo data (Faker), Kielx-style Getting Started."""

from __future__ import annotations

import random
from datetime import date, timedelta

from faker import Faker
from sqlalchemy import func, select

from iins_client_app.company_db import CompanySessionLocal, company_db_ping, get_company_engine, init_company_schema
from iins_client_app.company_models import (
    Branch,
    City,
    Claim,
    ClaimStatus,
    Client,
    ClientType,
    Employee,
    HouseNr,
    Insurance,
    InsuranceType,
    Payment,
    Phone,
    PhoneType,
    Region,
    Street,
)

fake = Faker("ru_RU")
Faker.seed(42)
random.seed(42)


def seed_company_db(*, force: bool = False, n_clients: int = 80, n_employees: int = 25, n_branches: int = 8) -> dict:
    ping = company_db_ping()
    if not ping["ok"]:
        raise RuntimeError(f"Company DB is down: {ping['message']}")

    init_company_schema()
    SessionLocal = CompanySessionLocal()
    db = SessionLocal()
    try:
        existing = db.scalar(select(func.count()).select_from(Client)) or 0
        if existing and not force:
            return {
                "seeded": False,
                "message": f"Already has {existing} clients (use force=True to rebuild)",
                "ping": ping,
            }

        if force:
            for model in (Claim, Insurance, Phone, Payment, Branch, Employee, Client,
                          ClaimStatus, InsuranceType, PhoneType, ClientType, HouseNr, Street, City, Region):
                db.query(model).delete()
            db.commit()

        regions = [Region(region_id=i, region_name=name) for i, name in enumerate(
            ["Центральный", "Северо-Западный", "Южный", "Приволжский", "Уральский", "Сибирский", "Дальневосточный", "Северо-Кавказский"], 1)]
        cities = [City(city_id=i, city_name=name) for i, name in enumerate(
            ["Москва", "Санкт-Петербург", "Казань", "Екатеринбург", "Новосибирск", "Краснодар", "Владивосток", "Ростов-на-Дону", "Самара", "Уфа"], 1)]
        streets = [Street(street_id=i, street_name=fake.street_name()[:50]) for i in range(1, 31)]
        houses = [HouseNr(housenr_id=i, housenr_nr=str(fake.building_number())[:10]) for i in range(1, 51)]
        phone_types = [
            PhoneType(phonetype_id=1, type_name="mobile"),
            PhoneType(phonetype_id=2, type_name="home"),
            PhoneType(phonetype_id=3, type_name="work"),
        ]
        client_types = [
            ClientType(clienttype_id=1, clienttype_name="Физическое лицо"),
            ClientType(clienttype_id=2, clienttype_name="VIP"),
            ClientType(clienttype_id=3, clienttype_name="Корпоративный"),
        ]
        ins_types = [
            InsuranceType(insurancetype_id=1, insurance_type="Страхование жизни"),
            InsuranceType(insurancetype_id=2, insurance_type="Медицинское страхование"),
            InsuranceType(insurancetype_id=3, insurance_type="Автострахование"),
            InsuranceType(insurancetype_id=4, insurance_type="Туристическое страхование"),
            InsuranceType(insurancetype_id=5, insurance_type="Имущественное страхование"),
        ]
        claim_statuses = [
            ClaimStatus(cs_id=1, cs_status="Новый"),
            ClaimStatus(cs_id=2, cs_status="В работе"),
            ClaimStatus(cs_id=3, cs_status="Одобрен"),
            ClaimStatus(cs_id=4, cs_status="Отклонён"),
            ClaimStatus(cs_id=5, cs_status="Выплачен"),
        ]
        db.add_all(regions + cities + streets + houses + phone_types + client_types + ins_types + claim_statuses)
        db.flush()

        def addr():
            return dict(
                region_id=random.choice(regions).region_id,
                city_id=random.choice(cities).city_id,
                street_id=random.choice(streets).street_id,
                housenr_id=random.choice(houses).housenr_id,
            )

        clients = []
        for i in range(1, n_clients + 1):
            clients.append(
                Client(
                    client_id=i,
                    first_name=fake.first_name()[:50],
                    last_name=fake.last_name()[:50],
                    date_of_birth=fake.date_of_birth(minimum_age=18, maximum_age=75),
                    clienttype_id=random.choice(client_types).clienttype_id,
                    discount=random.choice([0, 0, 5, 10, 15]),
                    **addr(),
                )
            )
        employees = []
        for i in range(1, n_employees + 1):
            employees.append(
                Employee(
                    employee_id=i,
                    first_name=fake.first_name()[:50],
                    last_name=fake.last_name()[:50],
                    date_of_birth=fake.date_of_birth(minimum_age=22, maximum_age=60),
                    date_of_employment=fake.date_between(start_date="-10y", end_date="-1y"),
                    salary=random.randint(60000, 250000),
                    **addr(),
                )
            )
        branches = []
        for i in range(1, n_branches + 1):
            branches.append(
                Branch(
                    branch_id=i,
                    branch_name=f"Филиал {cities[(i - 1) % len(cities)].city_name}"[:50],
                    **addr(),
                )
            )
        db.add_all(clients + employees + branches)
        db.flush()

        phones = []
        pid = 1
        for c in clients:
            phones.append(Phone(phone_id=pid, phone_number=fake.phone_number()[:20], client_id=c.client_id, phonetype_id=1))
            pid += 1
        for e in employees:
            phones.append(Phone(phone_id=pid, phone_number=fake.phone_number()[:20], employee_id=e.employee_id, phonetype_id=3))
            pid += 1
        for b in branches:
            phones.append(Phone(phone_id=pid, phone_number=fake.phone_number()[:20], branch_id=b.branch_id, phonetype_id=3))
            pid += 1
        db.add_all(phones)

        payments = []
        insurances = []
        claims = []
        for i in range(1, n_clients * 2 + 1):
            amount = random.randint(5000, 120000)
            pay = Payment(
                payment_id=i,
                payment_type=random.choice(["card", "cash", "transfer"]),
                payment_amount=amount,
                payment_date=fake.date_between(start_date="-3y", end_date="today"),
            )
            payments.append(pay)
            begin = fake.date_between(start_date="-2y", end_date="today")
            insurances.append(
                Insurance(
                    insurance_id=i,
                    insurance_number=f"INS-{100000 + i}",
                    client_id=random.choice(clients).client_id,
                    employee_id=random.choice(employees).employee_id,
                    begin_date=begin,
                    expiration_date=begin + timedelta(days=365),
                    insurancetype_id=random.choice(ins_types).insurancetype_id,
                    payment_id=i,
                    branch_id=random.choice(branches).branch_id,
                    price=amount,
                )
            )
        db.add_all(payments)
        db.flush()
        db.add_all(insurances)
        db.flush()

        for i, ins in enumerate(random.sample(insurances, k=min(60, len(insurances))), start=1):
            claims.append(
                Claim(
                    claim_id=i,
                    claim_name=random.choice(["ДТП", "Болезнь", "Кража", "Пожар", "Затопление"])[:50],
                    insurance_id=ins.insurance_id,
                    claim_amount=random.randint(3000, int(ins.price or 50000)),
                    cs_id=random.choice(claim_statuses).cs_id,
                )
            )
        db.add_all(claims)
        db.commit()

        counts = {
            "region": db.query(Region).count(),
            "city": db.query(City).count(),
            "client": db.query(Client).count(),
            "employee": db.query(Employee).count(),
            "branch": db.query(Branch).count(),
            "insurance": db.query(Insurance).count(),
            "payment": db.query(Payment).count(),
            "claim": db.query(Claim).count(),
            "phone": db.query(Phone).count(),
        }
        return {"seeded": True, "counts": counts, "ping": ping}
    finally:
        db.close()


if __name__ == "__main__":
    import json
    import sys

    force = "--force" in sys.argv
    print(json.dumps(seed_company_db(force=force), ensure_ascii=False, indent=2, default=str))
