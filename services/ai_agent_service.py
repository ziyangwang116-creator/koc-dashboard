from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai.prompts import SYSTEM_PROMPT
from ai.schemas import OPENAI_TOOLS
from ai.tools import AIToolError, AIToolRegistry
from database.ai_repository import AIRepository

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - surfaced as a configuration error.
    OpenAI = None


class AIAgentServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class AIAgentResponse:
    answer: str
    tool_calls: tuple[dict[str, Any], ...]


def _item_value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _output_item_payload(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    model_dump = getattr(item, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json", exclude_none=True)
    payload = {}
    for name in (
        "type",
        "id",
        "status",
        "role",
        "content",
        "call_id",
        "name",
        "arguments",
    ):
        value = getattr(item, name, None)
        if value is not None:
            payload[name] = value
    return payload


def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "status": result.get("status", "ok"),
        "keys": sorted(result.keys()),
    }
    for key in (
        "total_matches",
        "returned",
        "post_count",
        "matched_post_count",
        "unmatched_post_count",
    ):
        if key in result:
            summary[key] = result[key]
    for key in ("creators", "videos", "settlements", "contract_periods", "revisions"):
        if isinstance(result.get(key), list):
            summary[f"{key}_count"] = len(result[key])
    return summary


def _exception_status_code(exc: Exception) -> int | None:
    """Extract an HTTP status from wrapped SDK and transport exceptions."""
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        status_code = getattr(current, "status_code", None)
        if isinstance(status_code, int):
            return status_code
        response = getattr(current, "response", None)
        response_status = getattr(response, "status_code", None)
        if isinstance(response_status, int):
            return response_status
        message = str(current).casefold()
        if "429" in message or "too many requests" in message:
            return 429
        if "402" in message or "insufficient balance" in message:
            return 402
        if "401" in message or "invalid api key" in message:
            return 401
        current = current.__cause__ or current.__context__
    return None


class AIAgentService:
    MAX_TOOL_ROUNDS = 6

    def __init__(
        self,
        database_path: Path | str,
        *,
        api_key: str | None,
        model: str,
        provider: str = "openai",
        base_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.repository = AIRepository(database_path)
        self.tools = AIToolRegistry(database_path)
        self.provider = str(provider).strip().casefold()
        if self.provider not in {"deepseek", "openai"}:
            raise AIAgentServiceError("AI provider 必须是 deepseek 或 openai。")
        self.model = str(model).strip()
        if not self.model:
            raise AIAgentServiceError("AI 模型未配置。")
        if client is not None:
            self.client = client
        else:
            if not api_key:
                key_name = (
                    "DEEPSEEK_API_KEY"
                    if self.provider == "deepseek"
                    else "OPENAI_API_KEY"
                )
                raise AIAgentServiceError(f"{key_name} 未配置。")
            if OpenAI is None:
                raise AIAgentServiceError("缺少 openai Python 依赖。")
            client_options: dict[str, Any] = {
                "api_key": api_key,
                "max_retries": 0,
                "timeout": 45.0,
            }
            if base_url:
                client_options["base_url"] = base_url
            self.client = OpenAI(**client_options)

    def _execute_tool(
        self,
        *,
        conversation_id: str,
        tool_name: str,
        raw_arguments: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        started = time.perf_counter()
        try:
            decoded = json.loads(raw_arguments or "{}")
            if not isinstance(decoded, dict):
                raise AIToolError("工具参数必须是 JSON 对象。")
            result = self.tools.execute(tool_name, decoded)
            duration_ms = int((time.perf_counter() - started) * 1000)
            summary = _result_summary(result)
            self.repository.log_tool_call(
                conversation_id=conversation_id,
                tool_name=tool_name,
                arguments=decoded,
                result_summary=summary,
                duration_ms=duration_ms,
                status="SUCCESS",
            )
            return result, {
                "tool_name": tool_name,
                "arguments": decoded,
                "summary": summary,
                "duration_ms": duration_ms,
            }
        except (json.JSONDecodeError, AIToolError, TypeError, ValueError) as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            error_code = getattr(exc, "code", "INVALID_ARGUMENT")
            decoded = decoded if "decoded" in locals() and isinstance(decoded, dict) else {}
            result = {
                "status": "error",
                "error_code": error_code,
                "message": str(exc),
            }
            self.repository.log_tool_call(
                conversation_id=conversation_id,
                tool_name=tool_name,
                arguments=decoded,
                result_summary=result,
                duration_ms=duration_ms,
                status="ERROR",
                error_code=error_code,
            )
            return result, {
                "tool_name": tool_name,
                "arguments": decoded,
                "summary": result,
                "duration_ms": duration_ms,
            }

    def _chat_completion_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for tool in OPENAI_TOOLS:
            function = {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            }
            tools.append({"type": "function", "function": function})
        return tools

    def _ask_with_chat_completions(
        self,
        *,
        conversation_id: str,
        history: list[dict[str, Any]],
    ) -> AIAgentResponse:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *(
                {"role": item["role"], "content": item["content"]}
                for item in history
            ),
        ]
        tool_audits: list[dict[str, Any]] = []
        tools = self._chat_completion_tools()

        for _ in range(self.MAX_TOOL_ROUNDS + 1):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
            choices = _item_value(response, "choices", []) or []
            if not choices:
                raise AIAgentServiceError("AI 未返回可显示的回答。")
            message = _item_value(choices[0], "message")
            tool_calls = _item_value(message, "tool_calls", []) or []
            if not tool_calls:
                answer = str(_item_value(message, "content", "") or "").strip()
                if not answer:
                    raise AIAgentServiceError("AI 未返回可显示的回答。")
                return AIAgentResponse(answer=answer, tool_calls=tuple(tool_audits))

            messages.append(
                {
                    "role": "assistant",
                    "content": _item_value(message, "content", None),
                    "tool_calls": [
                        {
                            "id": str(_item_value(call, "id", "")),
                            "type": "function",
                            "function": {
                                "name": str(
                                    _item_value(_item_value(call, "function"), "name", "")
                                ),
                                "arguments": str(
                                    _item_value(
                                        _item_value(call, "function"),
                                        "arguments",
                                        "{}",
                                    )
                                ),
                            },
                        }
                        for call in tool_calls
                    ],
                }
            )
            for call in tool_calls:
                function = _item_value(call, "function")
                result, audit = self._execute_tool(
                    conversation_id=conversation_id,
                    tool_name=str(_item_value(function, "name", "")),
                    raw_arguments=str(_item_value(function, "arguments", "{}")),
                )
                tool_audits.append(audit)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(_item_value(call, "id", "")),
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )

        raise AIAgentServiceError("AI 工具调用轮次过多，已停止本次请求。")

    def ask(
        self,
        *,
        conversation_id: str,
        session_id: str,
        message: str,
    ) -> AIAgentResponse:
        cleaned_message = str(message).strip()
        if not cleaned_message:
            raise AIAgentServiceError("问题不能为空。")
        self.repository.delete_expired()
        self.repository.ensure_conversation(
            conversation_id,
            session_id,
            title=cleaned_message[:80],
        )
        self.repository.add_message(conversation_id, "user", cleaned_message)
        history = self.repository.list_messages(conversation_id, limit=30)
        if self.provider == "deepseek" and hasattr(self.client, "chat"):
            try:
                response = self._ask_with_chat_completions(
                    conversation_id=conversation_id,
                    history=history,
                )
            except AIAgentServiceError:
                raise
            except Exception as exc:
                raise AIAgentServiceError(self._provider_error_message(exc)) from exc
            self.repository.add_message(
                conversation_id,
                "assistant",
                response.answer,
                metadata={
                    "provider": self.provider,
                    "model": self.model,
                    "tool_calls": len(response.tool_calls),
                },
            )
            return response
        inputs = [
            {"role": item["role"], "content": item["content"]}
            for item in history
        ]
        tool_audits: list[dict[str, Any]] = []
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=SYSTEM_PROMPT,
                input=inputs,
                tools=OPENAI_TOOLS,
            )
            for _ in range(self.MAX_TOOL_ROUNDS):
                function_calls = [
                    item
                    for item in (_item_value(response, "output", []) or [])
                    if _item_value(item, "type") == "function_call"
                ]
                if not function_calls:
                    break
                inputs.extend(
                    _output_item_payload(item)
                    for item in (_item_value(response, "output", []) or [])
                )
                outputs = []
                for call in function_calls:
                    result, audit = self._execute_tool(
                        conversation_id=conversation_id,
                        tool_name=str(_item_value(call, "name", "")),
                        raw_arguments=str(_item_value(call, "arguments", "{}")),
                    )
                    tool_audits.append(audit)
                    outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": str(_item_value(call, "call_id", "")),
                            "output": json.dumps(result, ensure_ascii=False, default=str),
                        }
                    )
                inputs.extend(outputs)
                response = self.client.responses.create(
                    model=self.model,
                    instructions=SYSTEM_PROMPT,
                    input=inputs,
                    tools=OPENAI_TOOLS,
                )
            else:
                remaining_calls = [
                    item
                    for item in (_item_value(response, "output", []) or [])
                    if _item_value(item, "type") == "function_call"
                ]
                if remaining_calls:
                    raise AIAgentServiceError("AI 工具调用轮次过多，已停止本次请求。")
        except AIAgentServiceError:
            raise
        except Exception as exc:
            status_code = _exception_status_code(exc)
            provider_label = "DeepSeek" if self.provider == "deepseek" else "OpenAI"
            if status_code == 401:
                message = f"{provider_label} API Key 无效，请更新云端 Secrets 后重启。"
            elif status_code == 402:
                message = f"{provider_label} API 账户余额不足。"
            elif status_code == 429:
                message = (
                    f"{provider_label} API 当前限流（429）。请等待 30-60 秒后重试；"
                    "若持续出现，请检查账户余额以及并发、RPM/QPM 限制。"
                )
            else:
                message = f"{provider_label} AI 请求失败，请稍后重试。"
            raise AIAgentServiceError(message) from exc

        answer = str(_item_value(response, "output_text", "")).strip()
        if not answer:
            raise AIAgentServiceError("AI 未返回可显示的回答。")
        self.repository.add_message(
            conversation_id,
            "assistant",
            answer,
            metadata={
                "provider": self.provider,
                "model": self.model,
                "tool_calls": len(tool_audits),
            },
        )
        return AIAgentResponse(answer=answer, tool_calls=tuple(tool_audits))

    def _provider_error_message(self, exc: Exception) -> str:
        status_code = _exception_status_code(exc)
        provider_label = "DeepSeek" if self.provider == "deepseek" else "OpenAI"
        if status_code == 401:
            return f"{provider_label} API Key 无效，请更新云端 Secrets 后重启。"
        if status_code == 402:
            return f"{provider_label} API 账户余额不足。"
        if status_code == 429:
            return (
                f"{provider_label} API 当前限流（429）。请等待 30-60 秒后重试；"
                "若持续出现，请检查账户余额以及并发、RPM/QPM 限制。"
            )
        return f"{provider_label} AI 请求失败，请稍后重试。"
