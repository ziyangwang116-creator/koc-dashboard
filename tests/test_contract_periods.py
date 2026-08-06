from datetime import date

import pandas as pd
import pytest

from core.dashboard_processor import enrich_dashboard_creator_metadata
from core.grassroot_compensation import calculate_grassroot_compensation
from database.koc_repository import KOCRepository, KOCRepositoryError
from models.enums import CreatorCategory


def test_creator_categories_receive_their_default_contract_periods(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    long_term = repository.create(
        user_id="long-term",
        koc_name="long term",
        creator_category=CreatorCategory.LONG_TERM,
        effective_date=date(2026, 7, 1),
    )
    commentary = repository.create(
        user_id="commentary",
        koc_name="commentary",
        creator_category=CreatorCategory.COMMENTARY,
        effective_date=date(2026, 7, 1),
    )
    grassroot = repository.create(
        user_id="grassroot",
        koc_name="grassroot",
        creator_category=CreatorCategory.GRASSROOT,
        effective_date=date(2026, 7, 1),
    )

    assert (long_term.contract_start_date, long_term.contract_end_date) == (
        date(2026, 5, 1),
        date(2026, 12, 31),
    )
    assert (commentary.contract_start_date, commentary.contract_end_date) == (
        date(2026, 5, 1),
        date(2026, 8, 31),
    )
    assert (grassroot.contract_start_date, grassroot.contract_end_date) == (
        date(2026, 5, 1),
        date(2026, 10, 31),
    )


def test_contract_change_creates_a_new_period_from_its_effective_date(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="creator-1",
        koc_name="creator",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["TT"],
        follower_count=1_000,
        effective_date=date(2026, 6, 1),
    )

    updated = repository.update(
        record.id,
        user_id=record.user_id,
        koc_name=record.koc_name,
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["YTB"],
        homepage_url=record.homepage_url,
        follower_count=record.follower_count,
        active=record.active,
        note=record.note,
        effective_date=date(2026, 7, 1),
    )

    assert (updated.contract_start_date, updated.contract_end_date) == (
        date(2026, 7, 1),
        date(2026, 10, 31),
    )
    history = [
        snapshot
        for snapshot in repository.list_profile_history()
        if snapshot.creator_id == record.id
    ]
    assert [
        (snapshot.effective_date, snapshot.contract_start_date, snapshot.contract_end_date)
        for snapshot in history
    ] == [
        (date(2026, 5, 1), date(2026, 5, 1), date(2026, 6, 30)),
        (date(2026, 7, 1), date(2026, 7, 1), date(2026, 10, 31)),
    ]

    enriched = enrich_dashboard_creator_metadata(
        pd.DataFrame(
            [
                {
                    "user_id": record.user_id,
                    "publish_date": date(2026, 6, 30),
                },
                {
                    "user_id": record.user_id,
                    "publish_date": date(2026, 7, 1),
                },
            ]
        ),
        repository.list(include_inactive=True),
        repository.list_profile_history(),
    )
    assert enriched["contract_start_date"].tolist() == [
        "2026-05-01",
        "2026-07-01",
    ]


def test_backdated_contract_change_updates_later_profile_only_snapshots(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="backdated-contract",
        koc_name="backdated contract",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["TT"],
        effective_date=date(2026, 5, 1),
    )
    repository.update(
        record.id,
        user_id=record.user_id,
        koc_name=record.koc_name,
        creator_category=record.creator_category,
        contract_types=record.contract_types,
        homepage_url=record.homepage_url,
        follower_count=record.follower_count,
        active=record.active,
        note=record.note,
        effective_date=date(2026, 6, 15),
    )

    repository.update(
        record.id,
        user_id=record.user_id,
        koc_name=record.koc_name,
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["YTB"],
        homepage_url=record.homepage_url,
        follower_count=record.follower_count,
        active=record.active,
        note=record.note,
        effective_date=date(2026, 6, 1),
    )

    assert [
        (snapshot.effective_date, snapshot.contract_types, snapshot.contract_start_date)
        for snapshot in repository.list_profile_history_for_creator(record.id)
    ] == [
        (date(2026, 5, 1), ("TT",), date(2026, 5, 1)),
        (date(2026, 6, 1), ("YTB",), date(2026, 6, 1)),
        (date(2026, 6, 15), ("YTB",), date(2026, 6, 1)),
    ]


def test_contract_deadline_can_be_changed_without_changing_its_start(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="deadline-creator",
        koc_name="deadline creator",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["TT"],
        effective_date=date(2026, 5, 1),
    )

    updated = repository.update(
        record.id,
        user_id=record.user_id,
        koc_name=record.koc_name,
        creator_category=record.creator_category,
        contract_types=record.contract_types,
        homepage_url=record.homepage_url,
        follower_count=record.follower_count,
        active=record.active,
        note=record.note,
        effective_date=date(2026, 7, 1),
        contract_end_date=date(2026, 9, 15),
    )

    assert (updated.contract_start_date, updated.contract_end_date) == (
        date(2026, 5, 1),
        date(2026, 9, 15),
    )


def test_deleting_latest_contract_period_removes_all_group_snapshots_and_reverts_master(
    tmp_path,
):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="delete-latest",
        koc_name="delete latest",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["TT"],
        effective_date=date(2026, 5, 1),
    )
    repository.update(
        record.id,
        user_id=record.user_id,
        koc_name=record.koc_name,
        creator_category=record.creator_category,
        contract_types=record.contract_types,
        homepage_url=record.homepage_url,
        follower_count=1_000,
        active=record.active,
        note=record.note,
        effective_date=date(2026, 6, 15),
    )
    current = repository.get(record.id)
    assert current is not None
    repository.update(
        record.id,
        user_id=current.user_id,
        koc_name=current.koc_name,
        creator_category=current.creator_category,
        contract_types=["YTB shorts"],
        homepage_url=current.homepage_url,
        follower_count=current.follower_count,
        active=current.active,
        note=current.note,
        effective_date=date(2026, 7, 1),
    )
    current = repository.get(record.id)
    assert current is not None
    repository.update(
        record.id,
        user_id=current.user_id,
        koc_name=current.koc_name,
        creator_category=current.creator_category,
        contract_types=current.contract_types,
        homepage_url=current.homepage_url,
        follower_count=2_000,
        active=current.active,
        note=current.note,
        effective_date=date(2026, 7, 15),
    )

    deleted = repository.delete_contract_period(
        record.id,
        source_effective_date=date(2026, 7, 1),
    )

    assert deleted.contract_types == ("TT",)
    assert (deleted.contract_start_date, deleted.contract_end_date) == (
        date(2026, 5, 1),
        date(2026, 10, 31),
    )
    history = repository.list_profile_history_for_creator(record.id)
    assert [snapshot.effective_date for snapshot in history] == [
        date(2026, 5, 1),
        date(2026, 6, 15),
        date(2026, 7, 15),
    ]
    assert all(snapshot.contract_types == ("TT",) for snapshot in history)
    assert all(snapshot.contract_end_date == date(2026, 10, 31) for snapshot in history)


def test_deleting_middle_contract_period_bridges_adjacent_periods(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="delete-middle",
        koc_name="delete middle",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["TT"],
        effective_date=date(2026, 5, 1),
    )
    current = repository.update(
        record.id,
        user_id=record.user_id,
        koc_name=record.koc_name,
        creator_category=record.creator_category,
        contract_types=["YTB shorts"],
        homepage_url=record.homepage_url,
        follower_count=record.follower_count,
        active=record.active,
        note=record.note,
        effective_date=date(2026, 7, 1),
    )
    repository.update(
        record.id,
        user_id=current.user_id,
        koc_name=current.koc_name,
        creator_category=current.creator_category,
        contract_types=["TT"],
        homepage_url=current.homepage_url,
        follower_count=current.follower_count,
        active=current.active,
        note=current.note,
        effective_date=date(2026, 8, 1),
    )

    unchanged_current = repository.delete_contract_period(
        record.id,
        source_effective_date=date(2026, 7, 1),
    )

    assert unchanged_current.contract_types == ("TT",)
    assert unchanged_current.contract_start_date == date(2026, 8, 1)
    history = repository.list_profile_history_for_creator(record.id)
    assert [
        (
            snapshot.effective_date,
            snapshot.contract_types,
            snapshot.contract_start_date,
            snapshot.contract_end_date,
        )
        for snapshot in history
    ] == [
        (date(2026, 5, 1), ("TT",), date(2026, 5, 1), date(2026, 7, 31)),
        (date(2026, 8, 1), ("TT",), date(2026, 8, 1), date(2026, 10, 31)),
    ]


def test_only_contract_period_cannot_be_deleted(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="only-period",
        koc_name="only period",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["TT"],
        effective_date=date(2026, 5, 1),
    )

    with pytest.raises(KOCRepositoryError, match="至少需要保留一段合同周期"):
        repository.delete_contract_period(
            record.id,
            source_effective_date=date(2026, 5, 1),
        )


def test_history_repair_restores_the_old_contract_before_a_later_change(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="history-repair",
        koc_name="history repair",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["YTB shorts"],
        follower_count=5_000,
        effective_date=date(2026, 7, 1),
        contract_start_date=date(2026, 7, 1),
    )

    repository.save_contract_history_version(
        record.id,
        effective_date=date(2026, 5, 1),
        contract_types=["YTB"],
        contract_start_date=date(2026, 5, 1),
        contract_end_date=date(2026, 10, 31),
    )
    history = repository.list_profile_history_for_creator(record.id)
    assert [
        (snapshot.effective_date, snapshot.contract_types, snapshot.contract_end_date)
        for snapshot in history
    ] == [
        (date(2026, 5, 1), ("YTB",), date(2026, 6, 30)),
        (date(2026, 7, 1), ("YTB shorts",), date(2026, 10, 31)),
    ]

    posts = pd.DataFrame(
        [
            {
                "user_id": record.user_id,
                "publish_date": date(2026, 6, 15),
                "subtype": "long",
                "views": 1_200_000,
            },
            {
                "user_id": record.user_id,
                "publish_date": date(2026, 7, 15),
                "subtype": "YTB shorts",
                "views": 1_000_000,
            },
        ]
    )
    enriched = enrich_dashboard_creator_metadata(
        posts,
        repository.list(include_inactive=True),
        repository.list_profile_history(),
    )
    result = calculate_grassroot_compensation(
        enriched,
        repository.list(include_inactive=True),
        jpy_to_usd_rate=0.0062,
    )

    assert len(result.details) == 1
    detail = result.details.iloc[0]
    assert detail["合同类型"] == "YTB、YTB shorts"
    assert detail["计费 subtype"] == "long + livestream、shorts"
    assert detail["计费播放量"] == 2_200_000


def test_missing_history_never_falls_back_to_the_current_contract(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="history-missing",
        koc_name="history missing",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["YTB shorts"],
        follower_count=5_000,
        effective_date=date(2026, 7, 1),
        contract_start_date=date(2026, 7, 1),
    )
    posts = pd.DataFrame(
        [
            {
                "user_id": record.user_id,
                "publish_date": date(2026, 6, 15),
                "subtype": "YTB shorts",
                "views": 1_000_000,
            }
        ]
    )
    enriched = enrich_dashboard_creator_metadata(
        posts,
        repository.list(include_inactive=True),
        repository.list_profile_history(),
    )
    result = calculate_grassroot_compensation(
        enriched,
        repository.list(include_inactive=True),
        jpy_to_usd_rate=0.0062,
    )

    assert enriched["profile_status"].tolist() == ["HISTORY_MISSING"]
    detail = result.details.iloc[0]
    assert detail["结算状态"] == "历史资料缺失"
    assert detail["计费播放量"] == 0
    assert detail["总金额（日元）"] == 0


def test_contract_expired_posts_do_not_enter_grassroot_settlement(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="expired-creator",
        koc_name="expired creator",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["TT"],
        follower_count=1_000,
        effective_date=date(2026, 5, 1),
    )
    posts = pd.DataFrame(
        [
            {
                "user_id": record.user_id,
                "publish_date": date(2026, 11, 1),
                "subtype": "tiktok",
                "views": 500_000,
            }
        ]
    )
    enriched = enrich_dashboard_creator_metadata(
        posts,
        repository.list(include_inactive=True),
        repository.list_profile_history(),
    )

    result = calculate_grassroot_compensation(
        enriched,
        repository.list(include_inactive=True),
        jpy_to_usd_rate=0.0062,
    )
    detail = result.details.iloc[0]
    assert detail["结算状态"] == "合同期限外"
    assert detail["计费播放量"] == 0
    assert detail["全部视频类型播放量"] == 0
    assert detail["总金额（日元）"] == 0


def test_contract_correction_edits_the_existing_period_without_creating_change(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="correction-creator",
        koc_name="correction creator",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["YTB shorts"],
        effective_date=date(2026, 7, 1),
        contract_start_date=date(2026, 7, 1),
    )

    corrected = repository.correct_contract_period(
        record.id,
        source_effective_date=date(2026, 7, 1),
        contract_types=["YTB"],
        contract_start_date=date(2026, 7, 1),
        contract_end_date=date(2026, 10, 31),
        reason="initial entry was wrong",
    )

    assert corrected.contract_types == ("YTB",)
    periods = repository.list_contract_periods(record.id)
    assert len(periods) == 1
    assert periods[0].contract_types == ("YTB",)
    revision = repository.list_contract_revisions(record.id)[0]
    assert revision.operation_type == "CORRECTION"
    assert revision.reason == "initial entry was wrong"


def test_latest_contract_revision_can_be_reverted(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="revert-creator",
        koc_name="revert creator",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["TT"],
        effective_date=date(2026, 5, 1),
    )
    repository.create_contract_change(
        record.id,
        effective_date=date(2026, 7, 1),
        contract_types=["YTB shorts"],
        reason="real change",
    )
    change = repository.list_contract_revisions(record.id)[0]

    restored = repository.revert_contract_revision(change.id)

    assert restored.contract_types == ("TT",)
    assert len(repository.list_contract_periods(record.id)) == 1
    revisions = repository.list_contract_revisions(record.id)
    assert revisions[0].operation_type == "REVERT"
    assert revisions[1].reverted_at is not None
