from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

from core.dashboard_bootstrap import DashboardBootstrapResult, ensure_dashboard_seeded
from core.dashboard_processor import (
    DashboardResult,
    build_dashboard_result,
    enrich_dashboard_creator_metadata,
)
from database.dashboard_repository import DashboardRepository
from database.db import connect, is_postgres_target
from database.koc_repository import KOCRepository
from models.koc import CreatorProfileSnapshot, KOCRecord


DatabaseCacheToken = tuple[tuple[str, int, int], ...]


def _file_state(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return (str(path.resolve()), -1, -1)
    return (str(path.resolve()), stat.st_mtime_ns, stat.st_size)


def dashboard_cache_token(database_path: Path | str) -> DatabaseCacheToken:
    """Return a cache key that changes after a database commit."""
    if is_postgres_target(database_path):
        digest = hashlib.sha256()
        total_count = 0
        tracked_tables = (
            ("dashboard_post", "updated_at"),
            ("koc_master", "updated_at"),
            ("creator_contract", "updated_at"),
            ("creator_profile_history", "updated_at"),
            ("creator_contract_period", "updated_at"),
            ("dashboard_cross_industry_exclusion", "updated_at"),
            ("dashboard_traffic_boost_setting", "updated_at"),
        )
        revision_query = " UNION ALL ".join(
            f"SELECT '{table_name}' AS table_name, COUNT(*) AS row_count, "
            f"COALESCE(MAX({timestamp_column}), '') AS latest_update "
            f"FROM {table_name}"
            for table_name, timestamp_column in tracked_tables
        )
        with connect(database_path) as connection:
            rows = connection.execute(revision_query).fetchall()
        for row in rows:
            table_name = str(row[0])
            count = int(row[1])
            timestamp = str(row[2])
            total_count += count
            digest.update(f"{table_name}:{count}:{timestamp}".encode("utf-8"))
        target_hash = hashlib.sha256(str(database_path).encode("utf-8")).hexdigest()[:16]
        revision = int.from_bytes(digest.digest()[:8], "big", signed=False)
        return ((f"postgres:{target_hash}", total_count, revision),)
    path = Path(database_path)
    return tuple(
        _file_state(candidate)
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
    )


def ensure_dashboard_seeded_once(
    database_path: Path | str,
    timezone: str,
) -> DashboardBootstrapResult:
    """Seed a new local database at most once during a browser session."""
    target = (
        str(database_path)
        if is_postgres_target(database_path)
        else str(Path(database_path).resolve())
    )
    target_key = hashlib.sha256(target.encode("utf-8")).hexdigest()[:16]
    state_key = f"dashboard_bootstrap:{target_key}"
    if state_key not in st.session_state:
        st.session_state[state_key] = ensure_dashboard_seeded(database_path, timezone)
    return st.session_state[state_key]


@st.cache_data(show_spinner=False)
def load_prepared_dashboard_data(
    database_path: str,
    database_state: DatabaseCacheToken,
    include_inactive: bool,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    list[KOCRecord],
    list[CreatorProfileSnapshot],
]:
    """Load and enrich persisted dashboard rows once per database revision."""
    del database_state  # It is intentionally part of Streamlit's cache key.
    dashboard_repository = DashboardRepository(database_path)
    creator_repository = KOCRepository(database_path)
    creator_records = creator_repository.list(include_inactive=include_inactive)
    profile_history = creator_repository.list_profile_history()
    loaded = build_dashboard_result(dashboard_repository.load_posts())
    enriched = enrich_dashboard_creator_metadata(
        loaded.data,
        creator_records,
        profile_history,
    )
    result = build_dashboard_result(
        dashboard_repository.annotate_cross_industry_posts(enriched),
        loaded.file_reports,
    )
    return (
        result.data,
        result.file_reports,
        result.unmatched_uids,
        creator_records,
        profile_history,
    )


def prepared_dashboard_result(
    data: pd.DataFrame,
    file_reports: pd.DataFrame,
    unmatched_uids: pd.DataFrame,
) -> DashboardResult:
    return DashboardResult(
        data=data,
        file_reports=file_reports,
        unmatched_uids=unmatched_uids,
    )
