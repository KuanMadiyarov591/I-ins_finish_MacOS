from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from iins_actuary_app.api import (
    assumptions_routes,
    assistant_routes,
    auth_routes,
    dashboard_routes,
    premiums_routes,
    recommend_routes,
    report_routes,
    runs_routes,
)
from iins_actuary_app.config import ROOT, get_settings
from iins_actuary_app.db import Base, SessionLocal, engine
from iins_actuary_app.seed import seed_if_empty

WEB_DIR = ROOT / "web"
DATA_DIR = ROOT / "data"


def create_app() -> FastAPI:
    settings = get_settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings.corpus_dir.mkdir(parents=True, exist_ok=True)
    settings.model_dir.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_if_empty(db)

    app = FastAPI(
        title="Actuary Desk",
        description="Кабинет актуария: премии CGR, допущения, ML-прогноз selected_premium, AI Hub",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_routes.router)
    app.include_router(dashboard_routes.router)
    app.include_router(premiums_routes.router)
    app.include_router(assumptions_routes.router)
    app.include_router(runs_routes.router)
    app.include_router(recommend_routes.router)
    app.include_router(assistant_routes.router)
    app.include_router(report_routes.router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": "actuarial-desk", "port": settings.app_port}

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")

    return app


app = create_app()
