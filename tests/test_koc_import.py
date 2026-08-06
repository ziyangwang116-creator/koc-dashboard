import pandas as pd

from database.koc_repository import KOCRepository
from models.enums import ContractType, CreatorCategory, FollowerSyncStatus
from models.koc import KOC_EXPORT_COLUMNS


def test_name_uid_headers_import_and_numeric_uid_normalization(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    result = repository.import_dataframe(
        pd.DataFrame({"NAME": [" 日本語😀 "], "UID": [123456.0]})
    )

    record = repository.get_by_user_id("123456")
    assert result.added_count == 1
    assert record.koc_name == "日本語😀"
    assert record.user_id == "123456"


def test_standard_headers_and_optional_fields_import(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    result = repository.import_dataframe(
        pd.DataFrame(
            {
                "user_id": ["import-2"],
                "koc_name": ["中文达人"],
                "creator_category": ["GRASSROOT"],
                "contract_type": ["YTB_SHORTS"],
                "homepage_url": ["https://www.youtube.com/@creator"],
                "follower_count": [321],
                "active": [True],
                "note": ["备注"],
            }
        )
    )

    record = repository.get_by_user_id("import-2")
    assert result.added_count == 1
    assert record.creator_category is CreatorCategory.GRASSROOT
    assert record.contract_type is ContractType.YTB_SHORTS
    assert record.follower_count == 321
    assert record.follower_sync_status is FollowerSyncStatus.MANUAL


def test_blank_import_values_do_not_overwrite_existing_values(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    repository.create(
        user_id="import-3",
        koc_name="原名称",
        creator_category=CreatorCategory.GRASSROOT,
        contract_type=ContractType.TT,
        homepage_url="https://www.tiktok.com/@creator",
        follower_count=999,
        note="原备注",
    )

    result = repository.import_dataframe(
        pd.DataFrame(
            {
                "user_id": ["import-3"],
                "koc_name": ["更新名称"],
                "creator_category": [None],
                "contract_type": [""],
                "homepage_url": [pd.NA],
                "follower_count": [None],
                "active": [None],
                "note": [""],
            }
        ),
        strategy="update_existing",
    )

    record = repository.get_by_user_id("import-3")
    assert result.updated_count == 1
    assert record.koc_name == "更新名称"
    assert record.contract_type is ContractType.TT
    assert record.homepage_url == "https://www.tiktok.com/@creator"
    assert record.follower_count == 999
    assert record.note == "原备注"


def test_import_template_and_export_columns_use_only_new_model():
    assert KOC_EXPORT_COLUMNS == [
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


def test_chinese_homepage_and_follower_headers_update_existing_creator(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    existing = repository.create(
        user_id="930001",
        koc_name="中文表头测试",
        creator_category=CreatorCategory.LONG_TERM,
    )
    dataframe = pd.DataFrame(
        {
            "NAME": ["中文表头测试"],
            "UID": [930001.0],
            "主页链接": [" https://www.youtube.com/@creator "],
            "粉丝数": ["12,345"],
        }
    )

    result = repository.import_dataframe(dataframe, strategy="update_existing")
    updated = repository.get(existing.id)

    assert result.updated_count == 1
    assert result.failed_count == 0
    assert updated is not None
    assert updated.homepage_url == "https://www.youtube.com/@creator"
    assert updated.follower_count == 12345
    assert updated.follower_sync_status is FollowerSyncStatus.MANUAL
    assert updated.creator_category is CreatorCategory.LONG_TERM
