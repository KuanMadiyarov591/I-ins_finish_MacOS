from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from iins_agent_app.api import applications_routes, assistant_routes, auth_routes, crm_routes, recommend_routes
from iins_agent_app.config import ROOT, get_settings
from iins_agent_app.db import Base, SessionLocal, engine, migrate_schema
from iins_agent_app.seed import seed_if_empty

WEB_DIR = ROOT / "web"
DATA_DIR = ROOT / "data"


def create_app() -> FastAPI:
    settings = get_settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "models" / "agent").mkdir(parents=True, exist_ok=True)
    settings.corpus_dir.mkdir(parents=True, exist_ok=True)
    settings.docs_storage_dir.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(bind=engine)
    migrate_schema()
    with SessionLocal() as db:
        seed_if_empty(db)

    app = FastAPI(
        title="Insurance Agent Desk",
        description="Рабочее место агента: CRM клиентов, заявки, приоритеты, помощник",
        version="0.2.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_routes.router)
    app.include_router(crm_routes.router)
    app.include_router(applications_routes.router)
    app.include_router(assistant_routes.router)
    app.include_router(recommend_routes.router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": "insurance-agent-desk", "port": settings.app_port}

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")

    return app


app = create_app()
