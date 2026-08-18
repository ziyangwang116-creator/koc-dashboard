from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Mapping
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

TRANSFORM_RULE_VERSION = "2.2.0"

__all__ = [
    "DataTransformError",
    "OUTPUT_COLUMNS",
    "TRANSFORM_RULE_VERSION",
    "TransformDiagnostics",
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

SMART_IMPORT_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS + ["platform"]

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "view": (
        "view", "views", "viewcount", "play", "playcount", "播放量", "浏览量",
    ),
    "subtype": (
        "subtype", "videotype", "contenttype", "视频类型", "内容类型", "类型",
    ),
    "title": ("title", "videotitle", "标题", "视频标题", "投稿标题"),
    "userId": (
        "userid", "uid", "creatorid", "达人id", "博主id", "用户id",
    ),
    "url": ("url", "videourl", "link", "视频链接", "投稿链接", "链接"),
    "timestamp": (
        "timestamp", "publishtime", "publishedat", "publishdate", "date",
        "发布时间", "发布日期", "投稿日期", "日期",
    ),
    "platform": ("platform", "sourceplatform", "平台", "来源平台"),
    "likes": ("likes", "like", "likecount", "点赞", "点赞数"),
    "comment": ("comment", "comments", "commentcount", "评论", "评论数"),
    "reposted": (
        "reposted", "repost", "reposts", "share", "sharecount", "转发", "转发数",
    ),
    "description": ("description", "desc", "caption", "描述", "文案"),
    "collect": ("collect", "collection", "favorite", "收藏", "收藏数"),
}

DATE_METHOD_LABELS = {
    "excel_datetime": "Excel 日期",
    "excel_serial": "Excel 日期序列号",
    "unix_ms": "毫秒时间戳",
    "unix_s": "秒级时间戳",
    "yyyymmdd": "YYYYMMDD 日期",
    "date_text": "日期文本",
}


class DataTransformError(ValueError):
    """An input problem that can be shown directly to an end user."""


@dataclass(frozen=True)
class TransformResult:
    data: pd.DataFrame
    report: ValidationReport
    exceptions: pd.DataFrame
    diagnostics: "TransformDiagnostics"


@dataclass(frozen=True)
class TransformDiagnostics:
    source_columns: tuple[str, ...]
    column_mapping: dict[str, str]
    auto_mapped_columns: tuple[str, ...]
    date_method_counts: dict[str, int]
    warnings: tuple[str, ...]


def _normalized_header(value: object) -> str:
    return re.sub(r"[\s_\-./（）()\[\]【】]+", "", str(value)).casefold()


def _prepare_input_columns(
    raw_data: pd.DataFrame,
    column_mapping: Mapping[str, str] | None,
) -> tuple[pd.DataFrame, dict[str, str], tuple[str, ...], tuple[str, ...]]:
    source_columns = tuple(str(column) for column in raw_data.columns)
    source_by_name = {str(column): column for column in raw_data.columns}
    normalized_sources: dict[str, list[str]] = {}
    for source in source_columns:
        normalized_sources.setdefault(_normalized_header(source), []).append(source)

    requested = {
        str(canonical): str(source)
        for canonical, source in (column_mapping or {}).items()
        if str(source).strip()
    }
    unknown = sorted(set(requested) - set(SMART_IMPORT_COLUMNS))
    if unknown:
        raise DataTransformError(f"字段映射包含未知目标字段：{'、'.join(unknown)}。")

    resolved: dict[str, str] = {}
    auto_mapped: list[str] = []
    warnings: list[str] = []
    used_sources: set[str] = set()

    for canonical in SMART_IMPORT_COLUMNS:
        selected: str | None = None
        requested_source = requested.get(canonical)
        if requested_source is not None:
            if requested_source not in source_by_name:
                raise DataTransformError(
                    f"字段映射中的来源列“{requested_source}”不存在。"
                )
            selected = requested_source
        elif canonical in source_by_name:
            selected = canonical
        else:
            matches: list[str] = []
            for alias in COLUMN_ALIASES.get(canonical, (canonical,)):
                matches.extend(normalized_sources.get(_normalized_header(alias), []))
            matches = list(dict.fromkeys(matches))
            if matches:
                selected = matches[0]
                auto_mapped.append(canonical)
                if len(matches) > 1:
                    warnings.append(
                        f"字段 {canonical} 有多个候选列，已优先使用“{selected}”。"
                    )
        if selected is None:
            continue
        if selected in used_sources:
            raise DataTransformError(f"来源列“{selected}”不能同时映射到多个字段。")
        used_sources.add(selected)
        resolved[canonical] = selected

    prepared = raw_data.copy()
    for canonical, source in resolved.items():
        prepared[canonical] = raw_data[source]
    for canonical in auto_mapped:
        warnings.append(f"已自动将“{resolved[canonical]}”识别为 {canonical}。")
    return prepared, resolved, tuple(auto_mapped), tuple(warnings)


def _validate_input(raw_data: pd.DataFrame, timezone: str) -> None:
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in raw_data]
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


def _parse_date_value(value: object, timezone: str) -> tuple[date | None, str | None]:
    if value is None or value is pd.NA:
        return None, None
    try:
        if bool(pd.isna(value)):
            return None, None
    except (TypeError, ValueError):
        pass

    if isinstance(value, (pd.Timestamp, datetime, date)):
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert(timezone)
        return timestamp.date(), "excel_datetime"

    text = str(value).strip()
    if not text:
        return None, None
    numeric: float | None = None
    try:
        numeric = float(text.replace(",", ""))
    except ValueError:
        numeric = None

    if numeric is not None:
        integer = int(numeric)
        if numeric == integer and 19_000_101 <= integer <= 21_001_231:
            parsed = pd.to_datetime(str(integer), format="%Y%m%d", errors="coerce")
            if pd.notna(parsed):
                return parsed.date(), "yyyymmdd"
        if 20_000 <= numeric <= 80_000:
            return (date(1899, 12, 30) + timedelta(days=numeric)), "excel_serial"
        unit = "ms" if abs(numeric) >= 100_000_000_000 else "s"
        parsed = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
        if pd.notna(parsed):
            return parsed.tz_convert(timezone).date(), f"unix_{unit}"

    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None, None
    timestamp = pd.Timestamp(parsed)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(timezone)
    return timestamp.date(), "date_text"


def _build_publish_dates(
    raw_data: pd.DataFrame,
    timezone: str,
) -> tuple[pd.Series, dict[str, int]]:
    publish_dates = pd.Series(pd.NA, index=raw_data.index, dtype="object")
    method_counts: Counter[str] = Counter()
    candidate_columns = [
        column
        for column in (
            "timestamp",
            "date",
            "publish_date",
            "published_at",
            "日期",
            "发布日期",
        )
        if column in raw_data
    ]
    for column in candidate_columns:
        missing_indexes = publish_dates.index[publish_dates.isna()]
        if len(missing_indexes) == 0:
            break
        for index in missing_indexes:
            parsed, method = _parse_date_value(raw_data.at[index, column], timezone)
            if parsed is None or method is None:
                continue
            publish_dates.at[index] = parsed
            method_counts[method] += 1
    return publish_dates, dict(method_counts)


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
    column_mapping: Mapping[str, str] | None = None,
) -> TransformResult:
    prepared_data, resolved_mapping, auto_mapped, mapping_warnings = (
        _prepare_input_columns(raw_data, column_mapping)
    )
    _validate_input(prepared_data, timezone)

    for column in OPTIONAL_COLUMNS:
        if column not in prepared_data:
            prepared_data[column] = pd.Series(
                pd.NA, index=prepared_data.index, dtype="object"
            )

    mapped_names, normalized_user_ids = mapper.map_series(prepared_data["userId"])
    platform = _build_platform(prepared_data)
    publish_dates, date_method_counts = _build_publish_dates(prepared_data, timezone)

    reposted_source = prepared_data["reposted"]

    final_data = pd.DataFrame(
        {
            "koc_name": mapped_names,
            "platform": platform,
            "publish_date": publish_dates,
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
    warnings = list(mapping_warnings)
    invalid_date_count = int(publish_dates.isna().sum())
    if invalid_date_count:
        warnings.append(f"有 {invalid_date_count} 条投稿缺少有效发布日期。")
    if len(date_method_counts) > 1:
        labels = [DATE_METHOD_LABELS.get(method, method) for method in date_method_counts]
        warnings.append(f"日期列包含多种格式：{'、'.join(labels)}。")
    return TransformResult(
        data=final_data,
        report=report,
        exceptions=exceptions,
        diagnostics=TransformDiagnostics(
            source_columns=tuple(str(column) for column in raw_data.columns),
            column_mapping=resolved_mapping,
            auto_mapped_columns=auto_mapped,
            date_method_counts=date_method_counts,
            warnings=tuple(warnings),
        ),
    )
