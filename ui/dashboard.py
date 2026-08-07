from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from config.settings import Settings
from core.dashboard_bootstrap import DEFAULT_DASHBOARD_SOURCE_DIR
from core.dashboard_processor import (
    DashboardProcessor,
    DashboardResult,
    build_creator_summary,
    build_daily_summary,
    build_dimension_summary,
    date_bounds,
    filter_dashboard_data,
)
from core.cross_industry import (
    cross_industry_totals,
    exclude_cross_industry_posts,
    normalize_video_url,
    parse_pasted_urls,
)
from core.grassroot_compensation import (
    GrassrootCompensationResult,
    calculate_grassroot_compensation,
)
from core.traffic_boost import apply_july_traffic_boost, annotate_july_traffic_boost
from core.file_processor import UploadedExcel
from database.dashboard_repository import DashboardRepository
from database.koc_repository import KOCRepository
from models.enums import CreatorCategory
from models.koc import KOCRecord
from services.follower_service import FollowerService
from ui.dashboard_cache import (
    dashboard_cache_token,
    ensure_dashboard_seeded_once,
    load_prepared_dashboard_data,
    prepared_dashboard_result,
)


_FILTER_KEYS = (
    "dashboard_category_filter",
    "dashboard_platform_filter",
    "dashboard_content_filter",
    "dashboard_date_filter",
    "dashboard_creator_query",
    "dashboard_creator_filter",
    "dashboard_period_granularity",
    "dashboard_month_period",
    "dashboard_week_period",
    "dashboard_period_caption",
    "dashboard_include_cross_industry",
    "dashboard_include_july_traffic_boost",
)

_CHART_HEIGHT = 320
_METRICS_PER_ROW = 3
_JULY_TRAFFIC_BOOST_PERIOD = "2026-07"


DASHBOARD_CSS = """
<style>
  :root {
    --koc-bg: #f4f7f8;
    --koc-surface: #ffffff;
    --koc-surface-soft: #eef4f4;
    --koc-sidebar: #e8f0f0;
    --koc-border: #d4dfe1;
    --koc-border-strong: #b9cacc;
    --koc-text: #1c2933;
    --koc-muted: #667781;
    --koc-primary: #167d83;
    --koc-primary-hover: #11676c;
    --koc-primary-soft: #dceced;
  }
  [data-testid="stAppViewContainer"] {
    background: var(--koc-bg);
    color: var(--koc-text);
  }
  [data-testid="stApp"],
  [data-testid="stMain"],
  [data-testid="stMainBlockContainer"] {
    background: var(--koc-bg);
    color: var(--koc-text);
  }
  [data-testid="stHeader"] {
    background: rgba(244, 247, 248, 0.96);
  }
  [data-testid="stSidebar"] {
    background: var(--koc-sidebar);
    border-right: 1px solid var(--koc-border);
  }
  [data-testid="stSidebar"] * {
    color: var(--koc-text);
  }
  .block-container {
    max-width: 1560px;
    padding-top: 1.5rem;
    padding-bottom: 3rem;
  }
  .dashboard-kicker {
    color: var(--koc-primary);
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    margin-bottom: 0.4rem;
    text-transform: uppercase;
  }
  .dashboard-title {
    color: #17252b;
    font-size: 2rem;
    font-weight: 700;
    line-height: 1.2;
    margin: 0;
  }
  .dashboard-subtitle {
    color: var(--koc-muted);
    font-size: 0.95rem;
    margin-top: 0.55rem;
  }
  [data-testid="stMetric"] {
    background: var(--koc-surface);
    border: 1px solid var(--koc-border);
    border-radius: 6px;
    padding: 0.9rem 1rem;
    min-height: 112px;
    box-shadow: 0 1px 2px rgba(28, 41, 51, 0.04);
  }
  [data-testid="stMetricLabel"] {
    color: var(--koc-muted);
  }
  [data-testid="stMetricValue"] {
    color: var(--koc-text);
  }
  [data-testid="stDataFrame"] {
    border: 1px solid var(--koc-border);
    border-radius: 6px;
    overflow: hidden;
  }
  [data-testid="stExpander"] {
    border: 1px solid var(--koc-border);
    border-radius: 6px;
    background: var(--koc-surface);
  }
  [data-testid="stTextInput"] input,
  [data-testid="stNumberInput"] input,
  [data-testid="stDateInput"] input,
  [data-testid="stTextArea"] textarea,
  [data-baseweb="base-input"] input,
  [data-baseweb="select"] > div {
    background: var(--koc-surface);
    border-color: var(--koc-border-strong);
    color: var(--koc-text);
  }
  [data-baseweb="popover"] {
    background: var(--koc-surface);
    border: 1px solid var(--koc-border);
  }
  [data-baseweb="menu"] {
    background: var(--koc-surface);
  }
  [data-baseweb="menu"] li:hover,
  [data-baseweb="select"] [aria-selected="true"] {
    background: var(--koc-primary-soft);
  }
  [data-testid="stCaptionContainer"] {
    color: var(--koc-muted);
  }
  [data-testid="stAlert"] {
    background: var(--koc-surface-soft);
    border-color: var(--koc-border-strong);
  }
  [data-testid="stButton"] > button[kind="primary"] {
    background: var(--koc-primary);
    border-color: var(--koc-primary);
    color: #ffffff;
  }
  [data-testid="stButton"] > button {
    background: var(--koc-surface);
    border-color: var(--koc-border-strong);
    color: var(--koc-text);
    border-radius: 5px;
  }
  [data-testid="stButton"] > button:hover {
    border-color: var(--koc-primary);
    color: var(--koc-primary-hover);
  }
  [data-testid="stButton"] > button[kind="primary"]:hover {
    background: var(--koc-primary-hover);
    border-color: var(--koc-primary-hover);
    color: #ffffff;
  }
  [data-testid="stDivider"] {
    border-color: var(--koc-border);
  }
  [data-testid="stVegaLiteChart"] {
    background: var(--koc-surface);
    border: 1px solid var(--koc-border);
    border-radius: 6px;
    padding: 0.5rem;
  }
  [data-baseweb="tab-list"] {
    border-bottom-color: var(--koc-border);
    gap: 0.25rem;
  }
  [data-baseweb="tab"] {
    color: var(--koc-muted);
    background: transparent;
    border-radius: 5px 5px 0 0;
  }
  [data-baseweb="tab"][aria-selected="true"] {
    color: var(--koc-primary-hover);
    background: var(--koc-primary-soft);
  }
  [data-testid="stForm"],
  [data-testid="stDataEditor"],
  [data-testid="stDataFrame"] > div {
    background: var(--koc-surface);
  }
  [data-testid="stDataEditor"] [role="grid"],
  [data-testid="stDataFrame"] [role="grid"],
  [data-testid="stDataEditor"] [role="columnheader"],
  [data-testid="stDataFrame"] [role="columnheader"] {
    background: var(--koc-surface-soft);
    color: var(--koc-text);
    border-color: var(--koc-border);
  }
  [data-testid="stDataEditor"] [role="gridcell"],
  [data-testid="stDataFrame"] [role="gridcell"] {
    background: var(--koc-surface);
    color: var(--koc-text);
    border-color: var(--koc-border);
  }
  [data-testid="stDataEditor"] [role="gridcell"]:hover,
  [data-testid="stDataFrame"] [role="gridcell"]:hover {
    background: var(--koc-primary-soft);
  }
  [data-testid="stPopoverBody"],
  [data-baseweb="modal"] {
    background: var(--koc-surface);
    color: var(--koc-text);
  }
  [data-testid="stFileUploaderDropzone"] {
    background: var(--koc-surface);
    border-color: var(--koc-border-strong);
  }
  [data-testid="stFileUploaderDropzone"]:hover {
    background: var(--koc-surface-soft);
    border-color: var(--koc-primary);
  }
  [data-testid="stRadio"] label,
  [data-testid="stCheckbox"] label,
  [data-testid="stToggle"] label {
    color: var(--koc-text);
  }
  a {
    color: var(--koc-primary-hover);
  }
</style>
"""


def _numeric_sum(data: pd.DataFrame, column: str) -> int:
    values = pd.to_numeric(data[column], errors="coerce")
    return int(values.sum()) if values.notna().any() else 0


def _average_views(data: pd.DataFrame) -> int:
    values = pd.to_numeric(data["views"], errors="coerce")
    return int(round(values.mean())) if values.notna().any() else 0


def _engagement_rate(data: pd.DataFrame) -> float | None:
    views = _numeric_sum(data, "views")
    if views <= 0:
        return None
    interactions = sum(
        _numeric_sum(data, column)
        for column in ("likes", "comment", "reposted", "collect")
    )
    return interactions / views


def _format_rate(value: float | None) -> str:
    return "--" if value is None else f"{value:.2%}"


def _clear_dashboard_filters() -> None:
    for key in _FILTER_KEYS:
        st.session_state.pop(key, None)


def _date_filter_is_current(value: object, earliest: date, latest: date) -> bool:
    if isinstance(value, date):
        values = (value,)
    elif isinstance(value, (tuple, list)):
        values = tuple(value)
    else:
        return False
    return bool(values) and all(
        isinstance(item, date) and earliest <= item <= latest for item in values
    )


def _creator_filter_options(
    data: pd.DataFrame,
    creator_records: list[KOCRecord],
) -> tuple[list[str], dict[str, str]]:
    unique_creators = data[
        ["creator_key", "creator_label", "user_id"]
    ].drop_duplicates(subset=["creator_key"])
    labels: dict[str, str] = {}
    for record in unique_creators.to_dict("records"):
        key = str(record["creator_key"])
        label = str(record["creator_label"])
        user_id = str(record["user_id"])
        labels[key] = label if label == user_id else f"{label} · {user_id}"
    for record in creator_records:
        labels.setdefault(record.user_id, f"{record.koc_name} · {record.user_id}")
    options = sorted(labels, key=lambda key: labels[key].casefold())
    return options, labels


def _month_end(value: date) -> date:
    if value.month == 12:
        next_month = date(value.year + 1, 1, 1)
    else:
        next_month = date(value.year, value.month + 1, 1)
    return next_month - timedelta(days=1)


def _render_filters(
    data: pd.DataFrame,
    creator_records: list[KOCRecord],
    repository: DashboardRepository,
) -> pd.DataFrame:
    categories = sorted(data["creator_category"].dropna().astype(str).unique())
    platforms = sorted(data["source_platform"].dropna().astype(str).unique())
    content_types = sorted(data["content_type"].dropna().astype(str).unique())
    creator_options, creator_labels = _creator_filter_options(data, creator_records)
    earliest, latest = date_bounds(data)
    date_values = pd.to_datetime(data["publish_date"], errors="coerce").dt.date.dropna()
    month_options = sorted(
        {date(value.year, value.month, 1) for value in date_values},
        reverse=True,
    )
    week_options = sorted(
        {value - timedelta(days=value.weekday()) for value in date_values},
        reverse=True,
    )

    heading, reset = st.columns((6, 1))
    heading.subheader("数据范围")
    if reset.button(
        "重置筛选",
        icon=":material/restart_alt:",
        key="dashboard_reset_filters",
        help="清除当前筛选条件",
        width="stretch",
    ):
        _clear_dashboard_filters()
        st.rerun()

    first_row = st.columns((1.35, 1.75, 1, 1))
    creator_query = first_row[0].text_input(
        "搜索达人或 UID",
        placeholder="名称或 UID",
        key="dashboard_creator_query",
    )
    selected_creators = first_row[1].multiselect(
        "达人",
        creator_options,
        format_func=lambda value: creator_labels[value],
        placeholder="全部达人",
        key="dashboard_creator_filter",
    )
    selected_categories = first_row[2].multiselect(
        "合作类别",
        categories,
        placeholder="全部类别",
        key="dashboard_category_filter",
    )
    selected_platforms = first_row[3].multiselect(
        "平台",
        platforms,
        placeholder="全部平台",
        key="dashboard_platform_filter",
    )

    second_row = st.columns((1, 1.1, 1.45, 1.55))
    selected_content_types = second_row[0].multiselect(
        "内容形式",
        content_types,
        placeholder="全部形式",
        key="dashboard_content_filter",
    )
    period_mode = second_row[1].radio(
        "统计周期",
        ("月度", "周度", "自定义"),
        horizontal=True,
        key="dashboard_period_granularity",
    )
    include_cross_industry = second_row[3].toggle(
        "包含异业数据",
        value=False,
        key="dashboard_include_cross_industry",
        help="打开后展示全部投稿；关闭后排除异业视频。薪酬结算始终排除异业视频。",
    )
    selected_dates: tuple[date, date] | tuple[()] | date | None = None
    start_date: date | None = None
    end_date: date | None = None
    period_caption = "统计周期：全部数据"
    if period_mode == "月度" and month_options:
        selected_month = second_row[2].selectbox(
            "月份",
            month_options,
            format_func=lambda value: f"{value.year}年{value.month}月",
            key="dashboard_month_period",
        )
        start_date = selected_month
        end_date = _month_end(selected_month)
        period_caption = (
            f"统计周期：{selected_month.month}/{selected_month.day}-"
            f"{end_date.month}/{end_date.day}"
        )
    elif period_mode == "周度" and week_options:
        selected_week = second_row[2].selectbox(
            "周度",
            week_options,
            format_func=lambda value: (
                f"{value.month}/{value.day}-{(value + timedelta(days=6)).month}/"
                f"{(value + timedelta(days=6)).day}"
            ),
            key="dashboard_week_period",
        )
        start_date = selected_week
        end_date = selected_week + timedelta(days=6)
        period_caption = (
            f"统计周期：{selected_week.month}/{selected_week.day}-"
            f"{end_date.month}/{end_date.day}"
        )
    elif earliest is not None and latest is not None:
        previous_dates = st.session_state.get("dashboard_date_filter")
        if previous_dates is not None and not _date_filter_is_current(
            previous_dates,
            earliest,
            latest,
        ):
            st.session_state.pop("dashboard_date_filter", None)
        selected_dates = second_row[2].date_input(
            "投稿日期",
            value=(earliest, latest),
            min_value=earliest,
            max_value=latest,
            key="dashboard_date_filter",
        )
        if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
            start_date, end_date = selected_dates
        elif isinstance(selected_dates, date):
            start_date = end_date = selected_dates
        if start_date is not None and end_date is not None:
            period_caption = (
                f"统计周期：{start_date.month}/{start_date.day}-"
                f"{end_date.month}/{end_date.day}"
            )
    st.session_state["dashboard_period_caption"] = period_caption

    scoped = filter_dashboard_data(
        data,
        creator_categories=selected_categories,
        source_platforms=selected_platforms,
        content_types=selected_content_types,
        creator_keys=selected_creators,
        creator_query=creator_query,
        start_date=start_date,
        end_date=end_date,
    )
    excluded_count, excluded_views = cross_industry_totals(scoped)
    visible = (
        scoped.reset_index(drop=True)
        if include_cross_industry
        else exclude_cross_industry_posts(scoped)
    )
    eligible_boost_count = int(
        visible.get("is_july_traffic_boost", pd.Series(False, index=visible.index))
        .fillna(False)
        .astype(bool)
        .sum()
    )
    campaign_dates = pd.to_datetime(
        visible.get("publish_date", pd.Series(index=visible.index, dtype="object")),
        errors="coerce",
    )
    campaign_in_scope = campaign_dates.dt.strftime("%Y-%m").eq(
        _JULY_TRAFFIC_BOOST_PERIOD
    ).any()
    persisted_boost = repository.get_traffic_boost_enabled(
        _JULY_TRAFFIC_BOOST_PERIOD
    )
    boost_key = "dashboard_include_july_traffic_boost"
    if boost_key not in st.session_state:
        st.session_state[boost_key] = persisted_boost
    include_july_traffic_boost = second_row[3].toggle(
        "应用7月流量加成",
        disabled=not campaign_in_scope,
        key=boost_key,
        help=(
            "打开后保存 2026 年 7 月的结算口径：符合规则的视频按加成后播放量"
            "展示并用于草根、长包实时结算。"
        ),
    )
    if include_july_traffic_boost != persisted_boost:
        repository.save_traffic_boost_enabled(
            _JULY_TRAFFIC_BOOST_PERIOD,
            include_july_traffic_boost,
        )
    second_row[3].caption(
        f"{len(creator_options):,} 位达人 · {period_caption}"
    )
    if excluded_count:
        second_row[3].caption(
            f"异业 {excluded_count:,} 条 · {excluded_views:,} 播放"
        )
    if eligible_boost_count:
        second_row[3].caption(
            f"流量加成：{eligible_boost_count:,} 条符合 #手記の加筆 规则"
        )
    return apply_july_traffic_boost(
        visible,
        enabled=include_july_traffic_boost,
    )


def _cross_industry_post_lookup(data: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "url_key",
        "creator",
        "title",
        "publish_date",
        "views",
        "source_platform",
    ]
    if data.empty or "url" not in data:
        return pd.DataFrame(columns=columns)
    lookup = data.copy()
    lookup["url_key"] = lookup["url"].map(
        lambda value: (
            identity.url_key
            if (identity := normalize_video_url(value)) is not None
            else ""
        )
    )
    lookup = lookup.loc[lookup["url_key"].ne("")].copy()
    if lookup.empty:
        return pd.DataFrame(columns=columns)
    if "creator_label" in lookup:
        creator = lookup["creator_label"]
    elif "koc_name" in lookup:
        creator = lookup["koc_name"]
    else:
        creator = pd.Series("", index=lookup.index, dtype="string")
    lookup["creator"] = creator.astype("string").fillna("")
    for column in ("title", "publish_date", "views", "source_platform"):
        if column not in lookup:
            lookup[column] = pd.NA
    lookup["views"] = pd.to_numeric(lookup["views"], errors="coerce").astype(
        "Int64"
    )
    return (
        lookup.sort_values("publish_date", ascending=False, kind="stable")
        .drop_duplicates("url_key", keep="first")
        .reindex(columns=columns)
        .reset_index(drop=True)
    )


def _cross_industry_preview(url_text: str, data: pd.DataFrame) -> pd.DataFrame:
    lookup = _cross_industry_post_lookup(data).set_index("url_key", drop=False)
    rows: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    for url in parse_pasted_urls(url_text):
        identity = normalize_video_url(url)
        if identity is None or identity.url_key in seen_keys:
            continue
        seen_keys.add(identity.url_key)
        matched = lookup.loc[identity.url_key] if identity.url_key in lookup.index else None
        rows.append(
            {
                "url_key": identity.url_key,
                "匹配状态": "已匹配" if matched is not None else "待匹配",
                "平台": (
                    str(matched["source_platform"])
                    if matched is not None and pd.notna(matched["source_platform"])
                    else identity.platform
                ),
                "达人": (
                    str(matched["creator"])
                    if matched is not None and pd.notna(matched["creator"])
                    else ""
                ),
                "标题": (
                    str(matched["title"])
                    if matched is not None and pd.notna(matched["title"])
                    else ""
                ),
                "投稿日期": (
                    matched["publish_date"] if matched is not None else pd.NA
                ),
                "播放量": matched["views"] if matched is not None else pd.NA,
                "链接": identity.original_url,
            }
        )
    return pd.DataFrame(rows)


def _render_cross_industry_manager(
    repository: DashboardRepository,
    data: pd.DataFrame,
) -> None:
    preview_key = "dashboard_cross_industry_preview"
    with st.expander("异业数据管理", expanded=False):
        entry_columns = st.columns((2.3, 1, 0.8))
        url_text = entry_columns[0].text_area(
            "异业视频链接",
            placeholder="每行一条 YouTube 或 TikTok 链接",
            height=118,
            key="dashboard_cross_industry_urls",
        )
        reason = entry_columns[1].text_input(
            "排除原因",
            value="异业活动",
            key="dashboard_cross_industry_reason",
        )
        identify = entry_columns[2].button(
            "识别链接",
            icon=":material/link:",
            width="stretch",
            disabled=not url_text.strip(),
            key="dashboard_cross_industry_identify",
        )
        if identify:
            preview = _cross_industry_preview(url_text, data)
            st.session_state[preview_key] = preview
            if preview.empty:
                st.warning("没有识别到可用的视频链接。")

        preview = st.session_state.get(preview_key)
        if isinstance(preview, pd.DataFrame) and not preview.empty:
            st.dataframe(
                preview.drop(columns="url_key", errors="ignore"),
                hide_index=True,
                width="stretch",
                height=min(300, 72 + len(preview) * 36),
                column_config={
                    "播放量": st.column_config.NumberColumn("播放量", format="%d"),
                    "链接": st.column_config.LinkColumn("链接"),
                },
            )
            matched_count = int(preview["匹配状态"].eq("已匹配").sum())
            pending_count = len(preview) - matched_count
            st.caption(
                f"已匹配 {matched_count:,} 条 · 待后续导入匹配 {pending_count:,} 条"
            )
            if st.button(
                "确认标记为异业",
                type="primary",
                icon=":material/block:",
                key="dashboard_cross_industry_confirm",
            ):
                repository.save_cross_industry_exclusions(
                    preview["链接"].astype(str).tolist(),
                    reason=reason,
                )
                st.session_state.pop(preview_key, None)
                st.session_state["dashboard_flash"] = (
                    f"已将 {len(preview):,} 条视频标记为异业数据。"
                )
                st.rerun()

        active = repository.list_cross_industry_exclusions()
        st.markdown("#### 已排除链接")
        if active.empty:
            st.caption("当前没有异业视频记录。")
            return

        lookup = _cross_industry_post_lookup(data)
        current = active.merge(lookup, on="url_key", how="left")
        current["匹配状态"] = current["title"].notna().map(
            {True: "已匹配", False: "待匹配"}
        )
        current["恢复"] = False
        current = current.rename(
            columns={
                "id": "记录ID",
                "platform": "平台",
                "creator": "达人",
                "title": "标题",
                "publish_date": "投稿日期",
                "views": "播放量",
                "original_url": "链接",
                "reason": "排除原因",
                "updated_at": "更新时间",
            }
        )
        search_columns = st.columns((1.4, 1, 2.6))
        query = search_columns[0].text_input(
            "搜索异业链接",
            placeholder="达人、标题或链接",
            key="dashboard_cross_industry_search",
        )
        month_values = pd.to_datetime(current["投稿日期"], errors="coerce")
        months = sorted(month_values.dt.strftime("%Y-%m").dropna().unique(), reverse=True)
        selected_month = search_columns[1].selectbox(
            "投稿月份",
            ["全部月份", *months],
            key="dashboard_cross_industry_month",
        )
        if query.strip():
            folded = query.strip().casefold()
            matches = pd.Series(False, index=current.index)
            for column in ("达人", "标题", "链接", "平台"):
                matches |= current[column].astype("string").str.casefold().str.contains(
                    folded,
                    regex=False,
                    na=False,
                )
            current = current.loc[matches]
        if selected_month != "全部月份":
            current = current.loc[month_values.dt.strftime("%Y-%m").eq(selected_month)]
        search_columns[2].caption(f"当前 {len(current):,} 条异业视频")
        if current.empty:
            st.info("当前筛选条件下没有异业视频。")
            return

        editor_columns = [
            "恢复",
            "记录ID",
            "匹配状态",
            "平台",
            "达人",
            "标题",
            "投稿日期",
            "播放量",
            "链接",
            "排除原因",
            "更新时间",
        ]
        editable = current.reindex(columns=editor_columns).reset_index(drop=True)
        edited = st.data_editor(
            editable,
            hide_index=True,
            width="stretch",
            height=min(360, 72 + len(editable) * 36),
            num_rows="fixed",
            disabled=[column for column in editor_columns if column != "恢复"],
            key="dashboard_cross_industry_restore_editor",
            column_config={
                "恢复": st.column_config.CheckboxColumn("恢复计费"),
                "记录ID": None,
                "播放量": st.column_config.NumberColumn("播放量", format="%d"),
                "链接": st.column_config.LinkColumn("链接"),
            },
        )
        restore_ids = pd.to_numeric(
            edited.loc[edited["恢复"].fillna(False), "记录ID"],
            errors="coerce",
        ).dropna()
        if st.button(
            "恢复选中视频计费",
            icon=":material/restore:",
            disabled=restore_ids.empty,
            key="dashboard_cross_industry_restore",
        ):
            restored = repository.deactivate_cross_industry_exclusions(
                restore_ids.astype(int).tolist()
            )
            st.session_state["dashboard_flash"] = (
                f"已恢复 {restored:,} 条视频的正常展示与计费。"
            )
            st.rerun()


def _render_overview_metrics(data: pd.DataFrame) -> None:
    interactions = sum(
        _numeric_sum(data, column)
        for column in ("likes", "comment", "reposted", "collect")
    )
    metrics = (
        ("投稿数", len(data)),
        ("覆盖达人", int(data["creator_key"].nunique())),
        ("累计播放量", _numeric_sum(data, "views")),
        ("平均播放量", _average_views(data)),
        ("累计互动量", interactions),
        ("互动率", _format_rate(_engagement_rate(data))),
    )
    for offset in range(0, len(metrics), _METRICS_PER_ROW):
        columns = st.columns(_METRICS_PER_ROW, gap="small")
        for column, (label, value) in zip(
            columns,
            metrics[offset : offset + _METRICS_PER_ROW],
        ):
            column.metric(label, value)


def _settlement_month_options(data: pd.DataFrame) -> list[date]:
    dates = pd.to_datetime(data["publish_date"], errors="coerce").dt.date.dropna()
    return sorted(
        {date(value.year, value.month, 1) for value in dates}, reverse=True
    )


def _period_month_key(value: date) -> str:
    return f"{value.year}-{value.month:02d}"


def _month_data(data: pd.DataFrame, value: date) -> pd.DataFrame:
    return filter_dashboard_data(
        data,
        start_date=value,
        end_date=_month_end(value),
    )


def _grassroot_records(records: list[KOCRecord]) -> list[KOCRecord]:
    return [
        record
        for record in records
        if CreatorCategory.GRASSROOT in record.creator_categories
    ]


def _run_grassroot_follower_refresh(
    service: FollowerService,
    records: list[KOCRecord],
):
    progress = st.progress(0.0)
    current = st.empty()

    def show_current(completed: int, total: int, record: KOCRecord) -> None:
        progress.progress((completed - 1) / total if total else 0.0)
        current.caption(f"正在更新粉丝数：{record.koc_name}（{completed}/{total}）")

    def show_progress(
        completed: int,
        total: int,
        record: KOCRecord,
        _outcome: object,
    ) -> None:
        progress.progress(completed / total if total else 1.0)
        current.caption(f"已完成：{record.koc_name}（{completed}/{total}）")

    result = service.update_many(
        [record.id for record in records],
        progress_callback=show_progress,
        start_callback=show_current,
    )
    progress.empty()
    current.empty()
    return result


def _compensation_csv(details: pd.DataFrame) -> bytes:
    return details.to_csv(index=False).encode("utf-8-sig")


def _format_cpm(value: float | None) -> str:
    return "--" if value is None else f"${value:,.2f}"


def _render_compensation_metrics(result: GrassrootCompensationResult) -> None:
    ready_count = int(result.details["结算状态"].isin(["可结算", "未达标"]).sum())
    pending_count = int(result.details["结算状态"].eq("待更新粉丝").sum())
    metrics = (
        ("草根总体 CPM", _format_cpm(result.overall_cpm)),
        ("可结算达人", ready_count),
        ("待更新粉丝", pending_count),
        ("总金额（日元）", f"¥{result.total_amount_jpy:,.0f}"),
        ("有道应收（美元）", f"${result.youdao_receivable_usd:,.2f}"),
    )
    for column, (label, value) in zip(st.columns(5), metrics):
        column.metric(label, value)


def _render_grassroot_compensation(
    data: pd.DataFrame,
    repository: DashboardRepository,
    creator_repository: KOCRepository,
    settings: Settings,
) -> None:
    st.subheader("草根达人月度报酬")
    month_options = _settlement_month_options(data)
    if not month_options:
        st.info("当前没有可用于结算的月度投稿。")
        return
    selected_month = st.selectbox(
        "结算月份",
        month_options,
        format_func=lambda value: f"{value.year}年{value.month}月",
        key="grassroot_compensation_month",
    )
    period_key = _period_month_key(selected_month)
    saved_rate = repository.get_jpy_to_usd_rate(period_key)
    rate_key = f"grassroot_compensation_rate_{period_key}"
    if rate_key not in st.session_state:
        st.session_state[rate_key] = saved_rate or 0.0

    setting_column, action_column = st.columns((1.25, 2.75))
    with setting_column:
        with st.form(f"grassroot_compensation_rate_form_{period_key}"):
            rate = st.number_input(
                "JPY → USD 汇率（当月3日）",
                min_value=0.0,
                step=0.0001,
                format="%.6f",
                key=rate_key,
            )
            save_rate = st.form_submit_button(
                "保存汇率",
                icon=":material/save:",
                width="stretch",
            )
        if save_rate:
            if rate <= 0:
                st.error("请输入大于 0 的日元兑美元汇率。")
            else:
                repository.save_jpy_to_usd_rate(period_key, rate)
                st.rerun()

    grassroot_records = _grassroot_records(
        creator_repository.list(include_inactive=False)
    )
    with action_column:
        refresh = st.button(
            "更新草根粉丝并结算",
            type="primary",
            icon=":material/refresh:",
            disabled=not grassroot_records or saved_rate is None,
            help="更新失败的达人不会进入本次结算；可手动更新后重新结算。",
            key=f"grassroot_compensation_refresh_{period_key}",
        )
        recalculate = st.button(
            "手动更新后重新结算",
            icon=":material/calculate:",
            disabled=saved_rate is None,
            help="仅在达人库中手动补齐更新失败的粉丝数后使用。",
            key=f"grassroot_compensation_recalculate_{period_key}",
        )
        if saved_rate is None:
            st.caption("请先保存该月 3 日的 JPY → USD 汇率。")
        elif not grassroot_records:
            st.caption("达人库中没有启用的草根达人。")

    if refresh:
        follower_service = FollowerService(
            creator_repository,
            youtube_api_key=settings.youtube_api_key,
            tiktok_browser_data_dir=settings.tiktok_browser_data_dir,
            tiktok_persistent_headless=settings.tiktok_persistent_headless,
        )
        update_result = _run_grassroot_follower_refresh(
            follower_service,
            grassroot_records,
        )
        st.session_state["grassroot_compensation_refresh_period"] = period_key
        st.session_state["grassroot_compensation_update_result"] = update_result
        st.rerun()

    if recalculate:
        st.session_state["grassroot_compensation_refresh_period"] = period_key
        st.session_state.pop("grassroot_compensation_update_result", None)
        st.rerun()

    if st.session_state.get("grassroot_compensation_refresh_period") != period_key:
        st.info("保存汇率后，请更新粉丝数再开始本月结算。")
        return
    if saved_rate is None:
        return

    update_result = st.session_state.get("grassroot_compensation_update_result")
    if update_result is not None:
        st.caption(
            f"本次粉丝更新：成功 {update_result.success_count}，"
            f"失败 {update_result.failed_count}，跳过 {update_result.skipped_count}。"
        )
    refreshed_records = creator_repository.list(include_inactive=False)
    result = calculate_grassroot_compensation(
        _month_data(data, selected_month),
        refreshed_records,
        jpy_to_usd_rate=saved_rate,
    )
    _render_compensation_metrics(result)
    st.dataframe(
        result.details,
        hide_index=True,
        width="stretch",
        height=420,
        column_config={
            "计费播放量": st.column_config.NumberColumn("计费播放量", format="%d"),
            "投稿数": st.column_config.NumberColumn("投稿数", format="%d"),
            "粉丝数": st.column_config.NumberColumn("粉丝数", format="%d"),
            "short rank金额": st.column_config.NumberColumn("short rank金额", format="¥%d"),
            "long+livestreamrank金额": st.column_config.NumberColumn(
                "long+livestreamrank金额", format="¥%d"
            ),
            "short 投稿数奖励": st.column_config.NumberColumn(
                "short 投稿数奖励", format="¥%d"
            ),
            "long+livestream投稿数奖励": st.column_config.NumberColumn(
                "long+livestream投稿数奖励", format="¥%d"
            ),
            "总金额（日元）": st.column_config.NumberColumn("总金额（日元）", format="¥%d"),
            "博主应收（日元）(包含15$手续费)": st.column_config.NumberColumn(
                "博主应收（日元）(包含15$手续费)", format="¥%d"
            ),
            "有道应收（日元）（包含服务费）": st.column_config.NumberColumn(
                "有道应收（日元）（包含服务费）", format="¥%d"
            ),
            "博主应收（美元）": st.column_config.NumberColumn(
                "博主应收（美元）", format="$%.2f"
            ),
            "有道应收（美元）（包含服务费）": st.column_config.NumberColumn(
                "有道应收（美元）（包含服务费）", format="$%.2f"
            ),
            "CPM": st.column_config.NumberColumn("CPM", format="$%.2f"),
        },
    )
    st.download_button(
        "下载草根月度报酬 CSV",
        data=_compensation_csv(result.details),
        file_name=f"草根达人月度报酬_{period_key}.csv",
        mime="text/csv",
        icon=":material/download:",
    )


def _rank_creator_summary(
    data: pd.DataFrame,
    metric: str,
    *,
    limit: int,
    creator_records: list[KOCRecord] | None = None,
) -> pd.DataFrame:
    summary = build_creator_summary(data, creator_records)
    if summary.empty:
        return summary
    tie_breaker = "total_views" if metric == "post_count" else "post_count"
    return summary.sort_values(
        [metric, tie_breaker, "creator_label"],
        ascending=[False, False, True],
        kind="stable",
    ).head(limit).reset_index(drop=True)


def _platform_posts(data: pd.DataFrame, platform: str) -> pd.DataFrame:
    values = data["source_platform"].astype("string").str.casefold()
    if platform == "ytb":
        mask = values.str.contains("youtube", regex=False, na=False) | values.eq("ytb")
    elif platform == "tt":
        mask = values.str.contains("tiktok", regex=False, na=False) | values.eq("tt")
    else:
        raise ValueError(f"Unsupported dashboard platform: {platform}")
    return data.loc[mask].reset_index(drop=True)


def _platform_top_ranking(
    data: pd.DataFrame,
    platform: str,
    metric: str,
) -> pd.DataFrame:
    return _rank_creator_summary(
        _platform_posts(data, platform),
        metric,
        limit=30,
    )


def _platform_video_top_ranking(
    data: pd.DataFrame,
    platform: str,
    *,
    limit: int = 20,
) -> pd.DataFrame:
    posts = _platform_posts(data, platform)
    if posts.empty:
        return posts
    ranked = posts.copy()
    ranked["_video_views"] = pd.to_numeric(ranked["views"], errors="coerce").fillna(0)
    return ranked.sort_values(
        "_video_views",
        ascending=False,
        kind="stable",
    ).head(limit).reset_index(drop=True)


def _video_ranking_display_frame(ranking: pd.DataFrame) -> pd.DataFrame:
    display = ranking.reindex(
        columns=[
            "creator_label",
            "title",
            "content_type",
            "publish_date",
            "views",
            "url",
        ]
    ).copy()
    display.insert(0, "排名", range(1, len(display) + 1))
    display["views"] = pd.to_numeric(display["views"], errors="coerce").round().astype(
        "Int64"
    )
    return display.rename(
        columns={
            "creator_label": "达人",
            "title": "视频标题",
            "content_type": "内容形式",
            "publish_date": "投稿日期",
            "views": "播放量",
            "url": "链接",
        }
    )


def _ranking_display_frame(summary: pd.DataFrame, metric: str) -> pd.DataFrame:
    display = summary[
        ["creator_label", "post_count", "total_views", "average_views"]
    ].copy()
    display.insert(0, "排名", range(1, len(display) + 1))
    for column in ("post_count", "total_views", "average_views"):
        display[column] = pd.to_numeric(display[column], errors="coerce").round().astype(
            "Int64"
        )
    metric_label = "累计播放量" if metric == "total_views" else "投稿数"
    return display.rename(
        columns={
            "creator_label": "达人",
            "post_count": "投稿数",
            "total_views": "累计播放量",
            "average_views": "平均播放量",
        }
    ).sort_values("排名", kind="stable").reset_index(drop=True).rename(
        columns={"排名": f"排名（按{metric_label}）"}
    )


def _render_platform_top30(data: pd.DataFrame) -> None:
    st.subheader("平台 Top 30")
    ytb_tab, tt_tab = st.tabs(["YTB · YouTube", "TT · TikTok"])
    for tab, platform in ((ytb_tab, "ytb"), (tt_tab, "tt")):
        with tab:
            platform_data = _platform_posts(data, platform)
            if platform_data.empty:
                st.info("当前筛选条件下没有该平台投稿。")
                continue
            view_column, post_column = st.columns(2)
            with view_column:
                st.caption("累计播放量 Top 30")
                st.dataframe(
                    _ranking_display_frame(
                        _platform_top_ranking(data, platform, "total_views"),
                        "total_views",
                    ),
                    hide_index=True,
                    width="stretch",
                    height=720,
                    column_config={
                        "累计播放量": st.column_config.NumberColumn(
                            "累计播放量", format="%d"
                        ),
                        "投稿数": st.column_config.NumberColumn("投稿数", format="%d"),
                        "平均播放量": st.column_config.NumberColumn(
                            "平均播放量", format="%d"
                        ),
                    },
                )
            with post_column:
                st.caption("投稿数 Top 30")
                st.dataframe(
                    _ranking_display_frame(
                        _platform_top_ranking(data, platform, "post_count"),
                        "post_count",
                    ),
                    hide_index=True,
                    width="stretch",
                    height=720,
                    column_config={
                        "累计播放量": st.column_config.NumberColumn(
                            "累计播放量", format="%d"
                        ),
                        "投稿数": st.column_config.NumberColumn("投稿数", format="%d"),
                        "平均播放量": st.column_config.NumberColumn(
                            "平均播放量", format="%d"
                        ),
                    },
                )


def _render_platform_video_top20(data: pd.DataFrame) -> None:
    st.subheader("视频播放量 Top 20")
    ytb_tab, tt_tab = st.tabs(["YTB · YouTube", "TT · TikTok"])
    for tab, platform in ((ytb_tab, "ytb"), (tt_tab, "tt")):
        with tab:
            ranking = _platform_video_top_ranking(data, platform)
            if ranking.empty:
                st.info("当前筛选条件下没有该平台投稿。")
                continue
            st.dataframe(
                _video_ranking_display_frame(ranking),
                hide_index=True,
                width="stretch",
                height=560,
                column_config={
                    "播放量": st.column_config.NumberColumn("播放量", format="%d"),
                    "链接": st.column_config.LinkColumn("链接"),
                },
            )


def _comparison_month_options(data: pd.DataFrame) -> list[date]:
    dates = pd.to_datetime(data["publish_date"], errors="coerce").dropna()
    if dates.empty:
        return []
    earliest = date(dates.min().year, dates.min().month, 1)
    latest = date(dates.max().year, dates.max().month, 1)
    values: list[date] = []
    current = latest
    while current >= earliest:
        values.append(current)
        current = (
            date(current.year - 1, 12, 1)
            if current.month == 1
            else date(current.year, current.month - 1, 1)
        )
    return values


def _comparison_scope(data: pd.DataFrame) -> pd.DataFrame:
    """Reuse the non-date dashboard filters for an apples-to-apples comparison."""
    scoped = filter_dashboard_data(
        data,
        creator_categories=st.session_state.get("dashboard_category_filter", ()),
        source_platforms=st.session_state.get("dashboard_platform_filter", ()),
        content_types=st.session_state.get("dashboard_content_filter", ()),
        creator_keys=st.session_state.get("dashboard_creator_filter", ()),
        creator_query=st.session_state.get("dashboard_creator_query", ""),
    )
    if not st.session_state.get("dashboard_include_cross_industry", False):
        scoped = exclude_cross_industry_posts(scoped)
    return apply_july_traffic_boost(
        scoped,
        enabled=st.session_state.get("dashboard_include_july_traffic_boost", False),
    )


def _month_comparison_summary(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame(columns=["month", "post_count", "total_views"])
    prepared = data.copy()
    prepared["month"] = pd.to_datetime(
        prepared["publish_date"], errors="coerce"
    ).dt.to_period("M").astype("string")
    prepared["_views"] = pd.to_numeric(prepared["views"], errors="coerce").fillna(0)
    return (
        prepared.loc[prepared["month"].notna()]
        .groupby("month", as_index=False)
        .agg(post_count=("month", "size"), total_views=("_views", "sum"))
        .sort_values("month", kind="stable")
        .reset_index(drop=True)
    )


def _comparison_frame(
    current: pd.DataFrame,
    baseline: pd.DataFrame,
    *,
    key: str,
    label: str,
) -> pd.DataFrame:
    current_frame = current.reindex(columns=[key, "post_count", "total_views"]).copy()
    baseline_frame = baseline.reindex(
        columns=[key, "post_count", "total_views"]
    ).copy()
    current_frame["当前名称"] = current.reindex(columns=[label])[label]
    baseline_frame["对比名称"] = baseline.reindex(columns=[label])[label]
    current_frame = current_frame.rename(
        columns={
            "post_count": "当前投稿数",
            "total_views": "当前播放量",
        }
    )
    baseline_frame = baseline_frame.rename(
        columns={
            "post_count": "对比投稿数",
            "total_views": "对比播放量",
        }
    )
    merged = current_frame.merge(
        baseline_frame,
        on=key,
        how="outer",
    )
    merged[label] = merged["当前名称"].fillna(merged["对比名称"]).fillna("未分类")
    for column in ("当前投稿数", "当前播放量", "对比投稿数", "对比播放量"):
        merged[column] = pd.to_numeric(merged[column], errors="coerce").fillna(0).astype(int)
    merged["播放量变化"] = merged["当前播放量"] - merged["对比播放量"]
    merged["投稿数变化"] = merged["当前投稿数"] - merged["对比投稿数"]
    merged["播放量增长率"] = merged["播放量变化"].div(
        merged["对比播放量"].where(merged["对比播放量"] > 0)
    )
    return merged.drop(columns=["当前名称", "对比名称"]).sort_values(
        ["当前播放量", "播放量变化", label],
        ascending=[False, False, True],
        kind="stable",
    ).reset_index(drop=True)


def _dimension_comparison(
    current: pd.DataFrame,
    baseline: pd.DataFrame,
    dimension: str,
) -> pd.DataFrame:
    return _comparison_frame(
        build_dimension_summary(current, dimension),
        build_dimension_summary(baseline, dimension),
        key=dimension,
        label=dimension,
    )


def _creator_comparison(
    current: pd.DataFrame,
    baseline: pd.DataFrame,
    creator_records: list[KOCRecord],
) -> pd.DataFrame:
    return _comparison_frame(
        build_creator_summary(current, creator_records),
        build_creator_summary(baseline, creator_records),
        key="creator_key",
        label="creator_label",
    )


_CREATOR_VIDEO_TYPE_SPECS = (
    ("long", "Long"),
    ("livestream", "Livestream"),
    ("ytb shorts", "Shorts"),
    ("tiktok", "TikTok"),
)


def _creator_video_type_summary(data: pd.DataFrame) -> pd.DataFrame:
    columns = ["creator_key"]
    for _content_type, label in _CREATOR_VIDEO_TYPE_SPECS:
        columns.extend([f"{label}播放量", f"{label}投稿数"])
    if data.empty or "creator_key" not in data:
        return pd.DataFrame(columns=columns)

    prepared = data.copy()
    prepared["_views"] = pd.to_numeric(prepared["views"], errors="coerce").fillna(0)
    prepared["_content_type"] = prepared["content_type"].astype("string").str.casefold()
    result = pd.DataFrame({"creator_key": prepared["creator_key"].dropna().unique()})
    for content_type, label in _CREATOR_VIDEO_TYPE_SPECS:
        subset = prepared.loc[prepared["_content_type"].eq(content_type)]
        summary = (
            subset.groupby("creator_key", as_index=False)
            .agg(
                **{
                    f"{label}播放量": ("_views", "sum"),
                    f"{label}投稿数": ("creator_key", "size"),
                }
            )
            if not subset.empty
            else pd.DataFrame(columns=["creator_key", f"{label}播放量", f"{label}投稿数"])
        )
        result = result.merge(summary, on="creator_key", how="left")
    for column in columns[1:]:
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0).astype(int)
    return result.reindex(columns=columns)


def _comparison_rate(current: pd.Series, baseline: pd.Series) -> pd.Series:
    return (
        (current - baseline)
        .div(baseline.where(baseline > 0))
        .mul(100)
    )


def _creator_video_type_comparison(
    current: pd.DataFrame,
    baseline: pd.DataFrame,
    creator_records: list[KOCRecord],
) -> pd.DataFrame:
    current_summary = build_creator_summary(current, creator_records)
    baseline_summary = build_creator_summary(baseline, creator_records)
    comparison = _comparison_frame(
        current_summary,
        baseline_summary,
        key="creator_key",
        label="creator_label",
    )
    metadata = pd.concat(
        [
            current_summary.reindex(
                columns=["creator_key", "creator_category", "contract_types"]
            ),
            baseline_summary.reindex(
                columns=["creator_key", "creator_category", "contract_types"]
            ),
        ],
        ignore_index=True,
    )
    metadata = metadata.groupby("creator_key", as_index=False).first()
    detail = comparison.merge(metadata, on="creator_key", how="left")
    detail = detail.rename(
        columns={
            "当前播放量": "总播放量（本月）",
            "对比播放量": "总播放量（对比）",
            "播放量变化": "总播放量变化",
            "当前投稿数": "总投稿数（本月）",
            "对比投稿数": "总投稿数（对比）",
            "投稿数变化": "总投稿数变化",
        }
    )
    detail["总播放量变化率"] = _comparison_rate(
        detail["总播放量（本月）"], detail["总播放量（对比）"]
    )
    detail["总投稿数变化率"] = _comparison_rate(
        detail["总投稿数（本月）"], detail["总投稿数（对比）"]
    )

    current_types = _creator_video_type_summary(current).set_index("creator_key")
    baseline_types = _creator_video_type_summary(baseline).set_index("creator_key")
    for _content_type, label in _CREATOR_VIDEO_TYPE_SPECS:
        for metric in ("播放量", "投稿数"):
            current_column = f"{label}{metric}（本月）"
            baseline_column = f"{label}{metric}（对比）"
            change_column = f"{label}{metric}变化"
            rate_column = f"{label}{metric}变化率"
            source_column = f"{label}{metric}"
            detail[current_column] = (
                detail["creator_key"].map(current_types[source_column]).fillna(0).astype(int)
            )
            detail[baseline_column] = (
                detail["creator_key"].map(baseline_types[source_column]).fillna(0).astype(int)
            )
            detail[change_column] = detail[current_column] - detail[baseline_column]
            detail[rate_column] = _comparison_rate(
                detail[current_column], detail[baseline_column]
            )

    detail["达人状态"] = "持续投稿"
    detail.loc[
        detail["总投稿数（对比）"].eq(0) & detail["总投稿数（本月）"].gt(0),
        "达人状态",
    ] = "新增达人"
    detail.loc[
        detail["总投稿数（对比）"].gt(0) & detail["总投稿数（本月）"].eq(0),
        "达人状态",
    ] = "当月无投稿"
    detail.loc[
        detail["总投稿数（对比）"].eq(0) & detail["总投稿数（本月）"].eq(0),
        "达人状态",
    ] = "无投稿"
    rate_columns = [column for column in detail if column.endswith("变化率")]
    detail["预警"] = detail[rate_columns].lt(-30).any(axis=1).map(
        {True: "下降超过30%", False: ""}
    )
    return detail.sort_values(
        ["总播放量变化", "总投稿数变化", "creator_label"],
        ascending=[False, False, True],
        kind="stable",
    ).reset_index(drop=True)


def _format_growth(current: int, baseline: int) -> str:
    if baseline <= 0:
        return "新增" if current > 0 else "--"
    return f"{(current - baseline) / baseline:+.1%}"


def _comparison_display_frame(data: pd.DataFrame, label: str) -> pd.DataFrame:
    display = data.reindex(
        columns=[
            label,
            "当前播放量",
            "对比播放量",
            "播放量变化",
            "当前投稿数",
            "对比投稿数",
            "投稿数变化",
        ]
    ).copy()
    display["播放量环比"] = [
        _format_growth(current, baseline)
        for current, baseline in zip(
            display["当前播放量"], display["对比播放量"]
        )
    ]
    return display.rename(columns={label: "维度"})


def _render_comparison_metrics(
    current: pd.DataFrame,
    baseline: pd.DataFrame,
) -> None:
    current_views = _numeric_sum(current, "views")
    baseline_views = _numeric_sum(baseline, "views")
    current_posts = len(current)
    baseline_posts = len(baseline)
    current_average = _average_views(current)
    baseline_average = _average_views(baseline)
    current_rate = _engagement_rate(current) or 0.0
    baseline_rate = _engagement_rate(baseline) or 0.0
    metrics = (
        ("播放量", current_views, _format_growth(current_views, baseline_views)),
        ("投稿数", current_posts, _format_growth(current_posts, baseline_posts)),
        ("平均播放量", current_average, _format_growth(current_average, baseline_average)),
        ("互动率", _format_rate(current_rate), f"{(current_rate - baseline_rate):+.2%}"),
    )
    for column, (label, value, delta) in zip(st.columns(4), metrics):
        column.metric(label, value if isinstance(value, str) else f"{value:,}", delta)


def _render_dimension_comparison(
    data: pd.DataFrame,
    *,
    label: str,
    title: str,
) -> None:
    if data.empty:
        st.info("这两个统计月在当前筛选下没有可对比的数据。")
        return
    chart = data.set_index(label)[["当前播放量", "对比播放量"]]
    st.bar_chart(chart, height=_CHART_HEIGHT)
    with st.expander(f"查看{title}对比明细", expanded=False):
        display = _comparison_display_frame(data, label)
        st.dataframe(
            display,
            hide_index=True,
            width="stretch",
            height=min(440, 72 + len(display) * 35),
            column_config={
                "当前播放量": st.column_config.NumberColumn("当前播放量", format="%d"),
                "对比播放量": st.column_config.NumberColumn("对比播放量", format="%d"),
                "播放量变化": st.column_config.NumberColumn("播放量变化", format="%+d"),
                "当前投稿数": st.column_config.NumberColumn("当前投稿数", format="%d"),
                "对比投稿数": st.column_config.NumberColumn("对比投稿数", format="%d"),
                "投稿数变化": st.column_config.NumberColumn("投稿数变化", format="%+d"),
            },
        )


def _render_creator_video_type_comparison(data: pd.DataFrame) -> None:
    if data.empty:
        st.info("这两个统计月在当前筛选下没有达人可对比。")
        return

    st.subheader("达人视频类型与投稿变化")
    type_labels = [label for _content_type, label in _CREATOR_VIDEO_TYPE_SPECS]
    selected_types = st.multiselect(
        "展示视频类型",
        type_labels,
        default=type_labels,
        key="dashboard_creator_comparison_types",
    )
    sort_options = {
        "总播放量变化": "总播放量变化",
        "总投稿数变化": "总投稿数变化",
    }
    for _content_type, label in _CREATOR_VIDEO_TYPE_SPECS:
        sort_options[f"{label}播放量变化"] = f"{label}播放量变化"
        sort_options[f"{label}投稿数变化"] = f"{label}投稿数变化"
    sort_label = st.selectbox(
        "排序指标",
        list(sort_options),
        key="dashboard_creator_comparison_sort",
    )
    sort_column = sort_options[sort_label]
    display_columns = [
        "creator_key",
        "creator_label",
        "creator_category",
        "contract_types",
        "达人状态",
        "预警",
        "总播放量（本月）",
        "总播放量（对比）",
        "总播放量变化",
        "总播放量变化率",
        "总投稿数（本月）",
        "总投稿数（对比）",
        "总投稿数变化",
        "总投稿数变化率",
    ]
    for label in selected_types:
        for metric in ("播放量", "投稿数"):
            display_columns.extend(
                [
                    f"{label}{metric}（本月）",
                    f"{label}{metric}（对比）",
                    f"{label}{metric}变化",
                    f"{label}{metric}变化率",
                ]
            )
    display = data.reindex(columns=display_columns).sort_values(
        [sort_column, "creator_label"],
        ascending=[False, True],
        kind="stable",
    )
    rate_columns = [column for column in display if column.endswith("变化率")]

    def highlight_declines(row: pd.Series) -> list[str]:
        styles = [""] * len(row)
        for index, column in enumerate(row.index):
            value = pd.to_numeric(row[column], errors="coerce")
            if column in rate_columns and pd.notna(value) and value < -30:
                styles[index] = "background-color: #fee2e2; color: #b91c1c; font-weight: 700"
            if column == "预警" and row[column]:
                styles[index] = "background-color: #fee2e2; color: #b91c1c; font-weight: 700"
        return styles

    column_config: dict[str, object] = {
        "creator_key": None,
        "creator_label": st.column_config.TextColumn("达人"),
        "creator_category": st.column_config.TextColumn("合作类别"),
        "contract_types": st.column_config.TextColumn("合同类型"),
        "达人状态": st.column_config.TextColumn("达人状态"),
        "预警": st.column_config.TextColumn("预警"),
    }
    for column in display:
        if column.endswith("变化率"):
            column_config[column] = st.column_config.NumberColumn(column, format="%.1f%%")
        elif "播放量" in column or "投稿数" in column:
            column_config[column] = st.column_config.NumberColumn(column, format="%+d" if column.endswith("变化") else "%d")
    st.dataframe(
        display.style.apply(highlight_declines, axis=1),
        hide_index=True,
        width="stretch",
        height=min(760, 72 + len(display) * 35),
        column_config=column_config,
    )


def _render_creator_growth(
    data: pd.DataFrame,
    current: pd.DataFrame,
    baseline: pd.DataFrame,
    creator_records: list[KOCRecord],
) -> None:
    if data.empty:
        st.info("这两个统计月在当前筛选下没有达人可对比。")
        return
    winners, decliners = st.columns(2, gap="large")
    for column, heading, frame in (
        (
            winners,
            "播放量增长 Top 10",
            data.loc[data["播放量变化"] > 0]
            .sort_values("播放量变化", ascending=False, kind="stable")
            .head(10),
        ),
        (
            decliners,
            "播放量下降 Top 10",
            data.loc[data["播放量变化"] < 0]
            .sort_values("播放量变化", ascending=True, kind="stable")
            .head(10),
        ),
    ):
        with column:
            st.caption(heading)
            if frame.empty:
                st.caption("没有可展示的达人。")
            else:
                st.bar_chart(
                    frame.set_index("creator_label")[["播放量变化"]],
                    height=_CHART_HEIGHT,
                )
    _render_creator_video_type_comparison(
        _creator_video_type_comparison(current, baseline, creator_records)
    )


def _render_monthly_comparison(
    data: pd.DataFrame,
    creator_records: list[KOCRecord],
) -> None:
    options = _comparison_month_options(data)
    if len(options) < 2:
        st.info("至少导入两个自然月的数据后，才可以进行月度增长对比。")
        return
    latest = options[0]
    default_baseline = (
        date(latest.year - 1, 12, 1)
        if latest.month == 1
        else date(latest.year, latest.month - 1, 1)
    )
    if st.session_state.get("dashboard_compare_target_month") not in options:
        st.session_state["dashboard_compare_target_month"] = latest
    if st.session_state.get("dashboard_compare_baseline_month") not in options:
        st.session_state["dashboard_compare_baseline_month"] = default_baseline
    target_column, baseline_column = st.columns(2)
    target_month = target_column.selectbox(
        "目标月份",
        options,
        format_func=lambda value: f"{value.year}年{value.month}月",
        key="dashboard_compare_target_month",
    )
    baseline_month = baseline_column.selectbox(
        "对比月份",
        options,
        format_func=lambda value: f"{value.year}年{value.month}月",
        key="dashboard_compare_baseline_month",
    )
    if target_month == baseline_month:
        st.warning("请选择两个不同的月份进行比较。")
        return
    comparison_data = _comparison_scope(data)
    current = _month_data(comparison_data, target_month)
    baseline = _month_data(comparison_data, baseline_month)
    st.caption(
        f"{target_month.year}年{target_month.month}月 对比 "
        f"{baseline_month.year}年{baseline_month.month}月；"
        "比较遵循当前的达人、平台、内容、异业与流量加成范围。"
    )
    _render_comparison_metrics(current, baseline)

    trend = _month_comparison_summary(comparison_data)
    with st.expander("多月趋势", expanded=False):
        trend_metric = st.radio(
            "月度趋势指标",
            ("播放量", "投稿数"),
            horizontal=True,
            key="dashboard_monthly_trend_metric",
            label_visibility="collapsed",
        )
        column = "total_views" if trend_metric == "播放量" else "post_count"
        st.line_chart(
            trend.set_index("month")[[column]].rename(columns={column: trend_metric}),
            height=_CHART_HEIGHT,
        )

    platform_tab, content_tab, category_tab, creator_tab = st.tabs(
        ["平台", "视频类型", "合作类别", "达人"]
    )
    with platform_tab:
        _render_dimension_comparison(
            _dimension_comparison(current, baseline, "source_platform"),
            label="source_platform",
            title="平台",
        )
    with content_tab:
        _render_dimension_comparison(
            _dimension_comparison(current, baseline, "content_type"),
            label="content_type",
            title="视频类型",
        )
    with category_tab:
        _render_dimension_comparison(
            _dimension_comparison(current, baseline, "creator_category"),
            label="creator_category",
            title="合作类别",
        )
    with creator_tab:
        _render_creator_growth(
            _creator_comparison(current, baseline, creator_records),
            current,
            baseline,
            creator_records,
        )


def _render_charts(data: pd.DataFrame, creator_records: list[KOCRecord]) -> None:
    daily_summary = build_daily_summary(data)

    trend_column, rank_column = st.columns(2, gap="large")
    with trend_column:
        st.subheader("投稿趋势")
        trend_metric = st.radio(
            "趋势指标",
            ("播放量", "作品数"),
            horizontal=True,
            key="dashboard_trend_metric",
            label_visibility="collapsed",
        )
        trend_column_name = "total_views" if trend_metric == "播放量" else "post_count"
        trend_label = "播放量" if trend_metric == "播放量" else "投稿数"
        st.line_chart(
            daily_summary.set_index("publish_date")[[trend_column_name]].rename(
                columns={trend_column_name: trend_label}
            ),
            height=_CHART_HEIGHT,
        )
    with rank_column:
        st.subheader("达人表现排行")
        rank_metric = st.radio(
            "排行指标",
            ("累计播放量", "投稿数", "互动量"),
            horizontal=True,
            key="dashboard_rank_metric",
            label_visibility="collapsed",
        )
        rank_columns = {
            "累计播放量": "total_views",
            "投稿数": "post_count",
            "互动量": "total_interactions",
        }
        rank_column_name = rank_columns[rank_metric]
        ranked = _rank_creator_summary(
            data,
            rank_column_name,
            limit=10,
            creator_records=creator_records,
        )
        rank_labels = ranked["creator_label"].astype(str).copy()
        rank_labels.index = rank_labels.index + 1
        ranked = ranked.assign(
            rank_label=[f"{index:02d}. {label}" for index, label in rank_labels.items()]
        )
        st.bar_chart(
            ranked.set_index("rank_label")[[rank_column_name]].rename(
                columns={rank_column_name: rank_metric}
            ),
            height=_CHART_HEIGHT,
        )

    with st.expander("查看达人表现排行明细（Top 10）", expanded=False):
        st.dataframe(
            _ranking_display_frame(ranked, rank_column_name),
            hide_index=True,
            width="stretch",
            height=340,
        )


def _render_structure_analysis(data: pd.DataFrame) -> None:
    content_summary = build_dimension_summary(data, "content_type")
    category_summary = build_dimension_summary(data, "creator_category")
    content_column, category_column = st.columns(2, gap="large")
    with content_column:
        st.subheader("视频类型分布")
        st.bar_chart(
            content_summary.set_index("content_type")[["total_views", "post_count"]]
            .rename(columns={"total_views": "播放量", "post_count": "投稿数"}),
            height=_CHART_HEIGHT,
        )
    with category_column:
        st.subheader("合作类别分布")
        st.bar_chart(
            category_summary.set_index("creator_category")[["total_views", "post_count"]]
            .rename(columns={"total_views": "播放量", "post_count": "投稿数"}),
            height=_CHART_HEIGHT,
        )
    st.divider()
    _render_platform_top30(data)
    st.divider()
    _render_platform_video_top20(data)


def _summary_display_frame(summary: pd.DataFrame) -> pd.DataFrame:
    display = summary[
        [
            "creator_label",
            "creator_category",
            "contract_types",
            "source_platforms",
            "post_count",
            "total_views",
            "average_views",
            "max_views",
            "total_interactions",
            "engagement_rate",
            "earliest_date",
            "latest_date",
        ]
    ].copy()
    for column in (
        "post_count",
        "total_views",
        "average_views",
        "max_views",
        "total_interactions",
    ):
        display[column] = pd.to_numeric(display[column], errors="coerce").round().astype(
            "Int64"
        )
    display["engagement_rate"] = display["engagement_rate"].map(_format_rate)
    return display.rename(
        columns={
            "creator_label": "达人",
            "creator_category": "合作类别",
            "contract_types": "合同类型",
            "source_platforms": "平台",
            "post_count": "投稿数",
            "total_views": "累计播放量",
            "average_views": "平均播放量",
            "max_views": "最高播放量",
            "total_interactions": "互动量",
            "engagement_rate": "互动率",
            "earliest_date": "最早投稿",
            "latest_date": "最近投稿",
        }
    )


def _render_creator_summary(
    data: pd.DataFrame,
    creator_records: list[KOCRecord],
) -> pd.DataFrame:
    summary = build_creator_summary(data, creator_records)
    st.subheader("达人表现明细")
    st.dataframe(
        _summary_display_frame(summary),
        hide_index=True,
        width="stretch",
        height=420,
        column_config={
            "达人": st.column_config.TextColumn("达人", pinned=True),
            "投稿数": st.column_config.NumberColumn("投稿数", format="%d"),
            "累计播放量": st.column_config.NumberColumn("累计播放量", format="%d"),
            "平均播放量": st.column_config.NumberColumn("平均播放量", format="%d"),
            "最高播放量": st.column_config.NumberColumn("最高播放量", format="%d"),
            "互动量": st.column_config.NumberColumn("互动量", format="%d"),
        },
    )
    return summary


def _detail_display_frame(data: pd.DataFrame) -> pd.DataFrame:
    display = data.reindex(
        columns=[
            "publish_date",
            "creator_category",
            "source_platform",
            "content_type",
            "title",
            "url",
            "views",
            "original_views",
            "traffic_boost_views",
            "boosted_views",
            "is_july_traffic_boost",
            "likes",
            "comment",
            "reposted",
            "collect",
        ]
    ).copy()
    for column in (
        "views",
        "original_views",
        "traffic_boost_views",
        "boosted_views",
        "likes",
        "comment",
        "reposted",
        "collect",
    ):
        display[column] = pd.to_numeric(display[column], errors="coerce").astype("Int64")
    return display.rename(
        columns={
            "publish_date": "投稿日期",
            "creator_category": "合作类别",
            "source_platform": "平台",
            "content_type": "内容形式",
            "title": "标题",
            "url": "链接",
            "views": "播放量",
            "original_views": "原始播放量",
            "traffic_boost_views": "流量加成",
            "boosted_views": "加成后播放量",
            "is_july_traffic_boost": "命中流量加成",
            "likes": "点赞",
            "comment": "评论",
            "reposted": "转发",
            "collect": "收藏",
        }
    )


def _render_creator_detail(data: pd.DataFrame, summary: pd.DataFrame) -> None:
    if summary.empty:
        return
    with st.expander("查看单个达人投稿", expanded=False):
        labels = dict(zip(summary["creator_key"], summary["creator_label"]))
        selected_creator = st.selectbox(
            "达人",
            list(labels),
            format_func=lambda value: labels[value],
            key="dashboard_creator_detail",
        )
        detail = (
            data.loc[data["creator_key"] == selected_creator]
            .sort_values(["publish_date", "title"], ascending=[False, True], kind="stable")
            .reset_index(drop=True)
        )
        metrics = (
            ("投稿数", len(detail)),
            ("累计播放量", _numeric_sum(detail, "views")),
            ("平均播放量", _average_views(detail)),
            ("互动率", _format_rate(_engagement_rate(detail))),
        )
        for column, (label, value) in zip(st.columns(4), metrics):
            column.metric(label, value)
        st.dataframe(
            _detail_display_frame(detail),
            hide_index=True,
            width="stretch",
            height=360,
            column_config={
                "链接": st.column_config.LinkColumn("链接"),
                "播放量": st.column_config.NumberColumn("播放量", format="%d"),
                "原始播放量": st.column_config.NumberColumn("原始播放量", format="%d"),
                "流量加成": st.column_config.NumberColumn("流量加成", format="%d"),
                "加成后播放量": st.column_config.NumberColumn("加成后播放量", format="%d"),
                "点赞": st.column_config.NumberColumn("点赞", format="%d"),
                "评论": st.column_config.NumberColumn("评论", format="%d"),
                "转发": st.column_config.NumberColumn("转发", format="%d"),
                "收藏": st.column_config.NumberColumn("收藏", format="%d"),
            },
        )


def _monthly_master_display_frame(data: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "kol_name",
        "subtype",
        "description",
        "comment",
        "collect",
        "user_id",
        "source_platform",
        "url",
        "is_cross_industry",
        "compensation_eligible",
        "cross_industry_reason",
    ]
    boost_columns = [
        "is_july_traffic_boost",
        "traffic_boost_rule",
        "original_views",
        "traffic_boost_views",
        "boosted_views",
    ]
    if any(column in data for column in boost_columns):
        columns.extend(boost_columns)
    columns.extend(
        [
        "reposted",
        "timestamp",
        "likes",
        "title",
        "publish_date",
        "koc_name",
        "view",
        ]
    )
    labels = {
        "kol_name": "kol name",
        "subtype": "subtype",
        "description": "description",
        "comment": "comment",
        "collect": "collect",
        "user_id": "userId",
        "source_platform": "platform",
        "url": "url",
        "is_cross_industry": "是否异业",
        "compensation_eligible": "是否计费",
        "cross_industry_reason": "排除原因",
        "is_july_traffic_boost": "是否流量加成",
        "traffic_boost_rule": "流量加成规则",
        "original_views": "原始播放量",
        "traffic_boost_views": "流量加成播放量",
        "boosted_views": "加成后播放量",
        "reposted": "reposted",
        "timestamp": "timestamp",
        "likes": "likes",
        "title": "title",
        "publish_date": "日期",
        "koc_name": "koc",
        "view": "view",
    }
    display = data.reindex(columns=columns).copy()
    display["is_cross_industry"] = (
        display["is_cross_industry"]
        .astype("boolean")
        .fillna(False)
        .map({True: "是", False: "否"})
    )
    display["compensation_eligible"] = (
        display["compensation_eligible"]
        .astype("boolean")
        .fillna(True)
        .map({True: "计费", False: "不计费"})
    )
    if "is_july_traffic_boost" in display:
        display["is_july_traffic_boost"] = (
            display["is_july_traffic_boost"]
            .astype("boolean")
            .fillna(False)
            .map({True: "是", False: "否"})
        )
    return (
        display.rename(columns=labels)
        .sort_values(["日期", "title"], ascending=[False, True], kind="stable")
        .reset_index(drop=True)
    )


def _download_data(data: pd.DataFrame) -> bytes:
    return _monthly_master_display_frame(data).to_csv(index=False).encode("utf-8-sig")


def _render_monthly_master(data: pd.DataFrame) -> None:
    with st.expander("数据月度总表", expanded=False):
        master = _monthly_master_display_frame(data)
        st.dataframe(
            master,
            hide_index=True,
            width="stretch",
            height=460,
            column_config={"url": st.column_config.LinkColumn("url")},
        )
        st.download_button(
            "下载当前筛选 CSV",
            data=_download_data(data),
            file_name="KOC_数据月度总表.csv",
            mime="text/csv",
            icon=":material/download:",
        )


def _period_caption(data: pd.DataFrame) -> str:
    earliest, latest = date_bounds(data)
    if earliest is None or latest is None:
        return "无可用投稿日期"
    if earliest.year == latest.year and earliest.month == latest.month:
        return f"统计周期：{earliest.year} 年 {earliest.month} 月"
    return f"统计周期：{earliest.isoformat()} 至 {latest.isoformat()}"


def _render_import_reports(result: DashboardResult | None) -> None:
    if result is None or result.file_reports.empty:
        return
    with st.expander("本次数据更新结果", expanded=False):
        st.dataframe(result.file_reports, hide_index=True, width="stretch")
        if not result.unmatched_uids.empty:
            st.warning("存在未匹配 UID；这些投稿已保留在看板中，但不会归入合作类别。")
            st.dataframe(result.unmatched_uids, hide_index=True, width="stretch")


def _render_data_update(
    repository: DashboardRepository,
    database_path: Path,
    timezone: str,
    source_file_count: int,
) -> DashboardResult | None:
    with st.sidebar:
        st.subheader("本地数据")
        st.metric("已留存投稿", repository.count_posts())
        st.caption(f"初始化源文件：{source_file_count} 个")
        with st.expander("更新数据", expanded=False):
            uploaded_files = st.file_uploader(
                "上传月度完整导出文件",
                type=["xlsx"],
                accept_multiple_files=True,
                key="dashboard_files",
            )
            import_mode = st.radio(
                "导入方式",
                ("按实际日期替换完整月份", "仅追加或更新"),
                horizontal=True,
                key="dashboard_import_mode",
                help="替换模式只依据文件内投稿日期，不读取文件名中的月份。",
            )
            st.caption("默认替换文件覆盖到的完整月份；文件名称只作为来源审计记录。")
            if st.button(
                "导入并更新看板",
                type="primary",
                width="stretch",
                disabled=not uploaded_files,
                key="dashboard_import",
            ):
                uploaded_content = [
                    (uploaded.name, uploaded.getvalue()) for uploaded in uploaded_files
                ]
                files = [UploadedExcel(name=name, content=content) for name, content in uploaded_content]
                file_hashes = {
                    name: hashlib.sha256(content).hexdigest()
                    for name, content in uploaded_content
                }
                with st.spinner("正在保存并更新看板…"):
                    imported = DashboardProcessor(database_path, timezone).process(files)
                    failed_reports = imported.file_reports.loc[
                        imported.file_reports["error_message"]
                        .astype("string")
                        .str.strip()
                        .ne("")
                    ]
                    if not failed_reports.empty:
                        st.error(
                            "导入失败：存在缺少有效发布日期或格式不正确的文件。"
                            "请填写 timestamp，或提供 date/日期/发布日期列后重新导入。"
                        )
                        st.dataframe(
                            failed_reports,
                            hide_index=True,
                            width="stretch",
                        )
                        return imported
                    saved = repository.save_monthly_import(
                        imported.data,
                        replace_months=import_mode == "按实际日期替换完整月份",
                        source_files=(name for name, _ in uploaded_content),
                        file_hashes=file_hashes,
                        file_reports=imported.file_reports,
                    )
                _clear_dashboard_filters()
                st.session_state["dashboard_flash"] = (
                    f"已写入 {saved.saved_count:,} 条投稿，"
                    f"替换移除 {saved.removed_count:,} 条；"
                    f"本地共留存 {saved.total_count:,} 条。"
                )
                st.session_state["dashboard_import_reports"] = imported
                st.rerun()
        with st.expander("导入历史", expanded=False):
            history = repository.list_import_batches()
            if history.empty:
                st.caption("暂未记录导入批次。")
            else:
                st.dataframe(history, hide_index=True, width="stretch", height=260)
    reports = st.session_state.pop("dashboard_import_reports", None)
    return reports if isinstance(reports, DashboardResult) else None


def render(settings: Settings) -> None:
    st.markdown(DASHBOARD_CSS, unsafe_allow_html=True)
    repository = DashboardRepository(settings.database_path)
    creator_repository = KOCRepository(settings.database_path)
    bootstrap = ensure_dashboard_seeded_once(
        settings.database_path,
        settings.timezone,
    )
    import_reports = _render_data_update(
        repository,
        settings.database_path,
        settings.timezone,
        len(bootstrap.source_files),
    )
    if bootstrap.attempted:
        import_reports = bootstrap.imported_result

    flash = st.session_state.pop("dashboard_flash", None)
    if flash:
        st.success(flash)
    creator_sync_notice = st.session_state.pop(
        "dashboard_creator_sync_notice",
        None,
    )
    if creator_sync_notice:
        st.success(str(creator_sync_notice))

    database_state = dashboard_cache_token(settings.database_path)
    (
        prepared_data,
        file_reports,
        unmatched_uids,
        creator_records,
        _profile_history,
    ) = load_prepared_dashboard_data(
        str(settings.database_path),
        database_state,
        include_inactive=False,
    )
    result = prepared_dashboard_result(
        prepared_data,
        file_reports,
        unmatched_uids,
    )
    if result.data.empty:
        st.title("数据看板")
        st.error("没有可展示的投稿数据。请在侧栏“更新数据”中添加导出文件。")
        return

    st.markdown('<div class="dashboard-kicker">Identity V · Japan KOC campaign</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="dashboard-title">达人数据看板</h1>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="dashboard-subtitle">草根 · 解说 · 长包　{_period_caption(result.data)}</div>',
        unsafe_allow_html=True,
    )

    dashboard_data = annotate_july_traffic_boost(result.data)
    _render_import_reports(import_reports)
    _render_cross_industry_manager(repository, dashboard_data)
    filtered = _render_filters(dashboard_data, creator_records, repository)
    if filtered.empty:
        st.warning("当前筛选条件下没有投稿数据。")
        return

    scope_label = (
        "包含异业数据"
        if st.session_state.get("dashboard_include_cross_industry", False)
        else "已排除异业数据"
    )
    boost_label = (
        "已应用7月流量加成"
        if st.session_state.get("dashboard_include_july_traffic_boost", False)
        else "原始播放量"
    )
    st.caption(
        f"当前显示 {len(filtered):,} / {len(dashboard_data):,} 条投稿 · "
        f"{scope_label} · {boost_label}"
    )
    active_view = st.segmented_control(
        "看板视图",
        options=("总览", "月度对比", "结构分析", "达人与明细"),
        default="总览",
        key="dashboard_active_view",
        label_visibility="collapsed",
    )
    if active_view == "总览":
        _render_overview_metrics(filtered)
        st.divider()
        _render_charts(filtered, creator_records)
    elif active_view == "月度对比":
        _render_monthly_comparison(dashboard_data, creator_records)
    elif active_view == "结构分析":
        _render_structure_analysis(filtered)
    else:
        summary = _render_creator_summary(filtered, creator_records)
        _render_creator_detail(filtered, summary)
        _render_monthly_master(filtered)
