from __future__ import annotations

from collections.abc import Iterable
from typing import Any


POSTGRES_SCHEMA_MIGRATION_ID = "postgres_v2_ai_agent"
POSTGRES_COMMENTARY_THEME_COMPAT_MIGRATION_ID = "postgres_v3_commentary_theme_objects"
POSTGRES_IMPORT_ROLLBACK_AND_LOCK_AUDIT_MIGRATION_ID = (
    "postgres_v4_import_rollback_and_lock_audit"
)


POSTGRES_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        migration_id TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS koc_mapping (
        user_id TEXT PRIMARY KEY,
        koc_name TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS koc_master (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        koc_name TEXT NOT NULL,
        creator_category TEXT CHECK (
            creator_category IS NULL OR
            creator_category IN ('LONG_TERM', 'COMMENTARY', 'GRASSROOT')
        ),
        contract_start_date TEXT,
        contract_end_date TEXT,
        homepage_url TEXT,
        follower_count BIGINT CHECK (follower_count IS NULL OR follower_count >= 0),
        youtube_user_id TEXT,
        youtube_homepage_url TEXT,
        youtube_follower_count BIGINT CHECK (
            youtube_follower_count IS NULL OR youtube_follower_count >= 0
        ),
        tiktok_user_id TEXT,
        tiktok_homepage_url TEXT,
        tiktok_follower_count BIGINT CHECK (
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
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS creator_contract (
        id BIGSERIAL PRIMARY KEY,
        creator_id BIGINT NOT NULL REFERENCES koc_master(id) ON DELETE CASCADE,
        contract_type TEXT,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS creator_contract_period (
        id BIGSERIAL PRIMARY KEY,
        creator_id BIGINT NOT NULL REFERENCES koc_master(id) ON DELETE CASCADE,
        creator_category TEXT,
        contract_types_json TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        UNIQUE (creator_id, start_date),
        CHECK (end_date >= start_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS creator_contract_revision (
        id BIGSERIAL PRIMARY KEY,
        creator_id BIGINT NOT NULL REFERENCES koc_master(id) ON DELETE CASCADE,
        operation_type TEXT NOT NULL CHECK (
            operation_type IN ('CORRECTION', 'CHANGE', 'DELETE', 'REVERT')
        ),
        before_json TEXT NOT NULL,
        after_json TEXT NOT NULL,
        affected_start_date TEXT,
        affected_end_date TEXT,
        reason TEXT,
        reverted_revision_id BIGINT REFERENCES creator_contract_revision(id),
        reverted_at TEXT,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS creator_profile_history (
        creator_id BIGINT NOT NULL REFERENCES koc_master(id) ON DELETE CASCADE,
        effective_date TEXT NOT NULL,
        user_id TEXT NOT NULL,
        koc_name TEXT NOT NULL,
        creator_category TEXT,
        contract_types_json TEXT NOT NULL,
        homepage_url TEXT,
        follower_count BIGINT,
        active INTEGER NOT NULL CHECK (active IN (0, 1)),
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        contract_start_date TEXT,
        contract_end_date TEXT,
        youtube_homepage_url TEXT,
        youtube_follower_count BIGINT,
        tiktok_homepage_url TEXT,
        tiktok_follower_count BIGINT,
        youtube_user_id TEXT,
        tiktok_user_id TEXT,
        PRIMARY KEY (creator_id, effective_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dashboard_import_batch (
        id BIGSERIAL PRIMARY KEY,
        mode TEXT NOT NULL CHECK (mode IN ('REPLACE_MONTHS', 'APPEND')),
        period_months_json TEXT NOT NULL,
        source_files_json TEXT NOT NULL,
        file_hashes_json TEXT NOT NULL,
        input_count BIGINT NOT NULL,
        saved_count BIGINT NOT NULL,
        removed_count BIGINT NOT NULL DEFAULT 0,
        report_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        rolled_back_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dashboard_import_batch_snapshot (
        id BIGSERIAL PRIMARY KEY,
        batch_id BIGINT NOT NULL REFERENCES dashboard_import_batch(id) ON DELETE CASCADE,
        record_key TEXT NOT NULL,
        source_file TEXT NOT NULL,
        publish_date TEXT,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dashboard_post (
        record_key TEXT PRIMARY KEY,
        source_file TEXT NOT NULL,
        publish_date TEXT,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        import_batch_id BIGINT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dashboard_cross_industry_exclusion (
        id BIGSERIAL PRIMARY KEY,
        platform TEXT NOT NULL,
        url_key TEXT NOT NULL UNIQUE,
        original_url TEXT NOT NULL,
        normalized_url TEXT NOT NULL,
        reason TEXT,
        active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dashboard_traffic_boost_setting (
        period_month TEXT PRIMARY KEY,
        enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS follower_update_audit (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        koc_name TEXT NOT NULL,
        old_follower_count BIGINT,
        new_follower_count BIGINT,
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
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS grassroot_compensation_contract_snapshot (
        period_month TEXT NOT NULL,
        creator_id BIGINT NOT NULL REFERENCES koc_master(id) ON DELETE CASCADE,
        contract_types_json TEXT NOT NULL,
        captured_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        PRIMARY KEY (period_month, creator_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS grassroot_compensation_setting (
        period_month TEXT PRIMARY KEY,
        jpy_to_usd_rate DOUBLE PRECISION NOT NULL CHECK (jpy_to_usd_rate > 0),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS grassroot_compensation_version (
        id BIGSERIAL PRIMARY KEY,
        period_month TEXT NOT NULL,
        version_no INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('DRAFT', 'LOCKED')),
        jpy_to_usd_rate DOUBLE PRECISION NOT NULL CHECK (jpy_to_usd_rate > 0),
        details_json TEXT NOT NULL,
        summary_json TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        locked_at TEXT,
        lock_note TEXT,
        locked_by TEXT,
        UNIQUE (period_month, version_no)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS long_term_compensation_activity (
        period_month TEXT NOT NULL,
        creator_id BIGINT NOT NULL REFERENCES koc_master(id) ON DELETE CASCADE,
        activity_count INTEGER NOT NULL CHECK (activity_count >= 0),
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        PRIMARY KEY (period_month, creator_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS long_term_compensation_version (
        id BIGSERIAL PRIMARY KEY,
        period_month TEXT NOT NULL,
        version_no INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('DRAFT', 'LOCKED')),
        jpy_to_usd_rate DOUBLE PRECISION NOT NULL CHECK (jpy_to_usd_rate > 0),
        details_json TEXT NOT NULL,
        summary_json TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        locked_at TEXT,
        lock_note TEXT,
        locked_by TEXT,
        UNIQUE (period_month, version_no)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS commentary_post_validity (
        period_month TEXT NOT NULL,
        creator_id BIGINT NOT NULL REFERENCES koc_master(id) ON DELETE CASCADE,
        url TEXT NOT NULL,
        average_watch_rate DOUBLE PRECISION,
        recent_three_month_average DOUBLE PRECISION,
        valid_ratio DOUBLE PRECISION NOT NULL DEFAULT 1.0 CHECK (
            valid_ratio IN (0, 0.5, 0.6, 0.7, 1.0)
        ),
        review_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
            review_status IN ('AUTO', 'PENDING', 'APPROVED', 'REJECTED')
        ),
        reason TEXT,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        PRIMARY KEY (period_month, url)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS commentary_theme_definition (
        period_month TEXT NOT NULL,
        theme_code TEXT NOT NULL,
        theme_name TEXT NOT NULL,
        description TEXT,
        max_per_creator INTEGER NOT NULL DEFAULT 1 CHECK (max_per_creator > 0),
        reward_jpy BIGINT NOT NULL DEFAULT 15000 CHECK (reward_jpy >= 0),
        enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        PRIMARY KEY (period_month, theme_code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS commentary_theme_submission (
        id BIGSERIAL PRIMARY KEY,
        period_month TEXT NOT NULL,
        creator_id BIGINT NOT NULL REFERENCES koc_master(id) ON DELETE CASCADE,
        theme_code TEXT NOT NULL,
        content_format TEXT NOT NULL CHECK (content_format IN ('LONG', 'SHORT')),
        urls_json TEXT NOT NULL,
        submitted_date TEXT,
        review_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
            review_status IN ('PENDING', 'APPROVED', 'REJECTED')
        ),
        note TEXT,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        UNIQUE (period_month, creator_id, theme_code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS commentary_compensation_version (
        id BIGSERIAL PRIMARY KEY,
        period_month TEXT NOT NULL,
        version_no INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('DRAFT', 'LOCKED')),
        jpy_to_usd_rate DOUBLE PRECISION NOT NULL CHECK (jpy_to_usd_rate > 0),
        details_json TEXT NOT NULL,
        summary_json TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        locked_at TEXT,
        lock_note TEXT,
        locked_by TEXT,
        UNIQUE (period_month, version_no)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_conversation (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        title TEXT,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        expires_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_message (
        id BIGSERIAL PRIMARY KEY,
        conversation_id TEXT NOT NULL REFERENCES ai_conversation(id)
            ON DELETE CASCADE,
        role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
        content TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_tool_audit (
        id BIGSERIAL PRIMARY KEY,
        conversation_id TEXT REFERENCES ai_conversation(id) ON DELETE SET NULL,
        tool_name TEXT NOT NULL,
        arguments_json TEXT NOT NULL,
        result_summary_json TEXT NOT NULL,
        duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
        status TEXT NOT NULL CHECK (status IN ('SUCCESS', 'ERROR')),
        error_code TEXT,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    )
    """,
)


POSTGRES_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_koc_master_user_id ON koc_master(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_koc_master_youtube_user_id ON koc_master(youtube_user_id)",
    "CREATE INDEX IF NOT EXISTS idx_koc_master_tiktok_user_id ON koc_master(tiktok_user_id)",
    "CREATE INDEX IF NOT EXISTS idx_koc_master_name ON koc_master(koc_name)",
    "CREATE INDEX IF NOT EXISTS idx_koc_master_category ON koc_master(creator_category)",
    "CREATE INDEX IF NOT EXISTS idx_creator_contract_creator ON creator_contract(creator_id)",
    "CREATE INDEX IF NOT EXISTS idx_creator_contract_type ON creator_contract(contract_type)",
    "CREATE INDEX IF NOT EXISTS idx_creator_contract_period_lookup ON creator_contract_period(creator_id, start_date, end_date)",
    "CREATE INDEX IF NOT EXISTS idx_creator_contract_revision_creator ON creator_contract_revision(creator_id, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_creator_profile_history_uid_date ON creator_profile_history(user_id, effective_date)",
    "CREATE INDEX IF NOT EXISTS idx_dashboard_post_publish_date ON dashboard_post(publish_date)",
    "CREATE INDEX IF NOT EXISTS idx_dashboard_post_source_file ON dashboard_post(source_file)",
    "CREATE INDEX IF NOT EXISTS idx_dashboard_post_import_batch ON dashboard_post(import_batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_dashboard_import_snapshot_batch ON dashboard_import_batch_snapshot(batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_cross_industry_active ON dashboard_cross_industry_exclusion(active, platform)",
    "CREATE INDEX IF NOT EXISTS idx_follower_audit_user_time ON follower_update_audit(user_id, fetched_at)",
    "CREATE INDEX IF NOT EXISTS idx_compensation_version_period ON grassroot_compensation_version(period_month, version_no DESC)",
    "CREATE INDEX IF NOT EXISTS idx_long_term_activity_period ON long_term_compensation_activity(period_month, creator_id)",
    "CREATE INDEX IF NOT EXISTS idx_long_term_compensation_version_period ON long_term_compensation_version(period_month, version_no DESC)",
    "CREATE INDEX IF NOT EXISTS idx_commentary_validity_period_creator ON commentary_post_validity(period_month, creator_id)",
    "CREATE INDEX IF NOT EXISTS idx_commentary_theme_submission_period ON commentary_theme_submission(period_month, creator_id)",
    "CREATE INDEX IF NOT EXISTS idx_commentary_compensation_version_period ON commentary_compensation_version(period_month, version_no DESC)",
    "CREATE INDEX IF NOT EXISTS idx_ai_conversation_session ON ai_conversation(session_id, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_ai_message_conversation ON ai_message(conversation_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_ai_tool_audit_conversation ON ai_tool_audit(conversation_id, id DESC)",
)


# Forward-compatible repair for databases that were marked as v2 before the
# commentary theme tables were added. CREATE IF NOT EXISTS keeps this safe for
# both fresh databases and existing production databases.
POSTGRES_COMMENTARY_THEME_COMPAT_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS commentary_theme_definition (
        period_month TEXT NOT NULL,
        theme_code TEXT NOT NULL,
        theme_name TEXT NOT NULL,
        description TEXT,
        max_per_creator INTEGER NOT NULL DEFAULT 1 CHECK (max_per_creator > 0),
        reward_jpy BIGINT NOT NULL DEFAULT 15000 CHECK (reward_jpy >= 0),
        enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        PRIMARY KEY (period_month, theme_code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS commentary_theme_submission (
        id BIGSERIAL PRIMARY KEY,
        period_month TEXT NOT NULL,
        creator_id BIGINT NOT NULL REFERENCES koc_master(id) ON DELETE CASCADE,
        theme_code TEXT NOT NULL,
        content_format TEXT NOT NULL CHECK (content_format IN ('LONG', 'SHORT')),
        urls_json TEXT NOT NULL,
        submitted_date TEXT,
        review_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
            review_status IN ('PENDING', 'APPROVED', 'REJECTED')
        ),
        note TEXT,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
        UNIQUE (period_month, creator_id, theme_code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS commentary_theme_submission_revision (
        period_month TEXT PRIMARY KEY,
        revision TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    )
    """,
)

POSTGRES_COMMENTARY_THEME_COMPAT_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_commentary_theme_submission_period "
    "ON commentary_theme_submission(period_month, creator_id)",
)


POSTGRES_IMPORT_ROLLBACK_AND_LOCK_AUDIT_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS dashboard_import_batch_snapshot (
        id BIGSERIAL PRIMARY KEY,
        batch_id BIGINT NOT NULL REFERENCES dashboard_import_batch(id) ON DELETE CASCADE,
        record_key TEXT NOT NULL,
        source_file TEXT NOT NULL,
        publish_date TEXT,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    )
    """,
    "ALTER TABLE dashboard_import_batch ADD COLUMN IF NOT EXISTS rolled_back_at TEXT",
    "ALTER TABLE grassroot_compensation_version ADD COLUMN IF NOT EXISTS lock_note TEXT",
    "ALTER TABLE grassroot_compensation_version ADD COLUMN IF NOT EXISTS locked_by TEXT",
    "ALTER TABLE long_term_compensation_version ADD COLUMN IF NOT EXISTS lock_note TEXT",
    "ALTER TABLE long_term_compensation_version ADD COLUMN IF NOT EXISTS locked_by TEXT",
    "ALTER TABLE commentary_compensation_version ADD COLUMN IF NOT EXISTS lock_note TEXT",
    "ALTER TABLE commentary_compensation_version ADD COLUMN IF NOT EXISTS locked_by TEXT",
)

POSTGRES_IMPORT_ROLLBACK_AND_LOCK_AUDIT_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_dashboard_import_snapshot_batch "
    "ON dashboard_import_batch_snapshot(batch_id)",
)


JULY_COMMENTARY_THEMES = (
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


def _seed_default_creators(
    connection: Any,
    seed_records: Iterable[tuple[str, str]],
) -> None:
    count_row = connection.execute("SELECT COUNT(*) FROM koc_master").fetchone()
    if count_row is not None and int(count_row[0]) > 0:
        return
    records = tuple(seed_records)
    if not records:
        return
    connection.executemany(
        "INSERT INTO koc_master (user_id, koc_name) VALUES (?, ?)",
        records,
    )
    connection.executemany(
        """
        INSERT INTO koc_mapping (user_id, koc_name) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET koc_name = excluded.koc_name
        """,
        records,
    )


def apply_postgres_migrations(
    connection: Any,
    seed_records: Iterable[tuple[str, str]],
) -> None:
    """Create the PostgreSQL schema without running SQLite-only migrations."""
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtext('koc-dashboard-postgres-schema'))"
    )
    connection.execute(POSTGRES_SCHEMA_STATEMENTS[0])
    applied = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE migration_id = ?",
        (POSTGRES_SCHEMA_MIGRATION_ID,),
    ).fetchone()
    if applied is None:
        for statement in POSTGRES_SCHEMA_STATEMENTS[1:]:
            connection.execute(statement)
        for statement in POSTGRES_INDEX_STATEMENTS:
            connection.execute(statement)
        connection.executemany(
            """
            INSERT INTO commentary_theme_definition (
                period_month, theme_code, theme_name, description
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(period_month, theme_code) DO NOTHING
            """,
            JULY_COMMENTARY_THEMES,
        )
        connection.execute(
            "INSERT INTO schema_migrations (migration_id) VALUES (?)",
            (POSTGRES_SCHEMA_MIGRATION_ID,),
        )

    # Repair partially initialized v2 databases. This is deliberately a
    # separate forward migration because the original schema marker may exist
    # even when a later table addition was skipped during deployment.
    compat_applied = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE migration_id = ?",
        (POSTGRES_COMMENTARY_THEME_COMPAT_MIGRATION_ID,),
    ).fetchone()
    if compat_applied is None:
        for statement in POSTGRES_COMMENTARY_THEME_COMPAT_STATEMENTS:
            connection.execute(statement)
        for statement in POSTGRES_COMMENTARY_THEME_COMPAT_INDEX_STATEMENTS:
            connection.execute(statement)
        connection.executemany(
            """
            INSERT INTO commentary_theme_definition (
                period_month, theme_code, theme_name, description
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(period_month, theme_code) DO NOTHING
            """,
            JULY_COMMENTARY_THEMES,
        )
        connection.execute(
            "INSERT INTO schema_migrations (migration_id) VALUES (?)",
            (POSTGRES_COMMENTARY_THEME_COMPAT_MIGRATION_ID,),
        )

    forward_applied = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE migration_id = ?",
        (POSTGRES_IMPORT_ROLLBACK_AND_LOCK_AUDIT_MIGRATION_ID,),
    ).fetchone()
    if forward_applied is None:
        for statement in POSTGRES_IMPORT_ROLLBACK_AND_LOCK_AUDIT_STATEMENTS:
            connection.execute(statement)
        for statement in POSTGRES_IMPORT_ROLLBACK_AND_LOCK_AUDIT_INDEX_STATEMENTS:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations (migration_id) VALUES (?)",
            (POSTGRES_IMPORT_ROLLBACK_AND_LOCK_AUDIT_MIGRATION_ID,),
        )
    _seed_default_creators(connection, seed_records)
