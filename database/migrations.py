from __future__ import annotations

import sqlite3
import json
from collections.abc import Iterable, Sequence
from datetime import date, timedelta


KOC_MASTER_COLUMNS = (
    "id",
    "user_id",
    "koc_name",
    "creator_category",
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
    "follower_profile_url",
    "follower_count_is_estimated",
    "follower_count_updated_at",
    "follower_sync_status",
    "follower_error_code",
    "follower_sync_error",
    "settlement_eligible",
    "active",
    "note",
    "created_at",
    "updated_at",
)
TIKTOK_BROWSER_MIGRATION_ID = "v0.6_tiktok_persistent_browser_source"
DASHBOARD_STORAGE_MIGRATION_ID = "v0.7_persist_dashboard_posts"
TIKTOK_API_MIGRATION_ID = "v0.8_tiktok_api_source"
GRASSROOT_COMPENSATION_SETTINGS_MIGRATION_ID = "v0.9_grassroot_compensation_settings"
GRASSROOT_COMPENSATION_CONTRACT_SNAPSHOTS_MIGRATION_ID = (
    "v0.10_grassroot_compensation_contract_snapshots"
)
CREATOR_PROFILE_HISTORY_MIGRATION_ID = "v0.11_creator_profile_history"
DASHBOARD_IMPORT_BATCHES_MIGRATION_ID = "v0.12_dashboard_import_batches"
GRASSROOT_COMPENSATION_VERSIONS_MIGRATION_ID = "v0.13_grassroot_compensation_versions"
CONTRACT_PERIODS_MIGRATION_ID = "v0.14_creator_contract_periods"
LONG_TERM_COMPENSATION_MIGRATION_ID = "v1.5_long_term_compensation"
COMMENTARY_COMPENSATION_MIGRATION_ID = "v1.6_commentary_compensation"
CROSS_INDUSTRY_EXCLUSIONS_MIGRATION_ID = "v1.7_cross_industry_exclusions"
TRAFFIC_BOOST_SETTINGS_MIGRATION_ID = "v1.8_traffic_boost_settings"
AUTHORITATIVE_CONTRACT_PERIODS_MIGRATION_ID = (
    "v1.9_authoritative_contract_periods"
)
CONTRACT_REVISION_AUDIT_MIGRATION_ID = "v2.0_contract_revision_audit"
AI_AGENT_STORAGE_MIGRATION_ID = "v2.1_ai_agent_storage"
DASHBOARD_IMPORT_SNAPSHOT_MIGRATION_ID = "v2.2_dashboard_import_batch_snapshot"
SETTLEMENT_LOCK_AUDIT_MIGRATION_ID = "v2.3_settlement_lock_audit"
FOLLOWER_AUDIT_COLUMNS = (
    "id",
    "user_id",
    "koc_name",
    "old_follower_count",
    "new_follower_count",
    "raw_display_value",
    "source",
    "source_url",
    "fetched_at",
    "is_estimated",
    "settlement_eligible",
    "sync_status",
    "error_code",
    "operator_mode",
    "created_at",
)


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _migration_applied(connection: sqlite3.Connection, migration_id: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM schema_migrations WHERE migration_id = ?",
            (migration_id,),
        ).fetchone()
        is not None
    )


def _record_migration(connection: sqlite3.Connection, migration_id: str) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO schema_migrations (migration_id) VALUES (?)",
        (migration_id,),
    )


def _create_koc_master(connection: sqlite3.Connection, table_name: str) -> None:
    if table_name not in {"koc_master", "koc_master_v06"}:
        raise ValueError("不允许的迁移表名。")
    connection.execute(
        f"""
        CREATE TABLE {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            koc_name TEXT NOT NULL,
            creator_category TEXT CHECK (
                creator_category IS NULL OR
                creator_category IN ('LONG_TERM', 'COMMENTARY', 'GRASSROOT')
            ),
            contract_start_date TEXT,
            contract_end_date TEXT,
            homepage_url TEXT,
            follower_count INTEGER CHECK (
                follower_count IS NULL OR follower_count >= 0
            ),
            youtube_user_id TEXT,
            youtube_homepage_url TEXT,
            youtube_follower_count INTEGER CHECK (
                youtube_follower_count IS NULL OR youtube_follower_count >= 0
            ),
            tiktok_user_id TEXT,
            tiktok_homepage_url TEXT,
            tiktok_follower_count INTEGER CHECK (
                tiktok_follower_count IS NULL OR tiktok_follower_count >= 0
            ),
            follower_raw_display_value TEXT,
            follower_source TEXT CHECK (
                follower_source IS NULL OR
                follower_source IN (
                    'YOUTUBE_API', 'TIKTOK_API', 'TIKTOK_BROWSER', 'MANUAL'
                )
            ),
            follower_source_url TEXT,
            follower_profile_url TEXT,
            follower_count_is_estimated INTEGER CHECK (
                follower_count_is_estimated IS NULL OR
                follower_count_is_estimated IN (0, 1)
            ),
            follower_count_updated_at TEXT,
            follower_sync_status TEXT NOT NULL DEFAULT 'NEVER' CHECK (
                follower_sync_status IN ('NEVER', 'SUCCESS', 'FAILED', 'MANUAL')
            ),
            follower_error_code TEXT,
            follower_sync_error TEXT,
            settlement_eligible INTEGER NOT NULL DEFAULT 0 CHECK (
                settlement_eligible IN (0, 1)
            ),
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _create_creator_contract(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS creator_contract (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            contract_type TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (creator_id) REFERENCES koc_master(id) ON DELETE CASCADE
        )
        """
    )


def _create_dashboard_post_storage(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_post (
            record_key TEXT PRIMARY KEY,
            source_file TEXT NOT NULL,
            publish_date TEXT,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_dashboard_post_publish_date "
        "ON dashboard_post(publish_date)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_dashboard_post_source_file "
        "ON dashboard_post(source_file)"
    )


def _create_grassroot_compensation_settings(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS grassroot_compensation_setting (
            period_month TEXT PRIMARY KEY,
            jpy_to_usd_rate REAL NOT NULL CHECK (jpy_to_usd_rate > 0),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _create_grassroot_compensation_contract_snapshots(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS grassroot_compensation_contract_snapshot (
            period_month TEXT NOT NULL,
            creator_id INTEGER NOT NULL,
            contract_types_json TEXT NOT NULL,
            captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (period_month, creator_id),
            FOREIGN KEY (creator_id) REFERENCES koc_master(id) ON DELETE CASCADE
        )
        """
    )


def _create_creator_profile_history(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS creator_profile_history (
            creator_id INTEGER NOT NULL,
            effective_date TEXT NOT NULL,
            user_id TEXT NOT NULL,
            koc_name TEXT NOT NULL,
            creator_category TEXT,
            contract_types_json TEXT NOT NULL,
            contract_start_date TEXT,
            contract_end_date TEXT,
            homepage_url TEXT,
            follower_count INTEGER,
            youtube_user_id TEXT,
            youtube_homepage_url TEXT,
            youtube_follower_count INTEGER,
            tiktok_user_id TEXT,
            tiktok_homepage_url TEXT,
            tiktok_follower_count INTEGER,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (creator_id, effective_date),
            FOREIGN KEY (creator_id) REFERENCES koc_master(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_creator_profile_history_uid_date "
        "ON creator_profile_history(user_id, effective_date)"
    )


def _create_authoritative_contract_periods(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS creator_contract_period (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            creator_category TEXT,
            contract_types_json TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (creator_id, start_date),
            CHECK (end_date >= start_date),
            FOREIGN KEY (creator_id) REFERENCES koc_master(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_creator_contract_period_lookup "
        "ON creator_contract_period(creator_id, start_date, end_date)"
    )


def _create_contract_revision_audit(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS creator_contract_revision (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            operation_type TEXT NOT NULL
                CHECK (operation_type IN ('CORRECTION', 'CHANGE', 'DELETE', 'REVERT')),
            before_json TEXT NOT NULL,
            after_json TEXT NOT NULL,
            affected_start_date TEXT,
            affected_end_date TEXT,
            reason TEXT,
            reverted_revision_id INTEGER,
            reverted_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (creator_id) REFERENCES koc_master(id) ON DELETE CASCADE,
            FOREIGN KEY (reverted_revision_id)
                REFERENCES creator_contract_revision(id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_creator_contract_revision_creator "
        "ON creator_contract_revision(creator_id, id DESC)"
    )


def _normalized_contract_json(value: object) -> tuple[str, ...]:
    try:
        decoded = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(
        dict.fromkeys(
            text
            for item in decoded
            if (text := str(item).strip())
        )
    )


def _seed_authoritative_contract_periods(
    connection: sqlite3.Connection,
) -> None:
    """Collapse profile snapshots into non-overlapping contract terms.

    The current creator master wins when duplicate profile snapshots disagree.
    Profile-only revisions with the same contract are merged and never become
    additional contract changes.
    """
    if connection.execute(
        "SELECT 1 FROM creator_contract_period LIMIT 1"
    ).fetchone() is not None:
        return

    masters = connection.execute(
        """
        SELECT id, creator_category, contract_start_date, contract_end_date
        FROM koc_master
        ORDER BY id
        """
    ).fetchall()
    for master in masters:
        creator_id = int(master["id"])
        current_contracts = tuple(
            str(row["contract_type"]).strip()
            for row in connection.execute(
                """
                SELECT contract_type FROM creator_contract
                WHERE creator_id = ? AND contract_type IS NOT NULL
                  AND TRIM(contract_type) != ''
                ORDER BY id
                """,
                (creator_id,),
            ).fetchall()
        )
        candidates: dict[tuple[tuple[str, ...], str], dict[str, object]] = {}
        for row in connection.execute(
            """
            SELECT effective_date, creator_category, contract_types_json,
                   contract_start_date, contract_end_date
            FROM creator_profile_history
            WHERE creator_id = ?
            ORDER BY effective_date
            """,
            (creator_id,),
        ).fetchall():
            contracts = _normalized_contract_json(row["contract_types_json"])
            start = str(row["contract_start_date"] or "").strip()
            end = str(row["contract_end_date"] or "").strip()
            if not contracts or not start or not end:
                continue
            key = (contracts, start)
            existing = candidates.get(key)
            if existing is None or end > str(existing["end"]):
                candidates[key] = {
                    "contracts": contracts,
                    "category": row["creator_category"],
                    "start": start,
                    "end": end,
                    "is_master": False,
                }

        master_start = str(master["contract_start_date"] or "").strip()
        master_end = str(master["contract_end_date"] or "").strip()
        if current_contracts and master_start and master_end:
            candidates[(current_contracts, master_start)] = {
                "contracts": current_contracts,
                "category": master["creator_category"],
                "start": master_start,
                "end": master_end,
                "is_master": True,
            }

        ordered = sorted(
            candidates.values(),
            key=lambda item: (str(item["start"]), bool(item["is_master"])),
        )
        master_candidate = next(
            (item for item in ordered if bool(item["is_master"])),
            None,
        )
        collapsed: list[dict[str, object]] = []
        for item in ordered:
            if (
                master_candidate is not None
                and item is not master_candidate
                and item["contracts"] == master_candidate["contracts"]
                and str(item["start"]) <= str(master_candidate["end"])
                and str(item["end"]) >= str(master_candidate["start"])
            ):
                continue
            if collapsed and item["contracts"] == collapsed[-1]["contracts"]:
                previous_end = date.fromisoformat(str(collapsed[-1]["end"]))
                current_start = date.fromisoformat(str(item["start"]))
                if current_start <= previous_end + timedelta(days=1):
                    if bool(item["is_master"]):
                        collapsed[-1] = item
                    else:
                        collapsed[-1]["end"] = max(
                            str(collapsed[-1]["end"]), str(item["end"])
                        )
                    continue
            collapsed.append(item)

        for index, item in enumerate(collapsed):
            start = date.fromisoformat(str(item["start"]))
            end = date.fromisoformat(str(item["end"]))
            if index + 1 < len(collapsed):
                next_start = date.fromisoformat(str(collapsed[index + 1]["start"]))
                end = min(end, next_start - timedelta(days=1))
            if end < start:
                continue
            connection.execute(
                """
                INSERT INTO creator_contract_period (
                    creator_id, creator_category, contract_types_json,
                    start_date, end_date
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    creator_id,
                    item["category"],
                    json.dumps(list(item["contracts"]), ensure_ascii=False),
                    start.isoformat(),
                    end.isoformat(),
                ),
            )


def _seed_creator_profile_history(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT id, user_id, koc_name, creator_category,
               contract_start_date, contract_end_date, homepage_url,
               follower_count, youtube_user_id, youtube_homepage_url,
               youtube_follower_count, tiktok_user_id,
               tiktok_homepage_url, tiktok_follower_count, active
        FROM koc_master
        """
    ).fetchall()
    for row in rows:
        contracts = [
            str(contract_row[0]).strip()
            for contract_row in connection.execute(
                "SELECT contract_type FROM creator_contract "
                "WHERE creator_id = ? AND contract_type IS NOT NULL "
                "AND TRIM(contract_type) != '' ORDER BY id",
                (int(row["id"]),),
            ).fetchall()
        ]
        connection.execute(
            """
            INSERT OR IGNORE INTO creator_profile_history (
                creator_id, effective_date, user_id, koc_name,
                creator_category, contract_types_json,
                contract_start_date, contract_end_date, homepage_url,
                follower_count, youtube_user_id, youtube_homepage_url,
                youtube_follower_count, tiktok_user_id,
                tiktok_homepage_url, tiktok_follower_count, active
            ) VALUES (?, '1900-01-01', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(row["id"]),
                str(row["user_id"]),
                str(row["koc_name"]),
                row["creator_category"],
                json.dumps(contracts, ensure_ascii=False),
                row["contract_start_date"],
                row["contract_end_date"],
                row["homepage_url"],
                row["follower_count"],
                row["youtube_user_id"],
                row["youtube_homepage_url"],
                row["youtube_follower_count"],
                row["tiktok_user_id"],
                row["tiktok_homepage_url"],
                row["tiktok_follower_count"],
                int(row["active"]),
            ),
        )


def _ensure_platform_profile_columns(connection: sqlite3.Connection) -> None:
    master_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(koc_master)")
    }
    history_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(creator_profile_history)")
    }
    platform_columns = (
        ("youtube_user_id", "TEXT"),
        ("youtube_homepage_url", "TEXT"),
        ("youtube_follower_count", "INTEGER"),
        ("tiktok_user_id", "TEXT"),
        ("tiktok_homepage_url", "TEXT"),
        ("tiktok_follower_count", "INTEGER"),
    )
    for column, sql_type in platform_columns:
        if column not in master_columns:
            connection.execute(
                f"ALTER TABLE koc_master ADD COLUMN {column} {sql_type}"
            )
        if column not in history_columns:
            connection.execute(
                f"ALTER TABLE creator_profile_history ADD COLUMN {column} {sql_type}"
            )

    connection.execute(
        """
        UPDATE koc_master SET
            youtube_user_id = COALESCE(youtube_user_id, user_id),
            youtube_homepage_url = COALESCE(youtube_homepage_url, homepage_url),
            youtube_follower_count = COALESCE(youtube_follower_count, follower_count)
        WHERE LOWER(COALESCE(homepage_url, '')) LIKE '%youtu%'
        """
    )
    connection.execute(
        """
        UPDATE koc_master SET
            tiktok_user_id = COALESCE(tiktok_user_id, user_id),
            tiktok_homepage_url = COALESCE(tiktok_homepage_url, homepage_url),
            tiktok_follower_count = COALESCE(tiktok_follower_count, follower_count)
        WHERE LOWER(COALESCE(homepage_url, '')) LIKE '%tiktok%'
        """
    )
    connection.execute(
        """
        UPDATE creator_profile_history SET
            youtube_user_id = COALESCE(youtube_user_id, user_id),
            youtube_homepage_url = COALESCE(youtube_homepage_url, homepage_url),
            youtube_follower_count = COALESCE(youtube_follower_count, follower_count)
        WHERE LOWER(COALESCE(homepage_url, '')) LIKE '%youtu%'
        """
    )
    connection.execute(
        """
        UPDATE creator_profile_history SET
            tiktok_user_id = COALESCE(tiktok_user_id, user_id),
            tiktok_homepage_url = COALESCE(tiktok_homepage_url, homepage_url),
            tiktok_follower_count = COALESCE(tiktok_follower_count, follower_count)
        WHERE LOWER(COALESCE(homepage_url, '')) LIKE '%tiktok%'
        """
    )


def _contract_period_defaults(
    creator_category: object,
    contract_types: Iterable[object],
    *,
    year: int,
) -> tuple[str, str]:
    """Return the default May-based term for the creator's contract family."""
    category = str(creator_category or "").strip().upper()
    contracts = " ".join(str(value).casefold() for value in contract_types)
    long_term_label = "\u957f\u5305"
    commentary_label = "\u89e3\u8bf4"
    if category == "LONG_TERM" or "long_term" in contracts or long_term_label in contracts:
        return f"{year}-05-01", f"{year}-12-31"
    if category == "COMMENTARY" or "commentary" in contracts or commentary_label in contracts:
        return f"{year}-05-01", f"{year}-08-31"
    return f"{year}-05-01", f"{year}-10-31"


def _ensure_contract_period_columns(connection: sqlite3.Connection) -> None:
    master_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(koc_master)")
    }
    if "contract_start_date" not in master_columns:
        connection.execute("ALTER TABLE koc_master ADD COLUMN contract_start_date TEXT")
    if "contract_end_date" not in master_columns:
        connection.execute("ALTER TABLE koc_master ADD COLUMN contract_end_date TEXT")

    history_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(creator_profile_history)")
    }
    if "contract_start_date" not in history_columns:
        connection.execute(
            "ALTER TABLE creator_profile_history ADD COLUMN contract_start_date TEXT"
        )
    if "contract_end_date" not in history_columns:
        connection.execute(
            "ALTER TABLE creator_profile_history ADD COLUMN contract_end_date TEXT"
        )


def _backfill_contract_periods(connection: sqlite3.Connection) -> None:
    default_year = date.today().year
    master_rows = connection.execute(
        """
        SELECT master.id, master.creator_category,
               master.contract_start_date, master.contract_end_date,
               GROUP_CONCAT(contract.contract_type, char(31)) AS contract_types
        FROM koc_master AS master
        LEFT JOIN creator_contract AS contract ON contract.creator_id = master.id
        GROUP BY master.id
        """
    ).fetchall()
    for row in master_rows:
        contracts = str(row["contract_types"] or "").split(chr(31))
        start, end = _contract_period_defaults(
            row["creator_category"], contracts, year=default_year
        )
        connection.execute(
            """
            UPDATE koc_master
            SET contract_start_date = COALESCE(NULLIF(contract_start_date, ''), ?),
                contract_end_date = COALESCE(NULLIF(contract_end_date, ''), ?)
            WHERE id = ?
            """,
            (start, end, int(row["id"])),
        )

    history_rows = connection.execute(
        """
        SELECT creator_id, effective_date, creator_category, contract_types_json,
               contract_start_date, contract_end_date
        FROM creator_profile_history
        """
    ).fetchall()
    for row in history_rows:
        try:
            contracts = json.loads(str(row["contract_types_json"]))
        except json.JSONDecodeError:
            contracts = []
        if not isinstance(contracts, list):
            contracts = []
        start, end = _contract_period_defaults(
            row["creator_category"], contracts, year=default_year
        )
        connection.execute(
            """
            UPDATE creator_profile_history
            SET contract_start_date = COALESCE(NULLIF(contract_start_date, ''), ?),
                contract_end_date = COALESCE(NULLIF(contract_end_date, ''), ?)
            WHERE creator_id = ? AND effective_date = ?
            """,
            (start, end, int(row["creator_id"]), str(row["effective_date"])),
        )


def _create_dashboard_import_batches(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_import_batch (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL CHECK (mode IN ('REPLACE_MONTHS', 'APPEND')),
            period_months_json TEXT NOT NULL,
            source_files_json TEXT NOT NULL,
            file_hashes_json TEXT NOT NULL,
            input_count INTEGER NOT NULL,
            saved_count INTEGER NOT NULL,
            removed_count INTEGER NOT NULL DEFAULT 0,
            report_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    dashboard_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(dashboard_post)")
    }
    if "import_batch_id" not in dashboard_columns:
        connection.execute("ALTER TABLE dashboard_post ADD COLUMN import_batch_id INTEGER")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_dashboard_post_import_batch "
        "ON dashboard_post(import_batch_id)"
    )


def _create_cross_industry_exclusions(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_cross_industry_exclusion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            url_key TEXT NOT NULL UNIQUE,
            original_url TEXT NOT NULL,
            normalized_url TEXT NOT NULL,
            reason TEXT,
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_cross_industry_active "
        "ON dashboard_cross_industry_exclusion(active, platform)"
    )


def _create_traffic_boost_settings(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_traffic_boost_setting (
            period_month TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _create_ai_agent_storage(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_conversation (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            title TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_message (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES ai_conversation(id)
                ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_tool_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT,
            tool_name TEXT NOT NULL,
            arguments_json TEXT NOT NULL,
            result_summary_json TEXT NOT NULL,
            duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
            status TEXT NOT NULL CHECK (status IN ('SUCCESS', 'ERROR')),
            error_code TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES ai_conversation(id)
                ON DELETE SET NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_conversation_session "
        "ON ai_conversation(session_id, updated_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_message_conversation "
        "ON ai_message(conversation_id, id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_tool_audit_conversation "
        "ON ai_tool_audit(conversation_id, id DESC)"
    )


def _create_grassroot_compensation_versions(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS grassroot_compensation_version (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period_month TEXT NOT NULL,
            version_no INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('DRAFT', 'LOCKED')),
            jpy_to_usd_rate REAL NOT NULL CHECK (jpy_to_usd_rate > 0),
            details_json TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            locked_at TEXT,
            UNIQUE (period_month, version_no)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_compensation_version_period "
        "ON grassroot_compensation_version(period_month, version_no DESC)"
    )


def _create_long_term_compensation_storage(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS long_term_compensation_activity (
            period_month TEXT NOT NULL,
            creator_id INTEGER NOT NULL,
            activity_count INTEGER NOT NULL CHECK (activity_count >= 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (period_month, creator_id),
            FOREIGN KEY (creator_id) REFERENCES koc_master(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_long_term_activity_period "
        "ON long_term_compensation_activity(period_month, creator_id)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS long_term_compensation_version (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period_month TEXT NOT NULL,
            version_no INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('DRAFT', 'LOCKED')),
            jpy_to_usd_rate REAL NOT NULL CHECK (jpy_to_usd_rate > 0),
            details_json TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            locked_at TEXT,
            UNIQUE (period_month, version_no)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_long_term_compensation_version_period "
        "ON long_term_compensation_version(period_month, version_no DESC)"
    )


def _create_commentary_compensation_storage(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS commentary_post_validity (
            period_month TEXT NOT NULL,
            creator_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            average_watch_rate REAL,
            recent_three_month_average REAL,
            valid_ratio REAL NOT NULL DEFAULT 1.0 CHECK (
                valid_ratio IN (0, 0.5, 0.6, 0.7, 1.0)
            ),
            review_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
                review_status IN ('AUTO', 'PENDING', 'APPROVED', 'REJECTED')
            ),
            reason TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (period_month, url),
            FOREIGN KEY (creator_id) REFERENCES koc_master(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_commentary_validity_period_creator "
        "ON commentary_post_validity(period_month, creator_id)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS commentary_theme_definition (
            period_month TEXT NOT NULL,
            theme_code TEXT NOT NULL,
            theme_name TEXT NOT NULL,
            description TEXT,
            max_per_creator INTEGER NOT NULL DEFAULT 1 CHECK (max_per_creator > 0),
            reward_jpy INTEGER NOT NULL DEFAULT 15000 CHECK (reward_jpy >= 0),
            enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (period_month, theme_code)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS commentary_theme_submission (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period_month TEXT NOT NULL,
            creator_id INTEGER NOT NULL,
            theme_code TEXT NOT NULL,
            content_format TEXT NOT NULL CHECK (content_format IN ('LONG', 'SHORT')),
            urls_json TEXT NOT NULL,
            submitted_date TEXT,
            review_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
                review_status IN ('PENDING', 'APPROVED', 'REJECTED')
            ),
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (period_month, creator_id, theme_code),
            FOREIGN KEY (creator_id) REFERENCES koc_master(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_commentary_theme_submission_period "
        "ON commentary_theme_submission(period_month, creator_id)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS commentary_compensation_version (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period_month TEXT NOT NULL,
            version_no INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('DRAFT', 'LOCKED')),
            jpy_to_usd_rate REAL NOT NULL CHECK (jpy_to_usd_rate > 0),
            details_json TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            locked_at TEXT,
            UNIQUE (period_month, version_no)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_commentary_compensation_version_period "
        "ON commentary_compensation_version(period_month, version_no DESC)"
    )
    july_themes = (
        (
            "2026-07",
            "IJL_BEGINNER",
            "初心者向けIJLコンテンツ",
            "IJL赛事规则、术语、观战要点及初学者解说。",
        ),
        (
            "2026-07",
            "NEW_MODE",
            "新モード関連コンテンツ",
            "新模式介绍、解说、感想、攻略及看点。",
        ),
        (
            "2026-07",
            "LIVE_TALK_PLAN",
            "実写・トーク系／企画系コンテンツ",
            "真人出镜、访谈、对谈、问答或企划类内容。",
        ),
        (
            "2026-07",
            "DUAL_PERSPECTIVE",
            "同一名場面の視点別解説コンテンツ",
            "同一赛事名场面的监管者与求生者双视角解说。",
        ),
    )
    connection.executemany(
        """
        INSERT OR IGNORE INTO commentary_theme_definition (
            period_month, theme_code, theme_name, description
        ) VALUES (?, ?, ?, ?)
        """,
        july_themes,
    )


def _create_dashboard_import_batch_snapshot(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_import_batch_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            record_key TEXT NOT NULL,
            source_file TEXT NOT NULL,
            publish_date TEXT,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (batch_id) REFERENCES dashboard_import_batch(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_dashboard_import_snapshot_batch "
        "ON dashboard_import_batch_snapshot(batch_id)"
    )
    batch_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(dashboard_import_batch)")
    }
    if "rolled_back_at" not in batch_columns:
        connection.execute(
            "ALTER TABLE dashboard_import_batch ADD COLUMN rolled_back_at TEXT"
        )


def _add_column_if_missing(
    connection: sqlite3.Connection, table_name: str, column: str, ddl: str
) -> None:
    existing = {
        str(row[1]) for row in connection.execute(f"PRAGMA table_info({table_name})")
    }
    if column not in existing:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


def _create_settlement_lock_audit(connection: sqlite3.Connection) -> None:
    """Add lock_note/locked_by audit columns to the three settlement version
    tables (per 19.5.3: lock_note is required + operator_name is recorded),
    and a per-month revision tracker for commentary theme submissions so
    replace_commentary_theme_submissions() can support expected_revision
    optimistic concurrency (per 19.3.4)."""
    for table_name in (
        "grassroot_compensation_version",
        "long_term_compensation_version",
        "commentary_compensation_version",
    ):
        _add_column_if_missing(connection, table_name, "lock_note", "lock_note TEXT")
        _add_column_if_missing(connection, table_name, "locked_by", "locked_by TEXT")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS commentary_theme_submission_revision (
            period_month TEXT PRIMARY KEY,
            revision TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _current_columns(connection: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(
        str(row[1]) for row in connection.execute("PRAGMA table_info(koc_master)")
    )


def _has_unique_user_id_index(connection: sqlite3.Connection) -> bool:
    for index_row in connection.execute("PRAGMA index_list(koc_master)"):
        if not bool(index_row[2]):
            continue
        index_name = str(index_row[1]).replace("'", "''")
        columns = [
            str(row[2])
            for row in connection.execute(f"PRAGMA index_info('{index_name}')")
        ]
        if columns == ["user_id"]:
            return True
    return False


def _rebuild_koc_master(connection: sqlite3.Connection) -> None:
    before_rows = [
        (int(row[0]), str(row[1]), str(row[2]))
        for row in connection.execute(
            "SELECT id, user_id, koc_name FROM koc_master ORDER BY id"
        ).fetchall()
    ]
    existing_columns = set(_current_columns(connection))
    copy_columns = [
        column for column in KOC_MASTER_COLUMNS if column in existing_columns
    ]
    if not {"id", "user_id", "koc_name"}.issubset(copy_columns):
        raise RuntimeError("旧达人表缺少 id、user_id 或 koc_name，已停止迁移。")

    if "follower_source" in existing_columns:
        connection.execute(
            "UPDATE koc_master SET follower_source = 'MANUAL' "
            "WHERE follower_source = ?",
            ("TIK" + "VIB_PAGE",),
        )

    connection.execute("DROP TABLE IF EXISTS koc_master_v06")
    _create_koc_master(connection, "koc_master_v06")
    joined_columns = ", ".join(copy_columns)
    connection.execute(
        f"INSERT INTO koc_master_v06 ({joined_columns}) "
        f"SELECT {joined_columns} FROM koc_master"
    )

    after_rows = [
        (int(row[0]), str(row[1]), str(row[2]))
        for row in connection.execute(
            "SELECT id, user_id, koc_name FROM koc_master_v06 ORDER BY id"
        ).fetchall()
    ]
    if before_rows != after_rows:
        raise RuntimeError("达人主表迁移完整性检查失败，未替换旧表。")

    connection.execute("DROP TABLE koc_master")
    connection.execute("ALTER TABLE koc_master_v06 RENAME TO koc_master")


def _create_follower_audit_table(
    connection: sqlite3.Connection,
    table_name: str = "follower_update_audit",
) -> None:
    if table_name not in {"follower_update_audit", "follower_update_audit_v06"}:
        raise ValueError("不允许的粉丝审计迁移表名。")
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            koc_name TEXT NOT NULL,
            old_follower_count INTEGER,
            new_follower_count INTEGER,
            raw_display_value TEXT,
            source TEXT CHECK (
                source IS NULL OR source IN (
                    'YOUTUBE_API', 'TIKTOK_API', 'TIKTOK_BROWSER', 'MANUAL'
                )
            ),
            source_url TEXT,
            fetched_at TEXT NOT NULL,
            is_estimated INTEGER NOT NULL DEFAULT 0 CHECK (is_estimated IN (0, 1)),
            settlement_eligible INTEGER NOT NULL DEFAULT 0 CHECK (
                settlement_eligible IN (0, 1)
            ),
            sync_status TEXT NOT NULL,
            error_code TEXT,
            operator_mode TEXT NOT NULL CHECK (
                operator_mode IN ('AUTOMATIC', 'MANUAL_ASSISTED', 'MANUAL')
            ),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    if table_name == "follower_update_audit":
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_follower_audit_user_time "
            "ON follower_update_audit(user_id, fetched_at)"
        )


def _table_sql(connection: sqlite3.Connection, table_name: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return str(row[0] or "") if row is not None else ""


def _rebuild_follower_audit(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "follower_update_audit"):
        _create_follower_audit_table(connection)
        return
    connection.execute(
        "UPDATE follower_update_audit SET source = 'MANUAL' WHERE source = ?",
        ("TIK" + "VIB_PAGE",),
    )
    before_ids = [
        int(row[0])
        for row in connection.execute(
            "SELECT id FROM follower_update_audit ORDER BY id"
        ).fetchall()
    ]
    connection.execute("DROP TABLE IF EXISTS follower_update_audit_v06")
    _create_follower_audit_table(connection, "follower_update_audit_v06")
    columns = ", ".join(FOLLOWER_AUDIT_COLUMNS)
    connection.execute(
        f"INSERT INTO follower_update_audit_v06 ({columns}) "
        f"SELECT {columns} FROM follower_update_audit"
    )
    after_ids = [
        int(row[0])
        for row in connection.execute(
            "SELECT id FROM follower_update_audit_v06 ORDER BY id"
        ).fetchall()
    ]
    if before_ids != after_ids:
        raise RuntimeError("粉丝审计表迁移完整性检查失败，未替换旧表。")
    connection.execute("DROP TABLE follower_update_audit")
    connection.execute(
        "ALTER TABLE follower_update_audit_v06 RENAME TO follower_update_audit"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_follower_audit_user_time "
        "ON follower_update_audit(user_id, fetched_at)"
    )


def _ensure_creator(
    connection: sqlite3.Connection,
    user_id: object,
    koc_name: object,
) -> int:
    uid = str(user_id).strip()
    name = str(koc_name).strip()
    row = connection.execute(
        "SELECT id FROM koc_master WHERE user_id = ? ORDER BY id LIMIT 1",
        (uid,),
    ).fetchone()
    if row is not None:
        return int(row[0])
    cursor = connection.execute(
        "INSERT INTO koc_master (user_id, koc_name) VALUES (?, ?)",
        (uid, name),
    )
    return int(cursor.lastrowid)


def _seed_creators(
    connection: sqlite3.Connection,
    records: Iterable[Sequence[object]],
) -> None:
    for record in records:
        if len(record) < 2:
            continue
        _ensure_creator(connection, record[0], record[1])


def _import_creator_rows(
    connection: sqlite3.Connection,
    records: Iterable[Sequence[object]],
) -> None:
    for record in records:
        if len(record) < 2:
            continue
        creator_id = _ensure_creator(connection, record[0], record[1])
        if len(record) >= 3:
            raw_contract = record[2]
            contract = str(raw_contract).strip() if raw_contract is not None else None
            connection.execute(
                "INSERT INTO creator_contract (creator_id, contract_type) VALUES (?, ?)",
                (creator_id, contract or None),
            )


def apply_migrations(
    connection: sqlite3.Connection,
    seed_records: Iterable[tuple[str, str]],
    input_records: Iterable[Sequence[object]] | None = None,
) -> None:
    """Upgrade creator storage while preserving master and contract records."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    if not _table_exists(connection, "koc_master"):
        _create_koc_master(connection, "koc_master")

    initialization_id = "v0.2_initialize_koc_master"
    if not _migration_applied(connection, initialization_id):
        if _table_exists(connection, "koc_mapping"):
            legacy_rows = connection.execute(
                "SELECT user_id, koc_name FROM koc_mapping"
            ).fetchall()
            _seed_creators(connection, legacy_rows)
        _seed_creators(connection, tuple(seed_records))
        _record_migration(connection, initialization_id)

    normalized_contract_id = "v0.5_normalize_creator_contracts"
    legacy_columns = set(_current_columns(connection))
    _create_creator_contract(connection)
    if not _migration_applied(connection, normalized_contract_id):
        if "contract_type" in legacy_columns:
            connection.execute(
                """
                INSERT INTO creator_contract (creator_id, contract_type, created_at, updated_at)
                SELECT id, NULLIF(TRIM(contract_type), ''), created_at, updated_at
                FROM koc_master
                WHERE contract_type IS NOT NULL AND TRIM(contract_type) != ''
                """
            )
        if (
            set(_current_columns(connection)) != set(KOC_MASTER_COLUMNS)
            or _has_unique_user_id_index(connection)
        ):
            _rebuild_koc_master(connection)
        _record_migration(connection, normalized_contract_id)
    elif (
        set(_current_columns(connection)) != set(KOC_MASTER_COLUMNS)
        or _has_unique_user_id_index(connection)
    ):
        _rebuild_koc_master(connection)

    schema_migration_id = "v0.3_expand_koc_master"
    _record_migration(connection, schema_migration_id)

    follower_migration_id = "v0.4_follower_sources_and_audit"
    connection.execute(
        """
        UPDATE koc_master SET
            follower_raw_display_value = CAST(follower_count AS TEXT),
            follower_source = 'MANUAL',
            follower_profile_url = homepage_url,
            follower_count_is_estimated = 0,
            settlement_eligible = 0
        WHERE follower_count IS NOT NULL AND follower_source IS NULL
        """
    )
    _create_follower_audit_table(connection)
    _record_migration(connection, follower_migration_id)

    if not _migration_applied(connection, TIKTOK_BROWSER_MIGRATION_ID):
        master_sql = _table_sql(connection, "koc_master")
        legacy_source_marker = "TIK" + "VIB_PAGE"
        connection.execute(
            "UPDATE koc_master SET follower_source = 'MANUAL' "
            "WHERE follower_source = ?",
            (legacy_source_marker,),
        )
        if "TIKTOK_BROWSER" not in master_sql or legacy_source_marker in master_sql:
            _rebuild_koc_master(connection)

        audit_sql = _table_sql(connection, "follower_update_audit")
        if "TIKTOK_BROWSER" not in audit_sql or legacy_source_marker in audit_sql:
            _rebuild_follower_audit(connection)
        _record_migration(connection, TIKTOK_BROWSER_MIGRATION_ID)

    if not _migration_applied(connection, TIKTOK_API_MIGRATION_ID):
        master_sql = _table_sql(connection, "koc_master")
        if "TIKTOK_API" not in master_sql:
            _rebuild_koc_master(connection)
        audit_sql = _table_sql(connection, "follower_update_audit")
        if "TIKTOK_API" not in audit_sql:
            _rebuild_follower_audit(connection)
        _record_migration(connection, TIKTOK_API_MIGRATION_ID)

    input_migration_id = "v0.5_import_input_creator_contracts"
    if input_records is not None and not _migration_applied(
        connection, input_migration_id
    ):
        _import_creator_rows(connection, input_records)
        _record_migration(connection, input_migration_id)

    _create_dashboard_post_storage(connection)
    _record_migration(connection, DASHBOARD_STORAGE_MIGRATION_ID)
    _create_grassroot_compensation_settings(connection)
    _record_migration(connection, GRASSROOT_COMPENSATION_SETTINGS_MIGRATION_ID)
    _create_grassroot_compensation_contract_snapshots(connection)
    _record_migration(
        connection, GRASSROOT_COMPENSATION_CONTRACT_SNAPSHOTS_MIGRATION_ID
    )
    _create_creator_profile_history(connection)
    _ensure_platform_profile_columns(connection)
    # The profile-history seed below reads the contract-period columns. Ensure
    # they exist before seeding older databases that predate this migration.
    _ensure_contract_period_columns(connection)
    _seed_creator_profile_history(connection)
    _record_migration(connection, CREATOR_PROFILE_HISTORY_MIGRATION_ID)
    _create_dashboard_import_batches(connection)
    _record_migration(connection, DASHBOARD_IMPORT_BATCHES_MIGRATION_ID)
    _create_grassroot_compensation_versions(connection)
    _record_migration(connection, GRASSROOT_COMPENSATION_VERSIONS_MIGRATION_ID)
    _create_long_term_compensation_storage(connection)
    _record_migration(connection, LONG_TERM_COMPENSATION_MIGRATION_ID)
    _create_commentary_compensation_storage(connection)
    _record_migration(connection, COMMENTARY_COMPENSATION_MIGRATION_ID)
    _create_cross_industry_exclusions(connection)
    _record_migration(connection, CROSS_INDUSTRY_EXCLUSIONS_MIGRATION_ID)
    _create_traffic_boost_settings(connection)
    _record_migration(connection, TRAFFIC_BOOST_SETTINGS_MIGRATION_ID)
    if not _migration_applied(connection, CONTRACT_PERIODS_MIGRATION_ID):
        _backfill_contract_periods(connection)
        _record_migration(connection, CONTRACT_PERIODS_MIGRATION_ID)
    _create_authoritative_contract_periods(connection)
    if not _migration_applied(
        connection, AUTHORITATIVE_CONTRACT_PERIODS_MIGRATION_ID
    ):
        _seed_authoritative_contract_periods(connection)
        _record_migration(
            connection, AUTHORITATIVE_CONTRACT_PERIODS_MIGRATION_ID
        )
    _create_contract_revision_audit(connection)
    _record_migration(connection, CONTRACT_REVISION_AUDIT_MIGRATION_ID)
    _create_ai_agent_storage(connection)
    _record_migration(connection, AI_AGENT_STORAGE_MIGRATION_ID)
    _create_dashboard_import_batch_snapshot(connection)
    _record_migration(connection, DASHBOARD_IMPORT_SNAPSHOT_MIGRATION_ID)
    _add_column_if_missing(
        connection, "follower_update_audit", "operator_name", "operator_name TEXT"
    )
    _create_settlement_lock_audit(connection)
    _record_migration(connection, SETTLEMENT_LOCK_AUDIT_MIGRATION_ID)

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_koc_master_user_id ON koc_master(user_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_koc_master_youtube_user_id "
        "ON koc_master(youtube_user_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_koc_master_tiktok_user_id "
        "ON koc_master(tiktok_user_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_koc_master_name ON koc_master(koc_name)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_koc_master_category ON koc_master(creator_category)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_creator_contract_creator "
        "ON creator_contract(creator_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_creator_contract_type "
        "ON creator_contract(contract_type)"
    )
    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    if integrity is None or integrity[0] != "ok":
        raise RuntimeError("SQLite 完整性检查失败，达人库迁移未完成。")
