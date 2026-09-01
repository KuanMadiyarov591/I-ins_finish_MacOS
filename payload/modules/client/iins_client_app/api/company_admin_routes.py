"""Admin API for company ER database (PostgreSQL)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from iins_client_app.auth import require_admin
from iins_client_app.company_db import company_db_ping, get_company_db
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
from iins_client_app.models import User
from iins_client_app.services.company_seed import seed_company_db

router = APIRouter(prefix="/api/admin/company", tags=["admin-company-db"])


@router.get("/health")
def company_health(_: User = Depends(require_admin)) -> Dict[str, Any]:
    return company_db_ping()


@router.get("/overview")
def overview(
    db: Session = Depends(get_company_db),
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    ping = company_db_ping()
    if not ping["ok"]:
        raise HTTPException(status_code=503, detail=ping["message"])
    tables = {
        "region": db.query(Region).count(),
        "city": db.query(City).count(),
        "street": db.query(Street).count(),
        "housenr": db.query(HouseNr).count(),
        "phonetype": db.query(PhoneType).count(),
        "clienttype": db.query(ClientType).count(),
        "insurancetype": db.query(InsuranceType).count(),
        "claimstatus": db.query(ClaimStatus).count(),
        "client": db.query(Client).count(),
        "employee": db.query(Employee).count(),
        "branch": db.query(Branch).count(),
        "phone": db.query(Phone).count(),
        "payment": db.query(Payment).count(),
        "insurance": db.query(Insurance).count(),
        "claim": db.query(Claim).count(),
    }
    return {"ping": ping, "tables": tables, "model": "Kielx ER / InsuraDesk company DB"}


@router.post("/seed")
def seed(force: bool = False, _: User = Depends(require_admin)) -> Dict[str, Any]:
    try:
        return seed_company_db(force=force)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _page(q, limit: int, offset: int):
    total = q.count()
    rows = q.offset(offset).limit(limit).all()
    return total, rows


@router.get("/clients")
def list_clients(
    db: Session = Depends(get_company_db),
    _: User = Depends(require_admin),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    total, rows = _page(db.query(Client).order_by(Client.client_id), limit, offset)
    cities = {c.city_id: c.city_name for c in db.query(City).all()}
    ctypes = {c.clienttype_id: c.clienttype_name for c in db.query(ClientType).all()}
    return {
        "total": total,
        "items": [
            {
                "client_id": r.client_id,
                "first_name": r.first_name,
                "last_name": r.last_name,
                "date_of_birth": str(r.date_of_birth),
                "city": cities.get(r.city_id),
                "client_type": ctypes.get(r.clienttype_id),
                "discount": r.discount,
            }
            for r in rows
        ],
    }


@router.get("/employees")
def list_employees(
    db: Session = Depends(get_company_db),
    _: User = Depends(require_admin),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    total, rows = _page(db.query(Employee).order_by(Employee.employee_id), limit, offset)
    cities = {c.city_id: c.city_name for c in db.query(City).all()}
    return {
        "total": total,
        "items": [
            {
                "employee_id": r.employee_id,
                "first_name": r.first_name,
                "last_name": r.last_name,
                "city": cities.get(r.city_id),
                "date_of_employment": str(r.date_of_employment) if r.date_of_employment else None,
                "salary": r.salary,
            }
            for r in rows
        ],
    }


@router.get("/branches")
def list_branches(
    db: Session = Depends(get_company_db),
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    cities = {c.city_id: c.city_name for c in db.query(City).all()}
    regions = {r.region_id: r.region_name for r in db.query(Region).all()}
    rows = db.query(Branch).order_by(Branch.branch_id).all()
    return {
        "total": len(rows),
        "items": [
            {
                "branch_id": r.branch_id,
                "branch_name": r.branch_name,
                "city": cities.get(r.city_id),
                "region": regions.get(r.region_id),
            }
            for r in rows
        ],
    }


@router.get("/insurances")
def list_insurances(
    db: Session = Depends(get_company_db),
    _: User = Depends(require_admin),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    total, rows = _page(db.query(Insurance).order_by(Insurance.insurance_id), limit, offset)
    types = {t.insurancetype_id: t.insurance_type for t in db.query(InsuranceType).all()}
    return {
        "total": total,
        "items": [
            {
                "insurance_id": r.insurance_id,
                "insurance_number": r.insurance_number,
                "client_id": r.client_id,
                "employee_id": r.employee_id,
                "branch_id": r.branch_id,
                "type": types.get(r.insurancetype_id),
                "begin_date": str(r.begin_date),
                "expiration_date": str(r.expiration_date),
                "price": r.price,
            }
            for r in rows
        ],
    }


@router.get("/claims")
def list_claims(
    db: Session = Depends(get_company_db),
    _: User = Depends(require_admin),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    total, rows = _page(db.query(Claim).order_by(Claim.claim_id), limit, offset)
    statuses = {s.cs_id: s.cs_status for s in db.query(ClaimStatus).all()}
    return {
        "total": total,
        "items": [
            {
                "claim_id": r.claim_id,
                "claim_name": r.claim_name,
                "insurance_id": r.insurance_id,
                "claim_amount": r.claim_amount,
                "status": statuses.get(r.cs_id),
            }
            for r in rows
        ],
    }


@router.get("/payments")
def list_payments(
    db: Session = Depends(get_company_db),
    _: User = Depends(require_admin),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    total, rows = _page(db.query(Payment).order_by(Payment.payment_id), limit, offset)
    return {
        "total": total,
        "items": [
            {
                "payment_id": r.payment_id,
                "payment_type": r.payment_type,
                "payment_amount": r.payment_amount,
                "payment_date": str(r.payment_date) if r.payment_date else None,
            }
            for r in rows
        ],
    }


@router.get("/phones")
def list_phones(
    db: Session = Depends(get_company_db),
    _: User = Depends(require_admin),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    total, rows = _page(db.query(Phone).order_by(Phone.phone_id), limit, offset)
    types = {t.phonetype_id: t.type_name for t in db.query(PhoneType).all()}
    return {
        "total": total,
        "items": [
            {
                "phone_id": r.phone_id,
                "phone_number": r.phone_number,
                "type": types.get(r.phonetype_id),
                "client_id": r.client_id,
                "employee_id": r.employee_id,
                "branch_id": r.branch_id,
            }
            for r in rows
        ],
    }
