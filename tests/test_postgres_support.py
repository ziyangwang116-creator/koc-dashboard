from pathlib import Path

import socket

from database.db import (
    DatabaseRow,
    PostgresManagedConnection,
    _prefer_ipv4_for_supabase_pooler,
    _translate_postgres_sql,
    is_postgres_target,
    normalize_database_target,
)
from database.postgres_schema import (
    POSTGRES_SCHEMA_MIGRATION_ID,
    POSTGRES_SCHEMA_STATEMENTS,
    apply_postgres_migrations,
)


class _FakeCursor:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConnection:
    def __init__(self):
        self.executed = []
        self.batches = []

    def execute(self, sql, parameters=None):
        self.executed.append((sql, tuple(parameters or ())))
        normalized = " ".join(sql.split()).casefold()
        if "select 1 from schema_migrations" in normalized:
            return _FakeCursor(None)
        if "select count(*) from koc_master" in normalized:
            return _FakeCursor((0,))
        return _FakeCursor(None)

    def executemany(self, sql, parameters):
        self.batches.append((sql, tuple(tuple(row) for row in parameters)))
        return _FakeCursor(None)


class _RawCursor:
    rowcount = 1

    def __init__(self):
        self.sql = ""
        self.parameters = ()
        self._row = None

    def execute(self, sql, parameters):
        self.sql = sql
        self.parameters = parameters
        if "RETURNING id" in sql:
            self._row = DatabaseRow(("id",), (42,))

    def executemany(self, sql, parameters):
        self.sql = sql
        self.parameters = tuple(parameters)

    def fetchone(self):
        row, self._row = self._row, None
        return row

    def fetchall(self):
        return []


class _RawConnection:
    def __init__(self):
        self.cursor_instance = _RawCursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class _FakePool:
    def __init__(self):
        self.connection = _RawConnection()
        self.returned = None

    def getconn(self):
        return self.connection

    def putconn(self, connection):
        self.returned = connection


def test_postgres_target_detection_preserves_urls_and_local_paths():
    url = "postgresql://user:secret@example.test/postgres"

    assert is_postgres_target(url) is True
    assert is_postgres_target("postgres://user@example.test/postgres") is True
    assert is_postgres_target("postgresql+psycopg://user@example.test/postgres") is True
    assert is_postgres_target("data/koc.db") is False
    assert normalize_database_target(url) == url
    assert normalize_database_target("data/koc.db") == Path("data/koc.db")


def test_supabase_pooler_prefers_ipv4_without_replacing_tls_hostname(monkeypatch):
    calls = []

    def fake_getaddrinfo(host, port, *, family, type):
        calls.append((host, port, family, type))
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.9", port)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    resolved = _prefer_ipv4_for_supabase_pooler(
        "postgresql://user:secret@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
    )

    assert "aws-0-ap-southeast-1.pooler.supabase.com" in resolved
    assert "sslmode=require" in resolved
    assert "hostaddr=203.0.113.9" in resolved
    assert calls == [
        (
            "aws-0-ap-southeast-1.pooler.supabase.com",
            5432,
            socket.AF_INET,
            socket.SOCK_STREAM,
        )
    ]


def test_supabase_pooler_keeps_original_url_when_ipv4_resolution_fails(monkeypatch):
    url = "postgresql://user:secret@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"

    def failing_getaddrinfo(*args, **kwargs):
        raise OSError("DNS unavailable")

    monkeypatch.setattr(socket, "getaddrinfo", failing_getaddrinfo)

    assert _prefer_ipv4_for_supabase_pooler(url) == url


def test_non_supabase_database_urls_skip_ipv4_resolution(monkeypatch):
    def unexpected_getaddrinfo(*args, **kwargs):
        raise AssertionError("non-Supabase URLs must not resolve here")

    monkeypatch.setattr(socket, "getaddrinfo", unexpected_getaddrinfo)

    assert _prefer_ipv4_for_supabase_pooler(
        "postgresql://user:secret@db.example.test/postgres"
    ) == "postgresql://user:secret@db.example.test/postgres"


def test_database_row_matches_sqlite_row_access_patterns():
    row = DatabaseRow(("id", "name"), (7, "creator"))

    assert row[0] == 7
    assert row["name"] == "creator"
    assert row.keys() == ("id", "name")
    assert dict(row) == {"id": 7, "name": "creator"}


def test_sql_translation_handles_qmark_ignore_timestamp_and_lastrowid():
    translated = _translate_postgres_sql(
        """
        INSERT OR IGNORE INTO creator_contract_revision (
            creator_id, before_json, after_json, created_at
        ) VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """,
        return_insert_id=True,
    )

    assert "INSERT OR IGNORE" not in translated
    assert translated.count("%s") == 3
    assert "CURRENT_TIMESTAMP::text" in translated
    assert "ON CONFLICT DO NOTHING" in translated
    assert translated.endswith("RETURNING id")


def test_postgres_connection_preserves_lastrowid_and_transaction_semantics():
    pool = _FakePool()

    with PostgresManagedConnection(pool) as connection:
        cursor = connection.execute(
            "INSERT INTO koc_master (user_id, koc_name) VALUES (?, ?)",
            ("creator-1", "Creator One"),
        )

    assert cursor.lastrowid == 42
    assert pool.connection.cursor_instance.parameters == ("creator-1", "Creator One")
    assert pool.connection.committed is True
    assert pool.returned is pool.connection


def test_postgres_schema_covers_all_current_business_tables():
    schema = "\n".join(POSTGRES_SCHEMA_STATEMENTS)
    expected_tables = {
        "commentary_compensation_version",
        "commentary_post_validity",
        "commentary_theme_definition",
        "commentary_theme_submission",
        "creator_contract",
        "creator_contract_period",
        "creator_contract_revision",
        "creator_profile_history",
        "dashboard_cross_industry_exclusion",
        "dashboard_import_batch",
        "dashboard_post",
        "dashboard_traffic_boost_setting",
        "follower_update_audit",
        "grassroot_compensation_contract_snapshot",
        "grassroot_compensation_setting",
        "grassroot_compensation_version",
        "koc_mapping",
        "koc_master",
        "long_term_compensation_activity",
        "long_term_compensation_version",
        "schema_migrations",
        "ai_conversation",
        "ai_message",
        "ai_tool_audit",
    }

    for table_name in expected_tables:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in schema
    assert "AUTOINCREMENT" not in schema
    assert "PRAGMA" not in schema


def test_postgres_migration_is_transaction_friendly_and_seeds_defaults():
    connection = _FakeConnection()

    apply_postgres_migrations(connection, (("creator-1", "Creator One"),))

    executed_sql = "\n".join(sql for sql, _ in connection.executed)
    assert "pg_advisory_xact_lock" in executed_sql
    assert POSTGRES_SCHEMA_MIGRATION_ID in next(
        parameters
        for sql, parameters in connection.executed
        if "INSERT INTO schema_migrations" in sql
    )
    assert any("INSERT INTO koc_master" in sql for sql, _ in connection.batches)
