from __future__ import annotations

import json
import threading
from datetime import timedelta
from typing import Callable

import pandas as pd
from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, Field

from core.dashboard_processor import (
    build_creator_summary,
    build_dashboard_result,
    build_dimension_summary,
    enrich_dashboard_creator_metadata,
)
from database.dashboard_repository import DashboardRepository
from database.cache_token import DatabaseCacheToken, dashboard_cache_token
from database.db import connect, init_db
from database.koc_repository import KOCRepository
from ui.dashboard import (
    _platform_posts,
    _platform_top_ranking,
    _platform_video_top_ranking,
    _rank_creator_summary,
)

from api.dashboard_support import (
    apply_common_pipeline,
    creator_category_lookup,
    creator_keys_for_categories,
    parse_period,
    split_contract_types,
    validate_creator_categories,
    validate_traffic_boost_mode,
    validation_error,
    view_sum_columns,
)

MAX_PAGE_SIZE = 100
SUMMARY_SORT_WHITELIST = {"total_views", "-total_views", "engagement_rate", "-engagement_rate", "koc_name", "-koc_name"}
POSTS_SORT_WHITELIST = {"publish_date", "-publish_date", "views", "-views"}
RANKING_TYPES = {
    "creator_views_top10",
    "creator_posts_top10",
    "creator_ytb_top30",
    "creator_tt_top30",
    "video_ytb_top20",
    "video_tt_top20",
}
COMPARISON_DIMENSIONS = {"platform", "content_type", "creator_category", "creator"}
COMPARISON_METRICS = {"total_views", "post_count", "engagement_rate"}
CREATOR_BREAKDOWN_TYPES = (
    ("long", "long"),
    ("livestream", "livestream"),
    ("shorts", "ytb shorts"),
    ("tiktok", "tiktok"),
)

_PREPARED_DATA_LOCK = threading.RLock()
_PREPARED_DATA_CACHE: dict[
    tuple[str, DatabaseCacheToken], tuple[pd.DataFrame, list]
] = {}


def _load_enriched_posts(database_path) -> tuple[pd.DataFrame, list]:
    # A dashboard page issues several heavy reads in parallel. Build the shared
    # enriched frame once per database revision instead of re-reading and
    # normalizing every persisted post for each endpoint.
    target = str(database_path)
    token = dashboard_cache_token(database_path)
    cache_key = (target, token)
    with _PREPARED_DATA_LOCK:
        cached = _PREPARED_DATA_CACHE.get(cache_key)
        if cached is not None:
            return cached

        dashboard_repository = DashboardRepository(database_path)
        creator_repository = KOCRepository(database_path)
        creator_records = creator_repository.list(include_inactive=True)
        profile_history = creator_repository.list_profile_history()

        loaded = build_dashboard_result(dashboard_repository.load_posts())
        enriched = enrich_dashboard_creator_metadata(
            loaded.data, creator_records, profile_history
        )
        result = build_dashboard_result(
            dashboard_repository.annotate_cross_industry_posts(enriched),
            loaded.file_reports,
        )
        prepared = (result.data, creator_records)
        _PREPARED_DATA_CACHE.clear()
        _PREPARED_DATA_CACHE[cache_key] = prepared
        return prepared


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


def _serialize_summary_row(row: pd.Series) -> dict:
    return {
        "creator_key": row.get("creator_key"),
        "user_id": row.get("user_id"),
        "creator_label": row.get("creator_label"),
        "creator_category": row.get("_creator_category_value"),
        "contract_types": split_contract_types(row.get("contract_types")),
        "follower_count": _none_if_na(row.get("follower_count")),
        "source_platforms": [
            value for value in str(row.get("source_platforms") or "").split("、") if value
        ],
        "post_count": int(row.get("post_count") or 0),
        "view": int(row.get("view") or 0),
        "original_views": int(row.get("original_views") or 0),
        "traffic_boost_views": int(row.get("traffic_boost_views") or 0),
        "boosted_views": int(row.get("boosted_views") or 0),
        "total_views": int(row.get("total_views") or 0),
        "average_views": int(row.get("average_views") or 0),
        "max_views": int(row.get("max_views") or 0),
        "total_likes": int(row.get("total_likes") or 0),
        "total_comments": int(row.get("total_comments") or 0),
        "total_reposts": int(row.get("total_reposts") or 0),
        "total_collects": int(row.get("total_collects") or 0),
        "total_interactions": int(row.get("total_interactions") or 0),
        "engagement_rate": _none_if_na(row.get("engagement_rate")),
        "earliest_date": _date_str(row.get("earliest_date")),
        "latest_date": _date_str(row.get("latest_date")),
    }


def _none_if_na(value):
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA:
        return None
    return value


def _date_str(value):
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def _serialize_post_row(row: pd.Series) -> dict:
    return {
        "source_file": _none_if_na(row.get("source_file")),
        "creator_key": row.get("creator_key"),
        "user_id": row.get("user_id"),
        "creator_id": _none_if_na(row.get("creator_id")),
        "creator_active": bool(row.get("creator_active")),
        "profile_effective_date": _date_str(row.get("profile_effective_date")),
        "koc_name": row.get("koc_name"),
        "creator_label": _none_if_na(row.get("creator_label")),
        "kol_name": _none_if_na(row.get("kol_name")),
        "creator_category": row.get("_creator_category_value"),
        "contract_types": split_contract_types(row.get("contract_types")),
        "contract_start_date": _date_str(row.get("contract_start_date")),
        "contract_end_date": _date_str(row.get("contract_end_date")),
        "follower_count": _none_if_na(row.get("follower_count")),
        "homepage_url": _none_if_na(row.get("homepage_url")),
        "youtube_user_id": _none_if_na(row.get("youtube_user_id")),
        "youtube_homepage_url": _none_if_na(row.get("youtube_homepage_url")),
        "youtube_follower_count": _none_if_na(row.get("youtube_follower_count")),
        "tiktok_user_id": _none_if_na(row.get("tiktok_user_id")),
        "tiktok_homepage_url": _none_if_na(row.get("tiktok_homepage_url")),
        "tiktok_follower_count": _none_if_na(row.get("tiktok_follower_count")),
        "source_platform": row.get("source_platform"),
        "content_type": row.get("content_type"),
        "subtype": row.get("subtype"),
        "description": _none_if_na(row.get("description")),
        "timestamp": _none_if_na(row.get("timestamp")),
        "title": row.get("title"),
        "url": row.get("url"),
        "publish_date": _date_str(row.get("publish_date")),
        "view": int(pd.to_numeric(row.get("view"), errors="coerce") or 0),
        "original_views": int(pd.to_numeric(row.get("original_views"), errors="coerce") or 0),
        "traffic_boost_views": int(pd.to_numeric(row.get("traffic_boost_views"), errors="coerce") or 0),
        "boosted_views": int(pd.to_numeric(row.get("boosted_views"), errors="coerce") or 0),
        "views": int(pd.to_numeric(row.get("views"), errors="coerce") or 0),
        "likes": _none_if_na(row.get("likes")),
        "comment": _none_if_na(row.get("comment")),
        "reposted": _none_if_na(row.get("reposted")),
        "collect": _none_if_na(row.get("collect")),
        "cross_industry_url_key": _none_if_na(row.get("cross_industry_url_key")),
        "matched": bool(row.get("matched")),
        "profile_status": row.get("profile_status"),
        "is_cross_industry": bool(row.get("is_cross_industry")),
        "compensation_eligible": bool(row.get("compensation_eligible")),
        "cross_industry_reason": row.get("cross_industry_reason") or None,
        "cross_industry_exclusion_id": _none_if_na(
            row.get("cross_industry_exclusion_id")
        ),
    }


def _filter_creator_records(creator_records, creator_key, creator_category):
    category_keys = creator_keys_for_categories(creator_category, creator_records)
    if creator_key:
        effective_keys = set(creator_key)
        if category_keys is not None:
            effective_keys &= category_keys
    elif category_keys is not None:
        effective_keys = category_keys
    else:
        return list(creator_records)
    return [record for record in creator_records if record.user_id in effective_keys]


def _attach_creator_category(data: pd.DataFrame, creator_records) -> pd.DataFrame:
    lookup = creator_category_lookup(creator_records)
    prepared = data.copy()
    if "creator_key" in prepared.columns:
        prepared["_creator_category_value"] = prepared["creator_key"].map(lookup)
    else:
        prepared["_creator_category_value"] = None
    return prepared


class ComparisonPeriod(BaseModel):
    period_mode: str
    period_month: str | None = None
    week_start: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class ComparisonRequest(BaseModel):
    periods: list[ComparisonPeriod] = Field(default_factory=list)
    dimension: str
    metric: str = "total_views"
    creator_key: list[str] = Field(default_factory=list)
    creator_category: list[str] = Field(default_factory=list)
    source_platform: list[str] = Field(default_factory=list)
    content_type: list[str] = Field(default_factory=list)
    include_cross_industry: bool = False
    traffic_boost_mode: str = "saved_setting"


def _group_metric_table(data: pd.DataFrame, dimension: str, creator_records) -> pd.DataFrame:
    if dimension == "creator":
        table = build_creator_summary(data, creator_records)
        if table.empty:
            return pd.DataFrame(columns=["group_key", "group_label", "total_views", "post_count", "engagement_rate"])
        table = table.rename(columns={"creator_key": "group_key", "creator_label": "group_label"})
        return table

    column_map = {
        "platform": "source_platform",
        "content_type": "content_type",
        "creator_category": "creator_category",
    }
    column = column_map[dimension]
    table = build_dimension_summary(data, column)
    if table.empty:
        return pd.DataFrame(columns=["group_key", "group_label", "total_views", "post_count", "engagement_rate"])
    table = table.rename(columns={column: "group_key"})
    table["group_key"] = table["group_key"].fillna("未分类").astype(str)
    table["group_label"] = table["group_key"]
    table["engagement_rate"] = table["total_interactions"].div(
        table["total_views"].where(table["total_views"] > 0)
    )
    return table


def _metric_value(row: pd.Series | None, metric: str):
    if row is None:
        return 0
    if metric == "post_count":
        return int(row.get("post_count") or 0)
    if metric == "engagement_rate":
        value = row.get("engagement_rate")
        return None if value is None or pd.isna(value) else float(value)
    return int(row.get("total_views") or 0)


def _change_rate(points: list[dict]) -> tuple[float | None, bool]:
    if not points:
        return None, False
    earliest = points[0]["value"]
    latest = points[-1]["value"]
    if earliest is None or latest is None or not earliest:
        return None, False
    rate = (latest - earliest) / earliest
    return rate, rate <= -0.3


def _creator_breakdown_points(period_frames: list[pd.DataFrame], creator_key: str, period_labels: list[str]) -> dict:
    breakdown = {}
    for key, content_type in CREATOR_BREAKDOWN_TYPES:
        points = []
        for frame, label in zip(period_frames, period_labels):
            if frame.empty or "creator_key" not in frame.columns:
                points.append({"period_label": label, "value": 0, "post_count": 0})
                continue
            subset = frame.loc[
                frame["creator_key"].eq(creator_key)
                & frame["content_type"].astype("string").str.casefold().eq(content_type)
            ]
            views = int(pd.to_numeric(subset.get("views"), errors="coerce").fillna(0).sum())
            points.append({"period_label": label, "value": views, "post_count": int(len(subset))})
        rate, warning = _change_rate(points)
        post_count_points = [
            {**point, "value": point["post_count"]} for point in points
        ]
        post_count_rate, post_count_warning = _change_rate(post_count_points)
        breakdown[key] = {
            "points": points,
            "change_rate": rate,
            "warning": warning,
            "post_count_change_rate": post_count_rate,
            "post_count_warning": post_count_warning,
        }
    return breakdown


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

    def _resolve_period(period_mode, period_month, week_start, start_date, end_date):
        return parse_period(
            period_mode,
            period_month=period_month,
            week_start=week_start,
            start_date=start_date,
            end_date=end_date,
        )

    def _scoped_data(
        *,
        period_mode,
        period_month,
        week_start,
        start_date,
        end_date,
        creator_key,
        creator_category,
        source_platform,
        content_type,
        include_cross_industry,
        traffic_boost_mode,
    ):
        validate_creator_categories(creator_category)
        validate_traffic_boost_mode(traffic_boost_mode)
        range_start, range_end, _label, boost_month = _resolve_period(
            period_mode, period_month, week_start, start_date, end_date
        )
        data, creator_records = _load_enriched_posts(database_path)
        scoped = apply_common_pipeline(
            data,
            creator_records,
            start_date=range_start,
            end_date=range_end,
            creator_key=creator_key,
            creator_category=creator_category,
            source_platform=source_platform,
            content_type=content_type,
            include_cross_industry=include_cross_industry,
            traffic_boost_mode=traffic_boost_mode,
            boost_month=boost_month,
            database_path=database_path,
        )
        return _attach_creator_category(scoped, creator_records), creator_records

    @router.get("/api/dashboard/summary")
    def summary(
        period_mode: str | None = Query(default=None),
        period_month: str | None = Query(default=None),
        week_start: str | None = Query(default=None),
        start_date: str | None = Query(default=None),
        end_date: str | None = Query(default=None),
        creator_key: list[str] | None = Query(default=None),
        creator_category: list[str] | None = Query(default=None),
        source_platform: list[str] | None = Query(default=None),
        content_type: list[str] | None = Query(default=None),
        include_cross_industry: bool = Query(default=False),
        traffic_boost_mode: str = Query(default="saved_setting"),
        q: str = Query(default=""),
        page: int = Query(default=1),
        page_size: int = Query(default=20),
        sort: str = Query(default="-total_views"),
    ) -> dict:
        if sort not in SUMMARY_SORT_WHITELIST:
            raise validation_error(f"无效的 sort 取值：{sort}", "sort")
        if page < 1:
            raise validation_error("page 必须大于等于 1。", "page")
        if page_size < 1 or page_size > MAX_PAGE_SIZE:
            raise validation_error(f"page_size 必须在 1 到 {MAX_PAGE_SIZE} 之间。", "page_size")

        data, creator_records = _scoped_data(
            period_mode=period_mode,
            period_month=period_month,
            week_start=week_start,
            start_date=start_date,
            end_date=end_date,
            creator_key=creator_key,
            creator_category=creator_category,
            source_platform=source_platform,
            content_type=content_type,
            include_cross_industry=include_cross_industry,
            traffic_boost_mode=traffic_boost_mode,
        )

        roster = _filter_creator_records(creator_records, creator_key, creator_category)
        creator_summary = build_creator_summary(data, roster)
        if not creator_summary.empty:
            creator_summary = _attach_creator_category(creator_summary, creator_records)
            view_sums = view_sum_columns(data, "creator_key")
            creator_summary = creator_summary.merge(view_sums, on="creator_key", how="left")
            for column in ("view", "original_views", "traffic_boost_views", "boosted_views"):
                creator_summary[column] = pd.to_numeric(
                    creator_summary[column], errors="coerce"
                ).fillna(0)

        query = q.strip().casefold()
        if query and not creator_summary.empty:
            mask = (
                creator_summary["creator_label"].astype("string").str.casefold().str.contains(query, regex=False, na=False)
                | creator_summary["user_id"].astype("string").str.casefold().str.contains(query, regex=False, na=False)
            )
            creator_summary = creator_summary.loc[mask]

        reverse = sort.startswith("-")
        sort_field = sort[1:] if reverse else sort
        if not creator_summary.empty:
            creator_summary = creator_summary.sort_values(sort_field, ascending=not reverse, kind="stable")

        rows = [_serialize_summary_row(row) for _, row in creator_summary.iterrows()]
        total_items = len(rows)
        total_pages = max(1, (total_items + page_size - 1) // page_size)
        start = (page - 1) * page_size
        page_rows = rows[start : start + page_size]

        return {
            "data": page_rows,
            "meta": {
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_items": total_items,
                    "total_pages": total_pages,
                }
            },
        }

    @router.get("/api/dashboard/posts")
    def posts(
        period_mode: str | None = Query(default=None),
        period_month: str | None = Query(default=None),
        week_start: str | None = Query(default=None),
        start_date: str | None = Query(default=None),
        end_date: str | None = Query(default=None),
        creator_key: list[str] | None = Query(default=None),
        creator_category: list[str] | None = Query(default=None),
        source_platform: list[str] | None = Query(default=None),
        content_type: list[str] | None = Query(default=None),
        include_cross_industry: bool = Query(default=False),
        traffic_boost_mode: str = Query(default="saved_setting"),
        q: str = Query(default=""),
        page: int = Query(default=1),
        page_size: int = Query(default=20),
        sort: str = Query(default="-publish_date"),
    ) -> dict:
        if sort not in POSTS_SORT_WHITELIST:
            raise validation_error(f"无效的 sort 取值：{sort}", "sort")
        if page < 1:
            raise validation_error("page 必须大于等于 1。", "page")
        if page_size < 1 or page_size > MAX_PAGE_SIZE:
            raise validation_error(f"page_size 必须在 1 到 {MAX_PAGE_SIZE} 之间。", "page_size")

        data, _creator_records = _scoped_data(
            period_mode=period_mode,
            period_month=period_month,
            week_start=week_start,
            start_date=start_date,
            end_date=end_date,
            creator_key=creator_key,
            creator_category=creator_category,
            source_platform=source_platform,
            content_type=content_type,
            include_cross_industry=include_cross_industry,
            traffic_boost_mode=traffic_boost_mode,
        )

        query = q.strip().casefold()
        if query and not data.empty:
            mask = data["title"].astype("string").str.casefold().str.contains(query, regex=False, na=False)
            data = data.loc[mask]

        reverse = sort.startswith("-")
        sort_field = sort[1:] if reverse else sort
        if not data.empty:
            data = data.sort_values(sort_field, ascending=not reverse, kind="stable")

        rows = [_serialize_post_row(row) for _, row in data.iterrows()]
        total_items = len(rows)
        total_pages = max(1, (total_items + page_size - 1) // page_size)
        start = (page - 1) * page_size
        page_rows = rows[start : start + page_size]

        return {
            "data": page_rows,
            "meta": {
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_items": total_items,
                    "total_pages": total_pages,
                }
            },
        }

    @router.post("/api/dashboard/comparison")
    def comparison(payload: ComparisonRequest) -> dict:
        if len(payload.periods) < 2:
            raise validation_error("periods 至少需要提供两个周期。", "periods")
        if payload.dimension not in COMPARISON_DIMENSIONS:
            raise validation_error(f"无效的 dimension 取值：{payload.dimension}", "dimension")
        if payload.metric not in COMPARISON_METRICS:
            raise validation_error(f"无效的 metric 取值：{payload.metric}", "metric")
        validate_creator_categories(payload.creator_category)
        validate_traffic_boost_mode(payload.traffic_boost_mode)

        all_data, creator_records = _load_enriched_posts(database_path)

        period_frames: list[pd.DataFrame] = []
        period_labels: list[str] = []
        for period in payload.periods:
            range_start, range_end, label, boost_month = parse_period(
                period.period_mode,
                period_month=period.period_month,
                week_start=period.week_start,
                start_date=period.start_date,
                end_date=period.end_date,
            )
            scoped = apply_common_pipeline(
                all_data,
                creator_records,
                start_date=range_start,
                end_date=range_end,
                creator_key=payload.creator_key,
                creator_category=payload.creator_category,
                source_platform=payload.source_platform,
                content_type=payload.content_type,
                include_cross_industry=payload.include_cross_industry,
                traffic_boost_mode=payload.traffic_boost_mode,
                boost_month=boost_month,
                database_path=database_path,
            )
            period_frames.append(scoped)
            period_labels.append(label)

        group_tables = [
            _group_metric_table(frame, payload.dimension, creator_records) for frame in period_frames
        ]

        all_keys: dict[str, str] = {}
        for table in group_tables:
            for _, row in table.iterrows():
                all_keys.setdefault(row["group_key"], row["group_label"])

        series = []
        for group_key, group_label in all_keys.items():
            points = []
            for table, label in zip(group_tables, period_labels):
                if table.empty:
                    points.append({"period_label": label, "value": 0, "post_count": 0})
                    continue
                match = table.loc[table["group_key"] == group_key]
                row = match.iloc[0] if not match.empty else None
                points.append(
                    {
                        "period_label": label,
                        "value": _metric_value(row, payload.metric),
                        "post_count": int(row.get("post_count") or 0) if row is not None else 0,
                    }
                )
            rate, warning = _change_rate(points)
            entry = {
                "group_key": group_key,
                "group_label": group_label,
                "points": points,
                "change_rate": rate,
                "warning": warning,
            }
            if payload.dimension == "creator":
                entry["breakdown"] = _creator_breakdown_points(period_frames, group_key, period_labels)
            series.append(entry)

        return {
            "data": {
                "dimension": payload.dimension,
                "metric": payload.metric,
                "series": series,
            }
        }

    @router.get("/api/dashboard/rankings")
    def rankings(
        ranking_type: str = Query(...),
        period_mode: str | None = Query(default=None),
        period_month: str | None = Query(default=None),
        week_start: str | None = Query(default=None),
        start_date: str | None = Query(default=None),
        end_date: str | None = Query(default=None),
        creator_key: list[str] | None = Query(default=None),
        creator_category: list[str] | None = Query(default=None),
        source_platform: list[str] | None = Query(default=None),
        content_type: list[str] | None = Query(default=None),
        include_cross_industry: bool = Query(default=False),
        traffic_boost_mode: str = Query(default="saved_setting"),
    ) -> dict:
        if ranking_type not in RANKING_TYPES:
            raise validation_error(f"无效的 ranking_type 取值：{ranking_type}", "ranking_type")

        data, creator_records = _scoped_data(
            period_mode=period_mode,
            period_month=period_month,
            week_start=week_start,
            start_date=start_date,
            end_date=end_date,
            creator_key=creator_key,
            creator_category=creator_category,
            source_platform=source_platform,
            content_type=content_type,
            include_cross_industry=include_cross_industry,
            traffic_boost_mode=traffic_boost_mode,
        )
        category_lookup = creator_category_lookup(creator_records)

        if ranking_type in ("creator_views_top10", "creator_posts_top10"):
            metric = "total_views" if ranking_type == "creator_views_top10" else "post_count"
            ranked = _rank_creator_summary(data, metric, limit=10, creator_records=creator_records)
            items = [
                {
                    "rank": index + 1,
                    "creator_key": row.get("creator_key"),
                    "creator_label": row.get("creator_label"),
                    "creator_category": category_lookup.get(row.get("creator_key")),
                    "total_views": int(row.get("total_views") or 0),
                    "post_count": int(row.get("post_count") or 0),
                }
                for index, (_, row) in enumerate(ranked.iterrows())
            ]
        elif ranking_type in ("creator_ytb_top30", "creator_tt_top30"):
            platform = "ytb" if ranking_type == "creator_ytb_top30" else "tt"
            ranked = _platform_top_ranking(data, platform, "total_views")
            items = [
                {
                    "rank": index + 1,
                    "creator_key": row.get("creator_key"),
                    "creator_label": row.get("creator_label"),
                    "creator_category": category_lookup.get(row.get("creator_key")),
                    "total_views": int(row.get("total_views") or 0),
                    "post_count": int(row.get("post_count") or 0),
                }
                for index, (_, row) in enumerate(ranked.iterrows())
            ]
        else:
            platform = "ytb" if ranking_type == "video_ytb_top20" else "tt"
            ranked = _platform_video_top_ranking(data, platform, limit=20)
            items = [
                {
                    "rank": index + 1,
                    "creator_key": row.get("creator_key"),
                    "creator_label": row.get("creator_label"),
                    "title": row.get("title"),
                    "url": row.get("url"),
                    "publish_date": _date_str(row.get("publish_date")),
                    "views": int(pd.to_numeric(row.get("views"), errors="coerce") or 0),
                }
                for index, (_, row) in enumerate(ranked.iterrows())
            ]

        return {"data": {"ranking_type": ranking_type, "items": items}}

    @router.get("/api/dashboard/import-batches")
    def import_batches(limit: int = Query(default=30)) -> dict:
        if limit < 1 or limit > 200:
            raise validation_error("limit 必须在 1 到 200 之间。", "limit")

        init_db(database_path)
        with connect(database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, mode, period_months_json, source_files_json,
                       input_count, saved_count, removed_count, created_at
                FROM dashboard_import_batch
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        mode_map = {"REPLACE_MONTHS": "REPLACE_MONTHS", "APPEND": "APPEND_OR_UPDATE"}
        data = [
            {
                "batch_id": row["id"],
                "mode": mode_map.get(row["mode"], row["mode"]),
                "period_months": json.loads(row["period_months_json"]),
                "source_files": json.loads(row["source_files_json"]),
                "input_count": row["input_count"],
                "saved_count": row["saved_count"],
                "removed_count": row["removed_count"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
        return {"data": data}

    # ------------------------------------------------------------------
    # 19.3.2 traffic-boost toggle (shared by dashboard/grassroot/long-term
    # preview; commentary is explicitly excluded, see contract 19.3.2).
    # ------------------------------------------------------------------
    @router.put("/api/dashboard/{period_month}/traffic-boost")
    def save_traffic_boost(period_month: str, payload: dict = Body(...)) -> dict:
        if "enabled" not in payload:
            raise validation_error("enabled 是必填字段。", "enabled")
        repository = DashboardRepository(database_path)
        try:
            repository.save_traffic_boost_enabled(period_month, bool(payload.get("enabled")))
        except ValueError as exc:
            raise validation_error(str(exc)) from exc
        enabled = repository.get_traffic_boost_enabled(period_month)
        return {"data": {"period_month": period_month, "enabled": enabled}}

    return router

