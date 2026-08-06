from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import load_settings  # noqa: E402
from database.db import _normalize_postgres_url, is_postgres_target  # noqa: E402
from database.postgres_schema import (  # noqa: E402
    POSTGRES_INDEX_STATEMENTS,
    POSTGRES_SCHEMA_MIGRATION_ID,
    POSTGRES_SCHEMA_STATEMENTS,
)

try:
    import psycopg
    from psycopg import sql
except ImportError as exc:  # pragma: no cover - handled by requirements in production.
    raise SystemExit(
        "PostgreSQL migration requires psycopg. Install project requirements first."
    ) from exc


MIGRATION_TABLES = (
    "koc_mapping",
    "koc_master",
    "creator_contract",
    "creator_contract_period",
    "creator_contract_revision",
    "creator_profile_history",
    "dashboard_import_batch",
    "dashboard_post",
    "dashboard_cross_industry_exclusion",
    "dashboard_traffic_boost_setting",
    "follower_update_audit",
    "grassroot_compensation_contract_snapshot",
    "grassroot_compensation_setting",
    "grassroot_compensation_version",
    "long_term_compensation_activity",
    "long_term_compensation_version",
    "commentary_post_validity",
    "commentary_theme_definition",
    "commentary_theme_submission",
    "commentary_compensation_version",
)

SERIAL_TABLES = (
    "koc_master",
    "creator_contract",
    "creator_contract_period",
    "creator_contract_revision",
    "dashboard_import_batch",
    "dashboard_cross_industry_exclusion",
    "follower_update_audit",
    "grassroot_compensation_version",
    "long_term_compensation_version",
    "commentary_theme_submission",
    "commentary_compensation_version",
)


def _sqlite_connection(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _sqlite_columns(connection: sqlite3.Connection, table_name: str) -> tuple[str, ...]:
    return tuple(
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{table_name}")')
    )


def _postgres_columns(cursor: Any, table_name: str) -> tuple[str, ...]:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    )
    return tuple(str(row[0]) for row in cursor.fetchall())


def _table_exists(cursor: Any, table_name: str) -> bool:
    cursor.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
    return cursor.fetchone()[0] is not None


def _target_business_counts(cursor: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table_name in MIGRATION_TABLES:
        if not _table_exists(cursor, table_name):
            counts[table_name] = 0
            continue
        cursor.execute(
            sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table_name))
        )
        counts[table_name] = int(cursor.fetchone()[0])
    return counts


def _create_postgres_schema(cursor: Any) -> None:
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtext('koc-dashboard-sqlite-migration'))"
    )
    for statement in POSTGRES_SCHEMA_STATEMENTS:
        cursor.execute(statement)
    for statement in POSTGRES_INDEX_STATEMENTS:
        cursor.execute(statement)
    cursor.execute(
        """
        INSERT INTO schema_migrations (migration_id)
        VALUES (%s)
        ON CONFLICT(migration_id) DO NOTHING
        """,
        (POSTGRES_SCHEMA_MIGRATION_ID,),
    )


def _canonical_value(value: Any) -> Any:
    if isinstance(value, memoryview):
        return value.tobytes().hex()
    if isinstance(value, bytes):
        return value.hex()
    return value


def _rows_digest(rows: Iterable[Sequence[Any]]) -> str:
    digest = hashlib.sha256()
    canonical_rows = sorted(
        json.dumps(
            [_canonical_value(value) for value in row],
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        for row in rows
    )
    for row in canonical_rows:
        digest.update(row.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _copy_table(
    sqlite_connection: sqlite3.Connection,
    postgres_cursor: Any,
    table_name: str,
) -> tuple[int, str]:
    source_columns = _sqlite_columns(sqlite_connection, table_name)
    target_columns = _postgres_columns(postgres_cursor, table_name)
    if source_columns != target_columns:
        raise RuntimeError(
            f"Column mismatch for {table_name}: "
            f"SQLite={source_columns}, PostgreSQL={target_columns}"
        )

    source_rows = [
        tuple(row[column] for column in source_columns)
        for row in sqlite_connection.execute(f'SELECT * FROM "{table_name}"')
    ]
    if not source_rows:
        return 0, _rows_digest(())

    insert_columns = source_columns
    insert_rows = source_rows
    deferred_revisions: list[tuple[int, int]] = []
    if table_name == "creator_contract_revision":
        revision_index = source_columns.index("reverted_revision_id")
        id_index = source_columns.index("id")
        mutable_rows = []
        for source_row in source_rows:
            values = list(source_row)
            if values[revision_index] is not None:
                deferred_revisions.append(
                    (int(values[revision_index]), int(values[id_index]))
                )
                values[revision_index] = None
            mutable_rows.append(tuple(values))
        insert_rows = mutable_rows

    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table_name),
        sql.SQL(", ").join(sql.Identifier(column) for column in insert_columns),
        sql.SQL(", ").join(sql.Placeholder() for _ in insert_columns),
    )
    postgres_cursor.executemany(statement, insert_rows)

    for reverted_revision_id, record_id in deferred_revisions:
        postgres_cursor.execute(
            """
            UPDATE creator_contract_revision
            SET reverted_revision_id = %s
            WHERE id = %s
            """,
            (reverted_revision_id, record_id),
        )
    return len(source_rows), _rows_digest(source_rows)


def _reset_sequences(cursor: Any) -> None:
    for table_name in SERIAL_TABLES:
        cursor.execute(
            sql.SQL(
                """
                SELECT setval(
                    pg_get_serial_sequence(%s, 'id'),
                    COALESCE(MAX(id), 1),
                    COUNT(*) > 0
                )
                FROM {}
                """
            ).format(sql.Identifier(table_name)),
            (table_name,),
        )


def _verify_table(
    cursor: Any,
    table_name: str,
    columns: Sequence[str],
    expected_count: int,
    expected_digest: str,
) -> None:
    cursor.execute(
        sql.SQL("SELECT {} FROM {}").format(
            sql.SQL(", ").join(sql.Identifier(column) for column in columns),
            sql.Identifier(table_name),
        )
    )
    target_rows = cursor.fetchall()
    actual_count = len(target_rows)
    actual_digest = _rows_digest(target_rows)
    if actual_count != expected_count or actual_digest != expected_digest:
        raise RuntimeError(
            f"Verification failed for {table_name}: "
            f"expected {expected_count} rows, found {actual_count}"
        )


def migrate(sqlite_path: Path, database_url: str) -> dict[str, int]:
    if not sqlite_path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")
    if not is_postgres_target(database_url):
        raise ValueError("DATABASE_URL is not a PostgreSQL connection string.")

    with _sqlite_connection(sqlite_path) as sqlite_connection:
        integrity = sqlite_connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")

        with psycopg.connect(
            _normalize_postgres_url(database_url),
            connect_timeout=20,
            prepare_threshold=None,
        ) as postgres_connection:
            with postgres_connection.cursor() as cursor:
                existing_counts = _target_business_counts(cursor)
                populated = {
                    table_name: count
                    for table_name, count in existing_counts.items()
                    if count > 0
                }
                if populated:
                    details = ", ".join(
                        f"{table_name}={count}"
                        for table_name, count in sorted(populated.items())
                    )
                    raise RuntimeError(
                        "Target PostgreSQL database is not empty; migration stopped: "
                        + details
                    )

                _create_postgres_schema(cursor)
                copied_counts: dict[str, int] = {}
                digests: dict[str, str] = {}
                for table_name in MIGRATION_TABLES:
                    count, digest = _copy_table(
                        sqlite_connection,
                        cursor,
                        table_name,
                    )
                    copied_counts[table_name] = count
                    digests[table_name] = digest
                    print(f"COPIED {table_name}: {count}")

                _reset_sequences(cursor)
                for table_name in MIGRATION_TABLES:
                    _verify_table(
                        cursor,
                        table_name,
                        _sqlite_columns(sqlite_connection, table_name),
                        copied_counts[table_name],
                        digests[table_name],
                    )
                    print(f"VERIFIED {table_name}: {copied_counts[table_name]}")
                return copied_counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy the local koc.db business data to an empty PostgreSQL database."
    )
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        default=PROJECT_ROOT / "data" / "koc.db",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Required safety flag. Without it, no database changes are made.",
    )
    args = parser.parse_args()
    if not args.apply:
        parser.error("Add --apply after reviewing the configured DATABASE_URL.")

    settings = load_settings()
    counts = migrate(args.sqlite_path, str(settings.database_path))
    print(f"MIGRATION_COMPLETE tables={len(counts)} rows={sum(counts.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
