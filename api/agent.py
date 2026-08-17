from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database.ai_repository import AIRepository
from ai.visualizations import sanitize_visualizations
from services.ai_agent_service import AIAgentService, AIAgentServiceError


class AgentMessageRequest(BaseModel):
    message: str | None = None


class AgentActionRequest(BaseModel):
    approve: bool = False


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message}},
    )


def _safe_service_error(exc: AIAgentServiceError) -> HTTPException:
    marker = str(exc).casefold()
    if "429" in marker or "限流" in marker or "too many requests" in marker:
        return _error(503, "AI_RATE_LIMITED", "AI 服务当前限流，请稍后再试。")
    if "401" in marker or "api key" in marker or "未配置" in marker:
        return _error(503, "AI_NOT_CONFIGURED", "AI 服务配置无效，请联系管理员检查云端配置。")
    if "402" in marker or "余额" in marker or "balance" in marker:
        return _error(503, "AI_BALANCE_INSUFFICIENT", "AI 服务账户余额不足，请联系管理员。")
    return _error(503, "AI_SERVICE_ERROR", "AI 服务暂时无法完成请求，请稍后重试。")


def _conversation_id(value: str) -> str:
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _error(404, "CONVERSATION_NOT_FOUND", "对话不存在或已过期。") from exc


def _public_message(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "role": item.get("role"),
        "content": item.get("content"),
        "created_at": item.get("created_at"),
        "visualizations": sanitize_visualizations(metadata.get("visualizations")),
        "pending_actions": [
            _public_pending_action(action)
            for action in (metadata.get("pending_actions") or [])
            if isinstance(action, dict)
        ],
    }


def _public_pending_action(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": str(item.get("action_id", "")),
        "tool_name": str(item.get("tool_name", "")),
        "preview": item.get("preview", {}),
        "expires_in_seconds": int(item.get("expires_in_seconds", 0) or 0),
    }


def build_agent_router(
    *,
    database_path,
    require_session,
    session_context,
    provider: str,
    model: str,
    configured: bool,
    api_key: str | None,
    base_url: str | None,
    service_factory: Callable[[], Any] | None = None,
    import_preview_store: Any | None = None,
    follower_service_factory: Callable[[], Any] | None = None,
    follower_job_store: Any | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/agent", tags=["agent"], dependencies=[require_session])
    provider_name = str(provider).strip().casefold()
    provider_label = "DeepSeek" if provider_name == "deepseek" else "OpenAI"

    def repository() -> AIRepository:
        return AIRepository(database_path)

    def create_service(*, context: dict | None = None, conversation_id: str | None = None):
        if service_factory is not None:
            return service_factory()
        return AIAgentService(
            database_path,
            api_key=api_key,
            model=model,
            provider=provider_name,
            base_url=base_url,
            session_id=(context or {}).get("session_id"),
            operator_name=(context or {}).get("operator_name") or "team",
            import_preview_store=import_preview_store,
            follower_service_factory=follower_service_factory,
            follower_job_store=follower_job_store,
        )

    def require_conversation(conversation_id: str, session_id: str) -> str:
        normalized = _conversation_id(conversation_id)
        if not repository().conversation_belongs_to_session(normalized, session_id):
            raise _error(404, "CONVERSATION_NOT_FOUND", "对话不存在或已过期。")
        return normalized

    @router.get("/status")
    def status() -> dict[str, Any]:
        return {
            "data": {
                "configured": bool(configured),
                "provider": provider_name,
                "provider_label": provider_label,
                "model": model,
                "read_only": False,
                "write_enabled": True,
                "writes_require_confirmation": True,
            }
        }

    @router.post("/conversations", status_code=201)
    def create_conversation(context: dict = session_context) -> dict[str, Any]:
        conversation_id = str(uuid4())
        repository().ensure_conversation(conversation_id, context["session_id"])
        return {"data": {"conversation_id": conversation_id}}

    @router.get("/conversations/{conversation_id}/messages")
    def list_messages(
        conversation_id: str,
        context: dict = session_context,
    ) -> dict[str, Any]:
        normalized = require_conversation(conversation_id, context["session_id"])
        active_actions = {
            item["action_id"]: item
            for item in repository().list_pending_actions(
                normalized,
                session_id=context["session_id"],
            )
        }
        messages = []
        for item in repository().list_messages_for_session(
            normalized,
            context["session_id"],
            limit=50,
        ):
            public = _public_message(item)
            public["pending_actions"] = [
                action
                for action in public.get("pending_actions", [])
                if action.get("action_id") in active_actions
            ]
            messages.append(public)
        return {
            "data": messages
        }

    @router.post("/conversations/{conversation_id}/messages")
    def send_message(
        conversation_id: str,
        payload: AgentMessageRequest,
        context: dict = session_context,
    ) -> dict[str, Any]:
        cleaned_message = str(payload.message or "").strip()
        if not cleaned_message:
            raise _error(422, "VALIDATION_ERROR", "问题不能为空。")
        if len(cleaned_message) > 4000:
            raise _error(422, "VALIDATION_ERROR", "问题不能超过 4000 个字符。")
        if not configured:
            raise _error(503, "AI_NOT_CONFIGURED", "AI 服务尚未配置，请联系管理员。")

        normalized = require_conversation(conversation_id, context["session_id"])
        try:
            response = create_service(
                    context=context,
                    conversation_id=normalized,
                ).ask(
                    conversation_id=normalized,
                    session_id=context["session_id"],
                    message=cleaned_message,
            )
        except PermissionError as exc:
            raise _error(404, "CONVERSATION_NOT_FOUND", "对话不存在或已过期。") from exc
        except AIAgentServiceError as exc:
            raise _safe_service_error(exc) from exc

        evidence = [
            {
                "tool_name": item.get("tool_name", ""),
                "summary": item.get("summary", {}),
                "duration_ms": item.get("duration_ms", 0),
            }
            for item in response.tool_calls
        ]
        visualizations = sanitize_visualizations(response.visualizations)
        return {
            "data": {
                "conversation_id": normalized,
                "answer": response.answer,
                "tool_calls": evidence,
                "visualizations": visualizations,
                "pending_actions": [
                    _public_pending_action(item)
                    for item in response.pending_actions
                ],
            }
        }

    @router.post("/conversations/{conversation_id}/actions/{action_id}/confirm")
    def confirm_action(
        conversation_id: str,
        action_id: str,
        payload: AgentActionRequest,
        context: dict = session_context,
    ) -> dict[str, Any]:
        normalized = require_conversation(conversation_id, context["session_id"])
        try:
            result = create_service(
                context=context,
                conversation_id=normalized,
            ).confirm_action(
                conversation_id=normalized,
                session_id=context["session_id"],
                action_id=action_id,
                approve=bool(payload.approve),
            )
        except AIAgentServiceError as exc:
            raise _safe_service_error(exc) from exc
        return {"data": result}

    return router
