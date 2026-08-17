from __future__ import annotations

import logging
import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from config.settings import Settings, load_settings
from database.db import (
    CONNECTION_LOST_ERRORS,
    _prefer_ipv4_for_supabase_pooler,
    connect,
    is_postgres_target,
    sanitize_db_error_marker,
)
from ui.auth import password_matches

from api.agent import build_agent_router
from api.compensation import build_compensation_router
from api.creators import build_creators_router
from api.dashboard import build_dashboard_router
from api.followers import JobStore, build_followers_router
from api.imports import PreviewStore, build_imports_router
from api.session_store import SessionStore
from database.koc_repository import KOCRepository
from services.follower_service import FollowerService

SESSION_COOKIE_NAME = "koc_session"
SESSION_MAX_AGE_SECONDS = 28800

logger = logging.getLogger("api.db_resilience")

GENERIC_ERROR_RESPONSE = {
    "error": {"code": "INTERNAL_ERROR", "message": "服务器内部错误，请稍后重试。"}
}


class DatabaseResilienceMiddleware:
    """Bounded single retry for GET requests hit by a dead/lost DB connection.

    Every request in this app opens its own connection (or pool checkout),
    so a plain retry of the whole request is enough to pick up a fresh,
    live connection after psycopg reports the previous one as lost/closed.
    This middleware operates at the raw ASGI level (not `@app.middleware`'s
    `BaseHTTPMiddleware`) because that helper's `call_next` is single-use per
    request and cannot safely be invoked twice.

    Rules enforced here:
    - Only GET requests are retried. POST/PUT/DELETE are never retried.
    - At most one retry is ever attempted (never a loop).
    - On persistent failure, the existing generic unified 500 error is
      returned; only the exception class name is logged, never exception
      text (which for driver errors can embed connection details).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")

        # Buffer receive() messages so a retry can replay the same request
        # body (empty for GET) instead of re-reading an exhausted stream.
        buffered_messages: list[Message] = []
        buffer_index = 0

        async def recording_receive() -> Message:
            message = await receive()
            buffered_messages.append(message)
            return message

        async def replaying_receive() -> Message:
            nonlocal buffer_index
            if buffer_index < len(buffered_messages):
                message = buffered_messages[buffer_index]
                buffer_index += 1
                return message
            return await receive()

        async def attempt(receive_fn: Receive) -> None:
            await self.app(scope, receive_fn, send)

        try:
            await attempt(recording_receive)
            return
        except CONNECTION_LOST_ERRORS as exc:
            if method != "GET":
                logger.error("database connection error: %s", sanitize_db_error_marker(exc))
                await _send_generic_500(send)
                return
            logger.warning(
                "database connection error, retrying once: %s", sanitize_db_error_marker(exc)
            )
        except Exception as exc:  # noqa: BLE001 - unified generic 500 boundary
            if isinstance(exc, HTTPException):
                raise
            logger.error("unhandled request error: %s", sanitize_db_error_marker(exc))
            await _send_generic_500(send)
            return

        # Exactly one bounded retry, GET only. Never loops further: any
        # failure here — connection-lost or otherwise — becomes the final
        # generic 500 response.
        try:
            await attempt(replaying_receive)
        except CONNECTION_LOST_ERRORS as retry_exc:
            logger.error(
                "database connection error, retry failed: %s",
                sanitize_db_error_marker(retry_exc),
            )
            await _send_generic_500(send)
        except Exception as retry_exc:  # noqa: BLE001
            if isinstance(retry_exc, HTTPException):
                raise
            logger.error(
                "unhandled request error after retry: %s",
                sanitize_db_error_marker(retry_exc),
            )
            await _send_generic_500(send)


async def _send_generic_500(send: Send) -> None:
    response = JSONResponse(status_code=500, content=GENERIC_ERROR_RESPONSE)
    await response({"type": "http"}, _no_op_receive, send)


async def _no_op_receive() -> Message:
    return {"type": "http.disconnect"}


class LoginRequest(BaseModel):
    password: str | None = None
    operator_name: str | None = None


def create_app(
    settings: Settings | None = None,
    *,
    environment: str | None = None,
    followers_service_factory=None,
    agent_service_factory=None,
) -> FastAPI:
    """Build the FastAPI app. Phase 1: read-only endpoints + session auth only.

    `followers_service_factory` lets tests substitute a `FollowerService`
    wired with stub providers so the batch-update job endpoints never touch
    the real network; production callers leave it unset and get the real
    YouTube/TikTok providers wired from `resolved_settings`.
    """
    resolved_settings = settings or load_settings()
    resolved_environment = environment or os.environ.get("APP_ENV", "development")
    secure_cookie = resolved_environment != "development"
    session_store = SessionStore(ttl_seconds=SESSION_MAX_AGE_SECONDS)
    import_preview_store = PreviewStore()
    follower_job_store = JobStore()

    def create_follower_service() -> FollowerService:
        if followers_service_factory is not None:
            return followers_service_factory()
        return FollowerService(
            KOCRepository(resolved_settings.database_path),
            youtube_api_key=resolved_settings.youtube_api_key,
            tiktok_browser_data_dir=resolved_settings.tiktok_browser_data_dir,
            tiktok_persistent_headless=resolved_settings.tiktok_persistent_headless,
        )

    app = FastAPI(title="KOC Dashboard API")
    app.add_middleware(DatabaseResilienceMiddleware)

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

    def get_session_context(request: Request) -> dict:
        session_id = request.cookies.get(SESSION_COOKIE_NAME) or ""
        return {
            "session_id": session_id,
            "operator_name": session_store.operator_name_for(session_id),
        }

    creators_router = build_creators_router(
        database_path=resolved_settings.database_path,
        require_session=Depends(require_session),
        session_context=Depends(get_session_context),
    )
    app.include_router(creators_router)

    dashboard_router = build_dashboard_router(
        database_path=resolved_settings.database_path,
        require_session=Depends(require_session),
    )
    app.include_router(dashboard_router)

    compensation_router = build_compensation_router(
        database_path=resolved_settings.database_path,
        require_session=Depends(require_session),
        session_context=Depends(get_session_context),
    )
    app.include_router(compensation_router)

    imports_router = build_imports_router(
        database_path=resolved_settings.database_path,
        timezone=resolved_settings.timezone,
        require_session=Depends(require_session),
        session_context=Depends(get_session_context),
        preview_store=import_preview_store,
    )
    app.include_router(imports_router)

    followers_router = build_followers_router(
        database_path=resolved_settings.database_path,
        require_session=Depends(require_session),
        session_context=Depends(get_session_context),
        service_factory=create_follower_service,
        youtube_api_key=resolved_settings.youtube_api_key,
        tiktok_browser_data_dir=resolved_settings.tiktok_browser_data_dir,
        tiktok_persistent_headless=resolved_settings.tiktok_persistent_headless,
        job_store=follower_job_store,
    )
    app.include_router(followers_router)

    agent_router = build_agent_router(
        database_path=resolved_settings.database_path,
        require_session=Depends(require_session),
        session_context=Depends(get_session_context),
        provider=resolved_settings.ai_provider,
        model=resolved_settings.ai_model,
        configured=resolved_settings.ai_configured,
        api_key=resolved_settings.ai_api_key,
        base_url=resolved_settings.ai_base_url,
        service_factory=agent_service_factory,
        import_preview_store=import_preview_store,
        follower_service_factory=create_follower_service,
        follower_job_store=follower_job_store,
    )
    app.include_router(agent_router)

    @app.get("/api/health", response_model=None)
    def health():
        database = "postgres" if is_postgres_target(resolved_settings.database_path) else "sqlite"
        database_target = str(resolved_settings.database_path)
        try:
            with connect(resolved_settings.database_path) as connection:
                connection.execute("SELECT 1").fetchone()
        except Exception as exc:  # noqa: BLE001 - never expose driver details
            logger.error("database readiness check failed: %s", sanitize_db_error_marker(exc))
            return JSONResponse(status_code=503, content=GENERIC_ERROR_RESPONSE)

        return {
            "data": {
                "status": "ok",
                "database": database,
                "database_ready": True,
                "supabase_ipv4_preferred": (
                    _prefer_ipv4_for_supabase_pooler(database_target) != database_target
                ),
            }
        }

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

        operator_name = (payload.operator_name or "").strip() or None
        if operator_name is not None and not (2 <= len(operator_name) <= 30):
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "operator_name 必须为 2-30 个字符。",
                        "field_errors": [
                            {"field": "operator_name", "message": "operator_name 必须为 2-30 个字符。"}
                        ],
                    }
                },
            )

        session_id = session_store.create(operator_name=operator_name)
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
