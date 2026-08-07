from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config.settings import Settings, load_settings
from database.db import is_postgres_target
from ui.auth import password_matches

from api.creators import build_creators_router
from api.session_store import SessionStore

SESSION_COOKIE_NAME = "koc_session"
SESSION_MAX_AGE_SECONDS = 28800


class LoginRequest(BaseModel):
    password: str | None = None


def create_app(settings: Settings | None = None, *, environment: str | None = None) -> FastAPI:
    """Build the FastAPI app. Phase 1: read-only endpoints + session auth only."""
    resolved_settings = settings or load_settings()
    resolved_environment = environment or os.environ.get("APP_ENV", "development")
    secure_cookie = resolved_environment != "development"
    session_store = SessionStore(ttl_seconds=SESSION_MAX_AGE_SECONDS)

    app = FastAPI(title="KOC Dashboard API")

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    def require_session(request: Request) -> None:
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        if not session_store.is_valid(session_id):
            raise HTTPException(
                status_code=401,
                detail={"error": {"code": "UNAUTHENTICATED", "message": "未登录或会话已过期。"}},
            )

    creators_router = build_creators_router(
        database_path=resolved_settings.database_path,
        require_session=Depends(require_session),
    )
    app.include_router(creators_router)

    @app.get("/api/health")
    def health() -> dict:
        database = "postgres" if is_postgres_target(resolved_settings.database_path) else "sqlite"
        return {"data": {"status": "ok", "database": database}}

    @app.post("/api/auth/login")
    def login(payload: LoginRequest) -> JSONResponse:
        password = payload.password
        if not password:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "密码不能为空。",
                        "field_errors": [
                            {"field": "password", "message": "密码不能为空。"}
                        ],
                    }
                },
            )

        team_password = resolved_settings.team_password or ""
        if not team_password or not password_matches(team_password, password):
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "INVALID_CREDENTIALS",
                        "message": "密码不正确。",
                    }
                },
            )

        session_id = session_store.create()
        response = JSONResponse(content={"data": {"authenticated": True}})
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            secure=secure_cookie,
            samesite="lax",
            max_age=SESSION_MAX_AGE_SECONDS,
            path="/",
        )
        return response

    @app.post("/api/auth/logout")
    def logout(request: Request) -> JSONResponse:
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session_store.delete(session_id)
        response = JSONResponse(content={"data": {"authenticated": False}})
        response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
        return response

    return app


app = create_app()
