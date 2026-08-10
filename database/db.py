from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from core.koc_import import extract_basic_creator_records
from database.migrations import TIKTOK_BROWSER_MIGRATION_ID, apply_migrations
from database.postgres_schema import apply_postgres_migrations

try:
    import psycopg
    from psycopg_pool import ConnectionPool
except ImportError:  # PostgreSQL support is optional for existing local installs.
    psycopg = None
    ConnectionPool = None


SEED_FILE = Path(__file__).with_name("koc_seed.json")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_CREATOR_FILE = PROJECT_ROOT / "data" / "input" / "达人数据库.xlsx"


class ManagedConnection(sqlite3.Connection):
    """SQLite connection that commits or rolls back, then always closes."""

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc, traceback))
        finally:
            self.close()


class DatabaseRow:
    """Mapping-compatible row that also supports SQLite-style integer indexes."""

    def __init__(self, columns: Sequence[str], values: Sequence[Any]) -> None:
        self._columns = tuple(columns)
        self._values = tuple(values)
        self._mapping = dict(zip(self._columns, self._values, strict=True))

    def __getitem__(self, key: int | slice | str) -> Any:
        if isinstance(key, (int, slice)):
            return self._values[key]
        return self._mapping[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._columns)

    def __len__(self) -> int:
        return len(self._columns)

    def keys(self) -> tuple[str, ...]:
        return self._columns


def _postgres_row_factory(cursor: Any) -> Any:
    columns = tuple(column.name for column in (cursor.description or ()))

    def make_row(values: Sequence[Any]) -> DatabaseRow:
        return DatabaseRow(columns, values)

    return make_row


_POSTGRES_ID_TABLES = {
    "commentary_compensation_version",
    "ai_message",
    "ai_tool_audit",
    "commentary_theme_submission",
    "creator_contract",
    "creator_contract_period",
    "creator_contract_revision",
    "dashboard_cross_industry_exclusion",
    "dashboard_import_batch",
    "follower_update_audit",
    "grassroot_compensation_version",
    "koc_master",
    "long_term_compensation_version",
}
_INSERT_TABLE_PATTERN = re.compile(
    r'^\s*INSERT\s+INTO\s+"?([a-z_][a-z0-9_]*)"?',
    re.IGNORECASE,
)
_POSTGRES_POOLS: dict[str, Any] = {}
_POSTGRES_POOLS_LOCK = threading.Lock()


def is_postgres_target(database_path: Path | str) -> bool:
    value = str(database_path).strip().casefold()
    return value.startswith(("postgresql://", "postgres://", "postgresql+psycopg://"))


def normalize_database_target(database_path: Path | str) -> Path | str:
    value = str(database_path).strip()
    if is_postgres_target(value):
        return value
    return Path(database_path)


def _normalize_postgres_url(database_url: str) -> str:
    if database_url.casefold().startswith("postgresql+psycopg://"):
        return "postgresql://" + database_url.split("://", 1)[1]
    return database_url


def _translate_postgres_sql(sql: str, *, return_insert_id: bool) -> str:
    translated = sql.strip()
    insert_or_ignore = bool(
        re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", translated, re.IGNORECASE)
    )
    translated = re.sub(
        r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
        "INSERT INTO",
        translated,
        flags=re.IGNORECASE,
    )
    translated = re.sub(
        r"\bCURRENT_TIMESTAMP\b(?!\s*::text)",
        "CURRENT_TIMESTAMP::text",
        translated,
        flags=re.IGNORECASE,
    )
    translated = translated.replace("?", "%s")
    translated = translated.rstrip().rstrip(";")
    if insert_or_ignore and "ON CONFLICT" not in translated.upper():
        translated += " ON CONFLICT DO NOTHING"
    match = _INSERT_TABLE_PATTERN.match(translated)
    if (
        return_insert_id
        and match is not None
        and match.group(1).casefold() in _POSTGRES_ID_TABLES
        and "RETURNING" not in translated.upper()
    ):
        translated += " RETURNING id"
    return translated


class PostgresCursor:
    def __init__(self, cursor: Any, *, lastrowid: int | None = None) -> None:
        self._cursor = cursor
        self.lastrowid = lastrowid

    @property
    def rowcount(self) -> int:
        return int(self._cursor.rowcount)

    def fetchone(self) -> DatabaseRow | None:
        return self._cursor.fetchone()

    def fetchall(self) -> list[DatabaseRow]:
        return list(self._cursor.fetchall())


class PostgresManagedConnection:
    """Small DB-API compatibility layer used by the existing repositories."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self._connection = pool.getconn()
        self._closed = False

    def __enter__(self) -> "PostgresManagedConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        try:
            if exc_type is None:
                self._connection.commit()
            else:
                self._connection.rollback()
        finally:
            self.close()
        return False

    def execute(
        self,
        sql: str,
        parameters: Iterable[Any] | None = None,
    ) -> PostgresCursor:
        cursor = self._connection.cursor()
        translated = _translate_postgres_sql(sql, return_insert_id=True)
        cursor.execute(translated, tuple(parameters or ()))
        lastrowid = None
        if "RETURNING id" in translated:
            row = cursor.fetchone()
            if row is not None:
                lastrowid = int(row[0])
        return PostgresCursor(cursor, lastrowid=lastrowid)

    def executemany(
        self,
        sql: str,
        parameters: Iterable[Iterable[Any]],
    ) -> PostgresCursor:
        cursor = self._connection.cursor()
        translated = _translate_postgres_sql(sql, return_insert_id=False)
        cursor.executemany(translated, [tuple(row) for row in parameters])
        return PostgresCursor(cursor)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pool.putconn(self._connection)


def _postgres_pool(database_url: str) -> Any:
    if psycopg is None or ConnectionPool is None:
        raise RuntimeError(
            "PostgreSQL support requires psycopg. Run: pip install 'psycopg[binary,pool]'"
        )
    normalized = _normalize_postgres_url(database_url)
    with _POSTGRES_POOLS_LOCK:
        pool = _POSTGRES_POOLS.get(normalized)
        if pool is None:
            pool = ConnectionPool(
                conninfo=normalized,
                min_size=0,
                max_size=5,
                timeout=15,
                kwargs={
                    "row_factory": _postgres_row_factory,
                    "prepare_threshold": None,
                },
                # Liveness check before handing out a pooled connection, plus
                # bounded lifetime/idle recycling, so a stale/dropped server-side
                # connection is detected and replaced instead of surfacing as an
                # opaque failure on first use.
                check=ConnectionPool.check_connection,
                max_lifetime=1800.0,
                max_idle=300.0,
                open=True,
            )
            _POSTGRES_POOLS[normalized] = pool
        return pool


# Exceptions that indicate the underlying connection is dead/lost rather than
# a query-level error (bad SQL, constraint violation, etc.). These are the
# only errors eligible for the single bounded read-retry in the API layer.
if psycopg is None:
    CONNECTION_LOST_ERRORS: tuple[type[BaseException], ...] = ()
else:
    CONNECTION_LOST_ERRORS = (psycopg.OperationalError, psycopg.InterfaceError)


def sanitize_db_error_marker(exc: BaseException) -> str:
    """Return a safe, non-identifying marker for logging a DB error.

    Never returns str(exc): driver exceptions (e.g. psycopg connection
    errors) can embed the DSN, host, user, or SQL text. Only the exception
    class name is safe to log.
    """
    return type(exc).__name__


if psycopg is None:
    INTEGRITY_ERRORS = (sqlite3.IntegrityError,)
else:
    INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg.IntegrityError)


def _load_seed_records() -> tuple[tuple[str, str], ...]:
    with SEED_FILE.open("r", encoding="utf-8") as file:
        mapping = json.load(file)
    return tuple((str(user_id), str(koc_name)) for user_id, koc_name in mapping.items())


DEFAULT_KOCS = _load_seed_records()


def _load_input_creator_records() -> tuple[tuple[str, str, str | None], ...] | None:
    if not INPUT_CREATOR_FILE.exists():
        return None
    dataframe = pd.read_excel(INPUT_CREATOR_FILE, engine="openpyxl", dtype="object")
    return extract_basic_creator_records(dataframe)


def connect(database_path: Path | str) -> ManagedConnection | PostgresManagedConnection:
    if is_postgres_target(database_path):
        return PostgresManagedConnection(_postgres_pool(str(database_path)))
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, factory=ManagedConnection)
    connection.row_factory = sqlite3.Row
    return connection


def _needs_tiktok_browser_migration(database_path: Path) -> bool:
    if not database_path.exists() or database_path.stat().st_size == 0:
        return False
    connection = sqlite3.connect(database_path)
    try:
        has_master = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'koc_master'"
        ).fetchone()
        if has_master is None:
            return False
        has_migrations = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
        if has_migrations is None:
            return True
        applied = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE migration_id = ?",
            (TIKTOK_BROWSER_MIGRATION_ID,),
        ).fetchone()
        return applied is None
    finally:
        connection.close()


def backup_before_tiktok_browser_migration(
    database_path: Path | str,
) -> Path | None:
    if is_postgres_target(database_path):
        return None
    path = Path(database_path)
    if not _needs_tiktok_browser_migration(path):
        return None
    backup_dir = path.parent / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_dir / f"{path.stem}_before_tiktok_browser_{timestamp}.db"
    source = sqlite3.connect(path)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return backup_path


@lru_cache(maxsize=8)
def _init_db_once(database_target: str) -> None:
    if is_postgres_target(database_target):
        with connect(database_target) as connection:
            apply_postgres_migrations(connection, DEFAULT_KOCS)
        return
    database_path = Path(database_target)
    backup_before_tiktok_browser_migration(database_path)
    with connect(database_path) as connection:
        apply_migrations(
            connection,
            DEFAULT_KOCS,
            input_records=_load_input_creator_records(),
        )


def init_db(database_path: Path | str) -> None:
    """Initialize a database target once per application process."""
    normalized = normalize_database_target(database_path)
    target = str(normalized.resolve()) if isinstance(normalized, Path) else normalized
    _init_db_once(target)


def get_koc_mapping(
    database_path: Path | str,
    *,
    include_inactive: bool = False,
) -> dict[str, str]:
    init_db(database_path)
    with connect(database_path) as connection:
        query = "SELECT id, user_id, youtube_user_id, tiktok_user_id, koc_name FROM koc_master"
        if not include_inactive:
            query += " WHERE active = 1"
        query += " ORDER BY id"
        rows = connection.execute(query).fetchall()
        history_query = (
            "SELECT creator_id AS id, user_id, youtube_user_id, "
            "tiktok_user_id, koc_name FROM creator_profile_history"
        )
        if not include_inactive:
            history_query += " WHERE active = 1"
        history_query += " ORDER BY creator_id, effective_date DESC"
        history_rows = connection.execute(history_query).fetchall()
    mapping: dict[str, str] = {}
    for row in (*rows, *history_rows):
        for column in ("user_id", "youtube_user_id", "tiktok_user_id"):
            value = row[column]
            if value is not None and str(value).strip():
                mapping.setdefault(str(value).strip(), str(row["koc_name"]))
    return mapping
