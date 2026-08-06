from __future__ import annotations

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
    """Return a cache key that changes after a SQLite commit."""
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
    path = Path(database_path).resolve()
    state_key = f"dashboard_bootstrap:{path}"
    if state_key not in st.session_state:
        st.session_state[state_key] = ensure_dashboard_seeded(path, timezone)
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
