from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from database.koc_repository import KOCRepository
from followers.base import FollowerFetchResult, FollowerProvider
from followers.tiktok_public_provider import (
    TIKTOK_BATCH_STOP_ERROR_CODES,
    TikTokPublicProfileProvider,
)
from followers.tiktok_provider import (
    build_tiktok_profile,
)
from followers.url_parser import identify_platform
from followers.youtube_provider import YouTubeOfficialProvider
from models.enums import FollowerSource, FollowerSyncStatus, OperatorMode
from models.koc import KOCRecord


SKIPPED_ERROR_CODES = {
    "MISSING_URL",
    "UNSUPPORTED_PLATFORM",
    "TIKTOK_BATCH_STOPPED",
    "DUPLICATE_CREATOR",
}


@dataclass(frozen=True)
class FollowerUpdateOutcome:
    record_id: int
    user_id: str
    koc_name: str
    status: str
    result: FollowerFetchResult


@dataclass(frozen=True)
class BatchFollowerUpdateResult:
    success_count: int
    failed_count: int
    skipped_count: int
    details: pd.DataFrame
    youtube_success_count: int = 0
    youtube_failed_count: int = 0
    tiktok_success_count: int = 0
    tiktok_failed_count: int = 0
    stopped: bool = False
    stop_error_code: str | None = None


ProgressCallback = Callable[
    [int, int, KOCRecord, FollowerUpdateOutcome], None
]
StartCallback = Callable[[int, int, KOCRecord], None]


class FollowerService:
    def __init__(
        self,
        repository: KOCRepository,
        providers: dict[str, FollowerProvider] | None = None,
        *,
        youtube_api_key: str | None = None,
        tiktok_browser_data_dir: Path | None = None,
        tiktok_persistent_headless: bool = False,
    ) -> None:
        self.repository = repository
        default_tiktok = TikTokPublicProfileProvider()
        if providers is None:
            self.providers: dict[str, FollowerProvider] = {
                "YouTube": YouTubeOfficialProvider(api_key=youtube_api_key),
                "TikTok": default_tiktok,
            }
        else:
            self.providers = providers
        self.tiktok_provider = self.providers.get("TikTok", default_tiktok)

    @staticmethod
    def _result(
        *,
        error_code: str,
        error_message: str,
        platform: str | None = None,
        source: FollowerSource | None = None,
        profile_url: str | None = None,
    ) -> FollowerFetchResult:
        return FollowerFetchResult(
            False,
            None,
            platform,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            error_code,
            error_message,
            source=source,
            profile_url=profile_url,
        )

    @staticmethod
    def _contract_platforms(record: KOCRecord) -> tuple[bool, bool]:
        """Return whether a creator has TikTok and/or YouTube contract text."""
        compact_contracts = [
            str(contract).casefold().replace(" ", "")
            for contract in record.contract_types
            if str(contract).strip()
        ]
        is_tiktok = any("tt" in contract or "tiktok" in contract for contract in compact_contracts)
        is_youtube = any("ytb" in contract or "youtube" in contract for contract in compact_contracts)
        return is_tiktok, is_youtube

    @classmethod
    def required_platform_for_record(cls, record: KOCRecord) -> str | None:
        """Infer the follower source from the active contract text, not its month label."""
        is_tiktok, is_youtube = cls._contract_platforms(record)
        if is_tiktok and not is_youtube:
            return "TikTok"
        if is_youtube and not is_tiktok:
            return "YouTube"
        return None

    @classmethod
    def has_tiktok_contract(cls, record: KOCRecord) -> bool:
        return cls._contract_platforms(record)[0]

    @classmethod
    def has_youtube_contract(cls, record: KOCRecord) -> bool:
        return cls._contract_platforms(record)[1]

    @staticmethod
    def _homepage_for_platform(record: KOCRecord, platform: str | None) -> str | None:
        """Return a platform-specific profile URL without cross-platform fallback."""
        if platform is None:
            return record.homepage_url

        if platform.casefold() == "tiktok":
            if record.tiktok_homepage_url and record.tiktok_homepage_url.strip():
                return record.tiktok_homepage_url
            if identify_platform(record.homepage_url) == "TikTok":
                return record.homepage_url
            return None

        if platform.casefold() != "youtube":
            return record.homepage_for_platform(platform)

        if record.youtube_homepage_url and record.youtube_homepage_url.strip():
            return record.youtube_homepage_url
        if identify_platform(record.homepage_url) == "YouTube":
            return record.homepage_url
        # The company database UID is not a YouTube channel ID and must never
        # be used as a lookup fallback.
        return None

    def fetch_follower_count(
        self,
        homepage_url: str | None,
        *,
        required_platform: str | None = None,
    ) -> FollowerFetchResult:
        if homepage_url is None or not homepage_url.strip():
            return self._result(
                error_code="MISSING_URL",
                error_message="未填写达人主页链接。",
                platform=required_platform,
            )
        platform = required_platform or identify_platform(homepage_url)
        if platform is None:
            return self._result(
                error_code="UNSUPPORTED_PLATFORM",
                error_message="暂不支持该主页链接。",
            )
        provider = self.providers.get(platform)
        if provider is None:
            return self._result(
                error_code="DATA_SOURCE_NOT_CONFIGURED",
                error_message=f"{platform} 当前未配置可用的数据源。",
                platform=platform,
            )
        try:
            return provider.fetch(homepage_url)
        except Exception:
            return self._result(
                error_code="PROVIDER_ERROR",
                error_message=f"{platform} 粉丝数获取失败。",
                platform=platform,
            )

    def _save_result(
        self,
        record: KOCRecord,
        result: FollowerFetchResult,
    ) -> FollowerUpdateOutcome:
        if result.success and result.follower_count is not None:
            self.repository.apply_follower_success(
                record.id,
                result,
                sync_status=FollowerSyncStatus.SUCCESS,
                operator_mode=OperatorMode.AUTOMATIC,
            )
            status = "成功"
        elif result.error_code in SKIPPED_ERROR_CODES:
            self.repository.record_follower_attempt(record.id, result)
            status = "跳过"
        else:
            self.repository.apply_follower_failure(record.id, result)
            status = "失败"
        return FollowerUpdateOutcome(
            record.id, record.user_id, record.koc_name, status, result
        )

    def update_one(
        self, record_id: int, *, required_platform: str | None = None
    ) -> FollowerUpdateOutcome:
        record = self.repository.get(record_id)
        if record is None:
            raise ValueError("未找到要更新粉丝数的达人。")
        profile_url = self._homepage_for_platform(record, required_platform)
        result = self.fetch_follower_count(
            profile_url,
            required_platform=required_platform,
        )
        return self._save_result(record, result)

    def preview_tiktok(self, record_id: int) -> FollowerFetchResult:
        record = self.repository.get(record_id)
        if record is None:
            raise ValueError("未找到要测试的 TikTok 达人。")
        return self.fetch_follower_count(
            record.homepage_for_platform("TikTok"),
            required_platform="TikTok",
        )

    def confirm_tiktok_preview(
        self, record_id: int, result: FollowerFetchResult
    ) -> KOCRecord:
        if (
            not result.success
            or result.platform != "TikTok"
            or result.follower_count is None
        ):
            raise ValueError("只能确认写入成功的 TikTok 测试结果。")
        return self.repository.apply_follower_success(
            record_id,
            result,
            sync_status=FollowerSyncStatus.SUCCESS,
            operator_mode=OperatorMode.AUTOMATIC,
        )

    @staticmethod
    def _duplicate_result(record: KOCRecord, platform: str | None) -> FollowerFetchResult:
        return FollowerService._result(
            error_code="DUPLICATE_CREATOR",
            error_message="同一达人已在本批次处理，已跳过重复任务。",
            platform=platform,
            profile_url=(
                record.homepage_for_platform(platform)
                if platform is not None
                else record.homepage_url
            ),
        )

    @staticmethod
    def _stopped_result(
        record: KOCRecord, stop_error_code: str
    ) -> FollowerFetchResult:
        return FollowerService._result(
            error_code="TIKTOK_BATCH_STOPPED",
            error_message=(
                f"TikTok 批次已因 {stop_error_code} 停止，未继续访问主页。"
            ),
            platform="TikTok",
            source=FollowerSource.TIKTOK_BROWSER,
            profile_url=record.homepage_for_platform("TikTok"),
        )

    @staticmethod
    def _detail_row(outcome: FollowerUpdateOutcome) -> dict[str, Any]:
        profile = build_tiktok_profile(outcome.result.profile_url)
        return {
            "user_id": outcome.user_id,
            "koc_name": outcome.koc_name,
            "status": outcome.status,
            "platform": outcome.result.platform,
            "follower_count": outcome.result.follower_count,
            "tiktok_username": (
                f"@{profile.username}" if profile is not None else None
            ),
            "error_code": outcome.result.error_code,
            "message": outcome.result.error_message or "更新成功",
        }

    def update_many(
        self,
        record_ids: Iterable[int],
        *,
        required_platform: str | None = None,
        platform_by_record: dict[int, str | None] | None = None,
        progress_callback: ProgressCallback | None = None,
        start_callback: StartCallback | None = None,
    ) -> BatchFollowerUpdateResult:
        ids = list(dict.fromkeys(int(record_id) for record_id in record_ids))
        success = failed = skipped = 0
        youtube_success = youtube_failed = 0
        tiktok_success = tiktok_failed = 0
        rows: list[dict[str, Any]] = []
        total = len(ids)
        seen_user_ids: set[str] = set()
        seen_tiktok_usernames: set[str] = set()
        stop_error_code: str | None = None

        for completed, record_id in enumerate(ids, start=1):
            record = self.repository.get(record_id)
            if record is None:
                failed += 1
                rows.append(
                    {
                        "user_id": "",
                        "koc_name": "",
                        "status": "失败",
                        "platform": required_platform,
                        "follower_count": None,
                        "tiktok_username": None,
                        "error_code": "RECORD_NOT_FOUND",
                        "message": "达人记录不存在。",
                    }
                )
                continue
            if start_callback is not None:
                start_callback(completed, total, record)

            record_platform = (
                platform_by_record.get(record.id)
                if platform_by_record is not None
                else required_platform
            )
            profile_url = (
                record.homepage_for_platform(record_platform)
                if record_platform is not None
                else record.homepage_url
            )
            platform_hint = record_platform or identify_platform(profile_url)
            profile = build_tiktok_profile(profile_url)
            normalized_uid = record.user_id.casefold()
            normalized_username = profile.username.casefold() if profile else None
            is_duplicate = normalized_uid in seen_user_ids or (
                normalized_username is not None
                and normalized_username in seen_tiktok_usernames
            )

            if is_duplicate:
                result = self._duplicate_result(record, platform_hint)
                self.repository.record_follower_attempt(record.id, result)
                outcome = FollowerUpdateOutcome(
                    record.id, record.user_id, record.koc_name, "跳过", result
                )
            elif platform_hint == "TikTok" and stop_error_code is not None:
                result = self._stopped_result(record, stop_error_code)
                self.repository.record_follower_attempt(record.id, result)
                outcome = FollowerUpdateOutcome(
                    record.id, record.user_id, record.koc_name, "跳过", result
                )
            else:
                seen_user_ids.add(normalized_uid)
                if normalized_username is not None:
                    seen_tiktok_usernames.add(normalized_username)
                outcome = self.update_one(
                    record.id,
                    required_platform=record_platform,
                )
                if (
                    outcome.result.platform == "TikTok"
                    and outcome.result.error_code in TIKTOK_BATCH_STOP_ERROR_CODES
                ):
                    stop_error_code = outcome.result.error_code

            platform = outcome.result.platform or platform_hint
            if outcome.status == "成功":
                success += 1
                if platform == "YouTube":
                    youtube_success += 1
                elif platform == "TikTok":
                    tiktok_success += 1
            elif outcome.status == "跳过":
                skipped += 1
            else:
                failed += 1
                if platform == "YouTube":
                    youtube_failed += 1
                elif platform == "TikTok":
                    tiktok_failed += 1
            rows.append(self._detail_row(outcome))
            if progress_callback is not None:
                progress_callback(completed, total, record, outcome)

        columns = [
            "user_id",
            "koc_name",
            "status",
            "platform",
            "follower_count",
            "tiktok_username",
            "error_code",
            "message",
        ]
        return BatchFollowerUpdateResult(
            success_count=success,
            failed_count=failed,
            skipped_count=skipped,
            details=pd.DataFrame(rows, columns=columns),
            youtube_success_count=youtube_success,
            youtube_failed_count=youtube_failed,
            tiktok_success_count=tiktok_success,
            tiktok_failed_count=tiktok_failed,
            stopped=stop_error_code is not None,
            stop_error_code=stop_error_code,
        )

    def tiktok_contract_records(self) -> list[KOCRecord]:
        return [
            record
            for record in self.repository.list(active=True)
            if self.has_tiktok_contract(record)
        ]

    def update_all_tiktok(
        self,
        *,
        progress_callback: ProgressCallback | None = None,
        start_callback: StartCallback | None = None,
    ) -> BatchFollowerUpdateResult:
        records = self.tiktok_contract_records()
        return self.update_many(
            [record.id for record in records],
            required_platform="TikTok",
            progress_callback=progress_callback,
            start_callback=start_callback,
        )

    def update_all_youtube(
        self,
        *,
        progress_callback: ProgressCallback | None = None,
        start_callback: StartCallback | None = None,
    ) -> BatchFollowerUpdateResult:
        records = [
            record
            for record in self.repository.list(active=True)
            if self.has_youtube_contract(record)
        ]
        return self.update_many(
            [record.id for record in records],
            required_platform="YouTube",
            progress_callback=progress_callback,
            start_callback=start_callback,
        )


def fetch_follower_count(homepage_url: str | None) -> FollowerFetchResult:
    if homepage_url is None or not homepage_url.strip():
        return FollowerService._result(
            error_code="MISSING_URL", error_message="未填写达人主页链接。"
        )
    platform = identify_platform(homepage_url)
    if platform == "YouTube":
        return YouTubeOfficialProvider().fetch(homepage_url)
    if platform == "TikTok":
        return TikTokPersistentBrowserProvider(
            user_data_dir=Path("data") / "tiktok_browser_data"
        ).fetch(homepage_url)
    return FollowerService._result(
        error_code="UNSUPPORTED_PLATFORM", error_message="暂不支持该主页链接。"
    )
