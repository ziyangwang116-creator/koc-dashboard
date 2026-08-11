from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass

IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60


@dataclass
class CachedResponse:
    body_hash: str
    status_code: int
    body: dict
    expires_at: float


class IdempotencyCache:
    """In-memory 24h cache for Idempotency-Key deduplication (per 19.6.4).

    Keyed by (operation, session_id, idempotency_key). Stores the request
    body hash alongside the first successful response so that a repeat of
    the same key with a *different* body can be rejected as key reuse,
    while a repeat with the same body returns the cached result without
    re-executing the write.
    """

    def __init__(self, ttl_seconds: int = IDEMPOTENCY_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._entries: dict[tuple[str, str, str], CachedResponse] = {}

    @staticmethod
    def hash_body(body: object) -> str:
        canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _key(self, operation: str, session_id: str, idempotency_key: str) -> tuple[str, str, str]:
        return (operation, session_id, idempotency_key)

    def lookup(
        self, operation: str, session_id: str, idempotency_key: str
    ) -> CachedResponse | None:
        key = self._key(operation, session_id, idempotency_key)
        entry = self._entries.get(key)
        if entry is None:
            return None
        if time.time() >= entry.expires_at:
            del self._entries[key]
            return None
        return entry

    def store(
        self,
        operation: str,
        session_id: str,
        idempotency_key: str,
        *,
        body_hash: str,
        status_code: int,
        body: dict,
    ) -> None:
        key = self._key(operation, session_id, idempotency_key)
        self._entries[key] = CachedResponse(
            body_hash=body_hash,
            status_code=status_code,
            body=body,
            expires_at=time.time() + self.ttl_seconds,
        )
