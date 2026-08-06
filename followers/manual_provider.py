from __future__ import annotations

from datetime import datetime, timezone

from followers.base import FollowerFetchResult
from followers.value_parser import FollowerValueError, parse_follower_display_value
from models.enums import FollowerSource


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ManualProvider:
    def fetch(self, homepage_url: str) -> FollowerFetchResult:
        return FollowerFetchResult(
            success=False,
            follower_count=None,
            platform=None,
            fetched_at=_now(),
            error_code="MANUAL_INPUT_REQUIRED",
            error_message="人工数据源需要用户填写粉丝数。",
            source=FollowerSource.MANUAL,
            profile_url=homepage_url,
            settlement_eligible=False,
        )

    def from_value(
        self,
        raw_display_value: object,
        *,
        profile_url: str | None,
        settlement_confirmed: bool = False,
    ) -> FollowerFetchResult:
        try:
            parsed = parse_follower_display_value(raw_display_value)
        except FollowerValueError as exc:
            return FollowerFetchResult(
                success=False,
                follower_count=None,
                platform=None,
                fetched_at=_now(),
                error_code="INVALID_FOLLOWER_VALUE",
                error_message=str(exc),
                raw_display_value=str(raw_display_value).strip(),
                source=FollowerSource.MANUAL,
                profile_url=profile_url,
                settlement_eligible=False,
            )
        return FollowerFetchResult(
            success=True,
            follower_count=parsed.follower_count,
            platform=None,
            fetched_at=_now(),
            raw_display_value=parsed.raw_display_value,
            is_estimated=parsed.is_estimated,
            source=FollowerSource.MANUAL,
            profile_url=profile_url,
            settlement_eligible=settlement_confirmed,
        )
