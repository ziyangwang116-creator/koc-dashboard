from __future__ import annotations

from fastapi import FastAPI

from config.settings import Settings, load_settings
from database.db import is_postgres_target


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app. Phase 1: read-only endpoints only."""
    resolved_settings = settings or load_settings()
    app = FastAPI(title="KOC Dashboard API")

    @app.get("/api/health")
    def health() -> dict:
        database = "postgres" if is_postgres_target(resolved_settings.database_path) else "sqlite"
        return {"data": {"status": "ok", "database": database}}

    return app


app = create_app()
