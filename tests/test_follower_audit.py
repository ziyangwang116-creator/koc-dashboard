from database.koc_repository import KOCRepository
from followers.base import FollowerFetchResult
from models.enums import FollowerSource, FollowerSyncStatus
from services.follower_service import FollowerService


class OfficialSuccessProvider:
    def fetch(self, homepage_url):
        return FollowerFetchResult(
            success=True,
            follower_count=120000,
            platform="YouTube",
            fetched_at="2026-07-17T01:02:03+00:00",
            raw_display_value="120000",
            is_estimated=True,
            source=FollowerSource.YOUTUBE_API,
            source_url="https://www.googleapis.com/youtube/v3/channels",
            profile_url=homepage_url,
            settlement_eligible=True,
        )


class TikTokBrowserSuccessProvider:
    def fetch(self, homepage_url):
        return FollowerFetchResult(
            success=True,
            follower_count=12500,
            platform="TikTok",
            fetched_at="2026-07-21T01:02:03+00:00",
            raw_display_value="12.5K",
            is_estimated=True,
            source=FollowerSource.TIKTOK_BROWSER,
            source_url=homepage_url,
            profile_url=homepage_url,
            settlement_eligible=False,
        )


def test_official_success_saves_source_flags_and_audit(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="audit-youtube",
        koc_name="审计YouTube",
        homepage_url="https://www.youtube.com/@sample",
        follower_count=100,
    )
    service = FollowerService(
        repository, providers={"YouTube": OfficialSuccessProvider()}
    )

    service.update_one(record.id)
    updated = repository.get(record.id)
    audit = repository.list_follower_audit("audit-youtube").iloc[0]

    assert updated is not None
    assert updated.follower_count == 120000
    assert updated.follower_raw_display_value == "120000"
    assert updated.follower_source is FollowerSource.YOUTUBE_API
    assert updated.follower_count_is_estimated is True
    assert updated.settlement_eligible is True
    assert updated.follower_sync_status is FollowerSyncStatus.SUCCESS
    assert audit["old_follower_count"] == 100
    assert audit["new_follower_count"] == 120000
    assert audit["source"] == "YOUTUBE_API"
    assert audit["operator_mode"] == "AUTOMATIC"


def test_tiktok_browser_success_records_automatic_audit(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="audit-tiktok-browser",
        koc_name="审计TikTok浏览器",
        homepage_url="https://www.tiktok.com/@sample",
    )

    result = FollowerService(
        repository, {"TikTok": TikTokBrowserSuccessProvider()}
    ).update_one(record.id)
    updated = repository.get(record.id)
    audit = repository.list_follower_audit("audit-tiktok-browser").iloc[0]

    assert result.status == "成功"
    assert updated is not None
    assert updated.follower_count == 12500
    assert updated.follower_source is FollowerSource.TIKTOK_BROWSER
    assert updated.settlement_eligible is False
    assert updated.follower_sync_status is FollowerSyncStatus.SUCCESS
    assert audit["raw_display_value"] == "12.5K"
    assert audit["operator_mode"] == "AUTOMATIC"
    assert audit["settlement_eligible"] == 0


def test_automatic_failure_preserves_previous_source_and_settlement_flags(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="audit-preserve",
        koc_name="保留旧值",
        homepage_url="https://www.youtube.com/@sample",
    )
    repository.apply_follower_success(
        record.id,
        OfficialSuccessProvider().fetch(record.homepage_url),
    )
    old = repository.get(record.id)
    failure = FollowerFetchResult(
        success=False,
        follower_count=None,
        platform="YouTube",
        fetched_at="2026-07-17T02:03:04+00:00",
        error_code="QUOTA_EXCEEDED",
        error_message="YouTube API 配额已用尽。",
        source=FollowerSource.YOUTUBE_API,
        settlement_eligible=False,
    )

    repository.apply_follower_failure(record.id, failure)
    updated = repository.get(record.id)

    assert updated is not None and old is not None
    assert updated.follower_count == old.follower_count
    assert updated.follower_count_updated_at == old.follower_count_updated_at
    assert updated.follower_source is FollowerSource.YOUTUBE_API
    assert updated.settlement_eligible is True
    assert updated.follower_sync_status is FollowerSyncStatus.FAILED
