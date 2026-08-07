from __future__ import annotations

from datetime import timedelta
from typing import Callable

import pandas as pd
from fastapi import APIRouter

from core.dashboard_processor import build_dashboard_result, enrich_dashboard_creator_metadata
from database.dashboard_repository import DashboardRepository
from database.koc_repository import KOCRepository


def _load_enriched_posts(database_path) -> pd.DataFrame:
    dashboard_repository = DashboardRepository(database_path)
    creator_repository = KOCRepository(database_path)
    creator_records = creator_repository.list(include_inactive=True)
    profile_history = creator_repository.list_profile_history()

    loaded = build_dashboard_result(dashboard_repository.load_posts())
    enriched = enrich_dashboard_creator_metadata(loaded.data, creator_records, profile_history)
    result = build_dashboard_result(
        dashboard_repository.annotate_cross_industry_posts(enriched),
        loaded.file_reports,
    )
    return result.data, creator_records


def _unique_in_order(values) -> list[str]:
    seen: list[str] = []
    for value in values:
        if pd.isna(value):
            continue
        text = str(value)
        if text not in seen:
            seen.append(text)
    return seen


def _build_creators(data: pd.DataFrame) -> list[dict]:
    if "creator_key" not in data.columns:
        return []
    subset = data[["creator_key", "creator_label"]].dropna(subset=["creator_key"])
    subset = subset.drop_duplicates(subset="creator_key").sort_values("creator_key")
    return [
        {"creator_key": row["creator_key"], "creator_label": row.get("creator_label") or ""}
        for _, row in subset.iterrows()
    ]


def _build_creator_categories(data: pd.DataFrame, creator_records) -> list[str]:
    if "creator_id" not in data.columns:
        return []
    creator_ids = {
        int(value)
        for value in data["creator_id"].dropna().unique()
    }
    records_by_id = {record.id: record for record in creator_records}
    categories: set[str] = set()
    for creator_id in creator_ids:
        record = records_by_id.get(creator_id)
        if record is None:
            continue
        for category in record.creator_categories:
            categories.add(category.value)
    return sorted(categories)


def _build_available_months(data: pd.DataFrame) -> list[str]:
    if "publish_date" not in data.columns:
        return []
    dates = pd.to_datetime(data["publish_date"], errors="coerce").dropna()
    if dates.empty:
        return []
    return sorted(dates.dt.strftime("%Y-%m").unique().tolist())


def _build_available_weeks(data: pd.DataFrame) -> list[dict]:
    if "publish_date" not in data.columns:
        return []
    dates = pd.to_datetime(data["publish_date"], errors="coerce").dropna()
    if dates.empty:
        return []
    week_starts = sorted({(value - timedelta(days=value.weekday())).date() for value in dates})
    return [
        {
            "week_start": week_start.isoformat(),
            "week_end": (week_start + timedelta(days=6)).isoformat(),
        }
        for week_start in week_starts
    ]


def build_dashboard_router(*, database_path, require_session: Callable) -> APIRouter:
    router = APIRouter(dependencies=[require_session])

    @router.get("/api/dashboard/filter-options")
    def filter_options() -> dict:
        data, creator_records = _load_enriched_posts(database_path)
        return {
            "data": {
                "creators": _build_creators(data),
                "creator_categories": _build_creator_categories(data, creator_records),
                "source_platforms": _unique_in_order(data.get("source_platform", [])),
                "content_types": _unique_in_order(data.get("content_type", [])),
                "available_months": _build_available_months(data),
                "available_weeks": _build_available_weeks(data),
            }
        }

    return router
