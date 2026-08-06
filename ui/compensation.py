from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from config.settings import Settings
from core.dashboard_bootstrap import ensure_dashboard_seeded
from core.dashboard_processor import (
    build_dashboard_result,
    enrich_dashboard_creator_metadata,
    filter_dashboard_data,
)
from core.cross_industry import (
    cross_industry_totals,
    exclude_cross_industry_posts,
    normalize_video_url,
    parse_pasted_urls,
)
from core.commentary_compensation import (
    CommentaryCompensationResult,
    calculate_commentary_compensation,
    commentary_contract_mode,
)
from core.grassroot_compensation import (
    GrassrootCompensationResult,
    calculate_grassroot_compensation,
)
from core.long_term_compensation import (
    LongTermCompensationResult,
    calculate_long_term_compensation,
)
from core.traffic_boost import is_july_traffic_boost_month
from database.dashboard_repository import CompensationVersion, DashboardRepository
from database.koc_repository import KOCRepository
from models.enums import CreatorCategory
from models.koc import KOCRecord
from services.follower_service import FollowerService
from ui.dashboard import DASHBOARD_CSS


def _month_end(value: date) -> date:
    if value.month == 12:
        next_month = date(value.year + 1, 1, 1)
    else:
        next_month = date(value.year, value.month + 1, 1)
    return next_month - timedelta(days=1)


def _settlement_month_options(data: pd.DataFrame) -> list[date]:
    dates = pd.to_datetime(data["publish_date"], errors="coerce").dt.date.dropna()
    return sorted(
        {date(value.year, value.month, 1) for value in dates}, reverse=True
    )


def _period_month_key(value: date) -> str:
    return f"{value.year}-{value.month:02d}"


def _render_contract_revision_notice(
    creator_repository: KOCRepository,
    period_key: str,
    versions: list[CompensationVersion],
) -> None:
    locked_versions = [version for version in versions if version.status == "LOCKED"]
    revisions = creator_repository.contract_revisions_for_month(period_key)
    if not locked_versions or not revisions:
        return
    affected_creators = len({revision.creator_id for revision in revisions})
    st.warning(
        f"该月有 {affected_creators} 位达人的合同记录发生纠错、变更或撤销。"
        "已锁定版本保持原结果不变；实时预览已使用修正后的合同。"
        "确认差异后，请从实时预览新建修订草稿并重新锁定。"
    )


def _month_data(data: pd.DataFrame, value: date) -> pd.DataFrame:
    return exclude_cross_industry_posts(
        filter_dashboard_data(
            data,
            start_date=value,
            end_date=_month_end(value),
        )
    )


def _grassroot_records(records: list[KOCRecord]) -> list[KOCRecord]:
    return [
        record
        for record in records
        if CreatorCategory.GRASSROOT in record.creator_categories
    ]


def _long_term_records(records: list[KOCRecord]) -> list[KOCRecord]:
    return [
        record
        for record in records
        if CreatorCategory.LONG_TERM in record.creator_categories
    ]


def _commentary_records(records: list[KOCRecord]) -> list[KOCRecord]:
    return [
        record
        for record in records
        if CreatorCategory.COMMENTARY in record.creator_categories
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
        platform_by_record={
            record.id: service.required_platform_for_record(record)
            for record in records
        },
        progress_callback=show_progress,
        start_callback=show_current,
    )
    progress.empty()
    current.empty()
    return result


def _run_long_term_follower_refresh(
    service: FollowerService,
    records: list[KOCRecord],
):
    progress = st.progress(0.0)
    current = st.empty()

    def show_current(completed: int, total: int, record: KOCRecord) -> None:
        progress.progress((completed - 1) / total if total else 0.0)
        current.caption(f"正在更新 YouTube 粉丝数：{record.koc_name}（{completed}/{total}）")

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
        platform_by_record={record.id: "YouTube" for record in records},
        progress_callback=show_progress,
        start_callback=show_current,
    )
    progress.empty()
    current.empty()
    return result


def _run_platform_follower_refresh(
    service: FollowerService,
    records: list[KOCRecord],
    platform: str,
):
    progress = st.progress(0.0)
    current = st.empty()

    def show_current(completed: int, total: int, record: KOCRecord) -> None:
        progress.progress((completed - 1) / total if total else 0.0)
        current.caption(
            f"正在更新 {platform} 粉丝数：{record.koc_name}（{completed}/{total}）"
        )

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
        required_platform=platform,
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


def _render_compensation_metrics(
    result: (
        GrassrootCompensationResult
        | LongTermCompensationResult
        | CommentaryCompensationResult
    ),
    *,
    cpm_label: str,
    include_event_input: bool = False,
) -> None:
    ready_count = int(result.details["结算状态"].eq("可结算").sum())
    not_reached_count = int(result.details["结算状态"].eq("未达标").sum())
    pending_count = int(result.details["结算状态"].eq("待补充粉丝数").sum())
    metrics: list[tuple[str, str | int]] = [
        (cpm_label, _format_cpm(result.overall_cpm)),
        ("可结算达人", ready_count),
        ("未达标达人", not_reached_count),
        ("未更新粉丝数", pending_count),
    ]
    if include_event_input:
        metrics.append(
            (
                "待填写活动数",
                int(result.details["结算状态"].eq("待填写活动数").sum()),
            )
        )
    metrics.extend(
        [
            ("博主应收（美元）总额", f"${result.creator_receivable_usd:,.2f}"),
            ("有道应收（美元）", f"${result.youdao_receivable_usd:,.2f}"),
        ]
    )
    for start in range(0, len(metrics), 4):
        row = metrics[start : start + 4]
        for column, (label, value) in zip(st.columns(len(row)), row):
            column.metric(label, value)


def _result_summary(
    result: (
        GrassrootCompensationResult
        | LongTermCompensationResult
        | CommentaryCompensationResult
    ),
) -> dict[str, object]:
    return {
        "total_amount_jpy": result.total_amount_jpy,
        "creator_receivable_jpy": result.creator_receivable_jpy,
        "youdao_receivable_jpy": result.youdao_receivable_jpy,
        "creator_receivable_usd": result.creator_receivable_usd,
        "youdao_receivable_usd": result.youdao_receivable_usd,
        "settled_views": result.settled_views,
        "total_video_views": result.total_video_views,
        "overall_cpm": result.overall_cpm,
    }


def _result_from_version(version: CompensationVersion) -> GrassrootCompensationResult:
    summary = version.summary
    return GrassrootCompensationResult(
        details=version.details,
        total_amount_jpy=int(summary.get("total_amount_jpy", 0)),
        creator_receivable_jpy=int(summary.get("creator_receivable_jpy", 0)),
        youdao_receivable_jpy=int(summary.get("youdao_receivable_jpy", 0)),
        creator_receivable_usd=float(summary.get("creator_receivable_usd", 0)),
        youdao_receivable_usd=float(summary.get("youdao_receivable_usd", 0)),
        settled_views=int(summary.get("settled_views", 0)),
        total_video_views=int(summary.get("total_video_views", 0)),
        overall_cpm=summary.get("overall_cpm"),
    )


def _long_term_result_from_version(
    version: CompensationVersion,
) -> LongTermCompensationResult:
    summary = version.summary
    return LongTermCompensationResult(
        details=version.details,
        total_amount_jpy=int(summary.get("total_amount_jpy", 0)),
        creator_receivable_jpy=int(summary.get("creator_receivable_jpy", 0)),
        youdao_receivable_jpy=int(summary.get("youdao_receivable_jpy", 0)),
        creator_receivable_usd=float(summary.get("creator_receivable_usd", 0)),
        youdao_receivable_usd=float(summary.get("youdao_receivable_usd", 0)),
        settled_views=int(summary.get("settled_views", 0)),
        total_video_views=int(summary.get("total_video_views", 0)),
        overall_cpm=summary.get("overall_cpm"),
    )


def _commentary_result_from_version(
    version: CompensationVersion,
) -> CommentaryCompensationResult:
    summary = version.summary
    return CommentaryCompensationResult(
        details=version.details.drop(
            columns=["指定主题视频播放量"], errors="ignore"
        ),
        total_amount_jpy=int(summary.get("total_amount_jpy", 0)),
        creator_receivable_jpy=int(summary.get("creator_receivable_jpy", 0)),
        youdao_receivable_jpy=int(summary.get("youdao_receivable_jpy", 0)),
        creator_receivable_usd=float(summary.get("creator_receivable_usd", 0)),
        youdao_receivable_usd=float(summary.get("youdao_receivable_usd", 0)),
        settled_views=int(summary.get("settled_views", 0)),
        total_video_views=int(summary.get("total_video_views", 0)),
        overall_cpm=summary.get("overall_cpm"),
    )


def _commentary_result_from_details(
    details: pd.DataFrame,
) -> CommentaryCompensationResult:
    details = details.copy()
    if details.empty:
        return CommentaryCompensationResult(details, 0, 0, 0, 0.0, 0.0, 0, 0, None)

    statuses = details.get("结算状态", pd.Series("可结算", index=details.index))
    settled_rows = details.loc[statuses.isin(["可结算", "未达标"])]

    def numeric_total(column: str) -> float:
        if column not in settled_rows:
            return 0.0
        return float(
            pd.to_numeric(settled_rows[column], errors="coerce").fillna(0).sum()
        )

    settled_views = int(
        numeric_total("长视频播放量") + numeric_total("短视频播放量")
    )
    total_video_views = int(numeric_total("全部已付费内容播放量"))
    if "全部已付费内容播放量" not in settled_rows:
        total_video_views = settled_views
    youdao_usd = numeric_total("有道应收（美元）（包含服务费）")
    return CommentaryCompensationResult(
        details=details,
        total_amount_jpy=int(round(numeric_total("解说含税总额（日元）"))),
        creator_receivable_jpy=int(
            round(numeric_total("博主应收（日元）(包含15$手续费)"))
        ),
        youdao_receivable_jpy=int(
            round(numeric_total("有道应收（日元）（包含服务费）"))
        ),
        creator_receivable_usd=numeric_total("博主应收（美元）"),
        youdao_receivable_usd=youdao_usd,
        settled_views=settled_views,
        total_video_views=total_video_views,
        overall_cpm=(
            youdao_usd / total_video_views * 1_000
            if total_video_views > 0
            else None
        ),
    )


def _commentary_source_fingerprint(
    result: CommentaryCompensationResult,
) -> str:
    source = result.details.to_json(
        orient="split",
        date_format="iso",
        force_ascii=False,
    )
    return str(pd.util.hash_pandas_object(pd.Series([source]), index=False).iloc[0])


def _merge_commentary_details(
    original: pd.DataFrame,
    edited: pd.DataFrame,
) -> pd.DataFrame:
    merged = original.copy()
    if merged.empty or edited.empty or "creator_id" not in edited:
        return merged
    for row in edited.to_dict("records"):
        creator_id = pd.to_numeric(row.get("creator_id"), errors="coerce")
        if pd.isna(creator_id):
            continue
        target = pd.to_numeric(merged["creator_id"], errors="coerce").eq(
            int(creator_id)
        )
        if not target.any():
            continue
        for column in merged.columns:
            if column in row:
                merged.loc[target, column] = row[column]
    return merged


def _render_grassroot_compensation(
    data: pd.DataFrame,
    repository: DashboardRepository,
    creator_repository: KOCRepository,
    settings: Settings,
) -> None:
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
    traffic_boost_enabled = (
        repository.get_traffic_boost_enabled(period_key)
        if is_july_traffic_boost_month(selected_month)
        else False
    )
    if is_july_traffic_boost_month(selected_month) and traffic_boost_enabled:
        st.caption(
            "已启用7月流量加成：合同赛道按加成后播放量结算；"
            "非合同赛道仅统计符合活动规则的视频，并独立计算播放与投稿奖励。"
        )
        st.caption("CPM始终使用排除异业后的全部原始播放量，不使用5%加成播放量。")
    elif is_july_traffic_boost_month(selected_month):
        st.caption("7月流量加成未启用，当前按原始播放量结算。")
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
            "更新草根粉丝数（可选）",
            icon=":material/refresh:",
            disabled=not grassroot_records,
            help="更新用于刷新达人库粉丝数；已有粉丝数时，无论本次更新是否成功都可直接结算。",
            key=f"grassroot_compensation_refresh_{period_key}",
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
        st.session_state["grassroot_compensation_update_result"] = update_result
        st.rerun()
    if saved_rate is None:
        return

    update_result = st.session_state.get("grassroot_compensation_update_result")
    if update_result is not None:
        st.caption(
            f"本次粉丝更新：成功 {update_result.success_count}，"
            f"失败 {update_result.failed_count}，跳过 {update_result.skipped_count}。"
        )
    creator_records = creator_repository.list(include_inactive=True)
    live_result = calculate_grassroot_compensation(
        _month_data(data, selected_month),
        creator_records,
        jpy_to_usd_rate=saved_rate,
        traffic_boost_enabled=traffic_boost_enabled,
    )
    versions = repository.list_compensation_versions(period_key)
    _render_contract_revision_notice(creator_repository, period_key, versions)
    version_by_id = {version.id: version for version in versions}
    selection = st.selectbox(
        "结算版本",
        ["实时预览", *version_by_id],
        format_func=lambda value: (
            value
            if value == "实时预览"
            else (
                f"V{version_by_id[value].version_no} · "
                f"{'已锁定' if version_by_id[value].status == 'LOCKED' else '可编辑'} · "
                f"{version_by_id[value].updated_at[:16]}"
            )
        ),
        key=f"grassroot_compensation_version_{period_key}",
    )
    active_version = version_by_id.get(selection) if isinstance(selection, int) else None
    if active_version is None:
        result = live_result
        save_draft = st.button(
            "保存当前计算为可编辑版本",
            icon=":material/save:",
            key=f"grassroot_compensation_new_draft_{period_key}",
        )
        if save_draft:
            repository.create_compensation_draft(
                period_key,
                jpy_to_usd_rate=saved_rate,
                details=live_result.details,
                summary=_result_summary(live_result),
            )
            st.rerun()
        st.caption("实时预览会随达人库和看板数据变化；保存为版本后可编辑，锁定后金额不会再被改写。")
    else:
        result = _result_from_version(active_version)
        st.caption(
            f"当前查看 V{active_version.version_no}（"
            f"{'已锁定' if active_version.status == 'LOCKED' else '可编辑'}）。"
        )
        if active_version.status == "DRAFT":
            update_column, lock_column = st.columns(2)
            if update_column.button(
                "用当前预览更新草稿",
                icon=":material/refresh:",
                key=f"grassroot_compensation_update_draft_{active_version.id}",
            ):
                repository.update_compensation_draft(
                    active_version.id,
                    jpy_to_usd_rate=saved_rate,
                    details=live_result.details,
                    summary=_result_summary(live_result),
                    note=active_version.note,
                )
                st.rerun()
            if lock_column.button(
                "锁定当前版本",
                type="primary",
                icon=":material/lock:",
                key=f"grassroot_compensation_lock_{active_version.id}",
            ):
                repository.lock_compensation_version(active_version.id)
                st.rerun()
        elif st.button(
            "从当前预览新建修订草稿",
            icon=":material/edit_note:",
            key=f"grassroot_compensation_revision_{active_version.id}",
        ):
            repository.create_compensation_draft(
                period_key,
                jpy_to_usd_rate=saved_rate,
                details=live_result.details,
                summary=_result_summary(live_result),
                note=f"修订自 V{active_version.version_no}",
            )
            st.rerun()
    _render_compensation_metrics(result, cpm_label="草根总体 CPM")
    creator_query = st.text_input(
        "搜索达人（名称或 UID）",
        placeholder="输入达人名称或 UID",
        key=f"grassroot_compensation_creator_search_{period_key}",
    ).strip()
    settlement_details = result.details
    if creator_query:
        matched_name = settlement_details["达人"].astype("string").str.contains(
            creator_query,
            case=False,
            regex=False,
            na=False,
        )
        matched_uid = settlement_details["user_id"].astype("string").str.contains(
            creator_query,
            case=False,
            regex=False,
            na=False,
        )
        settlement_details = settlement_details.loc[matched_name | matched_uid]
    if settlement_details.empty:
        st.info("未找到匹配的达人结算记录。")
        return
    display_details = settlement_details.drop(
        columns=["总金额（日元）", "跨赛道视频链接"],
        errors="ignore",
    )
    st.dataframe(
        display_details,
        hide_index=True,
        width="stretch",
        height=420,
        column_config={
            "合同内计费播放量": st.column_config.NumberColumn(
                "合同内计费播放量", format="%d"
            ),
            "跨赛道活动投稿数": st.column_config.NumberColumn(
                "跨赛道活动投稿数", format="%d"
            ),
            "跨赛道原始播放量": st.column_config.NumberColumn(
                "跨赛道原始播放量", format="%d"
            ),
            "跨赛道加成后播放量": st.column_config.NumberColumn(
                "跨赛道加成后播放量", format="%d"
            ),
            "跨赛道 rank金额": st.column_config.NumberColumn(
                "跨赛道 rank金额", format="¥%d"
            ),
            "跨赛道投稿数奖励": st.column_config.NumberColumn(
                "跨赛道投稿数奖励", format="¥%d"
            ),
            "跨赛道结算金额": st.column_config.NumberColumn(
                "跨赛道结算金额", format="¥%d"
            ),
            "计费播放量": st.column_config.NumberColumn("计费播放量", format="%d"),
            "全部视频类型播放量": st.column_config.NumberColumn(
                "全部视频类型播放量", format="%d"
            ),
            "CPM计算播放量（无加成）": st.column_config.NumberColumn(
                "CPM计算播放量（无加成）", format="%d"
            ),
            "投稿数": st.column_config.NumberColumn("投稿数", format="%d"),
            "粉丝数": st.column_config.NumberColumn("粉丝数", format="%d"),
            "YouTube粉丝数": st.column_config.NumberColumn(
                "YouTube粉丝数", format="%d"
            ),
            "TikTok粉丝数": st.column_config.NumberColumn(
                "TikTok粉丝数", format="%d"
            ),
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
    if "跨赛道活动投稿数" in settlement_details:
        cross_lane_details = settlement_details.loc[
            pd.to_numeric(
                settlement_details["跨赛道活动投稿数"], errors="coerce"
            )
            .fillna(0)
            .gt(0),
            [
                column
                for column in (
                    "user_id",
                    "达人",
                    "合同类型",
                    "跨赛道类型",
                    "跨赛道活动投稿数",
                    "跨赛道原始播放量",
                    "跨赛道加成后播放量",
                    "跨赛道 rank",
                    "跨赛道 rank金额",
                    "跨赛道投稿数奖励",
                    "跨赛道结算金额",
                    "跨赛道视频链接",
                )
                if column in settlement_details
            ],
        ]
        if not cross_lane_details.empty:
            with st.expander("跨赛道活动结算明细"):
                st.caption(
                    "这里只展示符合7月流量加成规则的非合同赛道视频；"
                    "投稿奖励与播放等级奖励分别判定。"
                )
                st.dataframe(
                    cross_lane_details,
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "跨赛道活动投稿数": st.column_config.NumberColumn(
                            "活动投稿数", format="%d"
                        ),
                        "跨赛道原始播放量": st.column_config.NumberColumn(
                            "原始播放量", format="%d"
                        ),
                        "跨赛道加成后播放量": st.column_config.NumberColumn(
                            "加成后播放量", format="%d"
                        ),
                        "跨赛道 rank金额": st.column_config.NumberColumn(
                            "rank金额", format="¥%d"
                        ),
                        "跨赛道投稿数奖励": st.column_config.NumberColumn(
                            "投稿数奖励", format="¥%d"
                        ),
                        "跨赛道结算金额": st.column_config.NumberColumn(
                            "结算金额", format="¥%d"
                        ),
                        "跨赛道视频链接": st.column_config.TextColumn(
                            "活动视频链接", width="large"
                        ),
                    },
                )
    st.download_button(
        "下载当前结算明细 CSV",
        data=_compensation_csv(settlement_details),
        file_name=f"草根达人月度报酬_{period_key}.csv",
        mime="text/csv",
        icon=":material/download:",
    )


def _editable_activity_count(value: object) -> int | None:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text:
        return None
    try:
        numeric = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("本项目有效活动数必须为非负整数。") from exc
    if not numeric.is_integer() or numeric < 0:
        raise ValueError("本项目有效活动数必须为非负整数。")
    return int(numeric)


def _render_long_term_activity_editor(
    repository: DashboardRepository,
    period_key: str,
    details: pd.DataFrame,
) -> None:
    message = st.session_state.pop("long_term_activity_notice", None)
    if message:
        st.success(message)
    if details.empty:
        return

    activity_rows = details.copy()
    activity_rows["记录ID"] = pd.to_numeric(
        activity_rows["记录ID"], errors="coerce"
    ).astype("Int64")
    activity_rows = activity_rows.loc[
        activity_rows["记录ID"].notna()
        & activity_rows["结算状态"].ne("历史资料缺失")
    ].drop_duplicates("记录ID", keep="last")
    if activity_rows.empty:
        return

    activity_table = activity_rows[
        [
            "记录ID",
            "达人",
            "user_id",
            "粉丝数",
            "月度新投稿播放量",
            "每月活动数",
        ]
    ].copy()
    activity_table = activity_table.rename(
        columns={"user_id": "UID", "每月活动数": "本项目有效活动数"}
    )
    activity_table["本项目有效活动数"] = pd.to_numeric(
        activity_table["本项目有效活动数"], errors="coerce"
    ).astype("Int64")
    activity_table = activity_table.sort_values(
        ["达人", "UID"], kind="stable"
    ).reset_index(drop=True)

    st.subheader("长包活动数录入")
    with st.form(f"long_term_activity_form_{period_key}"):
        edited = st.data_editor(
            activity_table,
            hide_index=True,
            width="stretch",
            height=min(360, 72 + len(activity_table) * 36),
            num_rows="fixed",
            key=f"long_term_activity_editor_{period_key}",
            disabled=["记录ID", "达人", "UID", "粉丝数", "月度新投稿播放量"],
            column_config={
                "记录ID": None,
                "达人": st.column_config.TextColumn("达人", pinned=True),
                "UID": st.column_config.TextColumn("UID"),
                "粉丝数": st.column_config.NumberColumn("粉丝数", format="%d"),
                "月度新投稿播放量": st.column_config.NumberColumn(
                    "月度新投稿播放量", format="%d"
                ),
                "本项目有效活动数": st.column_config.NumberColumn(
                    "本项目有效活动数",
                    min_value=0,
                    step=1,
                    format="%d",
                ),
            },
        )
        submitted = st.form_submit_button(
            "保存活动数并重新计算",
            type="primary",
            icon=":material/calculate:",
        )
    if not submitted:
        return

    values: dict[int, int | None] = {}
    errors: list[str] = []
    for _, row in edited.iterrows():
        try:
            values[int(row["记录ID"])] = _editable_activity_count(
                row["本项目有效活动数"]
            )
        except (TypeError, ValueError) as exc:
            errors.append(f"{row['达人']}：{exc}")
    if errors:
        for error in errors:
            st.error(error)
        return
    repository.save_long_term_activity_counts(period_key, values)
    st.session_state["long_term_activity_notice"] = "本项目有效活动数已保存。"
    st.rerun()


def _render_long_term_compensation(
    data: pd.DataFrame,
    repository: DashboardRepository,
    creator_repository: KOCRepository,
    settings: Settings,
) -> None:
    month_options = _settlement_month_options(data)
    if not month_options:
        st.info("当前没有可用于结算的月度投稿。")
        return
    selected_month = st.selectbox(
        "结算月份",
        month_options,
        format_func=lambda value: f"{value.year}年{value.month}月",
        key="long_term_compensation_month",
    )
    period_key = _period_month_key(selected_month)
    traffic_boost_enabled = (
        repository.get_traffic_boost_enabled(period_key)
        if is_july_traffic_boost_month(selected_month)
        else False
    )
    if is_july_traffic_boost_month(selected_month) and traffic_boost_enabled:
        st.caption(
            "已启用7月流量加成：符合 #手記の加筆 规则的长包 YouTube 投稿按加成后播放量结算。"
        )
        st.caption("长包CPM使用无加成的原始YouTube播放量计算。")
    elif is_july_traffic_boost_month(selected_month):
        st.caption("7月流量加成未启用，当前按原始播放量结算。")
    saved_rate = repository.get_jpy_to_usd_rate(period_key)
    rate_key = f"long_term_compensation_rate_{period_key}"
    if rate_key not in st.session_state:
        st.session_state[rate_key] = saved_rate or 0.0

    setting_column, action_column = st.columns((1.25, 2.75))
    with setting_column:
        with st.form(f"long_term_compensation_rate_form_{period_key}"):
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

    long_term_records = _long_term_records(
        creator_repository.list(include_inactive=False)
    )
    with action_column:
        refresh = st.button(
            "更新长包 YouTube 粉丝数（可选）",
            icon=":material/refresh:",
            disabled=not long_term_records,
            help="刷新达人库粉丝数；已有粉丝数时，无论本次更新是否成功都可直接结算。",
            key=f"long_term_compensation_refresh_{period_key}",
        )
        if saved_rate is None:
            st.caption("请先保存该月 3 日的 JPY → USD 汇率。")
        elif not long_term_records:
            st.caption("达人库中没有启用的长包达人。")

    if refresh:
        follower_service = FollowerService(
            creator_repository,
            youtube_api_key=settings.youtube_api_key,
            tiktok_browser_data_dir=settings.tiktok_browser_data_dir,
            tiktok_persistent_headless=settings.tiktok_persistent_headless,
        )
        update_result = _run_long_term_follower_refresh(
            follower_service,
            long_term_records,
        )
        st.session_state["long_term_compensation_update_result"] = update_result
        st.rerun()
    if saved_rate is None:
        return

    update_result = st.session_state.get("long_term_compensation_update_result")
    if update_result is not None:
        st.caption(
            f"本次粉丝更新：成功 {update_result.success_count}，"
            f"失败 {update_result.failed_count}，跳过 {update_result.skipped_count}。"
        )
    creator_records = creator_repository.list(include_inactive=True)
    live_result = calculate_long_term_compensation(
        _month_data(data, selected_month),
        creator_records,
        jpy_to_usd_rate=saved_rate,
        event_counts=repository.get_long_term_activity_counts(period_key),
        period_start=selected_month,
        period_end=_month_end(selected_month),
        traffic_boost_enabled=traffic_boost_enabled,
    )
    _render_long_term_activity_editor(repository, period_key, live_result.details)

    versions = repository.list_long_term_compensation_versions(period_key)
    _render_contract_revision_notice(creator_repository, period_key, versions)
    version_by_id = {version.id: version for version in versions}
    selection = st.selectbox(
        "结算版本",
        ["实时预览", *version_by_id],
        format_func=lambda value: (
            value
            if value == "实时预览"
            else (
                f"V{version_by_id[value].version_no} · "
                f"{'已锁定' if version_by_id[value].status == 'LOCKED' else '可编辑'} · "
                f"{version_by_id[value].updated_at[:16]}"
            )
        ),
        key=f"long_term_compensation_version_{period_key}",
    )
    active_version = version_by_id.get(selection) if isinstance(selection, int) else None
    if active_version is None:
        result = live_result
        save_draft = st.button(
            "保存当前计算为可编辑版本",
            icon=":material/save:",
            key=f"long_term_compensation_new_draft_{period_key}",
        )
        if save_draft:
            repository.create_long_term_compensation_draft(
                period_key,
                jpy_to_usd_rate=saved_rate,
                details=live_result.details,
                summary=_result_summary(live_result),
            )
            st.rerun()
        st.caption("实时预览会随活动数、达人库和看板数据变化；锁定后金额不会再被改写。")
    else:
        result = _long_term_result_from_version(active_version)
        st.caption(
            f"当前查看 V{active_version.version_no}（"
            f"{'已锁定' if active_version.status == 'LOCKED' else '可编辑'}）。"
        )
        if active_version.status == "DRAFT":
            update_column, lock_column = st.columns(2)
            if update_column.button(
                "用当前预览更新草稿",
                icon=":material/refresh:",
                key=f"long_term_compensation_update_draft_{active_version.id}",
            ):
                repository.update_long_term_compensation_draft(
                    active_version.id,
                    jpy_to_usd_rate=saved_rate,
                    details=live_result.details,
                    summary=_result_summary(live_result),
                    note=active_version.note,
                )
                st.rerun()
            if lock_column.button(
                "锁定当前版本",
                type="primary",
                icon=":material/lock:",
                key=f"long_term_compensation_lock_{active_version.id}",
            ):
                repository.lock_long_term_compensation_version(active_version.id)
                st.rerun()
        elif st.button(
            "从当前预览新建修订草稿",
            icon=":material/edit_note:",
            key=f"long_term_compensation_revision_{active_version.id}",
        ):
            repository.create_long_term_compensation_draft(
                period_key,
                jpy_to_usd_rate=saved_rate,
                details=live_result.details,
                summary=_result_summary(live_result),
                note=f"修订自 V{active_version.version_no}",
            )
            st.rerun()

    _render_compensation_metrics(
        result,
        cpm_label="长包总体 CPM",
        include_event_input=True,
    )
    creator_query = st.text_input(
        "搜索长包达人（名称或 UID）",
        placeholder="输入达人名称或 UID",
        key=f"long_term_compensation_creator_search_{period_key}",
    ).strip()
    settlement_details = result.details
    if creator_query:
        matched_name = settlement_details["达人"].astype("string").str.contains(
            creator_query,
            case=False,
            regex=False,
            na=False,
        )
        matched_uid = settlement_details["user_id"].astype("string").str.contains(
            creator_query,
            case=False,
            regex=False,
            na=False,
        )
        settlement_details = settlement_details.loc[matched_name | matched_uid]
    if settlement_details.empty:
        st.info("未找到匹配的长包达人结算记录。")
        return
    display_details = settlement_details.drop(
        columns=["记录ID", "总金额（日元）"],
        errors="ignore",
    )
    st.dataframe(
        display_details,
        hide_index=True,
        width="stretch",
        height=420,
        column_config={
            "粉丝数": st.column_config.NumberColumn("粉丝数", format="%d"),
            "YouTube 投稿数": st.column_config.NumberColumn(
                "YouTube 投稿数", format="%d"
            ),
            "月度新投稿播放量": st.column_config.NumberColumn(
                "月度新投稿播放量", format="%d"
            ),
            "CPM计算播放量（无加成）": st.column_config.NumberColumn(
                "CPM计算播放量（无加成）", format="%d"
            ),
            "每月活动数": st.column_config.NumberColumn(
                "本项目有效活动数", format="%d"
            ),
            "活动数门槛": st.column_config.NumberColumn("活动数门槛", format="%d"),
            "rank金额": st.column_config.NumberColumn("rank金额", format="¥%d"),
            "预计 CPM（日元）": st.column_config.NumberColumn(
                "预计 CPM（日元）", format="¥%d"
            ),
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
        "下载当前长包结算明细 CSV",
        data=_compensation_csv(settlement_details),
        file_name=f"长包达人月度报酬_{period_key}.csv",
        mime="text/csv",
        icon=":material/download:",
    )


def _render_commentary_theme_editor(
    month_data: pd.DataFrame,
    repository: DashboardRepository,
    creator_records: list[KOCRecord],
    period_key: str,
) -> None:
    definitions = repository.list_commentary_theme_definitions(period_key)
    st.subheader("指定主题视频申报")
    notice_key = f"commentary_theme_notice_{period_key}"
    revision_key = f"commentary_theme_editor_revision_{period_key}"
    notice = st.session_state.pop(notice_key, None)
    if notice:
        st.success(str(notice))
    if not definitions:
        st.info("该月未配置指定主题视频。")
        return
    submissions = repository.list_commentary_theme_submissions(period_key)
    eligible_records = sorted(
        _commentary_records(creator_records),
        key=lambda record: (record.koc_name.casefold(), record.user_id.casefold()),
    )
    creator_label_by_id = {
        record.id: f"{record.koc_name} · {record.user_id}" for record in eligible_records
    }
    creator_id_by_label = {
        label: creator_id for creator_id, label in creator_label_by_id.items()
    }
    theme_label_by_code = {
        code: f"{definition['theme_name']} · {code}"
        for code, definition in definitions.items()
        if definition.get("enabled", True)
    }
    theme_code_by_label = {
        label: code for code, label in theme_label_by_code.items()
    }
    status_labels = {
        "PENDING": "待审核",
        "APPROVED": "已通过",
        "REJECTED": "不通过",
    }
    status_values = {label: value for value, label in status_labels.items()}
    format_labels = {"LONG": "长视频（1条）", "SHORT": "短视频（3条）"}
    format_values = {label: value for value, label in format_labels.items()}
    rows = [
        {
            "达人": creator_label_by_id.get(
                int(item["creator_id"]), f"达人ID {item['creator_id']}"
            ),
            "指定主题": theme_label_by_code.get(
                str(item["theme_code"]), str(item["theme_code"])
            ),
            "内容形式": format_labels.get(
                str(item["content_format"]), str(item["content_format"])
            ),
            "视频链接": "\n".join(str(url) for url in item.get("urls", [])),
            "提交日期": pd.to_datetime(item.get("submitted_date"), errors="coerce"),
            "审核状态": status_labels.get(
                str(item["review_status"]), str(item["review_status"])
            ),
            "备注": item.get("note"),
        }
        for item in submissions
    ]
    columns = ["达人", "指定主题", "内容形式", "视频链接", "提交日期", "审核状态", "备注"]
    edited = st.data_editor(
        pd.DataFrame(rows, columns=columns),
        hide_index=True,
        width="stretch",
        num_rows="dynamic",
        key=(
            f"commentary_theme_editor_{period_key}_"
            f"{st.session_state.get(revision_key, 0)}"
        ),
        column_config={
            "达人": st.column_config.SelectboxColumn(
                "达人", options=list(creator_id_by_label), required=True, width="medium"
            ),
            "指定主题": st.column_config.SelectboxColumn(
                "指定主题", options=list(theme_code_by_label), required=True, width="large"
            ),
            "内容形式": st.column_config.SelectboxColumn(
                "内容形式", options=list(format_values), required=True
            ),
            "视频链接": st.column_config.TextColumn(
                "视频链接", help="长视频填写1条；短视频填写3条，可用换行或逗号分隔。", width="large"
            ),
            "提交日期": st.column_config.DateColumn("提交日期", format="YYYY-MM-DD"),
            "审核状态": st.column_config.SelectboxColumn(
                "审核状态", options=list(status_values), required=True
            ),
            "备注": st.column_config.TextColumn("备注", width="medium"),
        },
    )
    if st.button(
        "保存指定主题申报",
        type="primary",
        icon=":material/save:",
        key=f"commentary_theme_save_{period_key}",
    ):
        values: list[dict[str, object]] = []
        errors: list[str] = []
        for row in edited.to_dict("records"):
            creator_label = str(row.get("达人") or "").strip()
            theme_label = str(row.get("指定主题") or "").strip()
            format_label = str(row.get("内容形式") or "").strip()
            raw_urls = str(row.get("视频链接") or "")
            if not any((creator_label, theme_label, format_label, raw_urls.strip())):
                continue
            urls = parse_pasted_urls(raw_urls)
            unique_urls: list[str] = []
            seen_url_keys: set[str] = set()
            for url in urls:
                identity = normalize_video_url(url)
                if identity is None or identity.url_key in seen_url_keys:
                    continue
                seen_url_keys.add(identity.url_key)
                unique_urls.append(url)
            urls = unique_urls
            status = status_values.get(str(row.get("审核状态")), "PENDING")
            content_format = format_values.get(format_label)
            creator_id = creator_id_by_label.get(creator_label)
            theme_code = theme_code_by_label.get(theme_label)
            if creator_id is None:
                errors.append(f"{creator_label or '未命名行'}：请选择解说达人。")
            if theme_code is None:
                errors.append(f"{creator_label or '未命名行'}：请选择指定主题。")
            if content_format is None:
                errors.append(f"{creator_label or '未命名行'}：请选择内容形式。")
            expected_count = 1 if content_format == "LONG" else 3
            if len(urls) != expected_count:
                errors.append(
                    f"{creator_label}：{format_label or '内容形式'}需要填写"
                    f"{expected_count}条不同的视频链接，当前识别到{len(urls)}条。"
                )
            values.append(
                {
                    "creator_id": creator_id,
                    "theme_code": theme_code,
                    "content_format": content_format,
                    "urls": urls,
                    "submitted_date": row.get("提交日期"),
                    "review_status": status,
                    "note": row.get("备注"),
                }
            )
        if errors:
            for error in errors:
                st.error(error)
        else:
            try:
                saved_count = repository.replace_commentary_theme_submissions(
                    period_key, values
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state[notice_key] = (
                    f"已保存 {saved_count} 条指定主题申报，已通过项目会立即进入实时结算。"
                )
                st.session_state[revision_key] = (
                    int(st.session_state.get(revision_key, 0)) + 1
                )
                settlement_revision_key = (
                    f"commentary_settlement_editor_revision_{period_key}"
                )
                st.session_state[settlement_revision_key] = (
                    int(st.session_state.get(settlement_revision_key, 0)) + 1
                )
                st.rerun()


def _render_commentary_metrics(result: CommentaryCompensationResult) -> None:
    metrics = [
        ("解说总体 CPM", _format_cpm(result.overall_cpm)),
        (
            "可结算达人",
            int(result.details["结算状态"].eq("可结算").sum()),
        ),
        ("未达标达人", int(result.details["结算状态"].eq("未达标").sum())),
        ("未更新粉丝数", int(result.details["结算状态"].eq("待补充粉丝数").sum())),
        ("博主应收（美元）总额", f"${result.creator_receivable_usd:,.2f}"),
        ("有道应收（美元）", f"${result.youdao_receivable_usd:,.2f}"),
    ]
    for start in range(0, len(metrics), 4):
        row = metrics[start : start + 4]
        for column, (label, value) in zip(st.columns(len(row)), row):
            column.metric(label, value)


def _render_commentary_compensation(
    data: pd.DataFrame,
    repository: DashboardRepository,
    creator_repository: KOCRepository,
    settings: Settings,
) -> None:
    month_options = [
        value
        for value in _settlement_month_options(data)
        if value >= date(2026, 7, 1)
    ]
    if not month_options:
        st.info("解说新合同与结算规则从 2026年7月1日开始生效。")
        return
    selected_month = st.selectbox(
        "结算月份",
        month_options,
        format_func=lambda value: f"{value.year}年{value.month}月",
        key="commentary_compensation_month",
    )
    period_key = _period_month_key(selected_month)
    saved_rate = repository.get_jpy_to_usd_rate(period_key)
    rate_key = f"commentary_compensation_rate_{period_key}"
    if rate_key not in st.session_state:
        st.session_state[rate_key] = saved_rate or 0.0

    rate_column, follower_column = st.columns((1.2, 2.8))
    with rate_column:
        with st.form(f"commentary_compensation_rate_form_{period_key}"):
            rate = st.number_input(
                "JPY → USD 汇率（当月3日）",
                min_value=0.0,
                step=0.0001,
                format="%.6f",
                key=rate_key,
            )
            save_rate = st.form_submit_button(
                "保存汇率", icon=":material/save:", width="stretch"
            )
        if save_rate:
            if rate <= 0:
                st.error("请输入大于 0 的日元兑美元汇率。")
            else:
                repository.save_jpy_to_usd_rate(period_key, rate)
                st.rerun()

    current_commentary = _commentary_records(
        creator_repository.list(include_inactive=False)
    )
    youtube_records = [
        record for record in current_commentary if service_has_youtube(record)
    ]
    tiktok_records = [
        record for record in current_commentary if service_has_tiktok(record)
    ]
    with follower_column:
        refresh_columns = st.columns(2)
        refresh_youtube = refresh_columns[0].button(
            "更新解说 YouTube 粉丝数（可选）",
            icon=":material/refresh:",
            disabled=not youtube_records,
            key=f"commentary_youtube_refresh_{period_key}",
        )
        refresh_tiktok = refresh_columns[1].button(
            "更新解说 TikTok 粉丝数（可选）",
            icon=":material/refresh:",
            disabled=not tiktok_records,
            key=f"commentary_tiktok_refresh_{period_key}",
        )
        if saved_rate is None:
            st.caption("请先保存该月 3 日的 JPY → USD 汇率。")

    if refresh_youtube or refresh_tiktok:
        follower_service = FollowerService(
            creator_repository,
            youtube_api_key=settings.youtube_api_key,
            tiktok_browser_data_dir=settings.tiktok_browser_data_dir,
            tiktok_persistent_headless=settings.tiktok_persistent_headless,
        )
        platform = "YouTube" if refresh_youtube else "TikTok"
        records = youtube_records if refresh_youtube else tiktok_records
        update_result = _run_platform_follower_refresh(
            follower_service, records, platform
        )
        st.session_state[f"commentary_{platform}_update_result"] = update_result
        st.rerun()
    if saved_rate is None:
        return

    for platform in ("YouTube", "TikTok"):
        update_result = st.session_state.get(f"commentary_{platform}_update_result")
        if update_result is not None:
            st.caption(
                f"{platform} 粉丝更新：成功 {update_result.success_count}，"
                f"失败 {update_result.failed_count}，跳过 {update_result.skipped_count}。"
            )

    month_data = _month_data(data, selected_month)
    creator_records = creator_repository.list(include_inactive=True)
    submissions = repository.list_commentary_theme_submissions(period_key)
    with st.expander("指定主题视频申报", expanded=False):
        _render_commentary_theme_editor(
            month_data, repository, creator_records, period_key
        )

    submissions = repository.list_commentary_theme_submissions(period_key)
    definitions = repository.list_commentary_theme_definitions(period_key)
    live_result = calculate_commentary_compensation(
        month_data,
        creator_records,
        period_month=period_key,
        jpy_to_usd_rate=saved_rate,
        profile_history=creator_repository.list_profile_history(),
        theme_submissions=submissions,
        theme_definitions=definitions,
    )
    source_fingerprint = _commentary_source_fingerprint(live_result)
    versions = repository.list_commentary_compensation_versions(period_key)
    _render_contract_revision_notice(creator_repository, period_key, versions)
    editable_draft = next(
        (version for version in versions if version.status == "DRAFT"),
        None,
    )
    draft_matches_source = bool(
        editable_draft
        and editable_draft.summary.get("source_fingerprint") == source_fingerprint
    )
    result = (
        _commentary_result_from_version(editable_draft)
        if editable_draft is not None and draft_matches_source
        else live_result
    )
    notice_key = f"commentary_settlement_notice_{period_key}"
    notice = st.session_state.pop(notice_key, None)
    if notice:
        st.success(str(notice))
    st.caption(
        f"{selected_month.year}年{selected_month.month}月独立保存；"
        "切换月份不会删除其他月份的结算数据。"
    )

    revision_key = f"commentary_settlement_editor_revision_{period_key}"
    revision = int(st.session_state.get(revision_key, 0))
    working_key = (
        f"commentary_settlement_working_{period_key}_"
        f"{source_fingerprint}_{revision}"
    )
    if working_key not in st.session_state:
        st.session_state[working_key] = result.details.copy()
    working_details = st.session_state[working_key].copy()

    metrics_container = st.container()
    query = st.text_input(
        "搜索解说达人（名称或 UID）",
        placeholder="输入达人名称或 UID",
        key=f"commentary_compensation_search_{period_key}",
    ).strip()
    visible_details = working_details
    if query and not visible_details.empty:
        mask = visible_details["达人"].astype("string").str.contains(
            query, case=False, regex=False, na=False
        ) | visible_details["UID"].astype("string").str.contains(
            query, case=False, regex=False, na=False
        )
        visible_details = visible_details.loc[mask]

    edited_details = working_details
    if visible_details.empty:
        st.info("未找到匹配的解说达人结算记录。")
    else:
        column_config = {
            "creator_id": None,
            "YouTube粉丝数": st.column_config.NumberColumn(
                "YouTube粉丝数", format="%d"
            ),
            "TikTok粉丝数": st.column_config.NumberColumn(
                "TikTok粉丝数", format="%d"
            ),
            "博主应收（美元）": st.column_config.NumberColumn(
                "博主应收（美元）", format="$%.2f"
            ),
            "有道应收（美元）（包含服务费）": st.column_config.NumberColumn(
                "有道应收（美元）（包含服务费）", format="$%.2f"
            ),
            "CPM": st.column_config.NumberColumn("CPM", format="$%.2f"),
        }
        query_token = abs(hash(query.casefold()))
        edited_visible = st.data_editor(
            visible_details,
            hide_index=True,
            width="stretch",
            height=min(620, 86 + len(visible_details) * 35),
            num_rows="fixed",
            disabled=[
                "creator_id",
                "UID",
                "达人",
                "合同类型",
                "YouTube UID",
                "TikTok UID",
            ],
            key=(
                f"commentary_settlement_editor_{period_key}_"
                f"{source_fingerprint}_{revision}_{query_token}"
            ),
            column_config=column_config,
        )
        edited_details = _merge_commentary_details(
            working_details, edited_visible
        )
        st.session_state[working_key] = edited_details.copy()

    edited_result = _commentary_result_from_details(edited_details)
    with metrics_container:
        _render_commentary_metrics(edited_result)

    if st.button(
        "保存解说结算表修改",
        type="primary",
        icon=":material/save:",
        key=f"commentary_settlement_save_{period_key}",
    ):
        summary = _result_summary(edited_result)
        summary["source_fingerprint"] = source_fingerprint
        if editable_draft is None:
            repository.create_commentary_compensation_draft(
                period_key,
                jpy_to_usd_rate=saved_rate,
                details=edited_result.details,
                summary=summary,
            )
        else:
            repository.update_commentary_compensation_draft(
                editable_draft.id,
                jpy_to_usd_rate=saved_rate,
                details=edited_result.details,
                summary=summary,
                note=editable_draft.note,
            )
        st.session_state[notice_key] = (
            f"已保存 {selected_month.year}年{selected_month.month}月解说结算表。"
        )
        st.session_state[revision_key] = revision + 1
        st.rerun()

    download_details = edited_details.loc[
        edited_details["creator_id"].isin(visible_details["creator_id"])
    ]
    st.download_button(
        "下载当前解说结算明细 CSV",
        data=_compensation_csv(download_details),
        file_name=f"解说达人月度报酬_{period_key}.csv",
        mime="text/csv",
        icon=":material/download:",
    )


def service_has_youtube(record: KOCRecord) -> bool:
    return FollowerService.has_youtube_contract(record)


def service_has_tiktok(record: KOCRecord) -> bool:
    return FollowerService.has_tiktok_contract(record)


def render(settings: Settings) -> None:
    st.markdown(DASHBOARD_CSS, unsafe_allow_html=True)
    dashboard_repository = DashboardRepository(settings.database_path)
    creator_repository = KOCRepository(settings.database_path)
    ensure_dashboard_seeded(settings.database_path, settings.timezone)
    creator_sync_notice = st.session_state.pop(
        "compensation_creator_sync_notice",
        None,
    )
    if creator_sync_notice:
        st.success(str(creator_sync_notice))
    creator_records = creator_repository.list(include_inactive=True)
    profile_history = creator_repository.list_profile_history()
    loaded = build_dashboard_result(dashboard_repository.load_posts())
    data = enrich_dashboard_creator_metadata(
        loaded.data,
        creator_records,
        profile_history,
    )
    data = dashboard_repository.annotate_cross_industry_posts(data)
    st.markdown(
        '<div class="dashboard-kicker">Identity V · Japan KOC campaign</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<h1 class="dashboard-title">KOL报酬看板</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="dashboard-subtitle">按达人库合同、月度投稿与活动数结算</div>',
        unsafe_allow_html=True,
    )
    excluded_count, excluded_views = cross_industry_totals(data)
    st.caption(
        f"薪酬口径固定排除异业视频：{excluded_count:,} 条，"
        f"{excluded_views:,} 播放；已锁定版本保持冻结。"
    )
    grassroot_tab, long_term_tab, commentary_tab = st.tabs(
        ["草根达人结算", "长包达人结算", "解说达人结算"]
    )
    with grassroot_tab:
        st.subheader("草根达人月度报酬")
        if data.empty:
            st.info("没有可用于结算的投稿数据。请先在“数据看板”导入月度数据。")
        else:
            _render_grassroot_compensation(
                data,
                dashboard_repository,
                creator_repository,
                settings,
            )
    with long_term_tab:
        st.subheader("长包达人月度报酬")
        if data.empty:
            st.info("没有可用于结算的投稿数据。请先在“数据看板”导入月度数据。")
        else:
            _render_long_term_compensation(
                data,
                dashboard_repository,
                creator_repository,
                settings,
            )
    with commentary_tab:
        st.subheader("解说达人月度报酬")
        if data.empty:
            st.info("没有可用于结算的投稿数据。请先在“数据看板”导入月度数据。")
        else:
            _render_commentary_compensation(
                data,
                dashboard_repository,
                creator_repository,
                settings,
            )
