"""SQLAlchemy models for company ER schema (admin DBMS)."""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from iins_admin_app.company_db import CompanyBase


class Region(CompanyBase):
    __tablename__ = "region"
    region_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    region_name: Mapped[str] = mapped_column(String(50), nullable=False)


class City(CompanyBase):
    __tablename__ = "city"
    city_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city_name: Mapped[str] = mapped_column(String(50), nullable=False)


class Street(CompanyBase):
    __tablename__ = "street"
    street_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    street_name: Mapped[str] = mapped_column(String(50), nullable=False)


class HouseNr(CompanyBase):
    __tablename__ = "housenr"
    housenr_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    housenr_nr: Mapped[str] = mapped_column(String(10), nullable=False)


class PhoneType(CompanyBase):
    __tablename__ = "phonetype"
    phonetype_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type_name: Mapped[str] = mapped_column(String(50), nullable=False)


class ClientType(CompanyBase):
    __tablename__ = "clienttype"
    clienttype_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clienttype_name: Mapped[str] = mapped_column(String(50), nullable=False)


class InsuranceType(CompanyBase):
    __tablename__ = "insurancetype"
    insurancetype_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    insurance_type: Mapped[str] = mapped_column(String(50), nullable=False)


class ClaimStatus(CompanyBase):
    __tablename__ = "claimstatus"
    cs_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cs_status: Mapped[str] = mapped_column(String(50), nullable=False)


class Client(CompanyBase):
    __tablename__ = "client"
    client_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(50), nullable=False)
    last_name: Mapped[str] = mapped_column(String(50), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    region_id: Mapped[int] = mapped_column(ForeignKey("region.region_id"), nullable=False)
    city_id: Mapped[int] = mapped_column(ForeignKey("city.city_id"), nullable=False)
    street_id: Mapped[int] = mapped_column(ForeignKey("street.street_id"), nullable=False)
    housenr_id: Mapped[int] = mapped_column(ForeignKey("housenr.housenr_id"), nullable=False)
    clienttype_id: Mapped[int] = mapped_column(ForeignKey("clienttype.clienttype_id"), nullable=False)
    discount: Mapped[Optional[int]] = mapped_column(Integer)


class Employee(CompanyBase):
    __tablename__ = "employee"
    employee_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(50), nullable=False)
    last_name: Mapped[str] = mapped_column(String(50), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    region_id: Mapped[int] = mapped_column(ForeignKey("region.region_id"), nullable=False)
    city_id: Mapped[int] = mapped_column(ForeignKey("city.city_id"), nullable=False)
    street_id: Mapped[int] = mapped_column(ForeignKey("street.street_id"), nullable=False)
    housenr_id: Mapped[int] = mapped_column(ForeignKey("housenr.housenr_id"), nullable=False)
    date_of_employment: Mapped[Optional[date]] = mapped_column(Date)
    salary: Mapped[Optional[int]] = mapped_column(Integer)


class Branch(CompanyBase):
    __tablename__ = "branch"
    branch_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_name: Mapped[str] = mapped_column(String(50), nullable=False)
    region_id: Mapped[int] = mapped_column(ForeignKey("region.region_id"), nullable=False)
    city_id: Mapped[int] = mapped_column(ForeignKey("city.city_id"), nullable=False)
    street_id: Mapped[int] = mapped_column(ForeignKey("street.street_id"), nullable=False)
    housenr_id: Mapped[int] = mapped_column(ForeignKey("housenr.housenr_id"), nullable=False)


class Phone(CompanyBase):
    __tablename__ = "phone"
    phone_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("client.client_id", ondelete="CASCADE"))
    phonetype_id: Mapped[int] = mapped_column(ForeignKey("phonetype.phonetype_id"), nullable=False)
    employee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employee.employee_id", ondelete="CASCADE"))
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branch.branch_id"))


class Payment(CompanyBase):
    __tablename__ = "payment"
    payment_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payment_amount: Mapped[Optional[int]] = mapped_column(Integer)
    payment_date: Mapped[Optional[date]] = mapped_column(Date)


class Insurance(CompanyBase):
    __tablename__ = "insurance"
    insurance_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    insurance_number: Mapped[str] = mapped_column(String(50), nullable=False)
    client_id: Mapped[int] = mapped_column(ForeignKey("client.client_id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employee.employee_id", ondelete="CASCADE"), nullable=False)
    begin_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiration_date: Mapped[date] = mapped_column(Date, nullable=False)
    insurancetype_id: Mapped[int] = mapped_column(ForeignKey("insurancetype.insurancetype_id"), nullable=False)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payment.payment_id"), nullable=False)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branch.branch_id"), nullable=False)
    price: Mapped[Optional[int]] = mapped_column(Integer)


class Claim(CompanyBase):
    __tablename__ = "claim"
    claim_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_name: Mapped[str] = mapped_column(String(50), nullable=False)
    insurance_id: Mapped[int] = mapped_column(ForeignKey("insurance.insurance_id"), nullable=False)
    claim_amount: Mapped[Optional[int]] = mapped_column(Integer)
    cs_id: Mapped[int] = mapped_column(ForeignKey("claimstatus.cs_id"), nullable=False)
