from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

import pandas as pd

from core.cross_industry import exclude_cross_industry_posts
from core.grassroot_compensation import SERVICE_FEE_MULTIPLIER, USD_HANDLING_FEE
from core.traffic_boost import apply_july_traffic_boost
from models.contracts import derive_creator_categories
from models.enums import CREATOR_CATEGORY_LABELS, CreatorCategory
from models.koc import KOCRecord


LONG_TERM_TIER_RULES: tuple[tuple[str, int, int, int | None, int], ...] = (
    ("S", 200_000, 6_000_000, 2, 2_000_000),
    ("A+", 150_000, 4_000_000, 2, 1_500_000),
    ("A", 120_000, 2_500_000, 2, 1_000_000),
    ("B+", 100_000, 1_500_000, 1, 700_000),
    ("B", 80_000, 1_000_000, 1, 500_000),
    ("C+", 50_000, 700_000, None, 400_000),
    ("C", 30_000, 400_000, None, 300_000),
    ("D+", 20_000, 200_000, None, 200_000),
    ("D", 10_000, 100_000, None, 100_000),
)

LONG_TERM_COMPENSATION_COLUMNS = [
    "记录ID",
    "user_id",
    "达人",
    "合同类型",
    "合同开始日期",
    "合同截止日期",
    "粉丝数",
    "YouTube 投稿数",
    "月度新投稿播放量",
    "CPM计算播放量（无加成）",
    "每月活动数",
    "活动数门槛",
    "结算状态",
    "rank",
    "rank金额",
    "预计 CPM（日元）",
    "总金额（日元）",
    "博主应收（日元）(包含15$手续费)",
    "有道应收（日元）（包含服务费）",
    "博主应收（美元）",
    "有道应收（美元）（包含服务费）",
    "CPM",
]

_STATUS_READY = "可结算"
_STATUS_NOT_REACHED = "未达标"
_STATUS_NEEDS_FOLLOWERS = "待补充粉丝数"
_STATUS_NEEDS_EVENTS = "待填写活动数"
_STATUS_OUTSIDE_CONTRACT = "合同期限外"
_STATUS_HISTORY_MISSING = "历史资料缺失"


@dataclass(frozen=True)
class LongTermCompensationResult:
    details: pd.DataFrame
    total_amount_jpy: int
    creator_receivable_jpy: int
    youdao_receivable_jpy: int
    creator_receivable_usd: float
    youdao_receivable_usd: float
    settled_views: int
    total_video_views: int
    overall_cpm: float | None


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return int(numeric)


def _optional_date(value: object) -> date | None:
    text = _text(value)
    if not text:
        return None
    try:
        return pd.to_datetime(text, errors="raise").date()
    except (TypeError, ValueError):
        return None


def _numeric_total(data: pd.DataFrame, column: str) -> int:
    if data.empty or column not in data:
        return 0
    values = pd.to_numeric(data[column], errors="coerce")
    return int(values.fillna(0).sum())


def _active_value(value: object, *, default: bool = True) -> bool:
    text = _text(value)
    if not text:
        return default
    return text.casefold() not in {"0", "false", "no", "off", "disabled"}


def _dashboard_contract_types(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        text = _text(value)
        for separator in ("、", ";", "/", "|"):
            text = text.replace(separator, ",")
        values = text.split(",")
    return tuple(
        dict.fromkeys(text for item in values if (text := _text(item)))
    )


def _is_long_term_profile(
    contract_types: tuple[str, ...],
    creator_category: object,
) -> bool:
    categories = derive_creator_categories(contract_types)
    if CreatorCategory.LONG_TERM in categories:
        return True
    category_text = _text(creator_category).casefold()
    return category_text in {
        CreatorCategory.LONG_TERM.value.casefold(),
        CREATOR_CATEGORY_LABELS[CreatorCategory.LONG_TERM].casefold(),
    }


def _is_youtube_row(data: pd.DataFrame) -> pd.Series:
    platform_column = "source_platform" if "source_platform" in data else "platform"
    if platform_column in data:
        platform = data[platform_column].astype("string").str.strip().str.casefold()
    else:
        platform = pd.Series("", index=data.index, dtype="string")
    subtype = (
        data["subtype"].astype("string").str.strip().str.casefold()
        if "subtype" in data
        else pd.Series("", index=data.index, dtype="string")
    )
    youtube = platform.str.contains("youtube", regex=False, na=False) | platform.eq(
        "ytb"
    )
    platform_unknown = platform.isna() | platform.isin(["", "未标注"])
    return youtube | (
        platform_unknown
        & subtype.isin(["long", "livestream", "shorts", "ytb shorts"])
    )


def _row_within_contract(row: pd.Series) -> bool:
    publish_date = _optional_date(row.get("_publish_date"))
    if publish_date is None:
        return True
    start = _optional_date(row.get("contract_start_date"))
    end = _optional_date(row.get("contract_end_date"))
    return (start is None or publish_date >= start) and (
        end is None or publish_date <= end
    )


def _record_period_intersects_month(
    record: KOCRecord,
    period_start: date | None,
    period_end: date | None,
) -> bool:
    if period_start is None or period_end is None:
        return True
    if record.contract_end_date is not None and record.contract_end_date < period_start:
        return False
    if record.contract_start_date is not None and record.contract_start_date > period_end:
        return False
    return True


def _empty_amounts() -> dict[str, object]:
    return {
        "rank": "",
        "rank金额": 0,
        "预计 CPM（日元）": None,
        "总金额（日元）": 0,
        "博主应收（日元）(包含15$手续费)": 0,
        "有道应收（日元）（包含服务费）": 0,
        "博主应收（美元）": 0.0,
        "有道应收（美元）（包含服务费）": 0.0,
        "CPM": None,
    }


def _rank_for_long_term(
    followers: int,
    views: int,
    events: int,
) -> tuple[str, int, int | None, int | None]:
    for rank, follower_threshold, view_threshold, event_threshold, reward in (
        LONG_TERM_TIER_RULES
    ):
        if followers < follower_threshold or views < view_threshold:
            continue
        if event_threshold is not None and events < event_threshold:
            continue
        expected_cpm = int(reward / view_threshold * 1_000)
        return rank, reward, event_threshold, expected_cpm
    return "无等级", 0, None, None


def _latest_nonempty(frame: pd.DataFrame, column: str) -> object:
    if frame.empty or column not in frame:
        return None
    values = frame[column]
    for value in reversed(values.tolist()):
        if _text(value):
            return value
    return None


def _profile_row(
    record_id: int,
    source_data: pd.DataFrame,
    event_counts: Mapping[int, int | None],
) -> dict[str, object]:
    long_profile_data = source_data.loc[
        source_data["_is_long_term"] & source_data["_is_active"]
    ]
    if not long_profile_data.empty:
        profile_dates = (
            pd.to_datetime(
                long_profile_data["profile_effective_date"], errors="coerce"
            )
            if "profile_effective_date" in long_profile_data
            else pd.Series(pd.NaT, index=long_profile_data.index)
        )
        publish_dates = pd.to_datetime(
            long_profile_data["_publish_date"], errors="coerce"
        )
        long_profile_data = (
            long_profile_data.assign(
                _profile_sort=profile_dates,
                _publish_sort=publish_dates,
            )
            .sort_values(
                ["_profile_sort", "_publish_sort"],
                kind="stable",
                na_position="first",
            )
            .drop(columns=["_profile_sort", "_publish_sort"])
        )
    latest = long_profile_data.iloc[-1] if not long_profile_data.empty else None
    followers = _optional_int(
        _latest_nonempty(long_profile_data, "follower_count")
    )
    contracts = _text(latest.get("contract_types")) if latest is not None else ""
    start = _optional_date(latest.get("contract_start_date")) if latest is not None else None
    end = _optional_date(latest.get("contract_end_date")) if latest is not None else None
    eligible_data = long_profile_data.loc[
        long_profile_data["_within_contract"] & long_profile_data["_is_youtube"]
    ]
    event_count = event_counts.get(record_id)
    return {
        "记录ID": record_id,
        "user_id": _text(latest.get("user_id")) if latest is not None else "",
        "达人": (
            _text(latest.get("koc_name"))
            or _text(latest.get("creator_label"))
            if latest is not None
            else ""
        ),
        "合同类型": contracts or "未设置",
        "合同开始日期": start.isoformat() if start else None,
        "合同截止日期": end.isoformat() if end else None,
        "粉丝数": followers,
        "YouTube 投稿数": len(eligible_data),
        "月度新投稿播放量": _numeric_total(eligible_data, "views"),
        "CPM计算播放量（无加成）": _numeric_total(
            eligible_data, "original_views"
        ),
        "每月活动数": event_count,
        "活动数门槛": None,
        "_source_has_posts": not source_data.empty,
        "_has_long_profile": not long_profile_data.empty,
        "_has_in_contract_profile": bool(
            long_profile_data["_within_contract"].any()
        ),
    }


def _fallback_row(
    record: KOCRecord,
    event_counts: Mapping[int, int | None],
) -> dict[str, object]:
    return {
        "记录ID": record.id,
        "user_id": record.user_id,
        "达人": record.koc_name,
        "合同类型": "、".join(record.contract_types) or "未设置",
        "合同开始日期": (
            record.contract_start_date.isoformat()
            if record.contract_start_date is not None
            else None
        ),
        "合同截止日期": (
            record.contract_end_date.isoformat()
            if record.contract_end_date is not None
            else None
        ),
        "粉丝数": record.follower_count,
        "YouTube 投稿数": 0,
        "月度新投稿播放量": 0,
        "CPM计算播放量（无加成）": 0,
        "每月活动数": event_counts.get(record.id),
        "活动数门槛": None,
        "_source_has_posts": False,
        "_has_long_profile": True,
        "_has_in_contract_profile": True,
    }


def _no_payment_row(
    base_row: dict[str, object],
    *,
    status: str,
    rank: str = "",
    reward: int = 0,
    event_threshold: int | None = None,
    expected_cpm: int | None = None,
) -> dict[str, object]:
    return {
        **base_row,
        "活动数门槛": event_threshold,
        "结算状态": status,
        "rank": rank,
        "rank金额": reward,
        "预计 CPM（日元）": expected_cpm,
        **{
            key: value
            for key, value in _empty_amounts().items()
            if key not in {"rank", "rank金额", "预计 CPM（日元）"}
        },
    }


def calculate_long_term_compensation(
    data: pd.DataFrame,
    creator_records: Iterable[KOCRecord],
    *,
    jpy_to_usd_rate: float,
    event_counts: Mapping[int, int | None],
    period_start: date | None = None,
    period_end: date | None = None,
    traffic_boost_enabled: bool = False,
) -> LongTermCompensationResult:
    """Calculate long-term KOL rewards from all in-term YouTube posts.

    Post rows have already been enriched from the creator profile effective on
    their publication date. This preserves historical category and contract
    changes while saved settlement versions freeze the final result.
    """
    if jpy_to_usd_rate <= 0:
        raise ValueError("日元兑美元汇率必须大于 0。")

    prepared = apply_july_traffic_boost(
        exclude_cross_industry_posts(data),
        enabled=traffic_boost_enabled,
    )
    for column in (
        "user_id",
        "creator_id",
        "creator_active",
        "creator_category",
        "contract_types",
        "contract_start_date",
        "contract_end_date",
        "follower_count",
        "profile_status",
        "publish_date",
        "views",
    ):
        if column not in prepared:
            prepared[column] = pd.Series(index=prepared.index, dtype="object")
    prepared["_record_id"] = pd.to_numeric(
        prepared["creator_id"], errors="coerce"
    ).astype("Int64")
    prepared["_publish_date"] = pd.to_datetime(
        prepared["publish_date"], errors="coerce"
    ).dt.date
    prepared["_is_active"] = prepared["creator_active"].map(_active_value)
    prepared["_is_long_term"] = [
        _is_long_term_profile(
            _dashboard_contract_types(contracts),
            category,
        )
        for contracts, category in zip(
            prepared["contract_types"], prepared["creator_category"]
        )
    ]
    prepared["_within_contract"] = prepared.apply(
        _row_within_contract,
        axis=1,
    )
    prepared["_is_youtube"] = _is_youtube_row(prepared)
    prepared["_profile_status"] = (
        prepared["profile_status"].astype("string").str.strip().str.upper()
    )

    records_by_id = {record.id: record for record in creator_records}
    rows: list[dict[str, object]] = []
    seen_record_ids = {
        int(record_id)
        for record_id in prepared.loc[
            prepared["_record_id"].notna(), "_record_id"
        ].tolist()
    }
    profile_record_ids = sorted(
        {
            int(record_id)
            for record_id in prepared.loc[
                prepared["_record_id"].notna(), "_record_id"
            ].tolist()
        }
    )
    for record_id in profile_record_ids:
        source_data = prepared.loc[prepared["_record_id"].eq(record_id)]
        current = records_by_id.get(record_id)
        current_is_long_term = current is not None and (
            CreatorCategory.LONG_TERM in current.creator_categories
        )
        history_missing = source_data["_profile_status"].eq(
            "HISTORY_MISSING"
        ).any()
        has_long_profile = bool(
            (source_data["_is_long_term"] & source_data["_is_active"]).any()
        )
        if not has_long_profile and not (history_missing and current_is_long_term):
            continue

        if history_missing:
            record = current
            rows.append(
                {
                    "记录ID": record_id,
                    "user_id": record.user_id if record else "",
                    "达人": record.koc_name if record else "",
                    "合同类型": _STATUS_HISTORY_MISSING,
                    "合同开始日期": None,
                    "合同截止日期": None,
                    "粉丝数": None,
                    "YouTube 投稿数": 0,
                    "月度新投稿播放量": 0,
                    "CPM计算播放量（无加成）": 0,
                    "每月活动数": event_counts.get(record_id),
                    "活动数门槛": None,
                    "结算状态": _STATUS_HISTORY_MISSING,
                    **_empty_amounts(),
                }
            )
            continue

        base_row = _profile_row(record_id, source_data, event_counts)
        source_has_posts = bool(base_row.pop("_source_has_posts"))
        has_in_contract_profile = bool(base_row.pop("_has_in_contract_profile"))
        base_row.pop("_has_long_profile")
        if source_has_posts and not has_in_contract_profile:
            rows.append(_no_payment_row(base_row, status=_STATUS_OUTSIDE_CONTRACT))
            continue
        followers = _optional_int(base_row["粉丝数"])
        events = _optional_int(base_row["每月活动数"])
        views = int(base_row["月度新投稿播放量"])
        cpm_views = int(base_row["CPM计算播放量（无加成）"])
        if followers is None:
            rows.append(_no_payment_row(base_row, status=_STATUS_NEEDS_FOLLOWERS))
            continue
        if events is None:
            rows.append(_no_payment_row(base_row, status=_STATUS_NEEDS_EVENTS))
            continue
        rank, reward, event_threshold, expected_cpm = _rank_for_long_term(
            followers,
            views,
            events,
        )
        if reward <= 0:
            rows.append(
                _no_payment_row(
                    base_row,
                    status=_STATUS_NOT_REACHED,
                    rank=rank,
                    reward=reward,
                    event_threshold=event_threshold,
                    expected_cpm=expected_cpm,
                )
            )
            continue

        creator_receivable_usd = reward * jpy_to_usd_rate + USD_HANDLING_FEE
        youdao_receivable_usd = creator_receivable_usd * SERVICE_FEE_MULTIPLIER
        creator_receivable_jpy = int(round(creator_receivable_usd / jpy_to_usd_rate))
        youdao_receivable_jpy = int(round(youdao_receivable_usd / jpy_to_usd_rate))
        rows.append(
            {
                **base_row,
                "活动数门槛": event_threshold,
                "结算状态": _STATUS_READY,
                "rank": rank,
                "rank金额": reward,
                "预计 CPM（日元）": expected_cpm,
                "总金额（日元）": reward,
                "博主应收（日元）(包含15$手续费)": creator_receivable_jpy,
                "有道应收（日元）（包含服务费）": youdao_receivable_jpy,
                "博主应收（美元）": creator_receivable_usd,
                "有道应收（美元）（包含服务费）": youdao_receivable_usd,
                "CPM": (
                    youdao_receivable_usd / cpm_views * 1_000
                    if cpm_views > 0
                    else None
                ),
            }
        )

    for record in records_by_id.values():
        if record.id in seen_record_ids or not record.active:
            continue
        if CreatorCategory.LONG_TERM not in record.creator_categories:
            continue
        if not _record_period_intersects_month(record, period_start, period_end):
            continue
        base_row = _fallback_row(record, event_counts)
        followers = _optional_int(base_row["粉丝数"])
        events = _optional_int(base_row["每月活动数"])
        if followers is None:
            rows.append(_no_payment_row(base_row, status=_STATUS_NEEDS_FOLLOWERS))
        elif events is None:
            rows.append(_no_payment_row(base_row, status=_STATUS_NEEDS_EVENTS))
        else:
            rank, reward, event_threshold, expected_cpm = _rank_for_long_term(
                followers,
                0,
                events,
            )
            rows.append(
                _no_payment_row(
                    base_row,
                    status=_STATUS_NOT_REACHED,
                    rank=rank,
                    reward=reward,
                    event_threshold=event_threshold,
                    expected_cpm=expected_cpm,
                )
            )

    details = pd.DataFrame(rows, columns=LONG_TERM_COMPENSATION_COLUMNS)
    if details.empty:
        return LongTermCompensationResult(
            details=details,
            total_amount_jpy=0,
            creator_receivable_jpy=0,
            youdao_receivable_jpy=0,
            creator_receivable_usd=0.0,
            youdao_receivable_usd=0.0,
            settled_views=0,
            total_video_views=0,
            overall_cpm=None,
        )

    settled_rows = details.loc[
        details["结算状态"].isin([_STATUS_READY, _STATUS_NOT_REACHED])
    ]
    settled_views = _numeric_total(settled_rows, "月度新投稿播放量")
    total_video_views = _numeric_total(
        settled_rows, "CPM计算播放量（无加成）"
    )
    youdao_receivable_usd = float(
        pd.to_numeric(
            settled_rows["有道应收（美元）（包含服务费）"], errors="coerce"
        )
        .fillna(0)
        .sum()
    )
    return LongTermCompensationResult(
        details=details,
        total_amount_jpy=_numeric_total(settled_rows, "总金额（日元）"),
        creator_receivable_jpy=_numeric_total(
            settled_rows,
            "博主应收（日元）(包含15$手续费)",
        ),
        youdao_receivable_jpy=_numeric_total(
            settled_rows,
            "有道应收（日元）（包含服务费）",
        ),
        creator_receivable_usd=float(
            pd.to_numeric(settled_rows["博主应收（美元）"], errors="coerce")
            .fillna(0)
            .sum()
        ),
        youdao_receivable_usd=youdao_receivable_usd,
        settled_views=settled_views,
        total_video_views=total_video_views,
        overall_cpm=(
            youdao_receivable_usd / total_video_views * 1_000
            if total_video_views > 0
            else None
        ),
    )
