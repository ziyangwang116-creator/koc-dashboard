import sqlite3

from database.db import init_db
from database.migrations import (
    CONTRACT_PERIODS_MIGRATION_ID,
    CROSS_INDUSTRY_EXCLUSIONS_MIGRATION_ID,
    DASHBOARD_STORAGE_MIGRATION_ID,
    GRASSROOT_COMPENSATION_SETTINGS_MIGRATION_ID,
    LONG_TERM_COMPENSATION_MIGRATION_ID,
    TIKTOK_API_MIGRATION_ID,
    TIKTOK_BROWSER_MIGRATION_ID,
)


def _create_v02_database(path):
    legacy_platform_column = "source" + "_platform"
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
        f"""
        CREATE TABLE koc_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            koc_name TEXT NOT NULL,
            {legacy_platform_column} TEXT NOT NULL DEFAULT 'YouTube',
            active INTEGER NOT NULL DEFAULT 1,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        "INSERT INTO koc_master (user_id, koc_name, note) VALUES (?, ?, ?)",
        ("old-uid", "用户手动修改名称😀", "保留备注"),
    )
    connection.commit()
    connection.close()
    return legacy_platform_column


def test_old_database_upgrades_without_losing_creators(tmp_path):
    database_path = tmp_path / "legacy.db"
    removed_column = _create_v02_database(database_path)

    init_db(database_path)
    connection = sqlite3.connect(database_path)
    columns = [row[1] for row in connection.execute("PRAGMA table_info(koc_master)")]
    rows = connection.execute(
        "SELECT user_id, koc_name, note FROM koc_master"
    ).fetchall()
    contract_period = connection.execute(
        "SELECT contract_start_date, contract_end_date FROM koc_master"
    ).fetchone()
    period_migration = connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE migration_id = ?",
        (CONTRACT_PERIODS_MIGRATION_ID,),
    ).fetchone()[0]
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    connection.close()

    assert removed_column not in columns
    assert rows == [("old-uid", "用户手动修改名称😀", "保留备注")]
    assert "follower_source" in columns
    assert "settlement_eligible" in columns
    assert "contract_start_date" in columns
    assert "contract_end_date" in columns
    assert contract_period == ("2026-05-01", "2026-10-31")
    assert period_migration == 1
    assert integrity == "ok"


def test_repeated_schema_migration_is_idempotent(tmp_path):
    database_path = tmp_path / "legacy.db"
    _create_v02_database(database_path)

    init_db(database_path)
    init_db(database_path)
    connection = sqlite3.connect(database_path)
    count = connection.execute("SELECT COUNT(id) FROM koc_master").fetchone()[0]
    migration_count = connection.execute(
        "SELECT COUNT(migration_id) FROM schema_migrations WHERE migration_id = ?",
        ("v0.3_expand_koc_master",),
    ).fetchone()[0]
    name = connection.execute(
        "SELECT koc_name FROM koc_master WHERE user_id = ?", ("old-uid",)
    ).fetchone()[0]
    audit_table_count = connection.execute(
        "SELECT COUNT(1) FROM sqlite_master WHERE type = ? AND name = ?",
        ("table", "follower_update_audit"),
    ).fetchone()[0]
    connection.close()

    assert count == 1
    assert migration_count == 1
    assert name == "用户手动修改名称😀"
    assert audit_table_count == 1


def _create_pre_browser_database(path):
    legacy_source = "TIK" + "VIB_PAGE"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE schema_migrations (
            migration_id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE koc_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            koc_name TEXT NOT NULL,
            creator_category TEXT,
            homepage_url TEXT,
            follower_count INTEGER,
            follower_raw_display_value TEXT,
            follower_source TEXT,
            follower_source_url TEXT,
            follower_profile_url TEXT,
            follower_count_is_estimated INTEGER,
            follower_count_updated_at TEXT,
            follower_sync_status TEXT NOT NULL DEFAULT 'NEVER',
            follower_error_code TEXT,
            follower_sync_error TEXT,
            settlement_eligible INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE creator_contract (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            contract_type TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE follower_update_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            koc_name TEXT NOT NULL,
            old_follower_count INTEGER,
            new_follower_count INTEGER,
            raw_display_value TEXT,
            source TEXT,
            source_url TEXT,
            fetched_at TEXT NOT NULL,
            is_estimated INTEGER NOT NULL DEFAULT 0,
            settlement_eligible INTEGER NOT NULL DEFAULT 0,
            sync_status TEXT NOT NULL,
            error_code TEXT,
            operator_mode TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    for migration_id in (
        "v0.2_initialize_koc_master",
        "v0.3_expand_koc_master",
        "v0.4_follower_sources_and_audit",
        "v0.5_normalize_creator_contracts",
        "v0.5_import_input_creator_contracts",
    ):
        connection.execute(
            "INSERT INTO schema_migrations (migration_id) VALUES (?)",
            (migration_id,),
        )
    connection.execute(
        """
        INSERT INTO koc_master (
            user_id, koc_name, homepage_url, follower_count,
            follower_raw_display_value, follower_source,
            follower_count_updated_at, follower_sync_status, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy-browser",
            "旧达人😀",
            "https://www.tiktok.com/@legacy_browser",
            4321,
            "4.3K",
            legacy_source,
            "2026-07-20T01:02:03+00:00",
            "SUCCESS",
            "保留",
        ),
    )
    creator_id = connection.execute(
        "SELECT id FROM koc_master WHERE user_id = ?", ("legacy-browser",)
    ).fetchone()[0]
    connection.executemany(
        "INSERT INTO creator_contract (creator_id, contract_type) VALUES (?, ?)",
        [(creator_id, "TT"), (creator_id, "MAY_TT")],
    )
    connection.execute(
        """
        INSERT INTO follower_update_audit (
            user_id, koc_name, old_follower_count, new_follower_count,
            raw_display_value, source, source_url, fetched_at,
            is_estimated, settlement_eligible, sync_status, operator_mode
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy-browser",
            "旧达人😀",
            4000,
            4321,
            "4.3K",
            legacy_source,
            "https://example.invalid/legacy",
            "2026-07-20T01:02:03+00:00",
            1,
            0,
            "SUCCESS",
            "AUTOMATIC",
        ),
    )
    connection.commit()
    connection.close()


def test_browser_source_migration_backs_up_and_preserves_creator_data(tmp_path):
    database_path = tmp_path / "legacy.db"
    _create_pre_browser_database(database_path)

    init_db(database_path)
    init_db(database_path)

    connection = sqlite3.connect(database_path)
    creator = connection.execute(
        """
        SELECT user_id, koc_name, homepage_url, follower_count,
               follower_count_updated_at, follower_source, note
        FROM koc_master WHERE user_id = ?
        """,
        ("legacy-browser",),
    ).fetchone()
    contracts = connection.execute(
        "SELECT contract_type FROM creator_contract ORDER BY id"
    ).fetchall()
    audit_source = connection.execute(
        "SELECT source FROM follower_update_audit ORDER BY id LIMIT 1"
    ).fetchone()[0]
    migration_count = connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE migration_id = ?",
        (TIKTOK_BROWSER_MIGRATION_ID,),
    ).fetchone()[0]
    master_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'koc_master'"
    ).fetchone()[0]
    connection.close()

    assert creator == (
        "legacy-browser",
        "旧达人😀",
        "https://www.tiktok.com/@legacy_browser",
        4321,
        "2026-07-20T01:02:03+00:00",
        "MANUAL",
        "保留",
    )
    assert contracts == [("TT",), ("MAY_TT",)]
    assert audit_source == "MANUAL"
    assert migration_count == 1
    assert "TIKTOK_BROWSER" in master_sql
    assert len(list((tmp_path / "backup").glob("*.db"))) == 1


def test_dashboard_storage_migration_creates_post_table(tmp_path):
    database_path = tmp_path / "dashboard.db"

    init_db(database_path)
    init_db(database_path)

    connection = sqlite3.connect(database_path)
    columns = [
        row[1] for row in connection.execute("PRAGMA table_info(dashboard_post)")
    ]
    migration_count = connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE migration_id = ?",
        (DASHBOARD_STORAGE_MIGRATION_ID,),
    ).fetchone()[0]
    connection.close()

    assert columns == [
        "record_key",
        "source_file",
        "publish_date",
        "payload_json",
        "created_at",
        "updated_at",
        "import_batch_id",
    ]
    assert migration_count == 1


def test_cross_industry_migration_creates_reversible_exclusion_table(tmp_path):
    database_path = tmp_path / "cross-industry.db"

    init_db(database_path)
    connection = sqlite3.connect(database_path)
    columns = [
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(dashboard_cross_industry_exclusion)"
        )
    ]
    migration_count = connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE migration_id = ?",
        (CROSS_INDUSTRY_EXCLUSIONS_MIGRATION_ID,),
    ).fetchone()[0]
    connection.close()

    assert columns == [
        "id",
        "platform",
        "url_key",
        "original_url",
        "normalized_url",
        "reason",
        "active",
        "created_at",
        "updated_at",
    ]
    assert migration_count == 1


def test_tiktok_api_source_migration_allows_new_audit_source(tmp_path):
    database_path = tmp_path / "tiktok-api.db"

    init_db(database_path)
    connection = sqlite3.connect(database_path)
    master_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'koc_master'"
    ).fetchone()[0]
    audit_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' "
        "AND name = 'follower_update_audit'"
    ).fetchone()[0]
    migration_count = connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE migration_id = ?",
        (TIKTOK_API_MIGRATION_ID,),
    ).fetchone()[0]
    connection.close()

    assert "TIKTOK_API" in master_sql
    assert "TIKTOK_API" in audit_sql
    assert migration_count == 1


def test_grassroot_compensation_settings_migration_creates_rate_table(tmp_path):
    database_path = tmp_path / "compensation.db"

    init_db(database_path)
    connection = sqlite3.connect(database_path)
    table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("grassroot_compensation_setting",),
    ).fetchone()
    migration_count = connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE migration_id = ?",
        (GRASSROOT_COMPENSATION_SETTINGS_MIGRATION_ID,),
    ).fetchone()[0]
    connection.close()

    assert table == ("grassroot_compensation_setting",)
    assert migration_count == 1


def test_long_term_compensation_migration_creates_activity_and_version_tables(tmp_path):
    database_path = tmp_path / "long-term-compensation.db"

    init_db(database_path)
    connection = sqlite3.connect(database_path)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    migration_count = connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE migration_id = ?",
        (LONG_TERM_COMPENSATION_MIGRATION_ID,),
    ).fetchone()[0]
    connection.close()

    assert "long_term_compensation_activity" in tables
    assert "long_term_compensation_version" in tables
    assert migration_count == 1
