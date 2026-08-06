from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from typing import Mapping

import pandas as pd

from core.cross_industry import exclude_cross_industry_posts
from core.traffic_boost import apply_july_traffic_boost
from models.enums import CREATOR_CATEGORY_LABELS, CreatorCategory
from models.contracts import derive_creator_categories
from models.koc import KOCRecord


USD_HANDLING_FEE = 15.0
SERVICE_FEE_MULTIPLIER = 1.15

LONG_VIEW_REWARDS: tuple[tuple[str, int, int], ...] = (
    ("S", 1_200_000, 2_000_000),
    ("A+", 900_000, 1_500_000),
    ("A", 700_000, 1_000_000),
    ("B+", 450_000, 700_000),
    ("B", 300_000, 500_000),
    ("C+", 240_000, 400_000),
    ("C", 180_000, 300_000),
    ("D+", 120_000, 200_000),
    ("D", 60_000, 100_000),
)

SHORT_VIEW_REWARDS: tuple[tuple[str, int, int, int], ...] = (
    ("S", 65_000, 10_000_000, 2_000_000),
    ("A+", 60_000, 7_000_000, 1_500_000),
    ("A", 50_000, 4_500_000, 1_000_000),
    ("B+", 40_000, 2_800_000, 700_000),
    ("B", 10_000, 1_600_000, 500_000),
    ("C+", 8_000, 1_200_000, 400_000),
    ("C", 5_000, 800_000, 300_000),
    ("D+", 1_000, 500_000, 200_000),
    ("D", 500, 250_000, 100_000),
)

ALL_VIDEO_SUBTYPES = ("long", "livestream", "shorts", "ytb shorts", "tiktok")

COMPENSATION_COLUMNS = [
    "user_id",
    "达人",
    "合同类型",
    "粉丝数",
    "YouTube粉丝数",
    "TikTok粉丝数",
    "计费 subtype",
    "合同内计费播放量",
    "跨赛道类型",
    "跨赛道活动投稿数",
    "跨赛道原始播放量",
    "跨赛道加成后播放量",
    "跨赛道 rank",
    "跨赛道 rank金额",
    "跨赛道投稿数奖励",
    "跨赛道结算金额",
    "跨赛道视频链接",
    "计费播放量",
    "全部视频类型播放量",
    "CPM计算播放量（无加成）",
    "投稿数",
    "结算状态",
    "rank",
    "short rank金额",
    "long+livestreamrank金额",
    "short 投稿数奖励",
    "long+livestream投稿数奖励",
    "总金额（日元）",
    "博主应收（日元）(包含15$手续费)",
    "有道应收（日元）（包含服务费）",
    "博主应收（美元）",
    "有道应收（美元）（包含服务费）",
    "CPM",
]


@dataclass(frozen=True)
class GrassrootCompensationResult:
    details: pd.DataFrame
    total_amount_jpy: int
    creator_receivable_jpy: int
    youdao_receivable_jpy: int
    creator_receivable_usd: float
    youdao_receivable_usd: float
    settled_views: int
    total_video_views: int
    overall_cpm: float | None


def _grassroot_records(records: Iterable[KOCRecord]) -> list[KOCRecord]:
    return [
        record
        for record in records
        if record.active and CreatorCategory.GRASSROOT in record.creator_categories
    ]


def _contract_for_settlement(record: KOCRecord) -> tuple[str, str] | None:
    contracts = tuple(
        dict.fromkeys(str(contract).strip() for contract in record.contract_types if str(contract).strip())
    )
    if len(contracts) != 1:
        return None
    contract_label = contracts[0]
    compact = contract_label.casefold().replace(" ", "")
    if "ytb" in compact:
        return ("shorts", contract_label) if "short" in compact else ("long", contract_label)
    if "tiktok" in compact or "tt" in compact:
        return "tiktok", contract_label
    return None


def _settlement_subtypes(contract_kind: str) -> tuple[str, ...]:
    if contract_kind == "long":
        return ("long", "livestream")
    if contract_kind == "shorts":
        # Current dashboard records use "YTB shorts" while some monthly exports
        # retain the source label "shorts". Both are the same paid content type.
        return ("shorts", "ytb shorts")
    return ("tiktok",)


def _settlement_subtype_label(contract_kind: str) -> str:
    if contract_kind == "long":
        return "long + livestream"
    if contract_kind == "shorts":
        return "shorts"
    return "tiktok"


def _numeric_total(data: pd.DataFrame, column: str) -> int:
    if data.empty or column not in data:
        return 0
    values = pd.to_numeric(data[column], errors="coerce")
    return int(values.fillna(0).sum())


def _long_rank(views: int) -> tuple[str, int]:
    for rank, threshold, reward in LONG_VIEW_REWARDS:
        if views >= threshold:
            return rank, reward
    return "无等级", 0


def _short_rank(followers: int, views: int) -> tuple[str, int]:
    for rank, follower_threshold, view_threshold, reward in SHORT_VIEW_REWARDS:
        if followers >= follower_threshold and views >= view_threshold:
            return rank, reward
    return "无等级", 0


def _long_post_reward(post_count: int) -> int:
    if post_count >= 30:
        return 100_000
    if post_count >= 10:
        return 50_000
    return 0


def _short_post_reward(post_count: int) -> int:
    return 15_000 if post_count >= 10 else 0


def _empty_amounts() -> dict[str, object]:
    return {
        "rank": "",
        "short rank金额": 0,
        "long+livestreamrank金额": 0,
        "short 投稿数奖励": 0,
        "long+livestream投稿数奖励": 0,
        "总金额（日元）": 0,
        "博主应收（日元）(包含15$手续费)": 0,
        "有道应收（日元）（包含服务费）": 0,
        "博主应收（美元）": 0.0,
        "有道应收（美元）（包含服务费）": 0.0,
        "CPM": None,
    }


def _legacy_calculate_grassroot_compensation(
    data: pd.DataFrame,
    creator_records: Iterable[KOCRecord],
    *,
    jpy_to_usd_rate: float,
    contract_type_snapshots: Mapping[int, tuple[str, ...]] | None = None,
    traffic_boost_enabled: bool = False,
) -> GrassrootCompensationResult:
    """Calculate one month's grassroot compensation from retained dashboard posts.

    The caller supplies one month's complete dashboard detail. Contract types can
    be frozen per month through snapshots; other creator data remains live.
    """
    if jpy_to_usd_rate <= 0:
        raise ValueError("日元兑美元汇率必须大于 0。")

    prepared = apply_july_traffic_boost(
        exclude_cross_industry_posts(data),
        enabled=traffic_boost_enabled,
    )
    if "user_id" not in prepared:
        prepared["user_id"] = pd.Series(dtype="string")
    if "subtype" not in prepared:
        prepared["subtype"] = pd.Series(dtype="string")
    if "publish_date" not in prepared:
        prepared["publish_date"] = pd.Series(dtype="object")
    prepared["_user_id"] = prepared["user_id"].astype("string").str.strip()
    prepared["_subtype"] = prepared["subtype"].astype("string").str.strip().str.casefold()
    prepared["_publish_date"] = pd.to_datetime(
        prepared["publish_date"], errors="coerce"
    ).dt.date

    effective_records = [
        replace(
            record,
            contract_types=contract_type_snapshots.get(record.id, record.contract_types),
        )
        if contract_type_snapshots is not None
        else record
        for record in creator_records
    ]

    rows: list[dict[str, object]] = []
    for record in _grassroot_records(effective_records):
        settlement_contract = _contract_for_settlement(record)
        if settlement_contract is None:
            rows.append(
                {
                    "user_id": record.user_id,
                    "达人": record.koc_name,
                    "合同类型": "、".join(record.contract_types) or "未设置",
                    "粉丝数": record.follower_count,
                    "计费 subtype": "",
                    "计费播放量": 0,
                    "全部视频类型播放量": 0,
                    "投稿数": 0,
                    "结算状态": "合同类型待确认",
                    **_empty_amounts(),
                }
            )
            continue

        contract_kind, contract_label = settlement_contract
        subtypes = _settlement_subtypes(contract_kind)
        creator_data = prepared.loc[
            prepared["_user_id"].eq(record.user_id)
            & prepared["_subtype"].isin(subtypes)
        ]
        all_video_data = prepared.loc[
            prepared["_user_id"].eq(record.user_id)
            & prepared["_subtype"].isin(ALL_VIDEO_SUBTYPES)
        ]
        views = _numeric_total(creator_data, "views")
        total_video_views = _numeric_total(all_video_data, "views")
        posts = len(creator_data)
        row: dict[str, object] = {
            "user_id": record.user_id,
            "达人": record.koc_name,
            "合同类型": contract_label,
            "粉丝数": record.follower_count,
            "计费 subtype": _settlement_subtype_label(contract_kind),
            "计费播放量": views,
            "全部视频类型播放量": total_video_views,
            "投稿数": posts,
        }
        if contract_kind == "long":
            rank, view_reward = _long_rank(views)
            short_rank_reward = 0
            long_rank_reward = view_reward
            short_post_reward = 0
            long_post_reward = _long_post_reward(posts)
        elif record.follower_count is None:
            rows.append(
                {
                    **row,
                    "结算状态": "待补充粉丝数",
                    **_empty_amounts(),
                }
            )
            continue
        else:
            rank, view_reward = _short_rank(record.follower_count, views)
            short_rank_reward = view_reward
            long_rank_reward = 0
            short_post_reward = _short_post_reward(posts)
            long_post_reward = 0

        total_amount = view_reward + short_post_reward + long_post_reward
        if total_amount <= 0:
            rows.append(
                {
                    **row,
                    "结算状态": "未达标",
                    "rank": rank,
                    "short rank金额": short_rank_reward,
                    "long+livestreamrank金额": long_rank_reward,
                    "short 投稿数奖励": short_post_reward,
                    "long+livestream投稿数奖励": long_post_reward,
                    **{
                        key: value
                        for key, value in _empty_amounts().items()
                        if key
                        not in {
                            "rank",
                            "short rank金额",
                            "long+livestreamrank金额",
                            "short 投稿数奖励",
                            "long+livestream投稿数奖励",
                        }
                    },
                }
            )
            continue

        creator_receivable_usd = total_amount * jpy_to_usd_rate + USD_HANDLING_FEE
        youdao_receivable_usd = creator_receivable_usd * SERVICE_FEE_MULTIPLIER
        creator_receivable_jpy = int(round(creator_receivable_usd / jpy_to_usd_rate))
        youdao_receivable_jpy = int(round(youdao_receivable_usd / jpy_to_usd_rate))
        cpm = (
            youdao_receivable_usd / total_video_views * 1_000
            if total_video_views > 0
            else None
        )
        rows.append(
            {
                **row,
                "结算状态": "可结算",
                "rank": rank,
                "short rank金额": short_rank_reward,
                "long+livestreamrank金额": long_rank_reward,
                "short 投稿数奖励": short_post_reward,
                "long+livestream投稿数奖励": long_post_reward,
                "总金额（日元）": total_amount,
                "博主应收（日元）(包含15$手续费)": creator_receivable_jpy,
                "有道应收（日元）（包含服务费）": youdao_receivable_jpy,
                "博主应收（美元）": creator_receivable_usd,
                "有道应收（美元）（包含服务费）": youdao_receivable_usd,
                "CPM": cpm,
            }
        )

    details = pd.DataFrame(rows, columns=COMPENSATION_COLUMNS)
    if details.empty:
        return GrassrootCompensationResult(
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

    settled = details["结算状态"].eq("可结算") | details["结算状态"].eq("未达标")
    settled_rows = details.loc[settled]
    settled_views = _numeric_total(settled_rows, "计费播放量")
    total_video_views = _numeric_total(settled_rows, "全部视频类型播放量")
    youdao_receivable_usd = float(
        pd.to_numeric(
            settled_rows["有道应收（美元）（包含服务费）"], errors="coerce"
        ).fillna(0).sum()
    )
    return GrassrootCompensationResult(
        details=details,
        total_amount_jpy=_numeric_total(settled_rows, "总金额（日元）"),
        creator_receivable_jpy=_numeric_total(
            settled_rows, "博主应收（日元）(包含15$手续费)"
        ),
        youdao_receivable_jpy=_numeric_total(
            settled_rows, "有道应收（日元）（包含服务费）"
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


@dataclass(frozen=True)
class SettlementCreator:
    """The creator profile that applied to a particular set of posts."""

    key: str
    record_id: int | None
    user_id: str
    koc_name: str
    contract_types: tuple[str, ...]
    contract_start_date: date | None
    contract_end_date: date | None
    follower_count: int | None
    youtube_follower_count: int | None
    tiktok_follower_count: int | None
    active: bool
    is_grassroot: bool
    history_missing: bool


(
    _USER_ID,
    _CREATOR_NAME,
    _CONTRACT_TYPES,
    _FOLLOWERS,
    _YOUTUBE_FOLLOWERS,
    _TIKTOK_FOLLOWERS,
    _SETTLEMENT_SUBTYPE,
    _CONTRACT_SETTLED_VIEWS,
    _CROSS_LANE_TYPES,
    _CROSS_LANE_POST_COUNT,
    _CROSS_LANE_ORIGINAL_VIEWS,
    _CROSS_LANE_BOOSTED_VIEWS,
    _CROSS_LANE_RANK,
    _CROSS_LANE_RANK_REWARD,
    _CROSS_LANE_POST_REWARD,
    _CROSS_LANE_AMOUNT,
    _CROSS_LANE_URLS,
    _SETTLED_VIEWS,
    _ALL_VIDEO_VIEWS,
    _CPM_VIEWS,
    _POST_COUNT,
    _STATUS,
    _RANK,
    _SHORT_RANK_REWARD,
    _LONG_RANK_REWARD,
    _SHORT_POST_REWARD,
    _LONG_POST_REWARD,
    _TOTAL_AMOUNT,
    _CREATOR_RECEIVABLE_JPY,
    _YOUDAO_RECEIVABLE_JPY,
    _CREATOR_RECEIVABLE_USD,
    _YOUDAO_RECEIVABLE_USD,
    _CPM,
) = COMPENSATION_COLUMNS

_LANE_KINDS = ("long", "shorts", "tiktok")
_LANE_LABELS = {
    "long": "long + livestream",
    "shorts": "YTB shorts",
    "tiktok": "tiktok",
}


@dataclass(frozen=True)
class CrossLaneSettlement:
    kind: str
    label: str
    post_count: int
    original_views: int
    boosted_views: int
    rank: str
    rank_reward: int
    post_reward: int
    video_urls: tuple[str, ...]

    @property
    def amount(self) -> int:
        return self.rank_reward + self.post_reward


def _followers_for_lane(creator: SettlementCreator, kind: str) -> int | None:
    if kind == "tiktok":
        return (
            creator.tiktok_follower_count
            if creator.tiktok_follower_count is not None
            else creator.follower_count
        )
    return (
        creator.youtube_follower_count
        if creator.youtube_follower_count is not None
        else creator.follower_count
    )


def _video_urls(data: pd.DataFrame) -> tuple[str, ...]:
    if data.empty or "url" not in data:
        return ()
    return tuple(
        dict.fromkeys(
            value
            for raw_value in data["url"].tolist()
            if (value := _text(raw_value))
        )
    )


def _cross_lane_settlements(
    creator_data: pd.DataFrame,
    *,
    contract_kind: str,
    creator: SettlementCreator,
) -> list[CrossLaneSettlement]:
    """Calculate July campaign exceptions outside the creator's contract lane."""
    if creator_data.empty or "is_july_traffic_boost" not in creator_data:
        return []

    eligible = creator_data["is_july_traffic_boost"].fillna(False).astype(bool)
    results: list[CrossLaneSettlement] = []
    for kind in _LANE_KINDS:
        if kind == contract_kind:
            continue
        lane_data = creator_data.loc[
            eligible
            & creator_data["_subtype"].isin(_settlement_subtypes(kind))
        ]
        if lane_data.empty:
            continue

        boosted_views = _numeric_total(lane_data, "views")
        original_views = _numeric_total(lane_data, "original_views")
        post_count = len(lane_data)
        if kind == "long":
            rank, rank_reward = _long_rank(boosted_views)
            post_reward = _long_post_reward(post_count)
        else:
            followers = _followers_for_lane(creator, kind)
            if followers is None:
                rank, rank_reward = _STATUS_NEEDS_FOLLOWERS, 0
            else:
                rank, rank_reward = _short_rank(followers, boosted_views)
            # The July exception explicitly allows the post-count reward even
            # when the boosted views do not reach a rank threshold.
            post_reward = _short_post_reward(post_count)

        results.append(
            CrossLaneSettlement(
                kind=kind,
                label=_LANE_LABELS[kind],
                post_count=post_count,
                original_views=original_views,
                boosted_views=boosted_views,
                rank=rank,
                rank_reward=rank_reward,
                post_reward=post_reward,
                video_urls=_video_urls(lane_data),
            )
        )
    return results


def _cross_lane_summary(
    settlements: list[CrossLaneSettlement],
) -> tuple[dict[str, object], int, int]:
    paid_settlements = [item for item in settlements if item.amount > 0]
    fields: dict[str, object] = {
        _CROSS_LANE_TYPES: "；".join(item.label for item in settlements),
        _CROSS_LANE_POST_COUNT: sum(item.post_count for item in settlements),
        _CROSS_LANE_ORIGINAL_VIEWS: sum(
            item.original_views for item in settlements
        ),
        _CROSS_LANE_BOOSTED_VIEWS: sum(
            item.boosted_views for item in settlements
        ),
        _CROSS_LANE_RANK: "；".join(
            f"{item.label}：{item.rank}" for item in settlements
        ),
        _CROSS_LANE_RANK_REWARD: sum(
            item.rank_reward for item in settlements
        ),
        _CROSS_LANE_POST_REWARD: sum(
            item.post_reward for item in settlements
        ),
        _CROSS_LANE_AMOUNT: sum(item.amount for item in settlements),
        _CROSS_LANE_URLS: "\n".join(
            dict.fromkeys(
                url for item in settlements for url in item.video_urls
            )
        ),
    }
    return (
        fields,
        sum(item.boosted_views for item in paid_settlements),
        sum(item.post_count for item in paid_settlements),
    )

_STATUS_READY = "\u53ef\u7ed3\u7b97"
_STATUS_NOT_REACHED = "\u672a\u8fbe\u6807"
_STATUS_NEEDS_FOLLOWERS = "\u5f85\u8865\u5145\u7c89\u4e1d\u6570"
_STATUS_CONTRACT_PENDING = "\u5408\u540c\u7c7b\u578b\u5f85\u786e\u8ba4"
_STATUS_OUTSIDE_CONTRACT = "\u5408\u540c\u671f\u9650\u5916"
_STATUS_HISTORY_MISSING = "\u5386\u53f2\u8d44\u6599\u7f3a\u5931"
_NOT_CONFIGURED = "\u672a\u8bbe\u7f6e"


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


def _joined_labels(rows: list[dict[str, object]], column: str) -> str:
    """Join distinct labels from a creator's internal contract segments."""
    labels = [
        _text(row.get(column))
        for row in rows
        if _text(row.get(column))
    ]
    return "、".join(dict.fromkeys(labels))


def _merge_creator_settlement_rows(
    rows: list[dict[str, object]],
    *,
    jpy_to_usd_rate: float,
) -> list[dict[str, object]]:
    """Present one settlement line per creator after internal term calculation."""
    groups: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        groups.setdefault(_text(row.get(_USER_ID)), []).append(row)

    merged_rows: list[dict[str, object]] = []
    for creator_rows in groups.values():
        if len(creator_rows) == 1:
            merged_rows.append(creator_rows[0])
            continue

        merged = creator_rows[-1].copy()
        statuses = {_text(row.get(_STATUS)) for row in creator_rows}
        numeric_columns = (
            _CONTRACT_SETTLED_VIEWS,
            _CROSS_LANE_POST_COUNT,
            _CROSS_LANE_ORIGINAL_VIEWS,
            _CROSS_LANE_BOOSTED_VIEWS,
            _CROSS_LANE_RANK_REWARD,
            _CROSS_LANE_POST_REWARD,
            _CROSS_LANE_AMOUNT,
            _SETTLED_VIEWS,
            _ALL_VIDEO_VIEWS,
            _CPM_VIEWS,
            _POST_COUNT,
            _SHORT_RANK_REWARD,
            _LONG_RANK_REWARD,
            _SHORT_POST_REWARD,
            _LONG_POST_REWARD,
        )
        for column in numeric_columns:
            merged[column] = _numeric_total(pd.DataFrame(creator_rows), column)

        merged[_CONTRACT_TYPES] = _joined_labels(creator_rows, _CONTRACT_TYPES)
        merged[_SETTLEMENT_SUBTYPE] = _joined_labels(
            creator_rows, _SETTLEMENT_SUBTYPE
        )
        merged[_CROSS_LANE_TYPES] = _joined_labels(
            creator_rows, _CROSS_LANE_TYPES
        )
        merged[_CROSS_LANE_RANK] = _joined_labels(
            creator_rows, _CROSS_LANE_RANK
        )
        merged[_CROSS_LANE_URLS] = _joined_labels(
            creator_rows, _CROSS_LANE_URLS
        )
        merged[_RANK] = _joined_labels(creator_rows, _RANK)
        follower_values = [
            _optional_int(row.get(_FOLLOWERS))
            for row in creator_rows
            if _optional_int(row.get(_FOLLOWERS)) is not None
        ]
        merged[_FOLLOWERS] = follower_values[-1] if follower_values else None
        for column in (_YOUTUBE_FOLLOWERS, _TIKTOK_FOLLOWERS):
            platform_values = [
                _optional_int(row.get(column))
                for row in creator_rows
                if _optional_int(row.get(column)) is not None
            ]
            merged[column] = platform_values[-1] if platform_values else None

        # A missing profile, unconfirmed contract, or missing follower count
        # keeps the whole creator out of payment until it is resolved.
        if _STATUS_HISTORY_MISSING in statuses:
            merged[_STATUS] = _STATUS_HISTORY_MISSING
            merged.update(_empty_amounts())
        elif _STATUS_NEEDS_FOLLOWERS in statuses:
            merged[_STATUS] = _STATUS_NEEDS_FOLLOWERS
            merged.update(_empty_amounts())
        elif _STATUS_CONTRACT_PENDING in statuses:
            merged[_STATUS] = _STATUS_CONTRACT_PENDING
            merged.update(_empty_amounts())
        else:
            total_amount = (
                int(merged[_SHORT_RANK_REWARD])
                + int(merged[_LONG_RANK_REWARD])
                + int(merged[_SHORT_POST_REWARD])
                + int(merged[_LONG_POST_REWARD])
            )
            if total_amount > 0:
                creator_receivable_usd = (
                    total_amount * jpy_to_usd_rate + USD_HANDLING_FEE
                )
                youdao_receivable_usd = (
                    creator_receivable_usd * SERVICE_FEE_MULTIPLIER
                )
                merged.update(
                    {
                        _STATUS: _STATUS_READY,
                        _TOTAL_AMOUNT: total_amount,
                        _CREATOR_RECEIVABLE_JPY: int(
                            round(creator_receivable_usd / jpy_to_usd_rate)
                        ),
                        _YOUDAO_RECEIVABLE_JPY: int(
                            round(youdao_receivable_usd / jpy_to_usd_rate)
                        ),
                        _CREATOR_RECEIVABLE_USD: creator_receivable_usd,
                        _YOUDAO_RECEIVABLE_USD: youdao_receivable_usd,
                        _CPM: (
                            youdao_receivable_usd
                            / int(merged[_CPM_VIEWS])
                            * 1_000
                            if int(merged[_CPM_VIEWS]) > 0
                            else None
                        ),
                    }
                )
            elif _STATUS_NOT_REACHED in statuses:
                merged[_STATUS] = _STATUS_NOT_REACHED
                merged.update(
                    _amounts_for_no_payment(
                        rank=str(merged[_RANK]),
                        short_rank_reward=int(merged[_SHORT_RANK_REWARD]),
                        long_rank_reward=int(merged[_LONG_RANK_REWARD]),
                        short_post_reward=int(merged[_SHORT_POST_REWARD]),
                        long_post_reward=int(merged[_LONG_POST_REWARD]),
                    )
                )
            else:
                merged[_STATUS] = _STATUS_OUTSIDE_CONTRACT
                merged.update(_empty_amounts())
        merged_rows.append(merged)
    return merged_rows


def _within_contract_period(
    data: pd.DataFrame,
    *,
    contract_start_date: date | None,
    contract_end_date: date | None,
) -> pd.DataFrame:
    """Keep only posts whose actual publication date is inside the contract term."""
    if data.empty:
        return data.copy()
    if "_publish_date" not in data:
        # Raw compatibility inputs created before dashboard persistence do not
        # carry dates, so there is no contract date to validate against.
        return data.copy()
    post_dates = pd.to_datetime(data["_publish_date"], errors="coerce").dt.date
    if not post_dates.notna().any():
        return data.copy()
    mask = post_dates.notna()
    if contract_start_date is not None:
        mask &= post_dates >= contract_start_date
    if contract_end_date is not None:
        mask &= post_dates <= contract_end_date
    return data.loc[mask]


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
        for separator in (chr(0x3001), ";", "/", "|"):
            text = text.replace(separator, ",")
        values = text.split(",")
    return tuple(
        dict.fromkeys(text for item in values if (text := _text(item)))
    )


def _is_grassroot_profile(
    contract_types: tuple[str, ...],
    creator_category: object,
) -> bool:
    categories = derive_creator_categories(contract_types)
    if CreatorCategory.GRASSROOT in categories:
        return True
    category_text = _text(creator_category).casefold()
    return category_text in {
        CreatorCategory.GRASSROOT.value.casefold(),
        CREATOR_CATEGORY_LABELS[CreatorCategory.GRASSROOT].casefold(),
    }


def _profile_term_key(
    *,
    record_id: int,
    contract_types: tuple[str, ...],
    creator_category: object,
    contract_start_date: date | None,
    contract_end_date: date | None,
) -> str:
    """Return the billing-term identity shared by profile-only revisions."""
    contract_signature = "\x1f".join(contract.casefold() for contract in contract_types)
    category = _text(creator_category).casefold()
    start = contract_start_date.isoformat() if contract_start_date else ""
    end = contract_end_date.isoformat() if contract_end_date else ""
    return f"profile:{record_id}:{category}:{contract_signature}:{start}:{end}"


def _profile_contract_key(
    record_id: int,
    contract_types: tuple[str, ...],
) -> tuple[int, tuple[str, ...]]:
    """Identify revisions that belong to the same named contract."""
    return record_id, tuple(contract.casefold() for contract in contract_types)


def _profile_term_candidates(prepared: pd.DataFrame) -> dict[
    tuple[int, tuple[str, ...]], list[tuple[date, date | None]]
]:
    """Collect saved contract periods that can complete legacy profile snapshots."""
    candidates: dict[tuple[int, tuple[str, ...]], list[tuple[date, date | None]]] = {}
    for _, row in prepared.iterrows():
        record_id = _optional_int(row.get("creator_id"))
        if record_id is None or _text(row.get("profile_status")).upper() == "HISTORY_MISSING":
            continue
        contract_types = _dashboard_contract_types(row.get("contract_types"))
        start_date = _optional_date(row.get("contract_start_date"))
        if not contract_types or start_date is None:
            continue
        key = _profile_contract_key(record_id, contract_types)
        candidate = (start_date, _optional_date(row.get("contract_end_date")))
        if candidate not in candidates.setdefault(key, []):
            candidates[key].append(candidate)
    for terms in candidates.values():
        terms.sort(key=lambda item: item[0])
    return candidates


def _complete_profile_term_dates(
    *,
    record_id: int,
    contract_types: tuple[str, ...],
    profile_date: date,
    contract_start_date: date | None,
    contract_end_date: date | None,
    candidates: dict[tuple[int, tuple[str, ...]], list[tuple[date, date | None]]],
) -> tuple[date | None, date | None]:
    """Fill an incomplete legacy snapshot from its matching contract period."""
    if contract_start_date is not None and contract_end_date is not None:
        return contract_start_date, contract_end_date
    if profile_date is date.max:
        return contract_start_date, contract_end_date

    matching_terms = [
        term
        for term in candidates.get(_profile_contract_key(record_id, contract_types), [])
        if term[0] <= profile_date
        and (term[1] is None or profile_date <= term[1])
    ]
    if not matching_terms:
        return contract_start_date, contract_end_date
    inferred_start, inferred_end = matching_terms[-1]
    return contract_start_date or inferred_start, contract_end_date or inferred_end


def _profile_creators_from_dashboard(
    prepared: pd.DataFrame,
) -> tuple[pd.DataFrame, list[SettlementCreator], set[int]]:
    """Build settlement identities from retained profile metadata.

    A follower refresh writes a new profile snapshot, but does not create a new
    billing term. Group those profile-only revisions so a creator is settled
    once per actual contract term rather than once per follower update.
    """
    working = prepared.copy()
    working["_settlement_key"] = pd.Series("", index=working.index, dtype="string")
    working["_profile_active"] = pd.Series(False, index=working.index, dtype="bool")
    if "creator_id" not in working:
        return working, [], set()

    term_candidates = _profile_term_candidates(working)
    creators: dict[str, SettlementCreator] = {}
    latest_profile_dates: dict[str, date] = {}
    latest_follower_dates: dict[str, date] = {}
    latest_platform_follower_dates: dict[tuple[str, str], date] = {}
    seen_record_ids: set[int] = set()
    for index, row in working.iterrows():
        record_id = _optional_int(row.get("creator_id"))
        user_id = _text(row.get("user_id"))
        if record_id is None or not user_id:
            continue
        seen_record_ids.add(record_id)
        history_missing = _text(row.get("profile_status")).upper() == (
            "HISTORY_MISSING"
        )
        contracts = (
            ()
            if history_missing
            else _dashboard_contract_types(row.get("contract_types"))
        )
        start_date = _optional_date(row.get("contract_start_date"))
        end_date = _optional_date(row.get("contract_end_date"))
        active = _active_value(row.get("creator_active"))
        profile_date = _optional_date(row.get("profile_effective_date")) or date.max
        if not history_missing:
            start_date, end_date = _complete_profile_term_dates(
                record_id=record_id,
                contract_types=contracts,
                profile_date=profile_date,
                contract_start_date=start_date,
                contract_end_date=end_date,
                candidates=term_candidates,
            )
        key = (
            f"history-missing:{record_id}:{user_id}"
            if history_missing
            else _profile_term_key(
                record_id=record_id,
                contract_types=contracts,
                creator_category=row.get("creator_category"),
                contract_start_date=start_date,
                contract_end_date=end_date,
            )
        )
        working.at[index, "_profile_active"] = active
        if key not in creators:
            name = _text(row.get("koc_name")) or _text(row.get("creator_label"))
            creators[key] = SettlementCreator(
                key=key,
                record_id=record_id,
                user_id=user_id,
                koc_name=name or user_id,
                contract_types=contracts,
                contract_start_date=start_date,
                contract_end_date=end_date,
                follower_count=_optional_int(row.get("follower_count")),
                youtube_follower_count=_optional_int(
                    row.get("youtube_follower_count")
                ),
                tiktok_follower_count=_optional_int(
                    row.get("tiktok_follower_count")
                ),
                active=active,
                is_grassroot=_is_grassroot_profile(
                    contracts, row.get("creator_category")
                ),
                history_missing=history_missing,
            )
            latest_profile_dates[key] = profile_date
            if creators[key].follower_count is not None:
                latest_follower_dates[key] = profile_date
            if creators[key].youtube_follower_count is not None:
                latest_platform_follower_dates[(key, "youtube")] = profile_date
            if creators[key].tiktok_follower_count is not None:
                latest_platform_follower_dates[(key, "tiktok")] = profile_date
        else:
            current = creators[key]
            latest_profile_date = latest_profile_dates[key]
            follower_count = current.follower_count
            row_followers = _optional_int(row.get("follower_count"))
            if row_followers is not None and profile_date >= latest_follower_dates.get(
                key, date.min
            ):
                follower_count = row_followers
                latest_follower_dates[key] = profile_date
            youtube_follower_count = current.youtube_follower_count
            row_youtube_followers = _optional_int(row.get("youtube_follower_count"))
            if row_youtube_followers is not None and profile_date >= (
                latest_platform_follower_dates.get((key, "youtube"), date.min)
            ):
                youtube_follower_count = row_youtube_followers
                latest_platform_follower_dates[(key, "youtube")] = profile_date
            tiktok_follower_count = current.tiktok_follower_count
            row_tiktok_followers = _optional_int(row.get("tiktok_follower_count"))
            if row_tiktok_followers is not None and profile_date >= (
                latest_platform_follower_dates.get((key, "tiktok"), date.min)
            ):
                tiktok_follower_count = row_tiktok_followers
                latest_platform_follower_dates[(key, "tiktok")] = profile_date
            if profile_date >= latest_profile_date:
                name = _text(row.get("koc_name")) or _text(row.get("creator_label"))
                creators[key] = replace(
                    current,
                    user_id=user_id,
                    koc_name=name or current.koc_name,
                    follower_count=follower_count,
                    youtube_follower_count=youtube_follower_count,
                    tiktok_follower_count=tiktok_follower_count,
                    active=current.active or active,
                )
                latest_profile_dates[key] = profile_date
            elif any(
                (
                    follower_count != current.follower_count,
                    youtube_follower_count != current.youtube_follower_count,
                    tiktok_follower_count != current.tiktok_follower_count,
                )
            ):
                creators[key] = replace(
                    current,
                    follower_count=follower_count,
                    youtube_follower_count=youtube_follower_count,
                    tiktok_follower_count=tiktok_follower_count,
                )
        working.at[index, "_settlement_key"] = key
    return working, list(creators.values()), seen_record_ids


def _fallback_creators(
    records: Iterable[KOCRecord],
    *,
    skipped_record_ids: set[int],
    contract_type_snapshots: Mapping[int, tuple[str, ...]] | None,
) -> list[SettlementCreator]:
    creators: list[SettlementCreator] = []
    for record in records:
        if record.id in skipped_record_ids or not record.active:
            continue
        contract_types = (
            contract_type_snapshots.get(record.id, record.contract_types)
            if contract_type_snapshots is not None
            else record.contract_types
        )
        is_grassroot = CreatorCategory.GRASSROOT in derive_creator_categories(
            contract_types, fallback=record.creator_category
        )
        if not is_grassroot:
            continue
        creators.append(
            SettlementCreator(
                key=f"record:{record.id}",
                record_id=record.id,
                user_id=record.user_id,
                koc_name=record.koc_name,
                contract_types=tuple(contract_types),
                contract_start_date=record.contract_start_date,
                contract_end_date=record.contract_end_date,
                follower_count=record.follower_count,
                youtube_follower_count=record.youtube_follower_count,
                tiktok_follower_count=record.tiktok_follower_count,
                active=True,
                is_grassroot=True,
                history_missing=False,
            )
        )
    return creators


def _amounts_for_no_payment(
    *,
    rank: str,
    short_rank_reward: int,
    long_rank_reward: int,
    short_post_reward: int,
    long_post_reward: int,
) -> dict[str, object]:
    amounts = _empty_amounts()
    amounts.update(
        {
            _RANK: rank,
            _SHORT_RANK_REWARD: short_rank_reward,
            _LONG_RANK_REWARD: long_rank_reward,
            _SHORT_POST_REWARD: short_post_reward,
            _LONG_POST_REWARD: long_post_reward,
        }
    )
    return amounts


def calculate_grassroot_compensation(
    data: pd.DataFrame,
    creator_records: Iterable[KOCRecord],
    *,
    jpy_to_usd_rate: float,
    contract_type_snapshots: Mapping[int, tuple[str, ...]] | None = None,
    traffic_boost_enabled: bool = False,
) -> GrassrootCompensationResult:
    """Calculate compensation from the profile version effective for each post.

    Dashboard rows retain their creator profile metadata. This lets a contract,
    name, follower count, or active-state update take effect from its selected
    date without rewriting the earlier posts. Raw/legacy data still falls back
    to the supplied current creator records for backward compatibility.
    """
    if jpy_to_usd_rate <= 0:
        raise ValueError("JPY to USD rate must be greater than zero.")

    prepared = apply_july_traffic_boost(
        exclude_cross_industry_posts(data),
        enabled=traffic_boost_enabled,
    )
    if "user_id" not in prepared:
        prepared["user_id"] = pd.Series(dtype="string")
    if "subtype" not in prepared:
        prepared["subtype"] = pd.Series(dtype="string")
    if "publish_date" not in prepared:
        prepared["publish_date"] = pd.Series(dtype="object")
    prepared["_user_id"] = prepared["user_id"].astype("string").str.strip()
    prepared["_subtype"] = prepared["subtype"].astype("string").str.strip().str.casefold()
    prepared["_publish_date"] = pd.to_datetime(
        prepared["publish_date"], errors="coerce"
    ).dt.date

    prepared, profile_creators, profile_record_ids = _profile_creators_from_dashboard(
        prepared
    )
    creators = [
        creator
        for creator in profile_creators
        if creator.active and creator.is_grassroot
    ]
    creators.extend(
        _fallback_creators(
            creator_records,
            skipped_record_ids=profile_record_ids,
            contract_type_snapshots=contract_type_snapshots,
        )
    )

    rows: list[dict[str, object]] = []
    for creator in creators:
        settlement_contract = _contract_for_settlement(creator)  # type: ignore[arg-type]
        if creator.key.startswith(("profile:", "history-missing:")):
            source_creator_data = prepared.loc[
                prepared["_settlement_key"].eq(creator.key)
                & prepared["_profile_active"]
            ]
        else:
            source_creator_data = prepared.loc[
                prepared["_user_id"].eq(creator.user_id)
            ]
        if creator.history_missing:
            cross_fields, _, _ = _cross_lane_summary([])
            rows.append(
                {
                    _USER_ID: creator.user_id,
                    _CREATOR_NAME: creator.koc_name,
                    _CONTRACT_TYPES: _STATUS_HISTORY_MISSING,
                    _FOLLOWERS: None,
                    _YOUTUBE_FOLLOWERS: None,
                    _TIKTOK_FOLLOWERS: None,
                    _SETTLEMENT_SUBTYPE: "",
                    _CONTRACT_SETTLED_VIEWS: 0,
                    **cross_fields,
                    _SETTLED_VIEWS: 0,
                    _ALL_VIDEO_VIEWS: 0,
                    _CPM_VIEWS: 0,
                    _POST_COUNT: 0,
                    _STATUS: _STATUS_HISTORY_MISSING,
                    **_empty_amounts(),
                }
            )
            continue
        creator_data = _within_contract_period(
            source_creator_data,
            contract_start_date=creator.contract_start_date,
            contract_end_date=creator.contract_end_date,
        )
        all_video_data = creator_data.loc[
            creator_data["_subtype"].isin(ALL_VIDEO_SUBTYPES)
        ]
        total_video_views = _numeric_total(all_video_data, "original_views")
        youtube_followers = _followers_for_lane(creator, "shorts")
        tiktok_followers = _followers_for_lane(creator, "tiktok")

        if settlement_contract is None:
            cross_fields, _, _ = _cross_lane_summary([])
            rows.append(
                {
                    _USER_ID: creator.user_id,
                    _CREATOR_NAME: creator.koc_name,
                    _CONTRACT_TYPES: "\u3001".join(creator.contract_types) or _NOT_CONFIGURED,
                    _FOLLOWERS: creator.follower_count,
                    _YOUTUBE_FOLLOWERS: youtube_followers,
                    _TIKTOK_FOLLOWERS: tiktok_followers,
                    _SETTLEMENT_SUBTYPE: "",
                    _CONTRACT_SETTLED_VIEWS: 0,
                    **cross_fields,
                    _SETTLED_VIEWS: 0,
                    _ALL_VIDEO_VIEWS: total_video_views,
                    _CPM_VIEWS: total_video_views,
                    _POST_COUNT: 0,
                    _STATUS: _STATUS_CONTRACT_PENDING,
                    **_empty_amounts(),
                }
            )
            continue

        contract_kind, contract_label = settlement_contract
        billable_data = creator_data.loc[
            creator_data["_subtype"].isin(_settlement_subtypes(contract_kind))
        ]
        views = _numeric_total(billable_data, "views")
        contract_posts = len(billable_data)
        cross_settlements = (
            _cross_lane_settlements(
                creator_data,
                contract_kind=contract_kind,
                creator=creator,
            )
            if traffic_boost_enabled
            else []
        )
        cross_fields, paid_cross_views, paid_cross_posts = _cross_lane_summary(
            cross_settlements
        )
        settlement_subtype = _settlement_subtype_label(contract_kind)
        if cross_settlements:
            settlement_subtype = (
                f"{settlement_subtype}；活动跨赛道 "
                f"{cross_fields[_CROSS_LANE_TYPES]}"
            )
        contract_followers = _followers_for_lane(creator, contract_kind)
        base_row: dict[str, object] = {
            _USER_ID: creator.user_id,
            _CREATOR_NAME: creator.koc_name,
            _CONTRACT_TYPES: contract_label,
            _FOLLOWERS: contract_followers,
            _YOUTUBE_FOLLOWERS: youtube_followers,
            _TIKTOK_FOLLOWERS: tiktok_followers,
            _SETTLEMENT_SUBTYPE: settlement_subtype,
            _CONTRACT_SETTLED_VIEWS: views,
            **cross_fields,
            _SETTLED_VIEWS: views + paid_cross_views,
            _ALL_VIDEO_VIEWS: total_video_views,
            _CPM_VIEWS: total_video_views,
            _POST_COUNT: contract_posts + paid_cross_posts,
        }

        if not source_creator_data.empty and creator_data.empty:
            rows.append(
                {
                    **base_row,
                    _STATUS: _STATUS_OUTSIDE_CONTRACT,
                    **_empty_amounts(),
                }
            )
            continue

        if contract_kind == "long":
            rank, view_reward = _long_rank(views)
            short_rank_reward = 0
            long_rank_reward = view_reward
            short_post_reward = 0
            long_post_reward = _long_post_reward(contract_posts)
        elif contract_followers is None:
            rank = _STATUS_NEEDS_FOLLOWERS
            view_reward = 0
            short_rank_reward = 0
            long_rank_reward = 0
            short_post_reward = 0
            long_post_reward = 0
        else:
            rank, view_reward = _short_rank(contract_followers, views)
            short_rank_reward = view_reward
            long_rank_reward = 0
            short_post_reward = _short_post_reward(contract_posts)
            long_post_reward = 0

        for cross_settlement in cross_settlements:
            if cross_settlement.kind == "long":
                long_rank_reward += cross_settlement.rank_reward
                long_post_reward += cross_settlement.post_reward
            else:
                short_rank_reward += cross_settlement.rank_reward
                short_post_reward += cross_settlement.post_reward

        display_rank = rank
        if cross_settlements:
            display_rank = (
                f"合同{_LANE_LABELS[contract_kind]}：{rank}；"
                f"{cross_fields[_CROSS_LANE_RANK]}"
            )
        total_amount = (
            short_rank_reward
            + long_rank_reward
            + short_post_reward
            + long_post_reward
        )
        if total_amount <= 0:
            missing_followers = rank == _STATUS_NEEDS_FOLLOWERS or any(
                item.rank == _STATUS_NEEDS_FOLLOWERS
                for item in cross_settlements
            )
            rows.append(
                {
                    **base_row,
                    _STATUS: (
                        _STATUS_NEEDS_FOLLOWERS
                        if missing_followers
                        else _STATUS_NOT_REACHED
                    ),
                    **_amounts_for_no_payment(
                        rank=display_rank,
                        short_rank_reward=short_rank_reward,
                        long_rank_reward=long_rank_reward,
                        short_post_reward=short_post_reward,
                        long_post_reward=long_post_reward,
                    ),
                }
            )
            continue

        creator_receivable_usd = total_amount * jpy_to_usd_rate + USD_HANDLING_FEE
        youdao_receivable_usd = creator_receivable_usd * SERVICE_FEE_MULTIPLIER
        creator_receivable_jpy = int(round(creator_receivable_usd / jpy_to_usd_rate))
        youdao_receivable_jpy = int(round(youdao_receivable_usd / jpy_to_usd_rate))
        rows.append(
            {
                **base_row,
                _STATUS: _STATUS_READY,
                _RANK: display_rank,
                _SHORT_RANK_REWARD: short_rank_reward,
                _LONG_RANK_REWARD: long_rank_reward,
                _SHORT_POST_REWARD: short_post_reward,
                _LONG_POST_REWARD: long_post_reward,
                _TOTAL_AMOUNT: total_amount,
                _CREATOR_RECEIVABLE_JPY: creator_receivable_jpy,
                _YOUDAO_RECEIVABLE_JPY: youdao_receivable_jpy,
                _CREATOR_RECEIVABLE_USD: creator_receivable_usd,
                _YOUDAO_RECEIVABLE_USD: youdao_receivable_usd,
                _CPM: (
                    youdao_receivable_usd / total_video_views * 1_000
                    if total_video_views > 0
                    else None
                ),
            }
        )

    details = pd.DataFrame(
        _merge_creator_settlement_rows(
            rows,
            jpy_to_usd_rate=jpy_to_usd_rate,
        ),
        columns=COMPENSATION_COLUMNS,
    )
    if details.empty:
        return GrassrootCompensationResult(
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

    settled_rows = details.loc[details[_STATUS].isin([_STATUS_READY, _STATUS_NOT_REACHED])]
    settled_views = _numeric_total(settled_rows, _SETTLED_VIEWS)
    total_video_views = _numeric_total(settled_rows, _CPM_VIEWS)
    youdao_receivable_usd = float(
        pd.to_numeric(settled_rows[_YOUDAO_RECEIVABLE_USD], errors="coerce")
        .fillna(0)
        .sum()
    )
    return GrassrootCompensationResult(
        details=details,
        total_amount_jpy=_numeric_total(settled_rows, _TOTAL_AMOUNT),
        creator_receivable_jpy=_numeric_total(settled_rows, _CREATOR_RECEIVABLE_JPY),
        youdao_receivable_jpy=_numeric_total(settled_rows, _YOUDAO_RECEIVABLE_JPY),
        creator_receivable_usd=float(
            pd.to_numeric(settled_rows[_CREATOR_RECEIVABLE_USD], errors="coerce")
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
