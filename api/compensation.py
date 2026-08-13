from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

import pandas as pd
from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from core.commentary_compensation import (
    COMMENTARY_COLUMNS,
    _video_url_key,
    calculate_commentary_compensation,
    commentary_contract_mode,
)
from core.cross_industry import exclude_cross_industry_posts
from core.dashboard_processor import filter_dashboard_data
from core.grassroot_compensation import (
    COMPENSATION_COLUMNS,
    calculate_grassroot_compensation,
)
from core.long_term_compensation import (
    LONG_TERM_COMPENSATION_COLUMNS,
    calculate_long_term_compensation,
)
from core.traffic_boost import is_july_traffic_boost_month
from database.dashboard_repository import (
    DashboardRepository,
    ThemeSubmissionRevisionExpiredError,
)
from database.db import connect, init_db
from database.koc_repository import KOCRepository
from models.enums import CreatorCategory

from api.dashboard import _load_enriched_posts
from api.dashboard_support import validation_error
from api.idempotency import IdempotencyCache

MAX_PAGE_SIZE = 100

# Fields a client may never set directly; always server-controlled from the
# session (see 19.6.7 audit convention / 19.5.3 lock endpoint constraint).
_SERVER_CONTROLLED_FIELDS = {"operator_name", "operator", "session_id"}


GRASSROOT_SORT_WHITELIST = {
    "total_amount_jpy",
    "-total_amount_jpy",
    "billable_views",
    "-billable_views",
    "all_video_views",
    "-all_video_views",
    "cpm",
    "-cpm",
    "creator_key",
    "-creator_key",
}
LONG_TERM_SORT_WHITELIST = {
    "total_amount_jpy",
    "-total_amount_jpy",
    "monthly_new_post_views",
    "-monthly_new_post_views",
    "cpm",
    "-cpm",
    "creator_key",
    "-creator_key",
}
COMMENTARY_SORT_WHITELIST = {
    "total_amount_jpy",
    "-total_amount_jpy",
    "all_paid_views",
    "-all_paid_views",
    "cpm",
    "-cpm",
    "creator_key",
    "-creator_key",
}
CATEGORY_VALUES = {"GRASSROOT", "LONG_TERM", "COMMENTARY"}
REVIEW_STATUS_VALUES = {"PENDING", "APPROVED", "REJECTED"}


def _month_end(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1) - timedelta(days=1)
    return date(value.year, value.month + 1, 1) - timedelta(days=1)


def _parse_period_month(period_month: str | None, field: str = "period_month") -> date:
    if not period_month:
        raise validation_error(f"{field} 是必填参数。", field)
    try:
        year_text, month_text = period_month.split("-")
        year = int(year_text)
        month = int(month_text)
        if not (1 <= month <= 12) or len(year_text) != 4 or len(month_text) != 2:
            raise ValueError
        return date(year, month, 1)
    except (ValueError, AttributeError) as exc:
        raise validation_error(
            f"{field} 必须是合法的 YYYY-MM 格式：{period_month}", field
        ) from exc


def _month_data(data: pd.DataFrame, selected_month: date) -> pd.DataFrame:
    return exclude_cross_industry_posts(
        filter_dashboard_data(
            data, start_date=selected_month, end_date=_month_end(selected_month)
        )
    )


def _none_if_na(value: Any) -> Any:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _int_or_none(value: Any) -> int | None:
    value = _none_if_na(value)
    if value is None:
        return None
    return int(value)


def _float_or_none(value: Any) -> float | None:
    value = _none_if_na(value)
    if value is None:
        return None
    return float(value)


def _text_or_none(value: Any) -> str | None:
    value = _none_if_na(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _split_contract_types(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(part).strip() for part in value if str(part).strip()]
    text = _text_or_none(value)
    if not text or text in ("未匹配", "未设置"):
        return []
    return [part for part in text.split("、") if part]


def _row_value(row: Any, *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if _none_if_na(value) is not None:
            return value
    return None


def _contract_text(value: Any) -> str | None:
    contract_types = _split_contract_types(value)
    return "、".join(contract_types) if contract_types else None


def _grassroot_api_row(row: Any) -> dict[str, Any]:
    cross_lane = _row_value(row, "cross_lane")
    if not isinstance(cross_lane, dict):
        cross_types = _text_or_none(_row_value(row, "跨赛道类型"))
        cross_lane = None
        if cross_types:
            cross_lane = {
                "types": cross_types,
                "post_count": _int_or_none(_row_value(row, "跨赛道活动投稿数")) or 0,
                "original_views": _int_or_none(_row_value(row, "跨赛道原始播放量")) or 0,
                "boosted_views": _int_or_none(_row_value(row, "跨赛道加成后播放量")) or 0,
                "rank": _text_or_none(_row_value(row, "跨赛道 rank")),
                "rank_reward_jpy": _int_or_none(_row_value(row, "跨赛道 rank金额")) or 0,
                "post_reward_jpy": _int_or_none(_row_value(row, "跨赛道投稿数奖励")) or 0,
                "amount_jpy": _int_or_none(_row_value(row, "跨赛道结算金额")) or 0,
                "urls": [
                    url
                    for url in str(_row_value(row, "跨赛道视频链接") or "").split("\n")
                    if url
                ],
            }

    rewards = _row_value(row, "rewards_jpy")
    if not isinstance(rewards, dict):
        rewards = {}

    return {
        "creator_key": _row_value(row, "creator_key", "user_id"),
        "creator_name": _row_value(row, "creator_name", "达人"),
        "contract_types": _split_contract_types(
            _row_value(row, "contract_types", "合同类型")
        ),
        "settlement_status": _row_value(row, "settlement_status", "结算状态"),
        "rank": _text_or_none(_row_value(row, "rank")),
        "settlement_subtype": _text_or_none(
            _row_value(row, "settlement_subtype", "计费 subtype")
        ),
        "followers": _int_or_none(_row_value(row, "followers", "粉丝数")),
        "youtube_followers": _int_or_none(
            _row_value(row, "youtube_followers", "YouTube粉丝数")
        ),
        "tiktok_followers": _int_or_none(
            _row_value(row, "tiktok_followers", "TikTok粉丝数")
        ),
        "billable_post_count": _int_or_none(
            _row_value(row, "billable_post_count", "投稿数")
        ) or 0,
        "billable_views": _int_or_none(
            _row_value(row, "billable_views", "计费播放量")
        ) or 0,
        "contract_billable_views": _int_or_none(
            _row_value(row, "contract_billable_views", "合同内计费播放量")
        ) or 0,
        "all_video_views": _int_or_none(
            _row_value(row, "all_video_views", "全部视频类型播放量")
        ) or 0,
        "cpm_views_no_boost": _int_or_none(
            _row_value(row, "cpm_views_no_boost", "CPM计算播放量（无加成）")
        ) or 0,
        "cross_lane": cross_lane,
        "rewards_jpy": {
            "short_rank": _int_or_none(
                rewards.get("short_rank", _row_value(row, "short rank金额"))
            ) or 0,
            "long_livestream_rank": _int_or_none(
                rewards.get(
                    "long_livestream_rank",
                    _row_value(row, "long+livestreamrank金额"),
                )
            ) or 0,
            "short_post": _int_or_none(
                rewards.get("short_post", _row_value(row, "short 投稿数奖励"))
            ) or 0,
            "long_livestream_post": _int_or_none(
                rewards.get(
                    "long_livestream_post",
                    _row_value(row, "long+livestream投稿数奖励"),
                )
            ) or 0,
        },
        "total_amount_jpy": _int_or_none(
            _row_value(row, "total_amount_jpy", "总金额（日元）")
        ) or 0,
        "creator_receivable_jpy": _int_or_none(
            _row_value(
                row,
                "creator_receivable_jpy",
                "博主应收（日元）(包含15$手续费)",
            )
        ) or 0,
        "youdao_receivable_jpy": _int_or_none(
            _row_value(
                row,
                "youdao_receivable_jpy",
                "有道应收（日元）（包含服务费）",
            )
        ) or 0,
        "creator_receivable_usd": _float_or_none(
            _row_value(row, "creator_receivable_usd", "博主应收（美元）")
        ) or 0.0,
        "youdao_receivable_usd": _float_or_none(
            _row_value(
                row,
                "youdao_receivable_usd",
                "有道应收（美元）（包含服务费）",
            )
        ) or 0.0,
        "cpm": _float_or_none(_row_value(row, "cpm", "CPM")),
    }


def _long_term_api_row(row: Any) -> dict[str, Any]:
    return {
        "record_id": _int_or_none(_row_value(row, "record_id", "记录ID")),
        "creator_key": _row_value(row, "creator_key", "user_id"),
        "creator_name": _row_value(row, "creator_name", "达人"),
        "contract_types": _split_contract_types(
            _row_value(row, "contract_types", "合同类型")
        ),
        "contract_start_date": _text_or_none(
            _row_value(row, "contract_start_date", "合同开始日期")
        ),
        "contract_end_date": _text_or_none(
            _row_value(row, "contract_end_date", "合同截止日期")
        ),
        "settlement_status": _row_value(row, "settlement_status", "结算状态"),
        "rank": _text_or_none(_row_value(row, "rank")),
        "followers": _int_or_none(_row_value(row, "followers", "粉丝数")),
        "youtube_post_count": _int_or_none(
            _row_value(row, "youtube_post_count", "YouTube 投稿数")
        ) or 0,
        "monthly_new_post_views": _int_or_none(
            _row_value(row, "monthly_new_post_views", "月度新投稿播放量")
        ) or 0,
        "cpm_views_no_boost": _int_or_none(
            _row_value(row, "cpm_views_no_boost", "CPM计算播放量（无加成）")
        ) or 0,
        "monthly_activity_count": _int_or_none(
            _row_value(row, "monthly_activity_count", "每月活动数")
        ),
        "activity_threshold": _int_or_none(
            _row_value(row, "activity_threshold", "活动数门槛")
        ),
        "rank_reward_jpy": _int_or_none(
            _row_value(row, "rank_reward_jpy", "rank金额")
        ) or 0,
        "expected_cpm_jpy": _int_or_none(
            _row_value(row, "expected_cpm_jpy", "预计 CPM（日元）")
        ),
        "total_amount_jpy": _int_or_none(
            _row_value(row, "total_amount_jpy", "总金额（日元）")
        ) or 0,
        "creator_receivable_jpy": _int_or_none(
            _row_value(
                row,
                "creator_receivable_jpy",
                "博主应收（日元）(包含15$手续费)",
            )
        ) or 0,
        "youdao_receivable_jpy": _int_or_none(
            _row_value(
                row,
                "youdao_receivable_jpy",
                "有道应收（日元）（包含服务费）",
            )
        ) or 0,
        "creator_receivable_usd": _float_or_none(
            _row_value(row, "creator_receivable_usd", "博主应收（美元）")
        ) or 0.0,
        "youdao_receivable_usd": _float_or_none(
            _row_value(
                row,
                "youdao_receivable_usd",
                "有道应收（美元）（包含服务费）",
            )
        ) or 0.0,
        "cpm": _float_or_none(_row_value(row, "cpm", "CPM")),
    }


def _commentary_api_row(row: Any) -> dict[str, Any]:
    mappings = {
        "creator_id": ("creator_id",),
        "creator_key": ("creator_key", "UID"),
        "creator_name": ("creator_name", "达人"),
        "settlement_status": ("settlement_status", "结算状态"),
        "youtube_uid": ("youtube_uid", "YouTube UID"),
        "youtube_followers": ("youtube_followers", "YouTube粉丝数"),
        "tiktok_uid": ("tiktok_uid", "TikTok UID"),
        "tiktok_followers": ("tiktok_followers", "TikTok粉丝数"),
        "short_platform": ("short_platform", "短视频平台"),
        "long_views": ("long_views", "长视频播放量"),
        "long_view_rank": ("long_view_rank", "长视频播放等级"),
        "long_follower_cap_rank": ("long_follower_cap_rank", "长视频粉丝上限等级"),
        "long_final_rank": ("long_final_rank", "长视频最终等级"),
        "long_reward_jpy": ("long_reward_jpy", "长视频报酬（日元）"),
        "short_views": ("short_views", "短视频播放量"),
        "short_view_rank": ("short_view_rank", "短视频播放等级"),
        "short_follower_cap_rank": ("short_follower_cap_rank", "短视频粉丝上限等级"),
        "short_final_rank": ("short_final_rank", "短视频最终等级"),
        "short_reward_jpy": ("short_reward_jpy", "短视频报酬（日元）"),
        "combined_bonus_rank": ("combined_bonus_rank", "并用奖金等级"),
        "combined_bonus_jpy": ("combined_bonus_jpy", "并用奖金（日元）"),
        "designated_theme_count": ("designated_theme_count", "指定主题件数"),
        "designated_theme_reward_jpy": (
            "designated_theme_reward_jpy",
            "指定主题报酬（日元）",
        ),
        "all_paid_views": ("all_paid_views", "全部已付费内容播放量"),
        "total_jpy_tax_incl": ("total_jpy_tax_incl", "解说含税总额（日元）"),
        "creator_receivable_jpy": (
            "creator_receivable_jpy",
            "博主应收（日元）(包含15$手续费)",
        ),
        "youdao_receivable_jpy": (
            "youdao_receivable_jpy",
            "有道应收（日元）（包含服务费）",
        ),
        "creator_receivable_usd": ("creator_receivable_usd", "博主应收（美元）"),
        "youdao_receivable_usd": (
            "youdao_receivable_usd",
            "有道应收（美元）（包含服务费）",
        ),
        "cpm": ("cpm", "CPM"),
    }
    result = {key: _row_value(row, *keys) for key, keys in mappings.items()}
    result["creator_id"] = _int_or_none(result["creator_id"])
    result["contract_types"] = _split_contract_types(
        _row_value(row, "contract_types", "合同类型")
    )
    integer_fields = {
        "youtube_followers",
        "tiktok_followers",
        "long_views",
        "long_reward_jpy",
        "short_views",
        "short_reward_jpy",
        "combined_bonus_jpy",
        "designated_theme_count",
        "designated_theme_reward_jpy",
        "all_paid_views",
        "total_jpy_tax_incl",
        "creator_receivable_jpy",
        "youdao_receivable_jpy",
    }
    for field in integer_fields:
        result[field] = _int_or_none(result[field]) or 0
    result["creator_receivable_usd"] = _float_or_none(
        result["creator_receivable_usd"]
    ) or 0.0
    result["youdao_receivable_usd"] = _float_or_none(
        result["youdao_receivable_usd"]
    ) or 0.0
    result["cpm"] = _float_or_none(result["cpm"])
    return result


def _legacy_grassroot_row(row: Any) -> dict[str, Any]:
    api_row = _grassroot_api_row(row)
    cross_lane = api_row.get("cross_lane") or {}
    rewards = api_row["rewards_jpy"]
    return {
        "user_id": api_row["creator_key"],
        "达人": api_row["creator_name"],
        "合同类型": _contract_text(api_row["contract_types"]),
        "粉丝数": api_row["followers"],
        "YouTube粉丝数": api_row["youtube_followers"],
        "TikTok粉丝数": api_row["tiktok_followers"],
        "计费 subtype": api_row["settlement_subtype"],
        "合同内计费播放量": api_row["contract_billable_views"],
        "跨赛道类型": cross_lane.get("types"),
        "跨赛道活动投稿数": cross_lane.get("post_count", 0),
        "跨赛道原始播放量": cross_lane.get("original_views", 0),
        "跨赛道加成后播放量": cross_lane.get("boosted_views", 0),
        "跨赛道 rank": cross_lane.get("rank"),
        "跨赛道 rank金额": cross_lane.get("rank_reward_jpy", 0),
        "跨赛道投稿数奖励": cross_lane.get("post_reward_jpy", 0),
        "跨赛道结算金额": cross_lane.get("amount_jpy", 0),
        "跨赛道视频链接": "\n".join(cross_lane.get("urls", [])),
        "计费播放量": api_row["billable_views"],
        "全部视频类型播放量": api_row["all_video_views"],
        "CPM计算播放量（无加成）": api_row["cpm_views_no_boost"],
        "投稿数": api_row["billable_post_count"],
        "结算状态": api_row["settlement_status"],
        "rank": api_row["rank"],
        "short rank金额": rewards["short_rank"],
        "long+livestreamrank金额": rewards["long_livestream_rank"],
        "short 投稿数奖励": rewards["short_post"],
        "long+livestream投稿数奖励": rewards["long_livestream_post"],
        "总金额（日元）": api_row["total_amount_jpy"],
        "博主应收（日元）(包含15$手续费)": api_row["creator_receivable_jpy"],
        "有道应收（日元）（包含服务费）": api_row["youdao_receivable_jpy"],
        "博主应收（美元）": api_row["creator_receivable_usd"],
        "有道应收（美元）（包含服务费）": api_row["youdao_receivable_usd"],
        "CPM": api_row["cpm"],
    }


def _legacy_long_term_row(row: Any) -> dict[str, Any]:
    api_row = _long_term_api_row(row)
    mapping = {
        "记录ID": "record_id",
        "user_id": "creator_key",
        "达人": "creator_name",
        "合同开始日期": "contract_start_date",
        "合同截止日期": "contract_end_date",
        "粉丝数": "followers",
        "YouTube 投稿数": "youtube_post_count",
        "月度新投稿播放量": "monthly_new_post_views",
        "CPM计算播放量（无加成）": "cpm_views_no_boost",
        "每月活动数": "monthly_activity_count",
        "活动数门槛": "activity_threshold",
        "结算状态": "settlement_status",
        "rank": "rank",
        "rank金额": "rank_reward_jpy",
        "预计 CPM（日元）": "expected_cpm_jpy",
        "总金额（日元）": "total_amount_jpy",
        "博主应收（日元）(包含15$手续费)": "creator_receivable_jpy",
        "有道应收（日元）（包含服务费）": "youdao_receivable_jpy",
        "博主应收（美元）": "creator_receivable_usd",
        "有道应收（美元）（包含服务费）": "youdao_receivable_usd",
        "CPM": "cpm",
    }
    result = {legacy: api_row[api] for legacy, api in mapping.items()}
    result["合同类型"] = _contract_text(api_row["contract_types"])
    return result


def _legacy_commentary_row(row: Any) -> dict[str, Any]:
    api_row = _commentary_api_row(row)
    mapping = {
        "creator_id": "creator_id",
        "UID": "creator_key",
        "达人": "creator_name",
        "结算状态": "settlement_status",
        "YouTube UID": "youtube_uid",
        "YouTube粉丝数": "youtube_followers",
        "TikTok UID": "tiktok_uid",
        "TikTok粉丝数": "tiktok_followers",
        "短视频平台": "short_platform",
        "长视频播放量": "long_views",
        "长视频播放等级": "long_view_rank",
        "长视频粉丝上限等级": "long_follower_cap_rank",
        "长视频最终等级": "long_final_rank",
        "长视频报酬（日元）": "long_reward_jpy",
        "短视频播放量": "short_views",
        "短视频播放等级": "short_view_rank",
        "短视频粉丝上限等级": "short_follower_cap_rank",
        "短视频最终等级": "short_final_rank",
        "短视频报酬（日元）": "short_reward_jpy",
        "并用奖金等级": "combined_bonus_rank",
        "并用奖金（日元）": "combined_bonus_jpy",
        "指定主题件数": "designated_theme_count",
        "指定主题报酬（日元）": "designated_theme_reward_jpy",
        "全部已付费内容播放量": "all_paid_views",
        "解说含税总额（日元）": "total_jpy_tax_incl",
        "博主应收（日元）(包含15$手续费)": "creator_receivable_jpy",
        "有道应收（日元）（包含服务费）": "youdao_receivable_jpy",
        "博主应收（美元）": "creator_receivable_usd",
        "有道应收（美元）（包含服务费）": "youdao_receivable_usd",
        "CPM": "cpm",
    }
    result = {legacy: api_row[api] for legacy, api in mapping.items()}
    result["合同类型"] = _contract_text(api_row["contract_types"])
    return result


def _legacy_details(lane: str, rows: list[dict[str, Any]]) -> pd.DataFrame:
    converters = {
        "grassroot": (_legacy_grassroot_row, COMPENSATION_COLUMNS),
        "long-term": (_legacy_long_term_row, LONG_TERM_COMPENSATION_COLUMNS),
        "commentary": (_legacy_commentary_row, COMMENTARY_COLUMNS),
    }
    converter, columns = converters[lane]
    return pd.DataFrame([converter(row) for row in rows], columns=columns)


def _paginate(
    rows: list[dict], *, page: int, page_size: int
) -> tuple[list[dict], dict]:
    total_items = len(rows)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    start = (page - 1) * page_size
    page_rows = rows[start : start + page_size]
    return page_rows, {
        "page": page,
        "page_size": page_size,
        "total_items": total_items,
        "total_pages": total_pages,
    }


def _validate_pagination(page: int, page_size: int) -> None:
    if page < 1:
        raise validation_error("page 必须大于等于 1。", "page")
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise validation_error(f"page_size 必须在 1 到 {MAX_PAGE_SIZE} 之间。", "page_size")


_FOLLOWERS_NOT_UPDATED_STATUSES = {"待补充粉丝数", "未更新粉丝数"}


def _status_summary(details: pd.DataFrame, row_converter) -> dict[str, int]:
    counts = {
        "settleable_creator_count": 0,
        "not_reached_creator_count": 0,
        "followers_not_updated_count": 0,
    }
    for _, row in details.iterrows():
        status = _text_or_none(row_converter(row).get("settlement_status"))
        if status == "可结算":
            counts["settleable_creator_count"] += 1
        elif status == "未达标":
            counts["not_reached_creator_count"] += 1
        elif status in _FOLLOWERS_NOT_UPDATED_STATUSES:
            counts["followers_not_updated_count"] += 1
    return counts


def _summary_dict(result, row_converter) -> dict[str, Any]:
    summary = {
        "total_amount_jpy": int(result.total_amount_jpy),
        "creator_receivable_jpy": int(result.creator_receivable_jpy),
        "youdao_receivable_jpy": int(result.youdao_receivable_jpy),
        "creator_receivable_usd": float(result.creator_receivable_usd),
        "youdao_receivable_usd": float(result.youdao_receivable_usd),
        "settled_views": int(result.settled_views),
        "total_video_views": int(result.total_video_views),
        "overall_cpm": _float_or_none(result.overall_cpm),
    }
    summary.update(_status_summary(result.details, row_converter))
    return summary


def _stored_summary_dict(
    summary: dict[str, Any],
    details: pd.DataFrame,
    row_converter,
) -> dict[str, Any]:
    result = {
        "total_amount_jpy": int(summary.get("total_amount_jpy", 0)),
        "creator_receivable_jpy": int(summary.get("creator_receivable_jpy", 0)),
        "youdao_receivable_jpy": int(summary.get("youdao_receivable_jpy", 0)),
        "creator_receivable_usd": float(summary.get("creator_receivable_usd", 0)),
        "youdao_receivable_usd": float(summary.get("youdao_receivable_usd", 0)),
        "settled_views": int(summary.get("settled_views", 0)),
        "total_video_views": int(summary.get("total_video_views", 0)),
        "overall_cpm": _float_or_none(summary.get("overall_cpm")),
    }
    result.update(_status_summary(details, row_converter))
    return result


def _calculation_meta(cache, *, source: str = "cache") -> dict[str, Any]:
    return {
        "source": source,
        "status": cache.status,
        "is_stale": cache.status == "STALE",
        "calculation_version": cache.calculation_version,
        "calculated_at": cache.calculated_at,
        "invalidated_at": cache.invalidated_at,
        "stale_reason": cache.stale_reason,
        "calculated_with_jpy_to_usd_rate": cache.jpy_to_usd_rate,
        "calculated_with_traffic_boost_enabled": cache.traffic_boost_enabled,
    }


def _version_meta(version) -> dict[str, Any]:
    return {
        "version_id": version.id,
        "version_no": version.version_no,
        "status": version.status,
        "created_at": version.created_at,
        "updated_at": version.updated_at,
        "locked_at": version.locked_at,
    }


def _currency_block(*, include_traffic_boost: bool) -> dict[str, Any]:
    return {
        "base": "JPY",
        "usd_fields": ["creator_receivable_usd", "youdao_receivable_usd", "cpm"],
        "handling_fee_usd": 15.0,
        "service_fee_multiplier": 1.15,
        "rounding": (
            "receivable_jpy=int(round); usd/cpm=unrounded float; "
            "zero-amount rows skip fee/multiplier entirely"
        ),
    }


def _find_version(versions: list, version_id: int):
    for version in versions:
        if version.id == version_id:
            return version
    return None


def _mode_for_status(status: str) -> str:
    return "frozen" if status == "LOCKED" else "saved_draft"


def _error_response(status_code: int, code: str, message: str, field: str | None = None) -> HTTPException:
    detail: dict[str, Any] = {"error": {"code": code, "message": message}}
    if field is not None:
        detail["error"]["field_errors"] = [{"field": field, "message": message}]
    return HTTPException(status_code=status_code, detail=detail)


def _not_found_error(message: str) -> HTTPException:
    return _error_response(404, "NOT_FOUND", message)


def _conflict_error(code: str, message: str) -> HTTPException:
    return _error_response(409, code, message)


def _strip_server_controlled(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key not in _SERVER_CONTROLLED_FIELDS}


def _clean_lock_note_field(payload: dict) -> str:
    if "lock_note" not in payload or payload.get("lock_note") in (None, ""):
        raise validation_error("lock_note 是必填字段，长度须为 1-500 个字符。", "lock_note")
    lock_note = str(payload["lock_note"]).strip()
    if not (1 <= len(lock_note) <= 500):
        raise validation_error("lock_note 长度须为 1-500 个字符。", "lock_note")
    return lock_note


def _serialize_version(version) -> dict:
    details = version.details
    if details is None or (hasattr(details, "empty") and details.empty):
        details_records: list[dict] = []
    else:
        details_records = (
            details.astype("object").where(pd.notna(details), None).to_dict("records")
        )
    return {
        "id": version.id,
        "period_month": version.period_month,
        "version_no": version.version_no,
        "status": version.status,
        "jpy_to_usd_rate": version.jpy_to_usd_rate,
        "details": details_records,
        "summary": version.summary,
        "note": version.note,
        "created_at": version.created_at,
        "updated_at": version.updated_at,
        "locked_at": version.locked_at,
        "lock_note": version.lock_note,
        "locked_by": version.locked_by,
    }


def build_compensation_router(
    *,
    database_path,
    require_session: Callable,
    session_context: Callable | None = None,
) -> APIRouter:
    router = APIRouter(dependencies=[require_session])
    idempotency_cache = IdempotencyCache()

    def _repository() -> DashboardRepository:
        return DashboardRepository(database_path)

    def _creator_repository() -> KOCRepository:
        return KOCRepository(database_path)

    def _calculate_current_cache(category: str, period_key: str, selected_month):
        repository = _repository()
        jpy_to_usd_rate = repository.get_jpy_to_usd_rate(period_key)
        if jpy_to_usd_rate is None:
            raise validation_error("该月尚未保存 JPY→USD 汇率", "jpy_to_usd_rate")
        traffic_boost_enabled = (
            repository.get_traffic_boost_enabled(period_key)
            if category in {"GRASSROOT", "LONG_TERM"}
            and is_july_traffic_boost_month(selected_month)
            else False
        )
        data, _creator_records = _load_enriched_posts(database_path)
        creator_repository = _creator_repository()
        creator_records = creator_repository.list(include_inactive=True)
        month_data = _month_data(data, selected_month)

        if category == "GRASSROOT":
            result = calculate_grassroot_compensation(
                month_data,
                creator_records,
                jpy_to_usd_rate=jpy_to_usd_rate,
                traffic_boost_enabled=traffic_boost_enabled,
            )
            summary = _summary_dict(result, _grassroot_api_row)
        elif category == "LONG_TERM":
            long_term_records = [
                record
                for record in creator_records
                if CreatorCategory.LONG_TERM in record.creator_categories
            ]
            result = calculate_long_term_compensation(
                month_data,
                long_term_records,
                jpy_to_usd_rate=jpy_to_usd_rate,
                event_counts=repository.get_long_term_activity_counts(period_key),
                period_start=selected_month,
                period_end=_month_end(selected_month),
                traffic_boost_enabled=traffic_boost_enabled,
            )
            summary = _summary_dict(result, _long_term_api_row)
        elif category == "COMMENTARY":
            commentary_records = [
                record
                for record in creator_records
                if CreatorCategory.COMMENTARY in record.creator_categories
            ]
            result = calculate_commentary_compensation(
                month_data,
                commentary_records,
                period_month=period_key,
                jpy_to_usd_rate=jpy_to_usd_rate,
                profile_history=creator_repository.list_profile_history(),
                theme_submissions=repository.list_commentary_theme_submissions(period_key),
                theme_definitions=repository.list_commentary_theme_definitions(period_key),
            )
            summary = _summary_dict(result, _commentary_api_row)
        else:
            raise validation_error("无效的结算类别。", "category")

        return repository.save_compensation_calculation_cache(
            period_key,
            category,
            jpy_to_usd_rate=jpy_to_usd_rate,
            traffic_boost_enabled=traffic_boost_enabled,
            details=result.details,
            summary=summary,
        )

    def _current_or_initial_cache(category: str, period_key: str, selected_month):
        repository = _repository()
        cache = repository.get_compensation_calculation_cache(period_key, category)
        if cache is None:
            cache = _calculate_current_cache(category, period_key, selected_month)
        return cache

    def _run_idempotent(
        *,
        operation: str,
        ctx: dict,
        idempotency_key: str | None,
        payload: dict,
        execute: Callable[[], tuple[int, dict]],
    ) -> JSONResponse:
        session_id = ctx.get("session_id", "") if isinstance(ctx, dict) else ""
        if idempotency_key:
            body_hash = IdempotencyCache.hash_body(payload)
            cached = idempotency_cache.lookup(operation, session_id, idempotency_key)
            if cached is not None:
                if cached.body_hash != body_hash:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "error": {
                                "code": "IDEMPOTENCY_KEY_REUSED",
                                "message": "该幂等键已用于不同的请求内容，请更换新的 Idempotency-Key。",
                            }
                        },
                    )
                return JSONResponse(status_code=cached.status_code, content=cached.body)
            status_code, body = execute()
            idempotency_cache.store(
                operation,
                session_id,
                idempotency_key,
                body_hash=body_hash,
                status_code=status_code,
                body=body,
            )
            return JSONResponse(status_code=status_code, content=body)
        status_code, body = execute()
        return JSONResponse(status_code=status_code, content=body)

    # ------------------------------------------------------------------
    # 18.1 periods
    # ------------------------------------------------------------------
    @router.get("/api/compensation/periods")
    def periods(category: str | None = Query(default=None)) -> dict:
        if category is not None and category not in CATEGORY_VALUES:
            raise validation_error(f"无效的 category 取值：{category}", "category")

        data, _creator_records = _load_enriched_posts(database_path)
        repository = _repository()

        post_months: set[str] = set()
        if not data.empty and "publish_date" in data:
            dates = pd.to_datetime(data["publish_date"], errors="coerce").dropna()
            post_months = set(dates.dt.strftime("%Y-%m").unique().tolist())

        init_db(database_path)
        with connect(database_path) as connection:
            grassroot_months = {
                str(row["period_month"])
                for row in connection.execute(
                    "SELECT DISTINCT period_month FROM grassroot_compensation_version"
                ).fetchall()
            }
            long_term_months = {
                str(row["period_month"])
                for row in connection.execute(
                    "SELECT DISTINCT period_month FROM long_term_compensation_version"
                ).fetchall()
            }
            commentary_months = {
                str(row["period_month"])
                for row in connection.execute(
                    "SELECT DISTINCT period_month FROM commentary_compensation_version"
                ).fetchall()
            }

        all_months = post_months | grassroot_months | long_term_months | commentary_months
        if category == "GRASSROOT":
            all_months = post_months | grassroot_months
        elif category == "LONG_TERM":
            all_months = post_months | long_term_months
        elif category == "COMMENTARY":
            all_months = post_months | commentary_months

        def _version_summary(months_set: set[str], month: str) -> dict:
            if month not in months_set:
                return {"count": 0, "has_locked": False}
            return None  # placeholder, replaced below

        rows = []
        for month in sorted(all_months, reverse=True):
            month_start = _parse_period_month(month)
            traffic_boost_applicable = is_july_traffic_boost_month(month_start)
            traffic_boost_enabled = (
                repository.get_traffic_boost_enabled(month)
                if traffic_boost_applicable
                else False
            )

            def _counts(list_fn) -> dict:
                versions = list_fn(month)
                return {
                    "count": len(versions),
                    "has_locked": any(v.status == "LOCKED" for v in versions),
                }

            entry = {
                "period_month": month,
                "has_posts": month in post_months,
                "traffic_boost_applicable": traffic_boost_applicable,
                "traffic_boost_enabled": traffic_boost_enabled,
                "versions": {
                    "grassroot": _counts(repository.list_compensation_versions),
                    "long_term": _counts(repository.list_long_term_compensation_versions),
                    "commentary": _counts(repository.list_commentary_compensation_versions),
                },
            }
            rows.append(entry)

        return {"data": rows, "meta": {}}

    # ------------------------------------------------------------------
    # 18.2 grassroot
    # ------------------------------------------------------------------
    @router.get("/api/compensation/grassroot")
    def grassroot(
        period_month: str = Query(...),
        version_id: int | None = Query(default=None),
        settlement_status: list[str] | None = Query(default=None),
        q: str = Query(default=""),
        page: int = Query(default=1),
        page_size: int = Query(default=20),
        sort: str = Query(default="-total_amount_jpy"),
    ) -> dict:
        if sort not in GRASSROOT_SORT_WHITELIST:
            raise validation_error(f"无效的 sort 取值：{sort}", "sort")
        _validate_pagination(page, page_size)
        selected_month = _parse_period_month(period_month)
        period_key = period_month

        repository = _repository()

        if version_id is not None:
            versions = repository.list_compensation_versions(period_key)
            version = _find_version(versions, version_id)
            if version is None:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=404,
                    detail={
                        "error": {
                            "code": "NOT_FOUND",
                            "message": "指定的结算版本不存在。",
                        }
                    },
                )
            details = version.details
            summary = version.summary
            mode = _mode_for_status(version.status)
            jpy_to_usd_rate = version.jpy_to_usd_rate
            traffic_boost_enabled = bool(summary.get("traffic_boost_enabled", False))
            summary_out = _stored_summary_dict(summary, details, _grassroot_api_row)
            version_meta = _version_meta(version)
        else:
            cache = _current_or_initial_cache("GRASSROOT", period_key, selected_month)
            details = cache.details
            summary_out = _stored_summary_dict(cache.summary, details, _grassroot_api_row)
            jpy_to_usd_rate = repository.get_jpy_to_usd_rate(period_key) or cache.jpy_to_usd_rate
            traffic_boost_enabled = (
                repository.get_traffic_boost_enabled(period_key)
                if is_july_traffic_boost_month(selected_month)
                else False
            )
            mode = "preview"
            version_meta = None
            calculation = _calculation_meta(cache)

        rows: list[dict] = []
        for _, row in details.iterrows():
            api_row = _grassroot_api_row(row)
            status = api_row["settlement_status"]
            if settlement_status and status not in settlement_status:
                continue
            creator_key = api_row["creator_key"]
            creator_name = api_row["creator_name"]
            if q:
                query = q.strip().casefold()
                if query and query not in str(creator_key or "").casefold() and query not in str(
                    creator_name or ""
                ).casefold():
                    continue
            rows.append(api_row)

        reverse = sort.startswith("-")
        sort_field = sort[1:] if reverse else sort
        rows.sort(
            key=lambda item: (
                item.get(sort_field) is None,
                item.get(sort_field) if item.get(sort_field) is not None else 0,
            ),
            reverse=reverse,
        )
        if sort_field != "creator_key":
            rows.sort(key=lambda item: str(item.get("creator_key") or ""))
            rows.sort(
                key=lambda item: (
                    item.get(sort_field) if item.get(sort_field) is not None else (
                        float("-inf") if reverse else float("inf")
                    )
                ),
                reverse=reverse,
            )

        page_rows, pagination = _paginate(rows, page=page, page_size=page_size)

        meta = {
            "mode": mode,
            "period_month": period_key,
            "jpy_to_usd_rate": jpy_to_usd_rate,
            "traffic_boost_enabled": traffic_boost_enabled,
            "version": version_meta,
            "currency": _currency_block(include_traffic_boost=True),
            "summary": summary_out,
            "calculation": calculation if version_id is None else {
                "source": "locked_version" if mode == "frozen" else "saved_draft",
                "status": "LOCKED" if mode == "frozen" else "DRAFT",
                "is_stale": False,
                "calculated_at": version_meta.get("updated_at") if version_meta else None,
            },
            "pagination": pagination,
        }
        return {"data": page_rows, "meta": meta}

    # ------------------------------------------------------------------
    # 18.3 long-term
    # ------------------------------------------------------------------
    @router.get("/api/compensation/long-term")
    def long_term(
        period_month: str = Query(...),
        version_id: int | None = Query(default=None),
        settlement_status: list[str] | None = Query(default=None),
        q: str = Query(default=""),
        page: int = Query(default=1),
        page_size: int = Query(default=20),
        sort: str = Query(default="-total_amount_jpy"),
    ) -> dict:
        if sort not in LONG_TERM_SORT_WHITELIST:
            raise validation_error(f"无效的 sort 取值：{sort}", "sort")
        _validate_pagination(page, page_size)
        selected_month = _parse_period_month(period_month)
        period_key = period_month

        repository = _repository()

        if version_id is not None:
            versions = repository.list_long_term_compensation_versions(period_key)
            version = _find_version(versions, version_id)
            if version is None:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=404,
                    detail={"error": {"code": "NOT_FOUND", "message": "指定的结算版本不存在。"}},
                )
            details = version.details
            summary = version.summary
            mode = _mode_for_status(version.status)
            jpy_to_usd_rate = version.jpy_to_usd_rate
            traffic_boost_enabled = bool(summary.get("traffic_boost_enabled", False))
            summary_out = _stored_summary_dict(summary, details, _long_term_api_row)
            version_meta = _version_meta(version)
        else:
            cache = _current_or_initial_cache("LONG_TERM", period_key, selected_month)
            details = cache.details
            summary_out = _stored_summary_dict(cache.summary, details, _long_term_api_row)
            jpy_to_usd_rate = repository.get_jpy_to_usd_rate(period_key) or cache.jpy_to_usd_rate
            traffic_boost_enabled = (
                repository.get_traffic_boost_enabled(period_key)
                if is_july_traffic_boost_month(selected_month)
                else False
            )
            mode = "preview"
            version_meta = None
            calculation = _calculation_meta(cache)

        rows: list[dict] = []
        for _, row in details.iterrows():
            api_row = _long_term_api_row(row)
            status = api_row["settlement_status"]
            if settlement_status and status not in settlement_status:
                continue
            creator_key = api_row["creator_key"]
            creator_name = api_row["creator_name"]
            if q:
                query = q.strip().casefold()
                if query and query not in str(creator_key or "").casefold() and query not in str(
                    creator_name or ""
                ).casefold():
                    continue
            rows.append(api_row)

        reverse = sort.startswith("-")
        sort_field = sort[1:] if reverse else sort
        rows.sort(key=lambda item: str(item.get("creator_key") or ""))
        rows.sort(
            key=lambda item: (
                item.get(sort_field) if item.get(sort_field) is not None else (
                    float("-inf") if reverse else float("inf")
                )
            ),
            reverse=reverse,
        )

        page_rows, pagination = _paginate(rows, page=page, page_size=page_size)

        meta = {
            "mode": mode,
            "period_month": period_key,
            "jpy_to_usd_rate": jpy_to_usd_rate,
            "traffic_boost_enabled": traffic_boost_enabled,
            "version": version_meta,
            "currency": _currency_block(include_traffic_boost=True),
            "summary": summary_out,
            "calculation": calculation if version_id is None else {
                "source": "locked_version" if mode == "frozen" else "saved_draft",
                "status": "LOCKED" if mode == "frozen" else "DRAFT",
                "is_stale": False,
                "calculated_at": version_meta.get("updated_at") if version_meta else None,
            },
            "pagination": pagination,
        }
        return {"data": page_rows, "meta": meta}

    # ------------------------------------------------------------------
    # 18.4 commentary
    # ------------------------------------------------------------------
    @router.get("/api/compensation/commentary")
    def commentary(
        period_month: str = Query(...),
        version_id: int | None = Query(default=None),
        settlement_status: list[str] | None = Query(default=None),
        q: str = Query(default=""),
        page: int = Query(default=1),
        page_size: int = Query(default=20),
        sort: str = Query(default="-total_amount_jpy"),
    ) -> dict:
        if sort not in COMMENTARY_SORT_WHITELIST:
            raise validation_error(f"无效的 sort 取值：{sort}", "sort")
        _validate_pagination(page, page_size)
        selected_month = _parse_period_month(period_month)
        period_key = period_month

        repository = _repository()

        if version_id is not None:
            versions = repository.list_commentary_compensation_versions(period_key)
            version = _find_version(versions, version_id)
            if version is None:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=404,
                    detail={"error": {"code": "NOT_FOUND", "message": "指定的结算版本不存在。"}},
                )
            details = version.details
            summary = version.summary
            mode = _mode_for_status(version.status)
            jpy_to_usd_rate = version.jpy_to_usd_rate
            summary_out = _stored_summary_dict(summary, details, _commentary_api_row)
            version_meta = _version_meta(version)
        else:
            cache = _current_or_initial_cache("COMMENTARY", period_key, selected_month)
            details = cache.details
            summary_out = _stored_summary_dict(cache.summary, details, _commentary_api_row)
            jpy_to_usd_rate = repository.get_jpy_to_usd_rate(period_key) or cache.jpy_to_usd_rate
            mode = "preview"
            version_meta = None
            calculation = _calculation_meta(cache)

        rows: list[dict] = []
        for _, row in details.iterrows():
            api_row = _commentary_api_row(row)
            status = api_row["settlement_status"]
            if settlement_status and status not in settlement_status:
                continue
            creator_key = api_row["creator_key"]
            creator_name = api_row["creator_name"]
            if q:
                query = q.strip().casefold()
                if query and query not in str(creator_key or "").casefold() and query not in str(
                    creator_name or ""
                ).casefold():
                    continue
            rows.append(api_row)

        sort_key_map = {"total_amount_jpy": "total_jpy_tax_incl"}
        reverse = sort.startswith("-")
        raw_sort_field = sort[1:] if reverse else sort
        sort_field = sort_key_map.get(raw_sort_field, raw_sort_field)
        rows.sort(key=lambda item: str(item.get("creator_key") or ""))
        rows.sort(
            key=lambda item: (
                item.get(sort_field) if item.get(sort_field) is not None else (
                    float("-inf") if reverse else float("inf")
                )
            ),
            reverse=reverse,
        )

        page_rows, pagination = _paginate(rows, page=page, page_size=page_size)

        meta = {
            "mode": mode,
            "period_month": period_key,
            "jpy_to_usd_rate": jpy_to_usd_rate,
            "version": version_meta,
            "currency": _currency_block(include_traffic_boost=False),
            "summary": summary_out,
            "calculation": calculation if version_id is None else {
                "source": "locked_version" if mode == "frozen" else "saved_draft",
                "status": "LOCKED" if mode == "frozen" else "DRAFT",
                "is_stale": False,
                "calculated_at": version_meta.get("updated_at") if version_meta else None,
            },
            "pagination": pagination,
        }
        return {"data": page_rows, "meta": meta}

    @router.post("/api/compensation/{lane}/{period_month}/recalculate")
    def recalculate_compensation(lane: str, period_month: str) -> dict:
        category_map = {
            "grassroot": "GRASSROOT",
            "long-term": "LONG_TERM",
            "commentary": "COMMENTARY",
        }
        category = category_map.get(lane)
        if category is None:
            raise validation_error("无效的结算类别。", "lane")
        selected_month = _parse_period_month(period_month)
        cache = _calculate_current_cache(category, period_month, selected_month)
        return {
            "data": {
                "period_month": period_month,
                "category": category,
                "calculation": _calculation_meta(cache),
            }
        }

    # ------------------------------------------------------------------
    # 18.5 versions
    # ------------------------------------------------------------------
    @router.get("/api/compensation/versions")
    def versions(
        period_month: str = Query(...),
        category: str = Query(...),
    ) -> dict:
        _parse_period_month(period_month)
        if category not in CATEGORY_VALUES:
            raise validation_error(f"无效的 category 取值：{category}", "category")

        repository = _repository()
        list_fn = {
            "GRASSROOT": repository.list_compensation_versions,
            "LONG_TERM": repository.list_long_term_compensation_versions,
            "COMMENTARY": repository.list_commentary_compensation_versions,
        }[category]
        version_list = list_fn(period_month)

        rows = []
        for version in version_list:
            summary = version.summary or {}
            rows.append(
                {
                    "version_id": version.id,
                    "version_no": version.version_no,
                    "status": version.status,
                    "schema_version": summary.get("schema_version"),
                    "jpy_to_usd_rate": version.jpy_to_usd_rate,
                    "note": version.note,
                    "created_at": version.created_at,
                    "updated_at": version.updated_at,
                    "locked_at": version.locked_at,
                    "lock_note": version.lock_note,
                    "locked_by": version.locked_by,
                    "summary": {
                        "total_amount_jpy": _int_or_none(summary.get("total_amount_jpy")) or 0,
                        "creator_receivable_jpy": _int_or_none(summary.get("creator_receivable_jpy")) or 0,
                        "youdao_receivable_jpy": _int_or_none(summary.get("youdao_receivable_jpy")) or 0,
                        "creator_receivable_usd": _float_or_none(summary.get("creator_receivable_usd")) or 0.0,
                        "youdao_receivable_usd": _float_or_none(summary.get("youdao_receivable_usd")) or 0.0,
                        "settled_views": _int_or_none(summary.get("settled_views")) or 0,
                        "total_video_views": _int_or_none(summary.get("total_video_views")) or 0,
                        "overall_cpm": _float_or_none(summary.get("overall_cpm")),
                    },
                }
            )

        return {
            "data": rows,
            "meta": {"period_month": period_month, "category": category},
        }

    # ------------------------------------------------------------------
    # 18.6 commentary theme submissions
    # ------------------------------------------------------------------
    @router.get("/api/compensation/commentary/theme-submissions")
    def theme_submissions(
        period_month: str = Query(...),
        creator_id: list[int] | None = Query(default=None),
        review_status: list[str] | None = Query(default=None),
    ) -> dict:
        _parse_period_month(period_month)
        if review_status:
            for value in review_status:
                if value not in REVIEW_STATUS_VALUES:
                    raise validation_error(
                        f"无效的 review_status 取值：{value}", "review_status"
                    )

        repository = _repository()
        creator_repository = _creator_repository()

        submissions = repository.list_commentary_theme_submissions(period_month)
        definitions = repository.list_commentary_theme_definitions(period_month)

        data, _creator_records = _load_enriched_posts(database_path)
        selected_month = _parse_period_month(period_month)
        month_data = _month_data(data, selected_month)

        creator_records = creator_repository.list(include_inactive=True)
        profile_history = creator_repository.list_profile_history()
        period_end = _month_end(selected_month)

        creator_modes: dict[int, str] = {}
        for record in creator_records:
            from core.commentary_compensation import _profile_at_month_end

            profile = _profile_at_month_end(record, profile_history, period_end)
            mode = commentary_contract_mode("、".join(profile.contract_types))
            if mode is not None:
                creator_modes[record.id] = mode

        month_url_keys: set[str] = set()
        if not month_data.empty and "url" in month_data:
            for value in month_data["url"].tolist():
                key = _video_url_key(value)
                if key:
                    month_url_keys.add(key)

        rows = []
        for submission in submissions:
            if creator_id and submission["creator_id"] not in creator_id:
                continue
            if review_status and submission["review_status"] not in review_status:
                continue

            definition = definitions.get(submission["theme_code"], {})
            # Determine eligibility strictly: does this submission independently
            # satisfy the same rule _valid_theme_submissions applies (approved +
            # enabled theme + mode known + correct link count for its format)?
            theme_reward_eligible = False
            urls = submission.get("urls") or []
            if (
                submission["review_status"].upper() == "APPROVED"
                and submission["creator_id"] in creator_modes
                and definition.get("enabled", True)
            ):
                max_per_creator = max(int(definition.get("max_per_creator", 1) or 1), 1)
                content_format = str(submission.get("content_format") or "").upper()
                expected_count = 1 if content_format == "LONG" else 3 if content_format == "SHORT" else None
                url_keys = [_video_url_key(url) for url in urls]
                url_keys = [key for key in url_keys if key]
                if (
                    content_format in {"LONG", "SHORT"}
                    and expected_count is not None
                    and len(url_keys) == expected_count
                ):
                    theme_reward_eligible = True

            matched_post_urls = [
                url for url in urls if _video_url_key(url) in month_url_keys
            ]
            billing_excluded_url_count = len(matched_post_urls)

            rows.append(
                {
                    "id": submission["id"],
                    "period_month": submission["period_month"],
                    "creator_id": submission["creator_id"],
                    "theme_code": submission["theme_code"],
                    "theme_name": definition.get("theme_name"),
                    "content_format": submission["content_format"],
                    "urls": urls,
                    "submitted_date": submission["submitted_date"],
                    "review_status": submission["review_status"],
                    "note": submission["note"],
                    "theme_reward_eligible": theme_reward_eligible,
                    "matched_post_urls": matched_post_urls,
                    "billing_excluded_url_count": billing_excluded_url_count,
                    "billing_excluded": billing_excluded_url_count > 0,
                }
            )

        rows.sort(key=lambda item: (item["creator_id"], item["theme_code"]))

        revision = repository.get_commentary_theme_submissions_revision(period_month)
        eligible_creators = [
            {
                "id": record.id,
                "creator_key": record.user_id,
                "creator_name": record.koc_name,
            }
            for record in creator_records
            if record.id in creator_modes and record.active
        ]
        theme_definitions = [
            definition
            for definition in definitions.values()
            if definition.get("enabled", True)
        ]
        return {
            "data": rows,
            "meta": {
                "period_month": period_month,
                "revision": revision,
                "definitions": theme_definitions,
                "eligible_creators": eligible_creators,
            },
        }

    # ==================================================================
    # 19.3.1 exchange-rate (one global rate/month; affects all 3 tracks'
    # CURRENT PREVIEW only, never touches LOCKED versions).
    # ==================================================================
    @router.put("/api/compensation/{period_month}/exchange-rate")
    def save_exchange_rate(period_month: str, payload: dict = Body(...)) -> dict:
        _parse_period_month(period_month)
        if "rate" not in payload or payload.get("rate") is None:
            raise validation_error("rate 是必填字段。", "rate")
        repository = _repository()
        try:
            rate = float(payload["rate"])
        except (TypeError, ValueError) as exc:
            raise validation_error("rate 必须是数字。", "rate") from exc
        try:
            repository.save_jpy_to_usd_rate(period_month, rate)
        except ValueError as exc:
            raise validation_error(str(exc), "rate") from exc
        return {
            "data": {
                "period_month": period_month,
                "rate": repository.get_jpy_to_usd_rate(period_month),
            }
        }

    # ==================================================================
    # 19.3.3 long-term activity-count save.
    # ==================================================================
    @router.put("/api/compensation/long-term/{period_month}/activity-counts")
    def save_long_term_activity_counts(period_month: str, payload: dict = Body(...)) -> dict:
        _parse_period_month(period_month)
        activity_counts = payload.get("activity_counts")
        if not isinstance(activity_counts, dict):
            raise validation_error("activity_counts 是必填字段，须为对象。", "activity_counts")
        repository = _repository()
        try:
            repository.save_long_term_activity_counts(period_month, activity_counts)
        except ValueError as exc:
            raise validation_error(str(exc), "activity_counts") from exc
        return {
            "data": {
                "period_month": period_month,
                "updated_count": len(activity_counts),
            }
        }

    # ==================================================================
    # 19.3.4 commentary theme-submission full-month replace with
    # expected_revision optimistic concurrency check.
    # ==================================================================
    @router.put("/api/compensation/commentary/{period_month}/theme-submissions")
    def save_commentary_theme_submissions(
        period_month: str,
        payload: dict = Body(...),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        ctx: dict = session_context,
    ) -> JSONResponse:
        _parse_period_month(period_month)
        if "expected_revision" not in payload or payload.get("expected_revision") in (None, ""):
            raise validation_error("expected_revision 是必填字段。", "expected_revision")
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise validation_error("rows 是必填字段，须为数组。", "rows")
        expected_revision = str(payload["expected_revision"])
        clean_payload = {"expected_revision": expected_revision, "rows": rows}
        repository = _repository()

        def execute() -> tuple[int, dict]:
            try:
                updated_count = repository.replace_commentary_theme_submissions(
                    period_month, rows, expected_revision=expected_revision
                )
            except ThemeSubmissionRevisionExpiredError as exc:
                raise _conflict_error("REVISION_EXPIRED", str(exc)) from exc
            except ValueError as exc:
                raise validation_error(str(exc)) from exc
            new_revision = repository.get_commentary_theme_submissions_revision(period_month)
            return 200, {
                "data": {
                    "period_month": period_month,
                    "updated_count": updated_count,
                    "revision": new_revision,
                }
            }

        return _run_idempotent(
            operation="commentary_theme_submissions_replace",
            ctx=ctx if isinstance(ctx, dict) else {},
            idempotency_key=idempotency_key,
            payload=clean_payload,
            execute=execute,
        )

    # ==================================================================
    # 19.5 settlement version drafts/locks for 草根/长包/解说.
    # ==================================================================
    def _version_track(
        *,
        prefix: str,
        lane: str,
        create_method: str,
        update_method: str,
        lock_method: str,
        get_method: str,
    ) -> None:
        @router.post(f"{prefix}/{{period_month}}/drafts")
        def create_draft(
            period_month: str,
            payload: dict = Body(...),
            idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
            ctx: dict = session_context,
        ) -> JSONResponse:
            _parse_period_month(period_month)
            clean = _strip_server_controlled(payload)
            details_rows = clean.get("details") or []
            if not isinstance(details_rows, list):
                raise validation_error("details 须为数组。", "details")
            summary = clean.get("summary") or {}
            if not isinstance(summary, dict):
                raise validation_error("summary 须为对象。", "summary")
            try:
                jpy_to_usd_rate = float(clean.get("jpy_to_usd_rate"))
            except (TypeError, ValueError) as exc:
                raise validation_error("jpy_to_usd_rate 是必填字段，须为大于 0 的数字。", "jpy_to_usd_rate") from exc
            note = clean.get("note")

            def execute() -> tuple[int, dict]:
                details_df = _legacy_details(lane, details_rows)
                repository = _repository()
                create_fn = getattr(repository, create_method)
                try:
                    version = create_fn(
                        period_month,
                        jpy_to_usd_rate=jpy_to_usd_rate,
                        details=details_df,
                        summary=summary,
                        note=note,
                    )
                except ValueError as exc:
                    raise validation_error(str(exc)) from exc
                return 201, {"data": _serialize_version(version)}

            return _run_idempotent(
                operation=f"create_draft_{prefix}",
                ctx=ctx if isinstance(ctx, dict) else {},
                idempotency_key=idempotency_key,
                payload=clean,
                execute=execute,
            )

        @router.put(f"{prefix}/drafts/{{version_id}}")
        def update_draft(version_id: int, payload: dict = Body(...)) -> dict:
            repository = _repository()
            get_fn = getattr(repository, get_method)
            current = get_fn(version_id)
            if current is None:
                raise _not_found_error("未找到该结算版本草稿。")
            if current.status == "LOCKED":
                raise _conflict_error("VERSION_LOCKED", "该版本已锁定，无法编辑，请创建新版本。")
            clean = _strip_server_controlled(payload)
            details_rows = clean.get("details") or []
            if not isinstance(details_rows, list):
                raise validation_error("details 须为数组。", "details")
            summary = clean.get("summary") or {}
            if not isinstance(summary, dict):
                raise validation_error("summary 须为对象。", "summary")
            try:
                jpy_to_usd_rate = float(clean.get("jpy_to_usd_rate"))
            except (TypeError, ValueError) as exc:
                raise validation_error("jpy_to_usd_rate 是必填字段，须为大于 0 的数字。", "jpy_to_usd_rate") from exc
            details_df = _legacy_details(lane, details_rows)
            update_fn = getattr(repository, update_method)
            try:
                updated = update_fn(
                    version_id,
                    jpy_to_usd_rate=jpy_to_usd_rate,
                    details=details_df,
                    summary=summary,
                    note=clean.get("note"),
                )
            except ValueError as exc:
                # The repository's WHERE status='DRAFT' guard is the structural
                # concurrency check (per 19.5.2): if it fires here it means the
                # version was locked concurrently between our pre-check and the
                # UPDATE, so surface it as a conflict rather than a validation error.
                raise _conflict_error("VERSION_LOCKED", str(exc)) from exc
            return {"data": _serialize_version(updated)}

        @router.post(f"{prefix}/drafts/{{version_id}}/lock")
        def lock_draft(
            version_id: int,
            payload: dict = Body(...),
            ctx: dict = session_context,
        ) -> dict:
            repository = _repository()
            get_fn = getattr(repository, get_method)
            current = get_fn(version_id)
            if current is None:
                raise _not_found_error("未找到该结算版本草稿。")
            if current.status == "LOCKED":
                raise _conflict_error("VERSION_ALREADY_LOCKED", "该版本已锁定，请勿重复锁定。")
            clean = _strip_server_controlled(payload)
            lock_note = _clean_lock_note_field(clean)
            operator_name = ctx.get("operator_name") if isinstance(ctx, dict) else None
            lock_fn = getattr(repository, lock_method)
            try:
                locked = lock_fn(version_id, lock_note=lock_note, locked_by=operator_name)
            except ValueError as exc:
                raise _conflict_error("VERSION_ALREADY_LOCKED", str(exc)) from exc
            return {"data": _serialize_version(locked)}

    _version_track(
        prefix="/api/compensation/grassroot",
        lane="grassroot",
        create_method="create_compensation_draft",
        update_method="update_compensation_draft",
        lock_method="lock_compensation_version",
        get_method="get_compensation_version",
    )
    _version_track(
        prefix="/api/compensation/long-term",
        lane="long-term",
        create_method="create_long_term_compensation_draft",
        update_method="update_long_term_compensation_draft",
        lock_method="lock_long_term_compensation_version",
        get_method="get_long_term_compensation_version",
    )
    _version_track(
        prefix="/api/compensation/commentary",
        lane="commentary",
        create_method="create_commentary_compensation_draft",
        update_method="update_commentary_compensation_draft",
        lock_method="lock_commentary_compensation_version",
        get_method="get_commentary_compensation_version",
    )

    return router
