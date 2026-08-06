from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from core.koc_import import extract_basic_creator_records
from database.migrations import TIKTOK_BROWSER_MIGRATION_ID, apply_migrations


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


def connect(database_path: Path | str) -> sqlite3.Connection:
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


def init_db(database_path: Path | str) -> None:
    backup_before_tiktok_browser_migration(database_path)
    with connect(database_path) as connection:
        apply_migrations(
            connection,
            DEFAULT_KOCS,
            input_records=_load_input_creator_records(),
        )


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
