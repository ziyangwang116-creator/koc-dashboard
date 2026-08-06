import sqlite3

import pandas as pd

from core.koc_import import analyze_import_dataframe
from core.koc_mapper import KOCMapper
from core.transformer import transform_data
from database.db import init_db
from database.koc_repository import KOCRepository
from followers.base import FollowerFetchResult
from models.enums import CreatorCategory
from services.follower_service import FollowerService


def test_duplicate_uid_import_preserves_every_contract_row(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    dataframe = pd.DataFrame(
        {
            "UID": ["multi-001", "multi-001"],
            "NAME": ["达人A", "达人A"],
            "类型": ["长包", "TT"],
        }
    )

    preview = analyze_import_dataframe(dataframe)
    result = repository.import_dataframe(dataframe)
    record = repository.get_by_user_id("multi-001")

    assert preview.total_records == 2
    assert preview.duplicate_uid_count == 1
    assert preview.duplicate_uid_rows == 2
    assert preview.duplicate_uid_details.iloc[0]["contract_types"] == "长包、TT"
    assert result.failed_count == 0
    assert result.contract_count == 2
    assert record is not None
    assert record.contract_types == ("长包", "TT")


def test_identical_uid_and_contract_rows_are_deduplicated(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    dataframe = pd.DataFrame(
        {
            "UID": [123456, 123456],
            "达人名称": ["同一达人", "同一达人"],
            "类型": ["TT", "TT"],
        }
    )

    repository.import_dataframe(dataframe)
    record = repository.get_by_user_id("123456")

    assert record is not None
    assert record.contract_types == ("TT",)


def test_creator_backup_expands_all_contract_relationships(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    repository.create(
        user_id="backup-multi",
        koc_name="备份达人",
        contract_types=["长包", "TT"],
    )

    exported = repository.to_dataframe(include_inactive=True)
    creator_rows = exported.loc[exported["user_id"] == "backup-multi"]

    assert creator_rows["contract_type"].tolist() == ["长包", "TT"]


def test_contract_type_filter_uses_or_logic_and_combines_with_category(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    mixed = repository.create(
        user_id="mixed",
        koc_name="混合达人",
        contract_types=["长包", "TT"],
    )
    ytb = repository.create(
        user_id="ytb-only",
        koc_name="YTB达人",
        contract_types=["YTB"],
    )
    repository.create(
        user_id="commentary",
        koc_name="解说达人",
        contract_types=["解说"],
    )

    or_rows = repository.list(contract_types=["TT", "YTB"])
    long_term_tt_rows = repository.list(
        creator_category=CreatorCategory.LONG_TERM,
        contract_types=["TT"],
    )
    long_term_ytb_rows = repository.list(
        creator_category=CreatorCategory.LONG_TERM,
        contract_types=["YTB"],
    )

    assert {row.id for row in or_rows} == {mixed.id, ytb.id}
    assert [row.id for row in long_term_tt_rows] == [mixed.id]
    assert long_term_ytb_rows == []


class _CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, homepage_url: str) -> FollowerFetchResult:
        self.calls += 1
        return FollowerFetchResult(
            True,
            1234,
            "YouTube",
            "2026-07-17T00:00:00+00:00",
        )


def test_multi_contract_creator_updates_followers_only_once(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    repository.create(
        user_id="follower-once",
        koc_name="只更新一次",
        contract_types=["长包", "TT"],
        homepage_url="https://www.youtube.com/@one",
    )
    provider = _CountingProvider()
    service = FollowerService(repository, {"YouTube": provider})
    creator_ids = [
        record.id
        for record in repository.list(search="只更新一次")
    ]

    service.update_many(creator_ids)

    assert len(creator_ids) == 1
    assert provider.calls == 1


def test_multi_contract_creator_does_not_duplicate_post_rows(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = KOCRepository(database_path)
    repository.create(
        user_id="post-once",
        koc_name="投稿只匹配一次",
        contract_types=["长包", "TT"],
    )
    raw = pd.DataFrame(
        {
            "view": [10],
            "subtype": ["short"],
            "title": ["投稿"],
            "userId": ["post-once"],
            "url": ["https://example.com/video"],
            "timestamp": [0],
        }
    )

    result = transform_data(
        raw,
        KOCMapper.from_database(database_path),
        "Asia/Shanghai",
    )

    assert len(result.data) == 1
    assert result.data.iloc[0]["koc_name"] == "投稿只匹配一次"


def _create_legacy_single_contract_database(path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE schema_migrations (
            migration_id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        "INSERT INTO schema_migrations (migration_id) VALUES (?)",
        ("v0.2_initialize_koc_master",),
    )
    connection.execute(
        """
        CREATE TABLE koc_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            koc_name TEXT NOT NULL,
            creator_category TEXT,
            contract_type TEXT,
            homepage_url TEXT,
            follower_count INTEGER,
            active INTEGER NOT NULL DEFAULT 1,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        INSERT INTO koc_master (
            user_id, koc_name, creator_category, contract_type,
            homepage_url, follower_count
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy-multi",
            "旧达人名称😀",
            "GRASSROOT",
            "TT",
            "https://www.tiktok.com/@legacy",
            98765,
        ),
    )
    connection.commit()
    connection.close()


def test_legacy_database_migrates_without_losing_base_or_contract_data(tmp_path):
    database_path = tmp_path / "legacy.db"
    _create_legacy_single_contract_database(database_path)

    init_db(database_path)
    init_db(database_path)
    repository = KOCRepository(database_path)
    record = repository.get_by_user_id("legacy-multi")
    connection = sqlite3.connect(database_path)
    master_columns = [
        row[1] for row in connection.execute("PRAGMA table_info(koc_master)")
    ]
    unique_uid_indexes = [
        row for row in connection.execute("PRAGMA index_list(koc_master)")
        if bool(row[2])
    ]
    contract_rows = connection.execute(
        "SELECT contract_type FROM creator_contract ORDER BY id"
    ).fetchall()
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    connection.close()

    assert record is not None
    assert record.koc_name == "旧达人名称😀"
    assert record.homepage_url == "https://www.tiktok.com/@legacy"
    assert record.follower_count == 98765
    assert record.contract_types == ("TT",)
    assert "contract_type" not in master_columns
    assert unique_uid_indexes == []
    assert contract_rows == [("TT",)]
    assert integrity == "ok"
