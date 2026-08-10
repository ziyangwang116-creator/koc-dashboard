from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable, Mapping

import pandas as pd

from core.cross_industry import (
    exclude_cross_industry_posts,
    normalize_video_url,
    parse_pasted_urls,
)
from core.grassroot_compensation import SERVICE_FEE_MULTIPLIER, USD_HANDLING_FEE
from models.enums import CreatorCategory
from models.koc import CreatorProfileSnapshot, KOCRecord


RANK_ORDER = ("SS", "S+", "S", "A+", "A", "B+", "B", "C+", "C", "D+", "D")

LONG_TIERS: tuple[tuple[str, int, int], ...] = (
    ("SS", 310_000, 500_000),
    ("S+", 240_000, 380_000),
    ("S", 190_000, 300_000),
    ("A+", 160_000, 250_000),
    ("A", 140_000, 210_000),
    ("B+", 110_000, 170_000),
    ("B", 85_000, 130_000),
    ("C+", 58_000, 90_000),
    ("C", 38_000, 60_000),
    ("D+", 18_000, 29_000),
    ("D", 8_000, 12_000),
)

SHORT_TIERS: tuple[tuple[str, int, int], ...] = (
    ("SS", 1_700_000, 450_000),
    ("S+", 1_200_000, 400_000),
    ("S", 900_000, 350_000),
    ("A+", 500_000, 230_000),
    ("A", 320_000, 170_000),
    ("B+", 230_000, 125_000),
    ("B", 160_000, 90_000),
    ("C+", 110_000, 65_000),
    ("C", 70_000, 45_000),
    ("D+", 35_000, 22_000),
    ("D", 16_000, 10_000),
)

BONUS_REWARDS = {
    "SS": 100_000,
    "S+": 80_000,
    "S": 60_000,
    "A+": 50_000,
    "B+": 30_000,
    "C+": 10_000,
}

THEME_REWARD_JPY = 15_000

COMMENTARY_COLUMNS = [
    "creator_id",
    "UID",
    "达人",
    "合同类型",
    "结算状态",
    "YouTube UID",
    "YouTube粉丝数",
    "TikTok UID",
    "TikTok粉丝数",
    "短视频平台",
    "长视频播放量",
    "长视频播放等级",
    "长视频粉丝上限等级",
    "长视频最终等级",
    "长视频报酬（日元）",
    "短视频播放量",
    "短视频播放等级",
    "短视频粉丝上限等级",
    "短视频最终等级",
    "短视频报酬（日元）",
    "并用奖金等级",
    "并用奖金（日元）",
    "指定主题件数",
    "指定主题报酬（日元）",
    "全部已付费内容播放量",
    "解说含税总额（日元）",
    "博主应收（日元）(包含15$手续费)",
    "有道应收（日元）（包含服务费）",
    "博主应收（美元）",
    "有道应收（美元）（包含服务费）",
    "CPM",
]

@dataclass(frozen=True)
class CommentaryCompensationResult:
    details: pd.DataFrame
    total_amount_jpy: int
    creator_receivable_jpy: int
    youdao_receivable_jpy: int
    creator_receivable_usd: float
    youdao_receivable_usd: float
    settled_views: int
    total_video_views: int
    overall_cpm: float | None


def _month_end(period_month: str) -> date:
    start = date.fromisoformat(f"{period_month}-01")
    if start.month == 12:
        return date(start.year + 1, 1, 1) - timedelta(days=1)
    return date(start.year, start.month + 1, 1) - timedelta(days=1)


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _int(value: object) -> int:
    try:
        numeric = pd.to_numeric(value, errors="coerce")
        if pd.isna(numeric):
            return 0
        return max(int(numeric), 0)
    except (TypeError, ValueError):
        return 0


def _active(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "no", "否"}
    try:
        if bool(pd.isna(value)):
            return True
    except (TypeError, ValueError):
        pass
    return bool(value)


def _row_within_contract(row: Mapping[str, object]) -> bool:
    if not _active(row.get("creator_active", True)):
        return False
    published = pd.to_datetime(row.get("publish_date"), errors="coerce")
    if pd.isna(published):
        return False
    start = pd.to_datetime(row.get("contract_start_date"), errors="coerce")
    end = pd.to_datetime(row.get("contract_end_date"), errors="coerce")
    if not pd.isna(start) and published.date() < start.date():
        return False
    if not pd.isna(end) and published.date() > end.date():
        return False
    return True


def commentary_contract_mode(contract_types: object) -> str | None:
    compact = _text(contract_types).casefold().replace(" ", "")
    if "ytb长+ytbshorts" in compact:
        return "YTB_LONG_YTB_SHORTS"
    if "ytb长+tt" in compact:
        return "YTB_LONG_TT"
    return None


def _is_long(row: Mapping[str, object]) -> bool:
    platform = _text(row.get("source_platform")).casefold()
    subtype = _text(row.get("subtype")).casefold().replace(" ", "")
    return "youtube" in platform and subtype == "long"


def _is_short(row: Mapping[str, object], mode: str) -> bool:
    platform = _text(row.get("source_platform")).casefold()
    subtype = _text(row.get("subtype")).casefold().replace(" ", "")
    if mode == "YTB_LONG_TT":
        return "tiktok" in platform or subtype == "tiktok"
    return "youtube" in platform and subtype in {"short", "shorts", "ytbshorts"}


def _view_rank(views: int, tiers: Iterable[tuple[str, int, int]]) -> tuple[str, int]:
    for rank, threshold, reward in tiers:
        if views >= threshold:
            return rank, reward
    return "", 0


def _follower_cap(followers: int | None) -> str | None:
    if followers is None:
        return None
    if followers >= 100_000:
        return "SS"
    if followers >= 80_000:
        return "S+"
    if followers >= 60_000:
        return "S"
    if followers >= 40_000:
        return "A+"
    if followers >= 20_000:
        return "B+"
    return "C+"


def _lower_rank(first: str, second: str) -> str:
    if not first or not second:
        return ""
    return RANK_ORDER[max(RANK_ORDER.index(first), RANK_ORDER.index(second))]


def _reward_for_rank(rank: str, tiers: Iterable[tuple[str, int, int]]) -> int:
    return next((reward for item_rank, _threshold, reward in tiers if item_rank == rank), 0)


def _bonus_for_ranks(long_rank: str, short_rank: str) -> tuple[str, int]:
    common = _lower_rank(long_rank, short_rank)
    if not common:
        return "", 0
    common_index = RANK_ORDER.index(common)
    for rank in ("SS", "S+", "S", "A+", "B+", "C+"):
        if common_index <= RANK_ORDER.index(rank):
            return rank, BONUS_REWARDS[rank]
    return "", 0


def _profile_at_month_end(
    record: KOCRecord,
    history: Iterable[CreatorProfileSnapshot],
    period_end: date,
) -> KOCRecord | CreatorProfileSnapshot:
    candidates = [
        snapshot
        for snapshot in history
        if snapshot.creator_id == record.id and snapshot.effective_date <= period_end
    ]
    return max(candidates, key=lambda item: item.effective_date) if candidates else record


def _video_url_key(value: object) -> str:
    identity = normalize_video_url(value)
    if identity is not None:
        return identity.url_key
    raw = _text(value)
    return f"raw:{raw.casefold()}" if raw else ""


def _theme_submission_urls(submission: Mapping[str, Any]) -> list[str]:
    values = submission.get("urls", ())
    if isinstance(values, str):
        values = parse_pasted_urls(values) or [values]

    urls: list[str] = []
    seen: set[str] = set()
    for value in values:
        parsed = parse_pasted_urls(value) or [_text(value)]
        for url in parsed:
            key = _video_url_key(url)
            if not key or key in seen:
                continue
            seen.add(key)
            urls.append(_text(url))
    return urls


def _valid_theme_submissions(
    _data: pd.DataFrame,
    submissions: Iterable[Mapping[str, Any]],
    definitions: Mapping[str, Mapping[str, Any]],
    creator_modes: Mapping[int, str],
) -> dict[int, dict[str, Any]]:
    results: dict[int, dict[str, Any]] = {}
    approved_by_theme: dict[tuple[int, str], int] = {}
    for submission in submissions:
        if _text(submission.get("review_status")).upper() != "APPROVED":
            continue
        creator_id = _int(submission.get("creator_id"))
        mode = creator_modes.get(creator_id)
        definition = definitions.get(_text(submission.get("theme_code")))
        if creator_id <= 0 or mode is None or definition is None:
            continue
        if not _active(definition.get("enabled", True)):
            continue
        theme_code = _text(submission.get("theme_code"))
        theme_key = (creator_id, theme_code)
        max_per_creator = max(_int(definition.get("max_per_creator", 1)), 1)
        if approved_by_theme.get(theme_key, 0) >= max_per_creator:
            continue
        urls = _theme_submission_urls(submission)
        url_keys = [_video_url_key(url) for url in urls]
        content_format = _text(submission.get("content_format")).upper()
        if content_format not in {"LONG", "SHORT"}:
            continue
        expected_count = 1 if content_format == "LONG" else 3
        if len(url_keys) != expected_count:
            continue
        result = results.setdefault(
            creator_id,
            {"urls": set(), "count": 0, "reward": 0},
        )
        result["urls"].update(urls)
        result["count"] += 1
        result["reward"] += THEME_REWARD_JPY
        approved_by_theme[theme_key] = approved_by_theme.get(theme_key, 0) + 1
    return results


def _settlement_content_views(
    data: pd.DataFrame,
    *,
    creator_id: int,
    excluded_theme_urls: Iterable[str],
) -> tuple[int, int]:
    """Return raw long and short views eligible for the commentary ladder."""
    excluded = {_video_url_key(url) for url in excluded_theme_urls if _video_url_key(url)}
    long_views = 0
    short_views = 0
    for source in data.to_dict("records"):
        if _int(source.get("creator_id")) != creator_id:
            continue
        if not _row_within_contract(source):
            continue
        if _video_url_key(source.get("url")) in excluded:
            continue
        mode = commentary_contract_mode(source.get("contract_types"))
        if mode is None:
            continue
        if _is_long(source):
            long_views += _int(source.get("views"))
        elif _is_short(source, mode):
            short_views += _int(source.get("views"))
    return long_views, short_views


def calculate_commentary_compensation(
    data: pd.DataFrame,
    creator_records: Iterable[KOCRecord],
    *,
    period_month: str,
    jpy_to_usd_rate: float,
    profile_history: Iterable[CreatorProfileSnapshot] = (),
    theme_submissions: Iterable[Mapping[str, Any]] = (),
    theme_definitions: Mapping[str, Mapping[str, Any]] | None = None,
) -> CommentaryCompensationResult:
    if jpy_to_usd_rate <= 0:
        raise ValueError("日元兑美元汇率必须大于0。")
    data = exclude_cross_industry_posts(data)
    period_end = _month_end(period_month)
    history = list(profile_history)
    all_records = list(creator_records)
    profiles = {
        record.id: _profile_at_month_end(record, history, period_end)
        for record in all_records
    }
    data_creator_ids = {
        _int(row.get("creator_id"))
        for row in data.to_dict("records")
        if commentary_contract_mode(row.get("contract_types")) is not None
        and _row_within_contract(row)
    }
    records: list[KOCRecord] = []
    for record in all_records:
        profile = profiles[record.id]
        mode = commentary_contract_mode("、".join(profile.contract_types))
        starts_in_time = (
            profile.contract_start_date is None
            or profile.contract_start_date <= period_end
        )
        ends_in_time = (
            profile.contract_end_date is None
            or profile.contract_end_date >= date.fromisoformat(f"{period_month}-01")
        )
        if record.id in data_creator_ids or (
            mode is not None and profile.active and starts_in_time and ends_in_time
        ):
            records.append(record)
    creator_modes = {
        creator_id: commentary_contract_mode("、".join(profile.contract_types))
        for creator_id, profile in profiles.items()
    }
    creator_modes = {
        creator_id: mode for creator_id, mode in creator_modes.items() if mode is not None
    }
    definitions = theme_definitions or {}
    submissions = list(theme_submissions)
    theme_results = _valid_theme_submissions(
        data,
        submissions,
        definitions,
        creator_modes,
    )

    detail_rows: list[dict[str, Any]] = []
    for record in records:
        profile = profiles[record.id]
        mode = creator_modes.get(record.id)
        if mode is None:
            continue
        theme = theme_results.get(
            record.id,
            {"urls": set(), "count": 0, "reward": 0},
        )
        long_views, short_views = _settlement_content_views(
            data,
            creator_id=record.id,
            excluded_theme_urls=theme["urls"],
        )
        youtube_followers = profile.followers_for_platform("YouTube")
        short_platform = "TikTok" if mode == "YTB_LONG_TT" else "YouTube"
        short_followers = profile.followers_for_platform(short_platform)
        tiktok_followers = profile.followers_for_platform("TikTok")

        missing_followers = (long_views > 0 and youtube_followers is None) or (
            short_views > 0 and short_followers is None
        )
        long_view_rank, _ = _view_rank(long_views, LONG_TIERS)
        short_view_rank, _ = _view_rank(short_views, SHORT_TIERS)
        long_cap = _follower_cap(youtube_followers) if long_views > 0 else ""
        short_cap = _follower_cap(short_followers) if short_views > 0 else ""
        long_final = _lower_rank(long_view_rank, long_cap or "")
        short_final = _lower_rank(short_view_rank, short_cap or "")
        long_reward = _reward_for_rank(long_final, LONG_TIERS)
        short_reward = _reward_for_rank(short_final, SHORT_TIERS)
        bonus_rank, bonus_reward = _bonus_for_ranks(long_final, short_final)
        total_amount = long_reward + short_reward + bonus_reward + _int(theme["reward"])
        status = "可结算"
        if missing_followers:
            status = "待补充粉丝数"
        elif total_amount == 0:
            status = "未达标"

        all_paid_views = long_views + short_views
        if status == "待补充粉丝数":
            payable = 0
        else:
            payable = total_amount
        if payable > 0:
            creator_usd = payable * jpy_to_usd_rate + USD_HANDLING_FEE
            youdao_usd = creator_usd * SERVICE_FEE_MULTIPLIER
            creator_jpy = int(round(creator_usd / jpy_to_usd_rate))
            youdao_jpy = int(round(youdao_usd / jpy_to_usd_rate))
        else:
            creator_usd = youdao_usd = 0.0
            creator_jpy = youdao_jpy = 0

        detail_rows.append(
            {
                "creator_id": record.id,
                "UID": profile.user_id,
                "达人": profile.koc_name,
                "合同类型": "、".join(profile.contract_types),
                "结算状态": status,
                "YouTube UID": profile.youtube_user_id or profile.user_id,
                "YouTube粉丝数": youtube_followers,
                "TikTok UID": profile.tiktok_user_id,
                "TikTok粉丝数": tiktok_followers,
                "短视频平台": short_platform,
                "长视频播放量": long_views,
                "长视频播放等级": long_view_rank or "无等级",
                "长视频粉丝上限等级": long_cap or "-",
                "长视频最终等级": long_final or "无等级",
                "长视频报酬（日元）": long_reward if payable else 0,
                "短视频播放量": short_views,
                "短视频播放等级": short_view_rank or "无等级",
                "短视频粉丝上限等级": short_cap or "-",
                "短视频最终等级": short_final or "无等级",
                "短视频报酬（日元）": short_reward if payable else 0,
                "并用奖金等级": bonus_rank or "不适用",
                "并用奖金（日元）": bonus_reward if payable else 0,
                "指定主题件数": _int(theme["count"]),
                "指定主题报酬（日元）": _int(theme["reward"]),
                "全部已付费内容播放量": all_paid_views,
                "解说含税总额（日元）": payable,
                "博主应收（日元）(包含15$手续费)": creator_jpy,
                "有道应收（日元）（包含服务费）": youdao_jpy,
                "博主应收（美元）": creator_usd,
                "有道应收（美元）（包含服务费）": youdao_usd,
                "CPM": youdao_usd / all_paid_views * 1_000 if all_paid_views > 0 else None,
            }
        )

    details = pd.DataFrame(detail_rows, columns=COMMENTARY_COLUMNS)
    if details.empty:
        return CommentaryCompensationResult(details, 0, 0, 0, 0.0, 0.0, 0, 0, None)
    settled = details["结算状态"].isin(["可结算", "未达标"])
    settled_rows = details.loc[settled]
    total_views = int(
        pd.to_numeric(settled_rows["全部已付费内容播放量"], errors="coerce")
        .fillna(0)
        .sum()
    )
    youdao_usd_total = float(
        pd.to_numeric(
            settled_rows["有道应收（美元）（包含服务费）"], errors="coerce"
        ).fillna(0).sum()
    )
    return CommentaryCompensationResult(
        details=details,
        total_amount_jpy=int(pd.to_numeric(settled_rows["解说含税总额（日元）"], errors="coerce").fillna(0).sum()),
        creator_receivable_jpy=int(pd.to_numeric(settled_rows["博主应收（日元）(包含15$手续费)"], errors="coerce").fillna(0).sum()),
        youdao_receivable_jpy=int(pd.to_numeric(settled_rows["有道应收（日元）（包含服务费）"], errors="coerce").fillna(0).sum()),
        creator_receivable_usd=float(pd.to_numeric(settled_rows["博主应收（美元）"], errors="coerce").fillna(0).sum()),
        youdao_receivable_usd=youdao_usd_total,
        settled_views=int(pd.to_numeric(settled_rows["长视频播放量"], errors="coerce").fillna(0).sum() + pd.to_numeric(settled_rows["短视频播放量"], errors="coerce").fillna(0).sum()),
        total_video_views=total_views,
        overall_cpm=youdao_usd_total / total_views * 1_000 if total_views > 0 else None,
    )
