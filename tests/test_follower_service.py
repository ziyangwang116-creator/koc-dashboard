import pytest

from followers.base import FollowerFetchResult
from database.koc_repository import KOCRepository
from models.enums import FollowerSource, FollowerSyncStatus
from services.follower_service import FollowerService
from services.koc_service import KOCService


class SuccessProvider:
    def fetch(self, homepage_url):
        return FollowerFetchResult(
            True, 456789, "YouTube", "2026-07-17T00:00:00+00:00"
        )


class FailedProvider:
    def fetch(self, homepage_url):
        return FollowerFetchResult(
            False,
            None,
            "YouTube",
            "2026-07-17T00:00:00+00:00",
            "FOLLOWER_COUNT_UNAVAILABLE",
            "无法获取粉丝数",
        )


class ExplodingProvider:
    def fetch(self, homepage_url):
        raise RuntimeError("provider exploded with secret response")


class TikTokBrowserSuccessProvider:
    def __init__(self):
        self.calls = 0

    def fetch(self, homepage_url):
        self.calls += 1
        return FollowerFetchResult(
            True,
            12500,
            "TikTok",
            "2026-07-17T00:00:00+00:00",
            raw_display_value="12.5K",
            is_estimated=True,
            source=FollowerSource.TIKTOK_BROWSER,
            source_url="https://www.tiktok.com/@sample_creator",
        )


class CaptchaProvider:
    def __init__(self):
        self.calls = 0

    def fetch(self, homepage_url):
        self.calls += 1
        return FollowerFetchResult(
            False,
            None,
            "TikTok",
            "2026-07-17T00:00:00+00:00",
            "CAPTCHA_REQUIRED",
            "TikTok 显示验证码。",
            source=FollowerSource.TIKTOK_BROWSER,
        )


class FirstStructureFailureThenSuccess:
    def __init__(self):
        self.calls = 0

    def fetch(self, homepage_url):
        self.calls += 1
        if self.calls == 1:
            return FollowerFetchResult(
                False,
                None,
                "TikTok",
                "2026-07-17T00:00:00+00:00",
                "PAGE_STRUCTURE_CHANGED",
                "无法确认 Followers 区域。",
                source=FollowerSource.TIKTOK_BROWSER,
            )
        return FollowerFetchResult(
            True,
            2000,
            "TikTok",
            "2026-07-17T00:01:00+00:00",
            raw_display_value="2K",
            is_estimated=True,
            source=FollowerSource.TIKTOK_BROWSER,
        )


def test_manual_follower_count_is_saved_as_integer(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(user_id="manual", koc_name="人工", follower_count=123456)
    assert record.follower_count == 123456
    assert record.follower_sync_status is FollowerSyncStatus.MANUAL


def test_editing_follower_count_marks_manual_and_updates_time(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(user_id="manual-edit", koc_name="人工修改")
    updated = KOCService(repository).update_creator(
        record.id,
        user_id=record.user_id,
        koc_name=record.koc_name,
        creator_category=None,
        contract_type=None,
        homepage_url=None,
        follower_count=222,
        active=True,
        note=None,
    )

    assert updated.follower_count == 222
    assert updated.follower_sync_status is FollowerSyncStatus.MANUAL
    assert updated.follower_count_updated_at is not None


def test_unknown_follower_count_stays_null(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(user_id="unknown", koc_name="未知")
    assert record.follower_count is None
    assert record.follower_count_updated_at is None
    assert record.follower_sync_status is FollowerSyncStatus.NEVER


def test_automatic_success_saves_count_and_time(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="success",
        koc_name="成功",
        homepage_url="https://www.youtube.com/@creator",
    )
    service = FollowerService(repository, {"YouTube": SuccessProvider()})

    outcome = service.update_one(record.id)
    updated = repository.get(record.id)

    assert outcome.status == "成功"
    assert updated.follower_count == 456789
    assert updated.follower_count_updated_at == "2026-07-17T00:00:00+00:00"
    assert updated.follower_sync_status is FollowerSyncStatus.SUCCESS
    assert updated.follower_sync_error is None


def test_automatic_failure_preserves_old_count_and_time(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="failed",
        koc_name="失败",
        homepage_url="https://www.youtube.com/@creator",
        follower_count=100,
    )
    old_time = record.follower_count_updated_at
    service = FollowerService(repository, {"YouTube": FailedProvider()})

    outcome = service.update_one(record.id)
    updated = repository.get(record.id)

    assert outcome.status == "失败"
    assert updated.follower_count == 100
    assert updated.follower_count_updated_at == old_time
    assert updated.follower_sync_status is FollowerSyncStatus.FAILED
    assert updated.follower_sync_error == "无法获取粉丝数"


def test_missing_homepage_is_skipped_without_changing_old_value(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(user_id="missing", koc_name="无链接", follower_count=88)
    service = FollowerService(repository)

    outcome = service.update_one(record.id)
    updated = repository.get(record.id)

    assert outcome.status == "跳过"
    assert outcome.result.error_code == "MISSING_URL"
    assert updated.follower_count == 88
    assert updated.follower_sync_status is FollowerSyncStatus.MANUAL


def test_unsupported_platform_is_skipped(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="unsupported",
        koc_name="不支持",
        homepage_url="https://example.com/creator",
        follower_count=77,
    )
    outcome = FollowerService(repository).update_one(record.id)

    assert outcome.status == "跳过"
    assert outcome.result.error_code == "UNSUPPORTED_PLATFORM"
    assert repository.get(record.id).follower_count == 77


def test_provider_exception_does_not_stop_batch(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    first = repository.create(
        user_id="explode",
        koc_name="异常",
        homepage_url="https://www.youtube.com/@bad",
        follower_count=1,
    )
    second = repository.create(
        user_id="skip",
        koc_name="跳过",
        homepage_url=None,
        follower_count=2,
    )
    service = FollowerService(repository, {"YouTube": ExplodingProvider()})

    result = service.update_many([first.id, second.id])

    assert result.success_count == 0
    assert result.failed_count == 1
    assert result.skipped_count == 1
    assert result.details["status"].tolist() == ["失败", "跳过"]
    assert "secret response" not in repository.get(first.id).follower_sync_error


def test_tiktok_browser_success_updates_database_from_public_page_result(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="tiktok-browser-batch",
        koc_name="TikTok自动更新",
        homepage_url="https://www.tiktok.com/@sample_creator",
        follower_count=321,
    )
    provider = TikTokBrowserSuccessProvider()

    result = FollowerService(
        repository, {"TikTok": provider}
    ).update_many([record.id])
    updated = repository.get(record.id)

    assert provider.calls == 1
    assert result.tiktok_success_count == 1
    assert result.success_count == 1
    assert updated.follower_count == 12500
    assert updated.follower_raw_display_value == "12.5K"
    assert updated.follower_count_is_estimated is True
    assert updated.follower_count_updated_at == "2026-07-17T00:00:00+00:00"
    assert updated.follower_source is FollowerSource.TIKTOK_BROWSER
    assert updated.follower_sync_status is FollowerSyncStatus.SUCCESS


def test_multi_contract_tiktok_creator_is_queried_only_once(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="multi-tiktok",
        koc_name="多合同TikTok",
        contract_types=["TT", "MAY_TT", "YTB"],
        homepage_url="https://www.tiktok.com/@multi_tiktok",
    )
    provider = TikTokBrowserSuccessProvider()
    creator_ids = [
        item.id for item in repository.list(search="多合同TikTok")
    ]

    FollowerService(
        repository, {"TikTok": provider}
    ).update_many(creator_ids)

    assert creator_ids == [record.id]
    assert provider.calls == 1


def test_captcha_stops_remaining_tiktok_batch_without_overwriting(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    first = repository.create(
        user_id="captcha-first",
        koc_name="验证码一",
        homepage_url="https://www.tiktok.com/@first",
        follower_count=100,
    )
    second = repository.create(
        user_id="captcha-second",
        koc_name="验证码二",
        homepage_url="https://www.tiktok.com/@second",
        follower_count=200,
    )
    first_time = first.follower_count_updated_at
    second_time = second.follower_count_updated_at
    provider = CaptchaProvider()

    result = FollowerService(
        repository, {"TikTok": provider}
    ).update_many([first.id, second.id])

    first_after = repository.get(first.id)
    second_after = repository.get(second.id)
    assert provider.calls == 1
    assert result.tiktok_failed_count == 1
    assert result.skipped_count == 1
    assert result.details["error_code"].tolist() == [
        "CAPTCHA_REQUIRED",
        "TIKTOK_BATCH_STOPPED",
    ]
    assert first_after.follower_count == 100
    assert first_after.follower_count_updated_at == first_time
    assert first_after.follower_sync_status is FollowerSyncStatus.FAILED
    assert second_after.follower_count == 200
    assert second_after.follower_count_updated_at == second_time
    assert second_after.follower_sync_status is FollowerSyncStatus.MANUAL


def test_nonblocking_tiktok_failure_does_not_stop_next_creator(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    first = repository.create(
        user_id="structure-first",
        koc_name="结构失败",
        homepage_url="https://www.tiktok.com/@first",
        follower_count=100,
    )
    second = repository.create(
        user_id="structure-second",
        koc_name="继续成功",
        homepage_url="https://www.tiktok.com/@second",
        follower_count=200,
    )
    provider = FirstStructureFailureThenSuccess()

    result = FollowerService(
        repository, {"TikTok": provider}
    ).update_many([first.id, second.id])

    assert provider.calls == 2
    assert result.tiktok_failed_count == 1
    assert result.tiktok_success_count == 1
    assert repository.get(first.id).follower_count == 100
    assert repository.get(second.id).follower_count == 2000


def test_update_all_tiktok_uses_tt_april_tt_and_may_tt_once_per_creator(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    first = repository.create(
        user_id="tt-first",
        koc_name="TT一",
        contract_types=["TT", "MAY_TT", "YTB"],
        homepage_url="https://www.tiktok.com/@tt_first",
    )
    second = repository.create(
        user_id="tt-second",
        koc_name="TT二",
        contract_types=["MAY_TT"],
        homepage_url="https://www.tiktok.com/@tt_second",
    )
    third = repository.create(
        user_id="tt-third",
        koc_name="四月TT",
        contract_types=["4月TT"],
        homepage_url="https://www.tiktok.com/@tt_third",
    )
    fourth = repository.create(
        user_id="tt-fourth",
        koc_name="五月TT",
        contract_types=["5月TT"],
        homepage_url="https://www.tiktok.com/@tt_fourth",
    )
    repository.create(
        user_id="not-selected",
        koc_name="不参与",
        contract_types=["YTB"],
        homepage_url="https://www.tiktok.com/@not_selected",
    )
    provider = TikTokBrowserSuccessProvider()

    result = FollowerService(repository, {"TikTok": provider}).update_all_tiktok()

    assert provider.calls == 4
    assert result.tiktok_success_count == 4
    assert repository.get(first.id).follower_count == 12500
    assert repository.get(second.id).follower_count == 12500
    assert repository.get(third.id).follower_count == 12500
    assert repository.get(fourth.id).follower_count == 12500


@pytest.mark.parametrize(
    "blocking_code", ["ACCESS_RESTRICTED", "SECURITY_VERIFICATION_REQUIRED"]
)
def test_access_or_security_blocker_stops_tiktok_batch_and_preserves_old_values(
    tmp_path, blocking_code
):
    class BlockingProvider:
        def __init__(self):
            self.calls = 0

        def fetch(self, homepage_url):
            self.calls += 1
            return FollowerFetchResult(
                False,
                None,
                "TikTok",
                "2026-07-21T00:00:00+00:00",
                blocking_code,
                "公开访问或安全验证阻断。",
                source=FollowerSource.TIKTOK_BROWSER,
            )

    repository = KOCRepository(tmp_path / "koc.db")
    first = repository.create(
        user_id="login-first",
        koc_name="登录一",
        contract_types=["TT"],
        homepage_url="https://www.tiktok.com/@login_first",
        follower_count=10,
    )
    second = repository.create(
        user_id="login-second",
        koc_name="登录二",
        contract_types=["MAY_TT"],
        homepage_url="https://www.tiktok.com/@login_second",
        follower_count=20,
    )
    old_first_time = first.follower_count_updated_at
    old_second_time = second.follower_count_updated_at
    provider = BlockingProvider()

    result = FollowerService(repository, {"TikTok": provider}).update_all_tiktok()

    assert provider.calls == 1
    assert result.stopped is True
    assert result.stop_error_code == blocking_code
    assert result.details["error_code"].tolist() == [
        blocking_code,
        "TIKTOK_BATCH_STOPPED",
    ]
    assert repository.get(first.id).follower_count == 10
    assert repository.get(first.id).follower_count_updated_at == old_first_time
    assert repository.get(second.id).follower_count == 20
    assert repository.get(second.id).follower_count_updated_at == old_second_time
