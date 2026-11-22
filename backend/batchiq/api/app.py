"""FastAPI application factory."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from batchiq.api.deps import get_service
from batchiq.api.routes import estate, intelligence, knowledge
from batchiq.config import settings


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    app = FastAPI(title="Batch Intelligence Overlay", version="0.2.0",
                  description="AI system of engagement over Control-M, AutoSys, Airflow and cloud schedulers.")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_methods=["*"],
                       allow_headers=["*"])
    app.include_router(estate.router, prefix="/api")
    app.include_router(intelligence.router, prefix="/api")
    app.include_router(knowledge.router, prefix="/api")

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz():
        get_service()
        return {"status": "ready"}

    # Optional: serve a built UI from the same process (single-container mode).
    static = Path(__file__).resolve().parents[2] / "static"
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="ui")
    return app


app = create_app()
