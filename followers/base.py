from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from models.enums import FollowerSource


@dataclass(frozen=True)
class FollowerFetchResult:
    success: bool
    follower_count: int | None
    platform: str | None
    fetched_at: str
    error_code: str | None = None
    error_message: str | None = None
    raw_display_value: str | None = None
    is_estimated: bool = False
    source: FollowerSource | None = None
    source_url: str | None = None
    profile_url: str | None = None
    settlement_eligible: bool = False
    profile_id: str | None = None
    profile_title: str | None = None


class FollowerProvider(Protocol):
    def fetch(self, homepage_url: str) -> FollowerFetchResult: ...
