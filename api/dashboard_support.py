from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
from fastapi import HTTPException

from core.cross_industry import exclude_cross_industry_posts
from core.dashboard_processor import filter_dashboard_data
from core.traffic_boost import apply_july_traffic_boost
from database.dashboard_repository import DashboardRepository

PERIOD_MODES = {"month", "week", "custom"}
TRAFFIC_BOOST_MODES = {"saved_setting", "original", "boosted_preview"}


def validation_error(message: str, field: str | None = None) -> HTTPException:
    error: dict = {"code": "VALIDATION_ERROR", "message": message}
    if field is not None:
        error["field_errors"] = [{"field": field, "message": message}]
    return HTTPException(status_code=422, detail={"error": error})


def _parse_iso_date(value: str, field: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise validation_error(f"{field} 必须是合法的 YYYY-MM-DD 日期。", field) from exc


def parse_period(
    period_mode: str | None,
    *,
    period_month: str | None = None,
    week_start: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[date, date, str, str]:
    """Validate the period parameters and return (start, end, period_label, boost_month)."""
    if period_mode is None or period_mode not in PERIOD_MODES:
        raise validation_error(
            f"period_mode 必须是 month、week 或 custom 之一，收到：{period_mode}",
            "period_mode",
        )

    if period_mode == "month":
        if week_start is not None or start_date is not None or end_date is not None:
            raise validation_error(
                "period_mode=month 时不能同时提供 week_start/start_date/end_date。",
                "period_mode",
            )
        if not period_month:
            raise validation_error("period_mode=month 时必须提供 period_month。", "period_month")
        try:
            parsed = datetime.strptime(period_month, "%Y-%m")
        except ValueError as exc:
            raise validation_error(
                f"period_month 必须是合法的 YYYY-MM 格式：{period_month}", "period_month"
            ) from exc
        range_start = date(parsed.year, parsed.month, 1)
        if parsed.month == 12:
            next_month = date(parsed.year + 1, 1, 1)
        else:
            next_month = date(parsed.year, parsed.month + 1, 1)
        range_end = next_month - timedelta(days=1)
        return range_start, range_end, period_month, period_month

    if period_mode == "week":
        if period_month is not None or start_date is not None or end_date is not None:
            raise validation_error(
                "period_mode=week 时不能同时提供 period_month/start_date/end_date。",
                "period_mode",
            )
        if not week_start:
            raise validation_error("period_mode=week 时必须提供 week_start。", "week_start")
        parsed_start = _parse_iso_date(week_start, "week_start")
        if parsed_start.weekday() != 0:
            raise validation_error("week_start 必须是周一。", "week_start")
        range_end = parsed_start + timedelta(days=6)
        return parsed_start, range_end, week_start, parsed_start.strftime("%Y-%m")

    if period_month is not None or week_start is not None:
        raise validation_error(
            "period_mode=custom 时不能同时提供 period_month/week_start。",
            "period_mode",
        )
    if not start_date or not end_date:
        raise validation_error(
            "period_mode=custom 时必须同时提供 start_date 与 end_date。", "start_date"
        )
    parsed_start = _parse_iso_date(start_date, "start_date")
    parsed_end = _parse_iso_date(end_date, "end_date")
    if parsed_end < parsed_start:
        raise validation_error("end_date 不能早于 start_date。", "end_date")
    return parsed_start, parsed_end, f"{start_date}~{end_date}", parsed_start.strftime("%Y-%m")


def creator_keys_for_categories(categories, creator_records) -> set[str] | None:
    if not categories:
        return None
    wanted = set(categories)
    keys: set[str] = set()
    for record in creator_records:
        if any(category.value in wanted for category in record.creator_categories):
            keys.add(record.user_id)
    return keys


def creator_category_lookup(creator_records) -> dict[str, str | None]:
    lookup: dict[str, str | None] = {}
    for record in creator_records:
        categories = record.creator_categories
        lookup[record.user_id] = categories[0].value if categories else None
    return lookup


def split_contract_types(value: object) -> list[str]:
    if isinstance(value, list):
        return list(value)
    if value is None:
        return []
    if isinstance(value, float) and pd.isna(value):
        return []
    text = str(value).strip()
    if not text or text in ("未匹配", "未设置"):
        return []
    return [part for part in text.split("、") if part]


def apply_traffic_boost_mode(
    data: pd.DataFrame,
    *,
    traffic_boost_mode: str,
    boost_month: str,
    database_path,
) -> pd.DataFrame:
    if traffic_boost_mode == "original":
        enabled = False
    elif traffic_boost_mode == "boosted_preview":
        enabled = True
    else:
        try:
            enabled = DashboardRepository(database_path).get_traffic_boost_enabled(boost_month)
        except ValueError:
            enabled = False
    return apply_july_traffic_boost(data, enabled=enabled)


def apply_common_pipeline(
    data: pd.DataFrame,
    creator_records,
    *,
    start_date: date,
    end_date: date,
    creator_key: list[str] | None,
    creator_category: list[str] | None,
    source_platform: list[str] | None,
    content_type: list[str] | None,
    include_cross_industry: bool,
    traffic_boost_mode: str,
    boost_month: str,
    database_path,
) -> pd.DataFrame:
    category_keys = creator_keys_for_categories(creator_category, creator_records)
    if creator_key:
        effective_keys = set(creator_key)
        if category_keys is not None:
            effective_keys &= category_keys
    elif category_keys is not None:
        effective_keys = category_keys
    else:
        effective_keys = None

    filtered = filter_dashboard_data(
        data,
        source_platforms=source_platform or None,
        content_types=content_type or None,
        creator_keys=list(effective_keys) if effective_keys is not None else None,
        start_date=start_date,
        end_date=end_date,
    )

    if not include_cross_industry:
        filtered = exclude_cross_industry_posts(filtered)

    return apply_traffic_boost_mode(
        filtered,
        traffic_boost_mode=traffic_boost_mode,
        boost_month=boost_month,
        database_path=database_path,
    )


def validate_traffic_boost_mode(value: str) -> str:
    if value not in TRAFFIC_BOOST_MODES:
        raise validation_error(
            f"traffic_boost_mode 必须是 saved_setting、original 或 boosted_preview 之一，收到：{value}",
            "traffic_boost_mode",
        )
    return value


def validate_creator_categories(values: list[str] | None) -> list[str] | None:
    if not values:
        return values
    from models.enums import CreatorCategory

    for value in values:
        try:
            CreatorCategory(value)
        except ValueError as exc:
            raise validation_error(
                f"无效的 creator_category 取值：{value}", "creator_category"
            ) from exc
    return values


def view_sum_columns(data: pd.DataFrame, group_col: str) -> pd.DataFrame:
    columns = ["view", "original_views", "traffic_boost_views", "boosted_views"]
    if data.empty or group_col not in data.columns:
        return pd.DataFrame(columns=[group_col, *columns])
    prepared = data.copy()
    for column in columns:
        prepared[column] = pd.to_numeric(prepared.get(column), errors="coerce").fillna(0)
    return prepared.groupby(group_col, as_index=False)[columns].sum()
