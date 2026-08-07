from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

import pandas as pd
from fastapi import APIRouter, Query

from core.commentary_compensation import (
    _video_url_key,
    calculate_commentary_compensation,
    commentary_contract_mode,
)
from core.cross_industry import exclude_cross_industry_posts
from core.dashboard_processor import filter_dashboard_data
from core.grassroot_compensation import calculate_grassroot_compensation
from core.long_term_compensation import calculate_long_term_compensation
from core.traffic_boost import is_july_traffic_boost_month
from database.dashboard_repository import DashboardRepository
from database.db import connect, init_db
from database.koc_repository import KOCRepository
from models.enums import CreatorCategory

from api.dashboard import _load_enriched_posts
from api.dashboard_support import validation_error

MAX_PAGE_SIZE = 100

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
    text = _text_or_none(value)
    if not text or text in ("未匹配", "未设置"):
        return []
    return [part for part in text.split("、") if part]


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


def _summary_dict(result) -> dict[str, Any]:
    return {
        "total_amount_jpy": int(result.total_amount_jpy),
        "creator_receivable_jpy": int(result.creator_receivable_jpy),
        "youdao_receivable_jpy": int(result.youdao_receivable_jpy),
        "creator_receivable_usd": float(result.creator_receivable_usd),
        "youdao_receivable_usd": float(result.youdao_receivable_usd),
        "settled_views": int(result.settled_views),
        "total_video_views": int(result.total_video_views),
        "overall_cpm": _float_or_none(result.overall_cpm),
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


def build_compensation_router(*, database_path, require_session: Callable) -> APIRouter:
    router = APIRouter(dependencies=[require_session])

    def _repository() -> DashboardRepository:
        return DashboardRepository(database_path)

    def _creator_repository() -> KOCRepository:
        return KOCRepository(database_path)

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
            summary_out = {
                "total_amount_jpy": int(summary.get("total_amount_jpy", 0)),
                "creator_receivable_jpy": int(summary.get("creator_receivable_jpy", 0)),
                "youdao_receivable_jpy": int(summary.get("youdao_receivable_jpy", 0)),
                "creator_receivable_usd": float(summary.get("creator_receivable_usd", 0)),
                "youdao_receivable_usd": float(summary.get("youdao_receivable_usd", 0)),
                "settled_views": int(summary.get("settled_views", 0)),
                "total_video_views": int(summary.get("total_video_views", 0)),
                "overall_cpm": _float_or_none(summary.get("overall_cpm")),
            }
            version_meta = _version_meta(version)
        else:
            jpy_to_usd_rate = repository.get_jpy_to_usd_rate(period_key)
            if jpy_to_usd_rate is None:
                raise validation_error("该月尚未保存 JPY→USD 汇率", "jpy_to_usd_rate")
            traffic_boost_enabled = (
                repository.get_traffic_boost_enabled(period_key)
                if is_july_traffic_boost_month(selected_month)
                else False
            )
            data, _creator_records = _load_enriched_posts(database_path)
            creator_repository = _creator_repository()
            creator_records = creator_repository.list(include_inactive=True)
            month_data = _month_data(data, selected_month)
            result = calculate_grassroot_compensation(
                month_data,
                creator_records,
                jpy_to_usd_rate=jpy_to_usd_rate,
                traffic_boost_enabled=traffic_boost_enabled,
            )
            details = result.details
            summary_out = _summary_dict(result)
            mode = "preview"
            version_meta = None

        rows: list[dict] = []
        for _, row in details.iterrows():
            status = row.get("结算状态")
            if settlement_status and status not in settlement_status:
                continue
            creator_key = row.get("user_id")
            creator_name = row.get("达人")
            if q:
                query = q.strip().casefold()
                if query and query not in str(creator_key or "").casefold() and query not in str(
                    creator_name or ""
                ).casefold():
                    continue

            cross_types = _text_or_none(row.get("跨赛道类型"))
            cross_lane = None
            if cross_types:
                cross_lane = {
                    "types": cross_types,
                    "post_count": _int_or_none(row.get("跨赛道活动投稿数")) or 0,
                    "original_views": _int_or_none(row.get("跨赛道原始播放量")) or 0,
                    "boosted_views": _int_or_none(row.get("跨赛道加成后播放量")) or 0,
                    "rank": _text_or_none(row.get("跨赛道 rank")),
                    "rank_reward_jpy": _int_or_none(row.get("跨赛道 rank金额")) or 0,
                    "post_reward_jpy": _int_or_none(row.get("跨赛道投稿数奖励")) or 0,
                    "amount_jpy": _int_or_none(row.get("跨赛道结算金额")) or 0,
                    "urls": [
                        url
                        for url in str(row.get("跨赛道视频链接") or "").split("\n")
                        if url
                    ],
                }

            rows.append(
                {
                    "creator_key": creator_key,
                    "creator_name": creator_name,
                    "contract_types": _split_contract_types(row.get("合同类型")),
                    "settlement_status": status,
                    "rank": _text_or_none(row.get("rank")),
                    "settlement_subtype": _text_or_none(row.get("计费 subtype")),
                    "followers": _int_or_none(row.get("粉丝数")),
                    "youtube_followers": _int_or_none(row.get("YouTube粉丝数")),
                    "tiktok_followers": _int_or_none(row.get("TikTok粉丝数")),
                    "billable_post_count": _int_or_none(row.get("投稿数")) or 0,
                    "billable_views": _int_or_none(row.get("计费播放量")) or 0,
                    "contract_billable_views": _int_or_none(row.get("合同内计费播放量")) or 0,
                    "all_video_views": _int_or_none(row.get("全部视频类型播放量")) or 0,
                    "cpm_views_no_boost": _int_or_none(row.get("CPM计算播放量（无加成）")) or 0,
                    "cross_lane": cross_lane,
                    "rewards_jpy": {
                        "short_rank": _int_or_none(row.get("short rank金额")) or 0,
                        "long_livestream_rank": _int_or_none(row.get("long+livestreamrank金额")) or 0,
                        "short_post": _int_or_none(row.get("short 投稿数奖励")) or 0,
                        "long_livestream_post": _int_or_none(row.get("long+livestream投稿数奖励")) or 0,
                    },
                    "total_amount_jpy": _int_or_none(row.get("总金额（日元）")) or 0,
                    "creator_receivable_jpy": _int_or_none(row.get("博主应收（日元）(包含15$手续费)")) or 0,
                    "youdao_receivable_jpy": _int_or_none(row.get("有道应收（日元）（包含服务费）")) or 0,
                    "creator_receivable_usd": _float_or_none(row.get("博主应收（美元）")) or 0.0,
                    "youdao_receivable_usd": _float_or_none(row.get("有道应收（美元）（包含服务费）")) or 0.0,
                    "cpm": _float_or_none(row.get("CPM")),
                }
            )

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
            summary_out = {
                "total_amount_jpy": int(summary.get("total_amount_jpy", 0)),
                "creator_receivable_jpy": int(summary.get("creator_receivable_jpy", 0)),
                "youdao_receivable_jpy": int(summary.get("youdao_receivable_jpy", 0)),
                "creator_receivable_usd": float(summary.get("creator_receivable_usd", 0)),
                "youdao_receivable_usd": float(summary.get("youdao_receivable_usd", 0)),
                "settled_views": int(summary.get("settled_views", 0)),
                "total_video_views": int(summary.get("total_video_views", 0)),
                "overall_cpm": _float_or_none(summary.get("overall_cpm")),
            }
            version_meta = _version_meta(version)
        else:
            jpy_to_usd_rate = repository.get_jpy_to_usd_rate(period_key)
            if jpy_to_usd_rate is None:
                raise validation_error("该月尚未保存 JPY→USD 汇率", "jpy_to_usd_rate")
            traffic_boost_enabled = (
                repository.get_traffic_boost_enabled(period_key)
                if is_july_traffic_boost_month(selected_month)
                else False
            )
            data, _creator_records = _load_enriched_posts(database_path)
            creator_repository = _creator_repository()
            creator_records = [
                record
                for record in creator_repository.list(include_inactive=True)
                if CreatorCategory.LONG_TERM in record.creator_categories
            ]
            month_data = _month_data(data, selected_month)
            event_counts = repository.get_long_term_activity_counts(period_key)
            result = calculate_long_term_compensation(
                month_data,
                creator_records,
                jpy_to_usd_rate=jpy_to_usd_rate,
                event_counts=event_counts,
                period_start=selected_month,
                period_end=_month_end(selected_month),
                traffic_boost_enabled=traffic_boost_enabled,
            )
            details = result.details
            summary_out = _summary_dict(result)
            mode = "preview"
            version_meta = None

        rows: list[dict] = []
        for _, row in details.iterrows():
            status = row.get("结算状态")
            if settlement_status and status not in settlement_status:
                continue
            creator_key = row.get("user_id")
            creator_name = row.get("达人")
            if q:
                query = q.strip().casefold()
                if query and query not in str(creator_key or "").casefold() and query not in str(
                    creator_name or ""
                ).casefold():
                    continue

            rows.append(
                {
                    "record_id": _int_or_none(row.get("记录ID")),
                    "creator_key": creator_key,
                    "creator_name": creator_name,
                    "contract_types": _split_contract_types(row.get("合同类型")),
                    "contract_start_date": _text_or_none(row.get("合同开始日期")),
                    "contract_end_date": _text_or_none(row.get("合同截止日期")),
                    "settlement_status": status,
                    "rank": _text_or_none(row.get("rank")),
                    "followers": _int_or_none(row.get("粉丝数")),
                    "youtube_post_count": _int_or_none(row.get("YouTube 投稿数")) or 0,
                    "monthly_new_post_views": _int_or_none(row.get("月度新投稿播放量")) or 0,
                    "cpm_views_no_boost": _int_or_none(row.get("CPM计算播放量（无加成）")) or 0,
                    "monthly_activity_count": _int_or_none(row.get("每月活动数")),
                    "activity_threshold": _int_or_none(row.get("活动数门槛")),
                    "rank_reward_jpy": _int_or_none(row.get("rank金额")) or 0,
                    "expected_cpm_jpy": _int_or_none(row.get("预计 CPM（日元）")),
                    "total_amount_jpy": _int_or_none(row.get("总金额（日元）")) or 0,
                    "creator_receivable_jpy": _int_or_none(row.get("博主应收（日元）(包含15$手续费)")) or 0,
                    "youdao_receivable_jpy": _int_or_none(row.get("有道应收（日元）（包含服务费）")) or 0,
                    "creator_receivable_usd": _float_or_none(row.get("博主应收（美元）")) or 0.0,
                    "youdao_receivable_usd": _float_or_none(row.get("有道应收（美元）（包含服务费）")) or 0.0,
                    "cpm": _float_or_none(row.get("CPM")),
                }
            )

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
            summary_out = {
                "total_amount_jpy": int(summary.get("total_amount_jpy", 0)),
                "creator_receivable_jpy": int(summary.get("creator_receivable_jpy", 0)),
                "youdao_receivable_jpy": int(summary.get("youdao_receivable_jpy", 0)),
                "creator_receivable_usd": float(summary.get("creator_receivable_usd", 0)),
                "youdao_receivable_usd": float(summary.get("youdao_receivable_usd", 0)),
                "settled_views": int(summary.get("settled_views", 0)),
                "total_video_views": int(summary.get("total_video_views", 0)),
                "overall_cpm": _float_or_none(summary.get("overall_cpm")),
            }
            version_meta = _version_meta(version)
        else:
            jpy_to_usd_rate = repository.get_jpy_to_usd_rate(period_key)
            if jpy_to_usd_rate is None:
                raise validation_error("该月尚未保存 JPY→USD 汇率", "jpy_to_usd_rate")
            data, _creator_records = _load_enriched_posts(database_path)
            creator_repository = _creator_repository()
            creator_records = [
                record
                for record in creator_repository.list(include_inactive=True)
                if CreatorCategory.COMMENTARY in record.creator_categories
            ]
            month_data = _month_data(data, selected_month)
            submissions = repository.list_commentary_theme_submissions(period_key)
            definitions = repository.list_commentary_theme_definitions(period_key)
            profile_history = creator_repository.list_profile_history()
            result = calculate_commentary_compensation(
                month_data,
                creator_records,
                period_month=period_key,
                jpy_to_usd_rate=jpy_to_usd_rate,
                profile_history=profile_history,
                theme_submissions=submissions,
                theme_definitions=definitions,
            )
            details = result.details
            summary_out = _summary_dict(result)
            mode = "preview"
            version_meta = None

        rows: list[dict] = []
        for _, row in details.iterrows():
            status = row.get("结算状态")
            if settlement_status and status not in settlement_status:
                continue
            creator_key = row.get("UID")
            creator_name = row.get("达人")
            if q:
                query = q.strip().casefold()
                if query and query not in str(creator_key or "").casefold() and query not in str(
                    creator_name or ""
                ).casefold():
                    continue

            rows.append(
                {
                    "creator_id": _int_or_none(row.get("creator_id")),
                    "creator_key": creator_key,
                    "creator_name": creator_name,
                    "contract_types": _split_contract_types(row.get("合同类型")),
                    "settlement_status": status,
                    "youtube_uid": _text_or_none(row.get("YouTube UID")),
                    "youtube_followers": _int_or_none(row.get("YouTube粉丝数")),
                    "tiktok_uid": _text_or_none(row.get("TikTok UID")),
                    "tiktok_followers": _int_or_none(row.get("TikTok粉丝数")),
                    "short_platform": _text_or_none(row.get("短视频平台")),
                    "long_views": _int_or_none(row.get("长视频播放量")) or 0,
                    "long_view_rank": _text_or_none(row.get("长视频播放等级")),
                    "long_follower_cap_rank": _text_or_none(row.get("长视频粉丝上限等级")),
                    "long_final_rank": _text_or_none(row.get("长视频最终等级")),
                    "long_reward_jpy": _int_or_none(row.get("长视频报酬（日元）")) or 0,
                    "short_views": _int_or_none(row.get("短视频播放量")) or 0,
                    "short_view_rank": _text_or_none(row.get("短视频播放等级")),
                    "short_follower_cap_rank": _text_or_none(row.get("短视频粉丝上限等级")),
                    "short_final_rank": _text_or_none(row.get("短视频最终等级")),
                    "short_reward_jpy": _int_or_none(row.get("短视频报酬（日元）")) or 0,
                    "combined_bonus_rank": _text_or_none(row.get("并用奖金等级")),
                    "combined_bonus_jpy": _int_or_none(row.get("并用奖金（日元）")) or 0,
                    "designated_theme_count": _int_or_none(row.get("指定主题件数")) or 0,
                    "designated_theme_reward_jpy": _int_or_none(row.get("指定主题报酬（日元）")) or 0,
                    "all_paid_views": _int_or_none(row.get("全部已付费内容播放量")) or 0,
                    "total_jpy_tax_incl": _int_or_none(row.get("解说含税总额（日元）")) or 0,
                    "creator_receivable_jpy": _int_or_none(row.get("博主应收（日元）(包含15$手续费)")) or 0,
                    "youdao_receivable_jpy": _int_or_none(row.get("有道应收（日元）（包含服务费）")) or 0,
                    "creator_receivable_usd": _float_or_none(row.get("博主应收（美元）")) or 0.0,
                    "youdao_receivable_usd": _float_or_none(row.get("有道应收（美元）（包含服务费）")) or 0.0,
                    "cpm": _float_or_none(row.get("CPM")),
                }
            )

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
            "pagination": pagination,
        }
        return {"data": page_rows, "meta": meta}

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

        return {"data": rows, "meta": {"period_month": period_month}}

    return router
