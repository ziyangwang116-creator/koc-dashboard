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


class AIAgentService:
    MAX_TOOL_ROUNDS = 6

    def __init__(
        self,
        database_path: Path | str,
        *,
        api_key: str | None,
        model: str,
        client: Any | None = None,
    ) -> None:
        self.repository = AIRepository(database_path)
        self.tools = AIToolRegistry(database_path)
        self.model = str(model).strip()
        if not self.model:
            raise AIAgentServiceError("OPENAI_MODEL 未配置。")
        if client is not None:
            self.client = client
        else:
            if not api_key:
                raise AIAgentServiceError("OPENAI_API_KEY 未配置。")
            if OpenAI is None:
                raise AIAgentServiceError("缺少 openai Python 依赖。")
            self.client = OpenAI(api_key=api_key)

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
                response = self.client.responses.create(
                    model=self.model,
                    instructions=SYSTEM_PROMPT,
                    previous_response_id=str(_item_value(response, "id", "")),
                    input=outputs,
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
            raise AIAgentServiceError(f"AI 请求失败：{exc}") from exc

        answer = str(_item_value(response, "output_text", "")).strip()
        if not answer:
            raise AIAgentServiceError("AI 未返回可显示的回答。")
        self.repository.add_message(
            conversation_id,
            "assistant",
            answer,
            metadata={"model": self.model, "tool_calls": len(tool_audits)},
        )
        return AIAgentResponse(answer=answer, tool_calls=tuple(tool_audits))
