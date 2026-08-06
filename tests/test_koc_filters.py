from database.koc_repository import KOCRepository
from followers.base import FollowerFetchResult
from models.enums import (
    ContractType,
    CreatorCategory,
    FollowerSource,
    FollowerSyncStatus,
)


def _build_filter_records(repository: KOCRepository) -> None:
    repository.create(
        user_id="filter-ytb",
        koc_name="筛选测试-YTB",
        creator_category=CreatorCategory.GRASSROOT,
        contract_type=ContractType.YTB,
    )
    repository.create(
        user_id="filter-april",
        koc_name="筛选测试-4月YTB",
        creator_category=CreatorCategory.GRASSROOT,
        contract_type=ContractType.APRIL_YTB,
        follower_count=100,
    )
    may = repository.create(
        user_id="filter-may",
        koc_name="筛选测试-5月YTB",
        creator_category=CreatorCategory.GRASSROOT,
        contract_type=ContractType.MAY_YTB,
    )
    repository.set_active(may.id, False)
    repository.create(
        user_id="filter-unset",
        koc_name="筛选测试-未设置合同",
        creator_category=CreatorCategory.LONG_TERM,
    )
    failed = repository.create(
        user_id="filter-tt",
        koc_name="筛选测试-TT",
        creator_category=CreatorCategory.GRASSROOT,
        contract_type=ContractType.TT,
    )
    repository.mark_follower_failure(failed.id, "测试失败")


def test_empty_contract_type_list_does_not_limit_results(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    _build_filter_records(repository)

    records = repository.list(search="筛选测试", contract_types=[])

    assert {record.user_id for record in records} == {
        "filter-ytb",
        "filter-april",
        "filter-may",
        "filter-unset",
        "filter-tt",
    }


def test_multiple_contract_types_use_or_logic(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    _build_filter_records(repository)

    records = repository.list(
        search="筛选测试",
        contract_types=[
            ContractType.YTB,
            ContractType.APRIL_YTB,
            ContractType.MAY_YTB,
        ],
    )

    assert {record.user_id for record in records} == {
        "filter-ytb",
        "filter-april",
        "filter-may",
    }


def test_unset_contract_type_matches_null_or_blank(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    _build_filter_records(repository)

    records = repository.list(search="筛选测试", contract_types=[None])
    records_from_blank_option = repository.list(
        search="筛选测试", contract_types=[""]
    )

    assert [record.user_id for record in records] == ["filter-unset"]
    assert [record.user_id for record in records_from_blank_option] == [
        "filter-unset"
    ]


def test_filter_dimensions_use_and_logic(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    _build_filter_records(repository)

    records = repository.list(
        search="筛选测试",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=[
            ContractType.YTB,
            ContractType.APRIL_YTB,
            ContractType.MAY_YTB,
        ],
        follower_sync_statuses=[
            FollowerSyncStatus.NEVER,
            FollowerSyncStatus.MANUAL,
        ],
        active=True,
    )

    assert {record.user_id for record in records} == {
        "filter-ytb",
        "filter-april",
    }


def test_follower_sync_status_filter_is_parameterized(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    _build_filter_records(repository)

    records = repository.list(
        search="筛选测试",
        contract_types=[ContractType.TT],
        follower_sync_statuses=[FollowerSyncStatus.FAILED],
    )

    assert [record.user_id for record in records] == ["filter-tt"]


def test_follower_source_and_settlement_filters_use_and_logic(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    manual = repository.create(
        user_id="source-manual",
        koc_name="人工数据",
        follower_count=10,
    )
    official = repository.create(
        user_id="source-youtube",
        koc_name="官方数据",
        homepage_url="https://www.youtube.com/@official",
    )
    repository.apply_follower_success(
        official.id,
        FollowerFetchResult(
            success=True,
            follower_count=20,
            platform="YouTube",
            fetched_at="2026-07-17T00:00:00+00:00",
            raw_display_value="20",
            is_estimated=True,
            source=FollowerSource.YOUTUBE_API,
            settlement_eligible=True,
        ),
    )

    official_rows = repository.list(
        follower_sources=[FollowerSource.YOUTUBE_API],
        settlement_eligible=True,
    )
    manual_rows = repository.list(
        follower_sources=[FollowerSource.MANUAL],
        requires_manual_confirmation=True,
    )

    assert [row.id for row in official_rows] == [official.id]
    assert [row.id for row in manual_rows] == [manual.id]
