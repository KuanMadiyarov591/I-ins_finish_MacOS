from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from iins_admin_app.api import admin_routes, auth_routes, company_admin_routes, customer_routes, rag_routes, recommender_routes
from iins_admin_app.config import ROOT, get_settings
from iins_admin_app.db import Base, SessionLocal, engine, migrate_sqlite_schema
from iins_admin_app.seed import seed_if_empty
from iins_admin_app.company_db import company_db_ping

WEB_DIR = ROOT / "web"
DATA_DIR = ROOT / "data"


def _instrument_metrics(app: FastAPI) -> None:
    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        from iins_admin_app.services.metrics_compat import apply_route_name_shim

        apply_route_name_shim()

        Instrumentator(
            should_group_status_codes=True,
            excluded_handlers=["/metrics", "/health"],
        ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    except ImportError:
        from fastapi.responses import PlainTextResponse

        @app.get("/metrics", include_in_schema=False)
        def metrics_stub() -> PlainTextResponse:
            return PlainTextResponse(
                "# HELP insuradesk_up Demo metric when instrumentator is not installed\n"
                "# TYPE insuradesk_up gauge\n"
                "insuradesk_up 1\n",
                media_type="text/plain; version=0.0.4",
            )


def create_app() -> FastAPI:
    settings = get_settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "client_docs").mkdir(parents=True, exist_ok=True)
    settings.docs_storage_dir.mkdir(parents=True, exist_ok=True)
    settings.corpus_dir.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(bind=engine)
    migrate_sqlite_schema()
    with SessionLocal() as db:
        seed_if_empty(db)

    app = FastAPI(
        title="InsuraDesk",
        description="Система управления страхованием: кабинеты, RAG, рекомендации, убытки и платежи",
        version="1.2.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_routes.router)
    app.include_router(admin_routes.router)
    app.include_router(company_admin_routes.router)
    app.include_router(customer_routes.router)
    app.include_router(rag_routes.router)
    app.include_router(recommender_routes.router)

    _instrument_metrics(app)

    @app.get("/health")
    def health() -> dict:
        company = company_db_ping()
        s = get_settings()
        surface = (s.app_surface or "client").strip().lower()
        if surface not in ("client", "admin"):
            surface = "client"
        return {
            "status": "ok",
            "service": "insurance-rag-system",
            "surface": surface,
            "port": s.app_port,
            "client_port": s.client_port,
            "admin_port": s.admin_port,
            "company_db": company,
        }

    @app.get("/api/meta")
    def meta() -> dict:
        s = get_settings()
        surface = (s.app_surface or "client").strip().lower()
        if surface not in ("client", "admin"):
            surface = "client"
        return {
            "surface": surface,
            "port": s.app_port,
            "client_port": s.client_port,
            "admin_port": s.admin_port,
            "client_url": f"http://{s.app_host}:{s.client_port}/",
            "admin_url": f"http://{s.app_host}:{s.admin_port}/",
        }

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")

    return app


app = create_app()
