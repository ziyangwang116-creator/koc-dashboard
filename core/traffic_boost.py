from __future__ import annotations

from datetime import date

import pandas as pd


JULY_TRAFFIC_BOOST_TAG = "#手記の加筆"
JULY_TRAFFIC_BOOST_TITLE_TEXT = "手記の加筆"
JULY_TRAFFIC_BOOST_START = date(2026, 7, 1)
JULY_TRAFFIC_BOOST_END = date(2026, 7, 31)
JULY_TRAFFIC_BOOST_RATE = 0.05


def _text_series(data: pd.DataFrame, column: str) -> pd.Series:
    if column not in data:
        return pd.Series("", index=data.index, dtype="string")
    return data[column].astype("string").fillna("").str.strip()


def _base_views(data: pd.DataFrame) -> pd.Series:
    source = data["original_views"] if "original_views" in data else data.get("views")
    if source is None:
        return pd.Series(0, index=data.index, dtype="Int64")
    values = pd.to_numeric(source, errors="coerce").fillna(0).clip(lower=0)
    return values.round().astype("Int64")


def july_traffic_boost_eligible(data: pd.DataFrame) -> pd.Series:
    """Return rows covered by the confirmed July 2026 traffic-boost rules."""
    if data.empty:
        return pd.Series(False, index=data.index, dtype="bool")

    if "publish_date" in data:
        dates = pd.to_datetime(data["publish_date"], errors="coerce")
    else:
        dates = pd.Series(pd.NaT, index=data.index, dtype="datetime64[ns]")
    in_campaign = dates.ge(pd.Timestamp(JULY_TRAFFIC_BOOST_START)) & dates.le(
        pd.Timestamp(JULY_TRAFFIC_BOOST_END)
    )
    platform = _text_series(data, "source_platform").str.casefold()
    subtype = _text_series(data, "subtype").str.casefold()
    description_has_tag = _text_series(data, "description").str.contains(
        JULY_TRAFFIC_BOOST_TAG,
        regex=False,
        na=False,
    )
    title_has_text = _text_series(data, "title").str.contains(
        JULY_TRAFFIC_BOOST_TITLE_TEXT,
        regex=False,
        na=False,
    )

    youtube = platform.str.contains("youtube", regex=False, na=False) | platform.eq(
        "ytb"
    )
    tiktok = platform.str.contains("tiktok", regex=False, na=False) | platform.eq(
        "tt"
    )
    platform_missing = platform.isin(("", "未标注"))
    youtube |= platform_missing & subtype.isin(
        ("long", "livestream", "shorts", "ytb shorts")
    )
    tiktok |= platform_missing & subtype.eq("tiktok")

    return (
        in_campaign
        & ((youtube & description_has_tag & title_has_text) | (tiktok & description_has_tag))
    ).fillna(False)


def annotate_july_traffic_boost(data: pd.DataFrame) -> pd.DataFrame:
    """Add auditable July traffic-boost fields without changing ``views``."""
    annotated = data.copy()
    original_views = _base_views(annotated)
    eligible = july_traffic_boost_eligible(annotated)

    # Round each boosted video to a whole play so all dashboard totals stay integral.
    boosted_views = ((original_views.astype("int64") * 105 + 50) // 100).astype(
        "Int64"
    )
    bonus_views = (boosted_views - original_views).astype("Int64")
    bonus_views = bonus_views.where(eligible, 0).astype("Int64")
    boosted_views = (original_views + bonus_views).astype("Int64")

    platform = _text_series(annotated, "source_platform").str.casefold()
    rule = pd.Series("", index=annotated.index, dtype="string")
    rule.loc[
        eligible & (platform.str.contains("youtube", regex=False, na=False) | platform.eq("ytb"))
    ] = "YTB：description #手記の加筆 + title 手記の加筆"
    rule.loc[
        eligible & (platform.str.contains("tiktok", regex=False, na=False) | platform.eq("tt"))
    ] = "TT：description"
    rule.loc[eligible & rule.eq("")] = "按内容类型匹配"

    annotated["original_views"] = original_views
    annotated["is_july_traffic_boost"] = eligible.astype(bool)
    annotated["traffic_boost_rate"] = pd.Series(
        JULY_TRAFFIC_BOOST_RATE,
        index=annotated.index,
    ).where(eligible, 0.0)
    annotated["traffic_boost_views"] = bonus_views
    annotated["boosted_views"] = boosted_views
    annotated["traffic_boost_rule"] = rule
    return annotated


def apply_july_traffic_boost(
    data: pd.DataFrame,
    *,
    enabled: bool = True,
) -> pd.DataFrame:
    """Return dashboard data using original or eligible boosted play counts."""
    prepared = annotate_july_traffic_boost(data)
    prepared["views"] = (
        prepared["boosted_views"] if enabled else prepared["original_views"]
    )
    return prepared


def is_july_traffic_boost_month(value: date) -> bool:
    return value.year == 2026 and value.month == 7
