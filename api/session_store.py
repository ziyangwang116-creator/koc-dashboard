from __future__ import annotations

import secrets
import time
from dataclasses import dataclass


@dataclass
class Session:
    issued_at: float
    expires_at: float
    operator_name: str | None = None


class SessionStore:
    """Minimal in-memory session store for phase-1 team-password auth."""

    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, Session] = {}

    def create(self, operator_name: str | None = None) -> str:
        session_id = secrets.token_urlsafe(32)
        now = time.time()
        self._sessions[session_id] = Session(
            issued_at=now,
            expires_at=now + self.ttl_seconds,
            operator_name=operator_name,
        )
        return session_id

    def is_valid(self, session_id: str | None) -> bool:
        if not session_id:
            return False
        session = self._sessions.get(session_id)
        if session is None:
            return False
        if time.time() >= session.expires_at:
            del self._sessions[session_id]
            return False
        return True

    def get(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if time.time() >= session.expires_at:
            del self._sessions[session_id]
            return None
        return session

    def operator_name_for(self, session_id: str | None) -> str:
        session = self.get(session_id)
        if session is not None and session.operator_name:
            return session.operator_name
        return "team"

    def delete(self, session_id: str | None) -> None:
        if session_id:
            self._sessions.pop(session_id, None)
