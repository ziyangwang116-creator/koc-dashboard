from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from core.koc_mapper import KOCMapper
from core.validator import ValidationReport, blank_mask, build_validation_report


OUTPUT_COLUMNS = [
    "koc_name",
    "platform",
    "publish_date",
    "title",
    "url",
    "views",
    "remark",
    "likes",
    "comment",
    "reposted",
]

TRANSFORM_RULE_VERSION = "2.1.0"

__all__ = [
    "DataTransformError",
    "OUTPUT_COLUMNS",
    "TRANSFORM_RULE_VERSION",
    "TransformResult",
    "transform_data",
]

REQUIRED_COLUMNS = [
    "view",
    "subtype",
    "title",
    "userId",
    "url",
    "timestamp",
]

OPTIONAL_COLUMNS = ["likes", "comment", "reposted", "description", "collect"]


class DataTransformError(ValueError):
    """An input problem that can be shown directly to an end user."""


@dataclass(frozen=True)
class TransformResult:
    data: pd.DataFrame
    report: ValidationReport
    exceptions: pd.DataFrame


def _validate_input(raw_data: pd.DataFrame, timezone: str) -> None:
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in raw_data]
    normalized_columns = {
        str(column).strip().casefold() for column in raw_data.columns
    }
    has_explicit_date = any(
        candidate.casefold() in normalized_columns
        for candidate in ("date", "publish_date", "published_at", "日期", "发布日期")
    )
    if has_explicit_date and "timestamp" in missing_columns:
        missing_columns.remove("timestamp")
    if missing_columns:
        joined = "、".join(missing_columns)
        raise DataTransformError(
            f"原始 Excel 缺少必要字段：{joined}。请检查 Rapid Query 导出列名后重试。"
        )

    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise DataTransformError(
            f"时区“{timezone}”无效，请使用 IANA 时区名称，例如 Asia/Shanghai。"
        ) from None


def _convert_timestamp(series: pd.Series, timezone: str) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    timestamps = pd.to_datetime(numeric, unit="ms", utc=True, errors="coerce")
    return timestamps.dt.tz_convert(timezone).dt.date


def _build_publish_dates(raw_data: pd.DataFrame, timezone: str) -> pd.Series:
    timestamp_source = (
        raw_data["timestamp"]
        if "timestamp" in raw_data
        else pd.Series(pd.NA, index=raw_data.index, dtype="object")
    )
    publish_dates = _convert_timestamp(timestamp_source, timezone).astype("object")
    normalized_columns = {
        str(column).strip().casefold(): column for column in raw_data.columns
    }
    for candidate in (
        "date",
        "publish_date",
        "published_at",
        "日期",
        "发布日期",
    ):
        column = normalized_columns.get(candidate.casefold())
        if column is None:
            continue
        missing = publish_dates.isna()
        if not missing.any():
            break
        explicit_dates = pd.to_datetime(raw_data.loc[missing, column], errors="coerce")
        publish_dates.loc[missing] = explicit_dates.dt.date
    missing_count = int(publish_dates.isna().sum())
    if missing_count:
        raise DataTransformError(
            f"有 {missing_count} 条投稿缺少有效发布日期。"
            "请填写 timestamp，或提供 date/日期/发布日期列后重新导入。"
        )
    return publish_dates


def _clean_optional_number(series: pd.Series) -> pd.Series:
    blanks = blank_mask(series)
    converted = pd.to_numeric(series, errors="coerce")
    invalid = ~blanks & converted.isna()
    result = converted.astype("object")
    result.loc[invalid] = series.loc[invalid]
    result.loc[blanks] = pd.NA
    return result


def _normalized_text(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().str.casefold()


def _build_platform(raw_data: pd.DataFrame) -> pd.Series:
    source_subtype = raw_data["subtype"]
    platform = source_subtype.astype("object").copy()
    normalized_subtype = _normalized_text(source_subtype)
    shorts_mask = blank_mask(source_subtype) | normalized_subtype.isin(["short", "nan"])
    platform.loc[shorts_mask] = "shorts"

    if "platform" in raw_data:
        tiktok_mask = _normalized_text(raw_data["platform"]).eq("tiktok").fillna(False)
        platform.loc[tiktok_mask] = "TikTok"
    return platform


def _build_exceptions(
    raw_data: pd.DataFrame,
    normalized_user_ids: pd.Series,
    mapped_names: pd.Series,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for position, (normalized_uid, mapped_name) in enumerate(
        zip(normalized_user_ids, mapped_names), start=2
    ):
        if pd.isna(normalized_uid):
            rows.append(
                {
                    "异常类型": "userId 为空",
                    "userId": None,
                    "原始行号": position,
                    "说明": "原始数据没有可用于达人匹配的 userId",
                }
            )
        elif pd.isna(mapped_name):
            rows.append(
                {
                    "异常类型": "未匹配 UID",
                    "userId": str(normalized_uid),
                    "原始行号": position,
                    "说明": "该 userId 不在当前达人库中，koc_name 已保留空白",
                }
            )
    return pd.DataFrame(rows, columns=["异常类型", "userId", "原始行号", "说明"])


def transform_data(
    raw_data: pd.DataFrame,
    mapper: KOCMapper,
    timezone: str,
) -> TransformResult:
    _validate_input(raw_data, timezone)

    prepared_data = raw_data.copy()
    for column in OPTIONAL_COLUMNS:
        if column not in prepared_data:
            prepared_data[column] = pd.Series(
                pd.NA, index=prepared_data.index, dtype="object"
            )

    mapped_names, normalized_user_ids = mapper.map_series(prepared_data["userId"])
    platform = _build_platform(prepared_data)

    reposted_source = prepared_data["reposted"]

    final_data = pd.DataFrame(
        {
            "koc_name": mapped_names,
            "platform": platform,
            "publish_date": _build_publish_dates(prepared_data, timezone),
            "title": prepared_data["title"],
            "url": prepared_data["url"],
            "views": _clean_optional_number(prepared_data["view"]),
            "remark": pd.Series(pd.NA, index=prepared_data.index, dtype="object"),
            "likes": _clean_optional_number(prepared_data["likes"]),
            "comment": _clean_optional_number(prepared_data["comment"]),
            "reposted": _clean_optional_number(reposted_source),
        },
        index=raw_data.index,
    )[OUTPUT_COLUMNS]

    report = build_validation_report(
        raw_data=prepared_data,
        final_data=final_data,
        normalized_user_ids=normalized_user_ids,
        mapped_names=mapped_names,
    )
    exceptions = _build_exceptions(prepared_data, normalized_user_ids, mapped_names)
    return TransformResult(data=final_data, report=report, exceptions=exceptions)
