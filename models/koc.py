from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from models.enums import (
    ContractType,
    CreatorCategory,
    FollowerSource,
    FollowerSyncStatus,
)
from models.contracts import derive_creator_categories


KOC_EXPORT_COLUMNS = [
    "user_id",
    "koc_name",
    "creator_category",
    "contract_type",
    "contract_start_date",
    "contract_end_date",
    "homepage_url",
    "follower_count",
    "youtube_user_id",
    "youtube_homepage_url",
    "youtube_follower_count",
    "tiktok_user_id",
    "tiktok_homepage_url",
    "tiktok_follower_count",
    "follower_raw_display_value",
    "follower_source",
    "follower_source_url",
    "follower_count_is_estimated",
    "follower_count_updated_at",
    "follower_sync_status",
    "settlement_eligible",
    "active",
    "note",
    "created_at",
    "updated_at",
]


@dataclass(frozen=True)
class CreatorContractPeriod:
    """The single authoritative contract term for a creator."""

    id: int
    creator_id: int
    effective_date: date
    creator_category: CreatorCategory | None
    contract_types: tuple[str, ...]
    contract_start_date: date
    contract_end_date: date
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CreatorContractRevision:
    """An auditable contract correction, change, deletion, or revert."""

    id: int
    creator_id: int
    operation_type: str
    before_periods: tuple[dict[str, object], ...]
    after_periods: tuple[dict[str, object], ...]
    affected_start_date: date | None
    affected_end_date: date | None
    reason: str | None
    reverted_revision_id: int | None
    reverted_at: str | None
    created_at: str


@dataclass(frozen=True)
class KOCRecord:
    id: int
    user_id: str
    koc_name: str
    creator_category: CreatorCategory | None
    contract_types: tuple[str, ...]
    contract_start_date: date | None
    contract_end_date: date | None
    homepage_url: str | None
    follower_count: int | None
    youtube_user_id: str | None
    youtube_homepage_url: str | None
    youtube_follower_count: int | None
    tiktok_user_id: str | None
    tiktok_homepage_url: str | None
    tiktok_follower_count: int | None
    follower_raw_display_value: str | None
    follower_source: FollowerSource | None
    follower_source_url: str | None
    follower_profile_url: str | None
    follower_count_is_estimated: bool | None
    follower_count_updated_at: str | None
    follower_sync_status: FollowerSyncStatus
    follower_error_code: str | None
    follower_sync_error: str | None
    settlement_eligible: bool
    active: bool
    note: str | None
    created_at: str
    updated_at: str

    @property
    def contract_type(self) -> ContractType | str | None:
        """Backward-compatible access to the first contract relationship."""
        if not self.contract_types:
            return None
        first = self.contract_types[0]
        try:
            return ContractType(first)
        except ValueError:
            return first

    @property
    def creator_categories(self) -> tuple[CreatorCategory, ...]:
        return derive_creator_categories(
            self.contract_types,
            fallback=self.creator_category,
        )

    def homepage_for_platform(self, platform: str) -> str | None:
        if platform.casefold() == "youtube":
            return self.youtube_homepage_url or self.homepage_url
        if platform.casefold() == "tiktok":
            return self.tiktok_homepage_url or self.homepage_url
        return self.homepage_url

    def user_id_for_platform(self, platform: str) -> str:
        if platform.casefold() == "youtube":
            return self.youtube_user_id or self.user_id
        if platform.casefold() == "tiktok":
            return self.tiktok_user_id or self.user_id
        return self.user_id

    def followers_for_platform(self, platform: str) -> int | None:
        if platform.casefold() == "youtube":
            return (
                self.youtube_follower_count
                if self.youtube_follower_count is not None
                else self.follower_count
            )
        if platform.casefold() == "tiktok":
            return (
                self.tiktok_follower_count
                if self.tiktok_follower_count is not None
                else self.follower_count
            )
        return self.follower_count


@dataclass(frozen=True)
class CreatorProfileSnapshot:
    """达人资料在某个生效日期开始使用的版本。"""

    creator_id: int
    effective_date: date
    user_id: str
    koc_name: str
    creator_category: CreatorCategory | None
    contract_types: tuple[str, ...]
    contract_start_date: date | None
    contract_end_date: date | None
    homepage_url: str | None
    follower_count: int | None
    youtube_user_id: str | None
    youtube_homepage_url: str | None
    youtube_follower_count: int | None
    tiktok_user_id: str | None
    tiktok_homepage_url: str | None
    tiktok_follower_count: int | None
    active: bool

    @property
    def creator_categories(self) -> tuple[CreatorCategory, ...]:
        return derive_creator_categories(
            self.contract_types,
            fallback=self.creator_category,
        )

    def followers_for_platform(self, platform: str) -> int | None:
        if platform.casefold() == "youtube":
            return (
                self.youtube_follower_count
                if self.youtube_follower_count is not None
                else self.follower_count
            )
        if platform.casefold() == "tiktok":
            return (
                self.tiktok_follower_count
                if self.tiktok_follower_count is not None
                else self.follower_count
            )
        return self.follower_count

    def user_id_for_platform(self, platform: str) -> str:
        if platform.casefold() == "youtube":
            return self.youtube_user_id or self.user_id
        if platform.casefold() == "tiktok":
            return self.tiktok_user_id or self.user_id
        return self.user_id
