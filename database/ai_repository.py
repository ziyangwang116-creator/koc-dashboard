from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from database.db import connect, init_db, normalize_database_target


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AIRepository:
    """Persist shared AI conversations and sanitized tool audit records."""

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = normalize_database_target(database_path)
        init_db(self.database_path)

    def ensure_conversation(
        self,
        conversation_id: str,
        session_id: str,
        *,
        title: str | None = None,
        retention_days: int = 30,
    ) -> None:
        now = _utc_now()
        expires_at = now + timedelta(days=max(1, retention_days))
        with connect(self.database_path) as connection:
            existing = connection.execute(
                "SELECT session_id FROM ai_conversation WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if existing is not None and str(existing["session_id"]) != session_id:
                raise PermissionError("Conversation does not belong to this session.")
            connection.execute(
                """
                INSERT INTO ai_conversation (
                    id, session_id, title, created_at, updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = COALESCE(ai_conversation.title, excluded.title),
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at
                """,
                (
                    conversation_id,
                    session_id,
                    title,
                    now.isoformat(),
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )

    def conversation_belongs_to_session(
        self,
        conversation_id: str,
        session_id: str,
    ) -> bool:
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM ai_conversation
                WHERE id = ? AND session_id = ? AND expires_at >= ?
                """,
                (conversation_id, session_id, _utc_now().isoformat()),
            ).fetchone()
        return row is not None

    def list_messages_for_session(
        self,
        conversation_id: str,
        session_id: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not self.conversation_belongs_to_session(conversation_id, session_id):
            raise PermissionError("Conversation does not belong to this session.")
        return self.list_messages(conversation_id, limit=limit)

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("AI message role must be user or assistant.")
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO ai_message (
                    conversation_id, role, content, metadata_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    role,
                    content.strip(),
                    json.dumps(metadata or {}, ensure_ascii=False, default=str),
                ),
            )
            connection.execute(
                "UPDATE ai_conversation SET updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (conversation_id,),
            )

    def list_messages(
        self,
        conversation_id: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT role, content, metadata_json, created_at
                FROM ai_message
                WHERE conversation_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (conversation_id, max(1, min(int(limit), 100))),
            ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in reversed(rows):
            try:
                metadata = json.loads(str(row["metadata_json"]))
            except json.JSONDecodeError:
                metadata = {}
            messages.append(
                {
                    "role": str(row["role"]),
                    "content": str(row["content"]),
                    "metadata": metadata if isinstance(metadata, dict) else {},
                    "created_at": str(row["created_at"]),
                }
            )
        return messages

    def log_tool_call(
        self,
        *,
        conversation_id: str | None,
        tool_name: str,
        arguments: dict[str, Any],
        result_summary: dict[str, Any],
        duration_ms: int,
        status: str,
        error_code: str | None = None,
    ) -> None:
        if status not in {"SUCCESS", "ERROR"}:
            raise ValueError("Tool audit status must be SUCCESS or ERROR.")
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO ai_tool_audit (
                    conversation_id, tool_name, arguments_json,
                    result_summary_json, duration_ms, status, error_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    tool_name,
                    json.dumps(arguments, ensure_ascii=False, default=str),
                    json.dumps(result_summary, ensure_ascii=False, default=str),
                    max(0, int(duration_ms)),
                    status,
                    error_code,
                ),
            )

    def delete_expired(self) -> int:
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                "DELETE FROM ai_conversation WHERE expires_at < ?",
                (_utc_now().isoformat(),),
            )
        return max(0, int(cursor.rowcount))
