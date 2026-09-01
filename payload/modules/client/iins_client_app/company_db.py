"""PostgreSQL company ER database (Kielx-style) for InsuraDesk admin."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "postgresql+psycopg2://insura:insura@127.0.0.1:5433/insurance_company"


def company_database_url() -> str:
    # Default: Postgres (Docker). Fallback SQLite file for offline demo.
    return os.getenv(
        "COMPANY_DATABASE_URL",
        DEFAULT_URL if os.getenv("COMPANY_DB_FORCE_SQLITE", "").lower() not in ("1", "true", "yes") else _sqlite_url(),
    )


def _sqlite_url() -> str:
    path = ROOT / "data" / "company_insurance.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


# If Postgres is unreachable at import time we still allow explicit sqlite override.
if os.getenv("COMPANY_DATABASE_URL"):
    pass
elif os.getenv("COMPANY_DB_FORCE_SQLITE", "").lower() in ("1", "true", "yes"):
    DEFAULT_URL = _sqlite_url()  # type: ignore[misc]


class CompanyBase(DeclarativeBase):
    pass


@lru_cache(maxsize=1)
def get_company_engine():
    url = company_database_url()
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    else:
        # Windows + psycopg2: force UTF-8 client encoding
        connect_args["options"] = "-c client_encoding=UTF8"
        os.environ.setdefault("PGCLIENTENCODING", "UTF8")
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


def CompanySessionLocal() -> sessionmaker[Session]:
    return sessionmaker(bind=get_company_engine(), autoflush=False, autocommit=False)


def get_company_db() -> Generator[Session, None, None]:
    SessionLocal = CompanySessionLocal()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def company_db_ping() -> dict:
    url = company_database_url()
    try:
        with get_company_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "url": _safe_url(url), "message": "PostgreSQL company DB is up"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "url": _safe_url(url), "message": str(exc)}


def _safe_url(url: str) -> str:
    # hide password
    if "@" in url and "://" in url:
        head, tail = url.split("://", 1)
        if "@" in tail and ":" in tail.split("@", 1)[0]:
            creds, host = tail.split("@", 1)
            user = creds.split(":", 1)[0]
            return f"{head}://{user}:***@{host}"
    return url


def init_company_schema() -> None:
    """Create tables via ORM metadata (idempotent)."""
    from iins_client_app import company_models  # noqa: F401

    CompanyBase.metadata.create_all(bind=get_company_engine())


def apply_sql_file(path: Path | None = None) -> None:
    sql_path = path or (ROOT / "company_db" / "create.sql")
    raw = sql_path.read_text(encoding="utf-8")
    with get_company_engine().begin() as conn:
        conn.execute(text(raw))
