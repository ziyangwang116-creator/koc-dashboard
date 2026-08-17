from __future__ import annotations

from collections.abc import MutableMapping
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from config.settings import Settings
from core.koc_import import (
    KOCImportFormatError,
    analyze_import_dataframe,
)
from database.dashboard_repository import DashboardRepository
from database.koc_repository import KOCRepository, KOCRepositoryError
from exporters.excel_exporter import build_koc_master_filename, export_koc_master
from followers.tiktok_provider import build_tiktok_profile
from models.enums import (
    CONTRACT_TYPE_LABELS,
    CREATOR_CATEGORY_LABELS,
    ContractType,
    CreatorCategory,
    parse_creator_category,
)
from models.koc import KOCRecord
from services.follower_service import FollowerService
from services.koc_service import KOCService


_LINKED_STATE_PREFIXES = (
    "grassroot_compensation_version_",
    "long_term_compensation_version_",
    "commentary_settlement_working_",
    "commentary_settlement_editor_",
    "commentary_settlement_editor_revision_",
)

_LINKED_STATE_KEYS = (
    "dashboard_creator_query",
    "dashboard_creator_filter",
    "dashboard_category_filter",
)


def _reset_linked_page_state(state: MutableMapping[str, object]) -> None:
    """Make the next dashboard and compensation render use current creator data."""
    for key in list(state):
        if key in _LINKED_STATE_KEYS or key.startswith(_LINKED_STATE_PREFIXES):
            state.pop(key, None)
    message = "已重新读取达人库，并按合同生效月份同步看板与实时结算。"
    state["dashboard_creator_sync_notice"] = message
    state["compensation_creator_sync_notice"] = message


def _editor_effective_month(value: object) -> date:
    text = _editor_optional_text(value)
    if not text:
        raise ValueError("请选择新合同生效月份。")
    try:
        parsed = pd.Period(text, freq="M")
    except (TypeError, ValueError) as exc:
        raise ValueError("新合同生效月份格式无效。") from exc
    return date(parsed.year, parsed.month, 1)


def _effective_month_options(reference: date | None = None) -> list[str]:
    current = reference or date.today()
    current_index = current.year * 12 + current.month - 1
    options: list[str] = []
    for offset in range(-24, 13):
        year, month_index = divmod(current_index + offset, 12)
        options.append(f"{year:04d}-{month_index + 1:02d}")
    return options


def _category_label(value: CreatorCategory | None) -> str:
    return "未设置" if value is None else CREATOR_CATEGORY_LABELS[value]


def _contract_label(value: ContractType | str | None) -> str:
    if value is None:
        return "未设置"
    if isinstance(value, ContractType):
        return CONTRACT_TYPE_LABELS[value]
    return str(value)


def _creator_category_display(record: KOCRecord) -> str:
    categories = record.creator_categories
    if not categories:
        return "未设置"
    return "、".join(_category_label(category) for category in categories)


def _contract_period_display(record: KOCRecord) -> str:
    start = record.contract_start_date.isoformat() if record.contract_start_date else "-"
    end = record.contract_end_date.isoformat() if record.contract_end_date else "-"
    return f"{start} 至 {end}"


def _display_updated_at(value: str | None, timezone_name: str) -> str:
    if not value:
        return "—"
    try:
        timestamp = pd.to_datetime(value, utc=True).tz_convert(timezone_name)
    except (TypeError, ValueError):
        return str(value)[:16]
    return timestamp.strftime("%Y-%m-%d %H:%M")


def _show_flash() -> None:
    message = st.session_state.pop("koc_flash", None)
    if message:
        st.success(message)


def _add_creator(service: KOCService, contract_options: list[str]) -> None:
    with st.expander("新增达人", expanded=False):
        user_id = st.text_input("UID *", key="add_koc_uid")
        koc_name = st.text_input("达人名称 *", key="add_koc_name")
        effective_date = st.date_input(
            "资料生效日期",
            value=date.today(),
            key="add_koc_effective_date",
            help="看板会按投稿日期读取当时生效的达人资料。",
        )
        category = st.selectbox(
            "合作类别",
            [None, *CreatorCategory],
            format_func=_category_label,
            key="add_koc_category",
        )
        contracts = st.multiselect(
            "合同类型",
            contract_options,
            accept_new_options=True,
            placeholder="可选择多个；新类型按实际文本录入",
            key="add_koc_contract",
        )
        st.caption("新增后系统会按合作类别自动写入合同期限：长包5月至12月，解说5月至8月，草根5月至10月。")
        homepage_url = st.text_input("达人主页链接", key="add_koc_homepage")
        follower_count = st.number_input(
            "粉丝数",
            min_value=0,
            value=None,
            step=1,
            placeholder="未知时保持空白",
            key="add_koc_followers",
        )
        active = st.checkbox("启用，参与自动匹配", value=True, key="add_koc_active")
        note = st.text_area("备注", key="add_koc_note")
        if st.button("保存新增达人", type="primary", key="save_new_koc"):
            try:
                record = service.create_creator(
                    user_id=user_id,
                    koc_name=koc_name,
                    creator_category=category,
                    contract_types=contracts,
                    homepage_url=homepage_url,
                    follower_count=follower_count,
                    active=active,
                    note=note,
                    effective_date=effective_date,
                )
            except (KOCRepositoryError, ValueError) as exc:
                st.error(str(exc))
            else:
                st.session_state["koc_flash"] = (
                    f"达人已新增：{record.user_id} → {record.koc_name}"
                )
                st.rerun()


def _edit_creator(
    service: KOCService,
    records: list[KOCRecord],
    contract_options: list[str],
) -> int | None:
    with st.expander("编辑、启用或停用达人", expanded=False):
        if not records:
            st.info("当前没有可编辑的达人记录。")
            return None
        record_by_id = {record.id: record for record in records}
        selected_id = st.selectbox(
            "选择达人",
            list(record_by_id),
            format_func=lambda value: (
                f"{record_by_id[value].user_id} · {record_by_id[value].koc_name}"
            ),
            key="edit_koc_choice",
        )
        selected = record_by_id[selected_id]
        # A saved profile gets a new timestamp, so this deliberately gives the
        # form fresh widget keys after every edit instead of reusing stale values.
        prefix = f"edit_koc_{selected.id}_{selected.updated_at}"
        user_id = st.text_input("UID *", value=selected.user_id, key=f"{prefix}_uid")
        koc_name = st.text_input(
            "达人名称 *", value=selected.koc_name, key=f"{prefix}_name"
        )
        effective_date = st.date_input(
            "资料生效日期",
            value=date.today(),
            key=f"{prefix}_effective_date",
            help="该日期之前的投稿保留旧资料；该日期及之后的投稿使用本次修改。",
        )
        category = st.selectbox(
            "合作类别",
            [None, *CreatorCategory],
            index=[None, *CreatorCategory].index(selected.creator_category),
            format_func=_category_label,
            key=f"{prefix}_category",
        )
        record_contract_options = list(
            dict.fromkeys([*contract_options, *selected.contract_types])
        )
        contracts = st.multiselect(
            "合同类型",
            record_contract_options,
            default=list(dict.fromkeys(selected.contract_types)),
            accept_new_options=True,
            placeholder="可选择多个合同类型",
            key=f"{prefix}_contract",
        )
        st.text_input(
            "合同开始日期",
            value=(
                selected.contract_start_date.isoformat()
                if selected.contract_start_date
                else "-"
            ),
            disabled=True,
            key=f"{prefix}_contract_start",
        )
        contract_end_date = st.date_input(
            "合同截止日期",
            value=(
                selected.contract_end_date
                if selected.contract_end_date
                else date.today().replace(month=10, day=31)
            ),
            key=f"{prefix}_contract_end",
            help="可单独修改截止日期。若合同类型变更，新版本会从资料生效日开始结算。",
        )
        homepage_url = st.text_input(
            "达人主页链接",
            value=selected.homepage_url or "",
            key=f"{prefix}_homepage",
        )
        if selected.homepage_url:
            st.link_button("打开当前达人主页", selected.homepage_url)
        follower_count = st.number_input(
            "粉丝数",
            min_value=0,
            value=selected.follower_count,
            step=1,
            placeholder="未知时保持空白",
            key=f"{prefix}_followers",
        )
        settlement_eligible = st.checkbox(
            "确认当前粉丝数可用于正式结算",
            value=selected.settlement_eligible,
            help="此选项沿用现有结算确认规则，本次更新不修改报酬计算逻辑。",
            key=f"{prefix}_settlement",
        )
        active = st.checkbox(
            "启用，参与自动匹配",
            value=selected.active,
            key=f"{prefix}_active",
        )
        note = st.text_area(
            "备注", value=selected.note or "", key=f"{prefix}_note"
        )
        if st.button("保存修改", type="primary", key=f"{prefix}_save"):
            try:
                updated = service.update_creator(
                    selected.id,
                    user_id=user_id,
                    koc_name=koc_name,
                    creator_category=category,
                    contract_types=contracts,
                    homepage_url=homepage_url,
                    follower_count=follower_count,
                    manual_settlement_eligible=settlement_eligible,
                    active=active,
                    note=note,
                    effective_date=effective_date,
                    contract_end_date=contract_end_date,
                )
            except (KOCRepositoryError, ValueError) as exc:
                st.error(str(exc))
            else:
                state = "启用" if updated.active else "停用"
                st.session_state["koc_flash"] = (
                    f"达人已更新：{updated.user_id} → {updated.koc_name}（{state}）"
                )
                st.rerun()
        return selected.id


def _edit_contract_history(
    service: KOCService,
    records: list[KOCRecord],
    contract_options: list[str],
) -> None:
    with st.expander("修正合同历史版本", expanded=False):
        st.caption(
            "用于补录或修正过去月份的合同。它不会修改当前达人库主合同，"
            "已锁定的结算版本也不会被改写。"
        )
        if not records:
            st.info("当前没有可修正合同历史的达人。")
            return

        record_by_id = {record.id: record for record in records}
        selected_id = st.selectbox(
            "选择达人",
            list(record_by_id),
            format_func=lambda value: (
                f"{record_by_id[value].user_id} · {record_by_id[value].koc_name}"
            ),
            key="contract_history_creator",
        )
        selected = record_by_id[selected_id]
        history = service.repository.list_profile_history_for_creator(selected.id)
        history_revision = "|".join(
            (
                f"{snapshot.effective_date}:{','.join(snapshot.contract_types)}:"
                f"{snapshot.contract_start_date}:{snapshot.contract_end_date}"
            )
            for snapshot in history
        ) or "empty"
        prefix = f"contract_history_{selected.id}_{history_revision}"
        history_table = pd.DataFrame(
            [
                {
                    "资料生效日期": snapshot.effective_date,
                    "合同类型": "、".join(snapshot.contract_types) or "未设置",
                    "合同开始日期": snapshot.contract_start_date,
                    "合同截止日期": snapshot.contract_end_date,
                }
                for snapshot in history
            ]
        )
        if history_table.empty:
            st.info("该达人暂无历史版本，请新增一条基础合同记录。")
        else:
            st.dataframe(history_table, hide_index=True, width="stretch")

        mode_options = ["新增历史版本", "编辑已有版本"]
        mode = st.radio(
            "修正方式",
            mode_options,
            horizontal=True,
            key=f"{prefix}_mode",
        )
        snapshots_by_date = {snapshot.effective_date: snapshot for snapshot in history}
        target = None
        if mode == "编辑已有版本" and snapshots_by_date:
            selected_effective_date = st.selectbox(
                "选择已有版本",
                list(snapshots_by_date),
                format_func=lambda value: value.isoformat(),
                key=f"{prefix}_existing_date",
            )
            target = snapshots_by_date[selected_effective_date]
            effective_date = st.date_input(
                "资料生效日期",
                value=target.effective_date,
                disabled=True,
                key=f"{prefix}_effective_date",
            )
        else:
            effective_date = st.date_input(
                "资料生效日期",
                value=selected.contract_start_date or date.today().replace(month=5, day=1),
                key=f"{prefix}_effective_date",
            )

        default_contracts = list(
            target.contract_types if target is not None else selected.contract_types
        )
        options = list(dict.fromkeys([*contract_options, *default_contracts]))
        contracts = st.multiselect(
            "合同类型",
            options,
            default=default_contracts,
            accept_new_options=True,
            key=f"{prefix}_contracts",
        )
        start_default = (
            target.contract_start_date
            if target is not None and target.contract_start_date
            else selected.contract_start_date
            or date.today().replace(month=5, day=1)
        )
        end_default = (
            target.contract_end_date
            if target is not None and target.contract_end_date
            else selected.contract_end_date
            or date.today().replace(month=10, day=31)
        )
        start_date, end_date = st.columns(2)
        contract_start_date = start_date.date_input(
            "合同开始日期",
            value=start_default,
            key=f"{prefix}_start",
        )
        contract_end_date = end_date.date_input(
            "合同截止日期",
            value=end_default,
            key=f"{prefix}_end",
        )
        if st.button("保存历史合同版本", type="primary", key=f"{prefix}_save"):
            try:
                saved = service.save_contract_history_version(
                    selected.id,
                    effective_date=effective_date,
                    contract_types=contracts,
                    contract_start_date=contract_start_date,
                    contract_end_date=contract_end_date,
                )
            except (KOCRepositoryError, ValueError) as exc:
                st.error(str(exc))
            else:
                contracts_text = "、".join(saved.contract_types) or "未设置"
                st.session_state["koc_flash"] = (
                    f"已保存 {selected.koc_name} 的历史合同："
                    f"{saved.effective_date.isoformat()} · "
                    f"{contracts_text}"
                )
                st.rerun()


def _edit_monthly_contract(
    dashboard_repository: DashboardRepository,
    records: list[KOCRecord],
    contract_options: list[str],
) -> None:
    with st.expander("设置月度合同快照", expanded=False):
        if not records:
            st.info("当前没有可编辑的达人记录。")
            return
        selected_month = st.date_input(
            "合同月份",
            value=date.today().replace(day=1),
            key="monthly_contract_month",
        )
        period_month = f"{selected_month.year}-{selected_month.month:02d}"
        snapshots = dashboard_repository.get_grassroot_contract_snapshots(period_month)
        record_by_id = {record.id: record for record in records}
        selected_id = st.selectbox(
            "选择达人",
            list(record_by_id),
            format_func=lambda value: (
                f"{record_by_id[value].user_id} · {record_by_id[value].koc_name}"
            ),
            key="monthly_contract_creator",
        )
        selected = record_by_id[selected_id]
        options = list(dict.fromkeys([*contract_options, *selected.contract_types]))
        snapshot_contracts = snapshots.get(selected.id, selected.contract_types)
        contracts = st.multiselect(
            "月度合同类型",
            options,
            default=list(snapshot_contracts),
            accept_new_options=True,
            placeholder="可选择多个合同类型",
            key=f"monthly_contract_values_{period_month}_{selected.id}",
        )
        if selected.id in snapshots:
            st.caption("该月份已有合同快照；保存会仅修正该月的结算合同。")
        else:
            st.caption("保存后会冻结该月份的结算合同，不会修改达人库主合同。")
        if st.button(
            "保存月度合同快照",
            type="primary",
            key=f"monthly_contract_save_{period_month}_{selected.id}",
        ):
            try:
                dashboard_repository.save_grassroot_contract_snapshot(
                    period_month,
                    selected.id,
                    contracts,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state["koc_flash"] = (
                    f"已保存 {selected.koc_name} 在 {period_month} 的合同快照："
                    f"{'、'.join(contracts) if contracts else '未设置'}"
                )
                st.rerun()


def _batch_import(service: KOCService) -> None:
    with st.expander("批量导入达人库", expanded=False):
        st.caption(
            "按真实表头读取：UID → user_id，NAME/达人名称 → koc_name，类型 → contract_type。重复 UID 只提示，所有合同关系都会保留。"
        )
        uploaded = st.file_uploader(
            "上传达人库 xlsx", type=["xlsx"], key="koc_import_file"
        )
        strategy_label = st.radio(
            "导入策略",
            ["仅新增（默认）", "更新已有"],
            horizontal=True,
            key="koc_import_strategy",
        )
        effective_date = st.date_input(
            "本次资料生效日期",
            value=date.today(),
            key="koc_import_effective_date",
            help="仅影响本次新增或更新的达人资料；历史投稿仍按旧版本显示。",
        )
        dataframe: pd.DataFrame | None = None
        if uploaded is not None:
            try:
                dataframe = pd.read_excel(
                    BytesIO(uploaded.getvalue()), engine="openpyxl", dtype="object"
                )
                preview = analyze_import_dataframe(dataframe)
            except (KOCImportFormatError, ValueError) as exc:
                st.error(str(exc))
                dataframe = None
            except Exception as exc:
                st.error(f"达人库 Excel 无法读取：{exc}")
                dataframe = None
            else:
                metrics = [
                    ("总记录数", preview.total_records),
                    ("重复 UID 数量", preview.duplicate_uid_count),
                    ("重复 UID 涉及记录", preview.duplicate_uid_rows),
                    ("空 UID", preview.empty_uid_count),
                    ("空名称", preview.empty_name_count),
                    ("空合同类型", preview.empty_contract_type_count),
                ]
                for start in range(0, len(metrics), 3):
                    columns = st.columns(3)
                    for column, (label, value) in zip(
                        columns, metrics[start : start + 3]
                    ):
                        column.metric(label, value)
                if preview.contract_types:
                    st.caption(
                        "文件中的合同类型：" + "、".join(preview.contract_types)
                    )
                if not preview.duplicate_uid_details.empty:
                    st.info("重复 UID 不视为错误；以下每一行都会参与导入。")
                    st.dataframe(
                        preview.duplicate_uid_details,
                        hide_index=True,
                        width="stretch",
                    )

        if st.button("开始导入达人库", disabled=dataframe is None):
            try:
                strategy = (
                    "add_only"
                    if strategy_label.startswith("仅新增")
                    else "update_existing"
                )
                assert dataframe is not None
                result = service.import_creators(
                    dataframe,
                    strategy=strategy,
                    effective_date=effective_date,
                )
            except (KOCRepositoryError, ValueError) as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(f"达人库 Excel 无法读取：{exc}")
            else:
                st.session_state["koc_import_result"] = result
                st.success(
                    f"导入完成：达人新增 {result.added_count}，达人资料更新 {result.updated_count}，"
                    f"基础资料跳过 {result.skipped_count}，合同关系保留 {result.contract_count}，失败 {result.failed_count}。"
                )
        result = st.session_state.get("koc_import_result")
        if result is not None:
            st.dataframe(result.details, hide_index=True, width="stretch")


def _show_data_source_status(settings: Settings) -> None:
    with st.container(border=True):
        st.subheader("粉丝数据源状态")
        columns = st.columns(2)
        columns[0].metric(
            "YouTube Data API",
            "已配置" if settings.youtube_api_configured else "未配置",
        )
        columns[1].metric(
            "TikTok 公开主页",
            "云端可用",
        )
        st.caption(
            "TikTok 仅使用达人库中的公开主页链接读取粉丝数，不使用 UID、登录 Cookie 或本地浏览器会话。"
        )


def _run_batch_update(
    follower_service: FollowerService,
    platform: str,
) -> None:
    progress = st.progress(0.0)
    current = st.empty()
    metrics_slot = st.empty()
    counts = {"completed": 0, "total": 0, "success": 0, "failed": 0, "skipped": 0}

    def render_metrics() -> None:
        with metrics_slot.container():
            columns = st.columns(3)
            columns[0].metric("已完成", counts["completed"])
            columns[1].metric("总数量", counts["total"])
            columns[2].metric("成功", counts["success"])
            columns = st.columns(2)
            columns[0].metric("失败", counts["failed"])
            columns[1].metric("跳过", counts["skipped"])

    def show_current(completed: int, total: int, record: KOCRecord) -> None:
        counts["total"] = total
        progress.progress((completed - 1) / total if total else 0.0)
        current.caption(f"当前处理达人：{record.koc_name}（{completed}/{total}）")
        render_metrics()

    def update_progress(
        completed: int,
        total: int,
        record: KOCRecord,
        outcome: object,
    ) -> None:
        status = outcome.status  # type: ignore[attr-defined]
        counts["completed"] = completed
        counts["total"] = total
        if status == "成功":
            counts["success"] += 1
        elif status == "失败":
            counts["failed"] += 1
        else:
            counts["skipped"] += 1
        progress.progress(completed / total if total else 1.0)
        current.caption(f"已完成：{record.koc_name}（{completed}/{total}）")
        render_metrics()

    render_metrics()
    if platform == "TikTok":
        result = follower_service.update_all_tiktok(
            progress_callback=update_progress,
            start_callback=show_current,
        )
    else:
        result = follower_service.update_all_youtube(
            progress_callback=update_progress,
            start_callback=show_current,
        )
    st.session_state["follower_update_result"] = result
    st.session_state["koc_flash"] = (
        f"{platform} 粉丝数更新完成：成功 {result.success_count}，"
        f"失败 {result.failed_count}，跳过 {result.skipped_count}。"
    )
    st.rerun()


def _show_batch_result() -> None:
    result = st.session_state.get("follower_update_result")
    if result is None:
        return
    columns = st.columns(3)
    columns[0].metric("成功", result.success_count)
    columns[1].metric("失败", result.failed_count)
    columns[2].metric("跳过", result.skipped_count)
    if result.stopped:
        st.warning(f"TikTok 批次已停止：{result.stop_error_code}")
    errors = result.details[result.details["status"] != "成功"]
    with st.expander(f"查看错误与跳过详情（{len(errors)}）", expanded=False):
        if errors.empty:
            st.caption("本批次没有错误或跳过记录。")
        else:
            st.dataframe(errors, hide_index=True, width="stretch")


def _single_tiktok_test(follower_service: FollowerService) -> None:
    st.subheader("测试单个 TikTok 达人")
    records = follower_service.tiktok_contract_records()
    if not records:
        st.info("当前没有合同类型为 TT、4月TT 或 5月TT 的启用达人。")
        return
    record_by_id = {record.id: record for record in records}
    selected_id = st.selectbox(
        "选择 TT 达人",
        list(record_by_id),
        format_func=lambda value: (
            f"{record_by_id[value].user_id} · {record_by_id[value].koc_name}"
        ),
        key="single_tiktok_creator",
    )
    selected = record_by_id[selected_id]
    profile = build_tiktok_profile(selected.homepage_url)
    st.caption(
        f"解析用户名：@{profile.username}"
        if profile is not None
        else "该达人尚未填写可解析的 TikTok 主页链接。"
    )
    if st.button(
        "测试单个 TikTok 达人",
        disabled=profile is None,
        icon=":material/search:",
        key="preview_single_tiktok",
    ):
        preview = follower_service.preview_tiktok(selected_id)
        st.session_state["tiktok_preview"] = (selected_id, preview)

    preview_state = st.session_state.get("tiktok_preview")
    if preview_state is None or preview_state[0] != selected_id:
        return
    preview = preview_state[1]
    if not preview.success:
        st.error(
            f"测试失败：{preview.error_code} · "
            f"{preview.error_message or '无法读取粉丝数。'}"
        )
        return
    st.success(
        f"@{preview.profile_id} 的公开 Followers："
        f"{preview.raw_display_value} → {preview.follower_count:,}"
    )
    if st.button(
        "更新单个达人粉丝数",
        type="primary",
        icon=":material/save:",
        key=f"confirm_tiktok_preview_{selected_id}",
    ):
        follower_service.confirm_tiktok_preview(selected_id, preview)
        st.session_state.pop("tiktok_preview", None)
        st.session_state["koc_flash"] = (
            f"已更新 {selected.koc_name} 的粉丝数：{preview.follower_count:,}"
        )
        st.rerun()


def _follower_controls(
    settings: Settings,
    follower_service: FollowerService,
) -> None:
    _show_data_source_status(settings)
    _single_tiktok_test(follower_service)
    st.subheader("批量更新粉丝数")
    st.caption(
        "TikTok 处理合同类型中包含 TT 或 TikTok 的全部启用达人，"
        "并在任务内部按达人和 username 去重。"
    )
    with st.container(horizontal=True):
        update_tiktok = st.button(
            "更新全部 TikTok 达人粉丝数",
            icon=":material/refresh:",
            key="update_all_tiktok",
        )
        update_youtube = st.button(
            "更新全部 YouTube 达人粉丝数",
            icon=":material/refresh:",
            key="update_all_youtube",
        )
    if update_tiktok:
        _run_batch_update(follower_service, "TikTok")
    if update_youtube:
        _run_batch_update(follower_service, "YouTube")
    _show_batch_result()


def _manual_follower_update(
    service: KOCService,
    records: list[KOCRecord],
) -> None:
    with st.expander("手动更新粉丝数", expanded=False):
        if not records:
            st.info("当前没有可更新的达人记录。")
            return
        record_by_id = {record.id: record for record in records}
        selected_id = st.selectbox(
            "达人",
            list(record_by_id),
            format_func=lambda value: (
                f"{record_by_id[value].user_id} · {record_by_id[value].koc_name}"
            ),
            key="manual_follower_creator",
        )
        selected = record_by_id[selected_id]
        followers = st.number_input(
            "最新粉丝数",
            min_value=0,
            value=selected.follower_count,
            step=1,
            placeholder="请输入整数粉丝数",
            key=f"manual_follower_value_{selected_id}",
        )
        if st.button(
            "保存手动粉丝数",
            type="primary",
            icon=":material/save:",
            key=f"manual_follower_save_{selected_id}",
        ):
            try:
                updated = service.update_follower_count_manually(
                    selected_id,
                    followers,
                )
            except (KOCRepositoryError, ValueError) as exc:
                st.error(str(exc))
            else:
                st.session_state["koc_flash"] = (
                    f"已手动更新 {updated.koc_name} 的粉丝数："
                    f"{updated.follower_count:,}"
                    if updated.follower_count is not None
                    else f"已手动清空 {updated.koc_name} 的粉丝数。"
                )
                st.rerun()


def _editor_optional_text(value: object) -> str | None:
    """Normalize editable DataFrame cells without turning blanks into text."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _editor_date(value: object) -> date | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _editor_follower_count(value: object) -> int | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    return int(float(str(value).replace(",", "").strip()))


def _editor_contract_types(value: object) -> tuple[str, ...]:
    text = _editor_optional_text(value)
    if text is None or text == "未设置":
        return ()
    for separator in ("、", "，", ";", "；", "\n"):
        text = text.replace(separator, ",")
    return tuple(dict.fromkeys(part.strip() for part in text.split(",") if part.strip()))


def _editor_category(record: KOCRecord, value: object) -> CreatorCategory | None:
    """Keep an inferred category untouched unless the table cell was edited."""
    text = _editor_optional_text(value)
    if text == _creator_category_display(record):
        return record.creator_category
    if text is None or text == "未设置":
        return None
    return parse_creator_category(text)


def _editor_bool(value: object) -> bool:
    if value is None or pd.isna(value):
        return False
    return bool(value)


def _creator_editor_table(records: list[KOCRecord], settings: Settings) -> pd.DataFrame:
    columns = [
        "记录ID",
        "UID",
        "达人名称",
        "合作类别",
        "合同类型",
        "合同开始日期",
        "合同截止日期",
        "新合同生效月份",
        "YouTube UID",
        "YouTube主页",
        "YouTube粉丝数",
        "TikTok UID",
        "TikTok主页",
        "TikTok粉丝数",
        "粉丝数可结算",
        "启用",
        "备注",
        "粉丝数最后更新时间",
    ]
    return pd.DataFrame(
        [
            {
                "记录ID": record.id,
                "UID": record.user_id,
                "达人名称": record.koc_name,
                "合作类别": _creator_category_display(record),
                "合同类型": "、".join(record.contract_types) or "未设置",
                "合同开始日期": record.contract_start_date,
                "合同截止日期": record.contract_end_date,
                "新合同生效月份": (
                    record.contract_start_date.strftime("%Y-%m")
                    if record.contract_start_date is not None
                    else date.today().strftime("%Y-%m")
                ),
                "YouTube UID": record.youtube_user_id,
                "YouTube主页": record.youtube_homepage_url,
                "YouTube粉丝数": record.youtube_follower_count,
                "TikTok UID": record.tiktok_user_id,
                "TikTok主页": record.tiktok_homepage_url,
                "TikTok粉丝数": record.tiktok_follower_count,
                "粉丝数可结算": record.settlement_eligible,
                "启用": record.active,
                "备注": record.note,
                "粉丝数最后更新时间": _display_updated_at(
                    record.follower_count_updated_at,
                    settings.timezone,
                ),
            }
            for record in records
        ],
        columns=columns,
    )


def _save_creator_editor_changes(
    service: KOCService,
    records: list[KOCRecord],
    edited: pd.DataFrame,
) -> tuple[int, list[str]]:
    records_by_id = {record.id: record for record in records}
    updated_count = 0
    errors: list[str] = []
    for _, row in edited.iterrows():
        try:
            record_id = int(row["记录ID"])
            record = records_by_id[record_id]
            user_id = _editor_optional_text(row["UID"])
            koc_name = _editor_optional_text(row["达人名称"])
            category = _editor_category(record, row["合作类别"])
            contracts = _editor_contract_types(row["合同类型"])
            contract_start_date = _editor_date(row["合同开始日期"])
            contract_end_date = _editor_date(row["合同截止日期"])
            selected_effective_month = _editor_effective_month(
                row["新合同生效月份"]
            )
            youtube_user_id = _editor_optional_text(
                row.get("YouTube UID", record.youtube_user_id)
            )
            youtube_homepage_url = _editor_optional_text(
                row.get("YouTube主页", record.youtube_homepage_url)
            )
            youtube_follower_count = _editor_follower_count(
                row.get("YouTube粉丝数", record.youtube_follower_count)
            )
            tiktok_user_id = _editor_optional_text(
                row.get("TikTok UID", record.tiktok_user_id)
            )
            tiktok_homepage_url = _editor_optional_text(
                row.get("TikTok主页", record.tiktok_homepage_url)
            )
            tiktok_follower_count = _editor_follower_count(
                row.get("TikTok粉丝数", record.tiktok_follower_count)
            )
            settlement_eligible = _editor_bool(row["粉丝数可结算"])
            active = _editor_bool(row["启用"])
            note = _editor_optional_text(row["备注"])
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"表格中有无法读取的记录：{exc}")
            continue

        contract_effective_month_changed = (
            selected_effective_month != record.contract_start_date
        )
        changed = any(
            (
                user_id != record.user_id,
                koc_name != record.koc_name,
                category != record.creator_category,
                contracts != record.contract_types,
                contract_start_date != record.contract_start_date,
                contract_end_date != record.contract_end_date,
                contract_effective_month_changed,
                youtube_user_id != record.youtube_user_id,
                youtube_homepage_url != record.youtube_homepage_url,
                youtube_follower_count != record.youtube_follower_count,
                tiktok_user_id != record.tiktok_user_id,
                tiktok_homepage_url != record.tiktok_homepage_url,
                tiktok_follower_count != record.tiktok_follower_count,
                settlement_eligible != record.settlement_eligible,
                active != record.active,
                note != record.note,
            )
        )
        if not changed:
            continue

        contract_changed = (
            contracts != record.contract_types
            or category != record.creator_category
        )
        effective_date = (
            selected_effective_month
            if contract_changed or contract_effective_month_changed
            else date.today()
        )
        if contract_effective_month_changed:
            contract_start_date = selected_effective_month
        # An unchanged start date belongs to the previous contract. Let the
        # repository start a new contract at its effective date instead.
        if contract_changed and contract_start_date == record.contract_start_date:
            contract_start_date = None
        try:
            service.update_creator(
                record_id,
                user_id=user_id,
                koc_name=koc_name,
                creator_category=category,
                contract_types=contracts,
                homepage_url=record.homepage_url,
                follower_count=record.follower_count,
                youtube_user_id=youtube_user_id,
                youtube_homepage_url=youtube_homepage_url,
                youtube_follower_count=youtube_follower_count,
                tiktok_user_id=tiktok_user_id,
                tiktok_homepage_url=tiktok_homepage_url,
                tiktok_follower_count=tiktok_follower_count,
                manual_settlement_eligible=settlement_eligible,
                active=active,
                note=note,
                effective_date=effective_date,
                contract_start_date=contract_start_date,
                contract_end_date=contract_end_date,
            )
        except (KOCRepositoryError, ValueError) as exc:
            errors.append(f"{record.user_id} · {record.koc_name}：{exc}")
        else:
            updated_count += 1
    return updated_count, errors


def _contract_period_status(
    effective_date: date,
    start: date | None,
    end: date | None,
    next_effective_date: date | None,
) -> str:
    today = date.today()
    applies_from = max(effective_date, start) if start is not None else effective_date
    if applies_from > today:
        return "未生效"
    if next_effective_date is not None and next_effective_date <= today:
        return "已替换"
    if end is not None and end < today:
        return "已结束"
    return "当前"


def _contract_period_table(
    records: list[KOCRecord],
    history: list,
) -> pd.DataFrame:
    columns = [
        "记录ID",
        "合同周期ID",
        "达人",
        "UID",
        "变更生效日",
        "合同类型",
        "合同开始日期",
        "合同截止日期",
        "状态",
    ]
    snapshots_by_creator: dict[int, list] = {}
    visible_ids = {record.id for record in records}
    for snapshot in history:
        if snapshot.creator_id in visible_ids:
            snapshots_by_creator.setdefault(snapshot.creator_id, []).append(snapshot)

    rows: list[dict[str, object]] = []
    for record in records:
        periods: dict[tuple[tuple[str, ...], date], list] = {}
        for snapshot in snapshots_by_creator.get(record.id, []):
            start = snapshot.contract_start_date or snapshot.effective_date
            periods.setdefault((snapshot.contract_types, start), []).append(snapshot)
        period_entries: list[tuple[tuple[str, ...], date, object, object, date | None]] = []
        for (contracts, start), snapshots in periods.items():
            ordered = sorted(snapshots, key=lambda snapshot: snapshot.effective_date)
            source = ordered[0]
            latest = ordered[-1]
            end = latest.contract_end_date or source.contract_end_date
            period_entries.append((contracts, start, source, latest, end))
        period_entries.sort(key=lambda entry: entry[2].effective_date)
        for index, (contracts, start, source, _latest, end) in enumerate(
            period_entries
        ):
            next_effective = (
                period_entries[index + 1][2].effective_date
                if index + 1 < len(period_entries)
                else None
            )
            rows.append(
                {
                    "记录ID": record.id,
                    "合同周期ID": source.effective_date,
                    "达人": record.koc_name,
                    "UID": record.user_id,
                    "变更生效日": max(source.effective_date, start),
                    "合同类型": "、".join(contracts) or "未设置",
                    "合同开始日期": start,
                    "合同截止日期": end,
                    "状态": _contract_period_status(
                        source.effective_date,
                        start,
                        end,
                        next_effective,
                    ),
                }
            )
    return pd.DataFrame(
        sorted(
            rows,
            key=lambda row: (
                str(row["达人"]).casefold(),
                row["变更生效日"],
            ),
            reverse=True,
        ),
        columns=columns,
    )


def _filter_contract_period_table(
    table: pd.DataFrame,
    *,
    search: str = "",
    contract_types: tuple[str, ...] | list[str] = (),
    statuses: tuple[str, ...] | list[str] = (),
) -> pd.DataFrame:
    filtered = table.copy()
    needle = search.strip().casefold()
    if needle:
        searchable = filtered[["达人", "UID", "合同类型"]].fillna("").astype(str)
        mask = searchable.apply(
            lambda row: needle in " ".join(row.tolist()).casefold(),
            axis=1,
        )
        filtered = filtered.loc[mask]

    selected_contracts = {
        str(value).strip() for value in contract_types if str(value).strip()
    }
    if selected_contracts:
        filtered = filtered.loc[
            filtered["合同类型"].map(
                lambda value: bool(
                    selected_contracts.intersection(_editor_contract_types(value))
                )
            )
        ]

    selected_statuses = {
        str(value).strip() for value in statuses if str(value).strip()
    }
    if selected_statuses:
        filtered = filtered.loc[filtered["状态"].isin(selected_statuses)]
    return filtered.reset_index(drop=True)


def _save_contract_period_changes(
    service: KOCService,
    records: list[KOCRecord],
    original: pd.DataFrame,
    edited: pd.DataFrame,
) -> tuple[int, list[str]]:
    records_by_id = {record.id: record for record in records}
    original_by_key = {
        (
            int(row["记录ID"]),
            _editor_date(row["合同周期ID"]),
        ): row
        for _, row in original.iterrows()
    }
    updated_count = 0
    errors: list[str] = []
    for _, row in edited.iterrows():
        try:
            record_id = int(row["记录ID"])
            source_effective = _editor_date(row["合同周期ID"])
            if source_effective is None:
                raise ValueError("缺少合同周期标识")
            record = records_by_id[record_id]
            before = original_by_key[(record_id, source_effective)]
            contracts = _editor_contract_types(row["合同类型"])
            start = _editor_date(row["合同开始日期"])
            end = _editor_date(row["合同截止日期"])
            before_contracts = _editor_contract_types(before["合同类型"])
            before_start = _editor_date(before["合同开始日期"])
            before_end = _editor_date(before["合同截止日期"])
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"合同周期表中有无法读取的记录：{exc}")
            continue
        if (contracts, start, end) == (before_contracts, before_start, before_end):
            continue
        try:
            service.update_contract_period(
                record_id,
                source_effective_date=source_effective,
                contract_types=contracts,
                contract_start_date=start,
                contract_end_date=end,
                reason="合同周期表：更正录入错误",
            )
        except (KOCRepositoryError, ValueError) as exc:
            errors.append(f"{record.user_id} · {record.koc_name}：{exc}")
        else:
            updated_count += 1
    return updated_count, errors


def _render_contract_period_delete_confirmation(service: KOCService) -> None:
    pending = st.session_state.get("koc_contract_period_delete_pending")
    if not pending:
        return

    st.warning(
        f"确认删除 {pending['达人']}（{pending['UID']}）的合同周期："
        f"{pending['合同类型']}，{pending['合同开始日期']} 至 "
        f"{pending['合同截止日期']}。删除后无法在页面中撤销。"
    )
    actions = st.columns([1, 1, 5])
    if actions[0].button(
        "确认删除",
        type="primary",
        key="confirm_contract_period_delete",
    ):
        try:
            service.delete_contract_period(
                int(pending["记录ID"]),
                source_effective_date=pending["合同周期ID"],
                reason="合同周期表：删除错误周期",
            )
        except (KOCRepositoryError, ValueError) as exc:
            st.error(str(exc))
        else:
            st.session_state.pop("koc_contract_period_delete_pending", None)
            _reset_linked_page_state(st.session_state)
            st.session_state["koc_flash"] = (
                f"已删除 {pending['达人']} 的合同周期，并同步看板与报酬。"
            )
            st.rerun()
    if actions[1].button("取消", key="cancel_contract_period_delete"):
        st.session_state.pop("koc_contract_period_delete_pending", None)
        st.rerun()


def _render_contract_period_editor(
    service: KOCService,
    records: list[KOCRecord],
) -> None:
    history = service.repository.list_contract_periods()
    table = _contract_period_table(records, history)
    if table.empty:
        st.info("当前筛选范围内没有合同周期。")
        return

    contract_options = sorted(
        {
            contract
            for value in table["合同类型"]
            for contract in _editor_contract_types(value)
        },
        key=str.casefold,
    )
    filter_columns = st.columns([2, 1.4, 1.2])
    search = filter_columns[0].text_input(
        "搜索合同周期",
        placeholder="达人名称、UID 或合同类型",
        key="koc_contract_period_search",
    )
    contract_filters = filter_columns[1].multiselect(
        "合同类型筛选",
        contract_options,
        placeholder="全部合同",
        key="koc_contract_period_contract_filters",
    )
    status_filters = filter_columns[2].multiselect(
        "周期状态筛选",
        ["当前", "未生效", "已替换", "已结束"],
        placeholder="全部状态",
        key="koc_contract_period_status_filters",
    )
    filtered_table = _filter_contract_period_table(
        table,
        search=search,
        contract_types=contract_filters,
        statuses=status_filters,
    )
    _render_contract_period_delete_confirmation(service)
    if filtered_table.empty:
        st.info("没有符合当前搜索和筛选条件的合同周期。")
        return

    editor_table = filtered_table.copy()
    editor_table.insert(0, "删除", False)
    revision = "|".join(
        f"{row['记录ID']}:{row['合同周期ID']}:{row['合同类型']}:"
        f"{row['合同开始日期']}:{row['合同截止日期']}"
        for _, row in filtered_table.iterrows()
    )
    with st.form("contract_period_editor_form"):
        edited = st.data_editor(
            editor_table,
            hide_index=True,
            width="stretch",
            height=360,
            num_rows="fixed",
            key=f"contract_period_editor_{revision}",
            disabled=[
                "记录ID",
                "合同周期ID",
                "达人",
                "UID",
                "变更生效日",
                "状态",
            ],
            column_config={
                "删除": st.column_config.CheckboxColumn(
                    "删除",
                    help="勾选一条记录后点击“删除所选周期”。",
                    width="small",
                ),
                "记录ID": None,
                "合同周期ID": None,
                "达人": st.column_config.TextColumn("达人", pinned=True),
                "UID": st.column_config.TextColumn("UID"),
                "变更生效日": st.column_config.DateColumn(
                    "变更生效日", format="YYYY-MM-DD"
                ),
                "合同类型": st.column_config.TextColumn(
                    "合同类型",
                    help="多个合同请用顿号或逗号分隔。",
                ),
                "合同开始日期": st.column_config.DateColumn(
                    "合同开始日期", format="YYYY-MM-DD"
                ),
                "合同截止日期": st.column_config.DateColumn(
                    "合同截止日期", format="YYYY-MM-DD"
                ),
                "状态": st.column_config.TextColumn("状态"),
            },
        )
        form_actions = st.columns([1, 1, 4])
        save_submitted = form_actions[0].form_submit_button(
            "保存合同周期",
            type="primary",
        )
        delete_submitted = form_actions[1].form_submit_button(
            "删除所选周期"
        )
    st.caption(
        f"当前显示 {len(filtered_table):,} / {len(table):,} 段合同周期"
    )

    if delete_submitted:
        selected = edited.loc[edited["删除"].fillna(False).astype(bool)]
        if selected.empty:
            st.warning("请先勾选一段要删除的合同周期。")
            return
        if len(selected) > 1:
            st.warning("为避免误删，每次只能删除一段合同周期。")
            return
        row = selected.iloc[0]
        source_effective = _editor_date(row["合同周期ID"])
        if source_effective is None:
            st.error("缺少合同周期标识，请刷新页面后重试。")
            return
        st.session_state["koc_contract_period_delete_pending"] = {
            "记录ID": int(row["记录ID"]),
            "合同周期ID": source_effective.isoformat(),
            "达人": str(row["达人"]),
            "UID": str(row["UID"]),
            "合同类型": str(row["合同类型"]),
            "合同开始日期": str(row["合同开始日期"]),
            "合同截止日期": str(row["合同截止日期"]),
        }
        st.rerun()

    if not save_submitted:
        return

    updated_count, errors = _save_contract_period_changes(
        service,
        records,
        filtered_table,
        edited.drop(columns=["删除"]),
    )
    if updated_count:
        _reset_linked_page_state(st.session_state)
    if errors:
        if updated_count:
            st.warning(f"已保存并同步 {updated_count} 段合同周期；其余记录需要修正后再保存。")
        for message in errors:
            st.error(message)
        return
    if updated_count:
        st.session_state["koc_flash"] = (
            f"已保存并同步 {updated_count} 段合同周期。"
        )
        st.rerun()
    st.info("没有检测到需要保存的合同周期修改。")


def _render_creator_editor(
    repository: KOCRepository,
    service: KOCService,
    settings: Settings,
    all_records: list[KOCRecord],
    contract_options: list[str],
) -> None:
    st.subheader("达人列表")
    st.caption(
        "直接在表格中修改资料。合同类型变更时，只需选择“新合同生效月份”；"
        "保存后会自动同步看板和实时报酬，生效月份之前的数据保持不变。"
    )
    filter_columns = st.columns(2)
    category_filter = filter_columns[0].selectbox(
        "合作类别筛选", [None, *CreatorCategory], format_func=_category_label
    )
    contract_filter_revision = "|".join(
        f"{record.id}:{record.updated_at}" for record in all_records
    ) or "empty"
    contract_filters = filter_columns[1].multiselect(
        "合同类型筛选",
        contract_options,
        placeholder="未选择时显示全部合同类型",
        key=f"koc_contract_filters_{contract_filter_revision}",
    )
    filtered = repository.list(
        creator_category=category_filter,
        contract_types=contract_filters,
    )
    table = _creator_editor_table(filtered, settings)
    if not table.empty:
        table["YouTube粉丝数"] = table["YouTube粉丝数"].astype("Int64")
        table["TikTok粉丝数"] = table["TikTok粉丝数"].astype("Int64")

    editor_key = (
        "koc_master_editor_"
        f"{contract_filter_revision}_{category_filter or 'all'}_"
        f"{'|'.join(contract_filters) or 'all'}"
    )
    with st.form("koc_master_editor_form"):
        edited = st.data_editor(
            table,
            hide_index=True,
            width="stretch",
            height=520,
            num_rows="fixed",
            key=editor_key,
            disabled=["记录ID", "合同开始日期", "粉丝数最后更新时间"],
            column_config={
                "记录ID": None,
                "UID": st.column_config.TextColumn("UID", required=True, pinned=True),
                "达人名称": st.column_config.TextColumn("达人名称", required=True),
                "合作类别": st.column_config.SelectboxColumn(
                    "合作类别",
                    options=["未设置", *CREATOR_CATEGORY_LABELS.values()],
                ),
                "合同类型": st.column_config.TextColumn(
                    "合同类型",
                    help="可直接输入新合同；多个合同请用顿号或逗号分隔。",
                ),
                "合同开始日期": st.column_config.DateColumn(
                    "合同开始日期", format="YYYY-MM-DD"
                ),
                "合同截止日期": st.column_config.DateColumn(
                    "合同截止日期", format="YYYY-MM-DD"
                ),
                "新合同生效月份": st.column_config.SelectboxColumn(
                    "新合同生效月份",
                    options=_effective_month_options(),
                    help="新合同从所选月份1日开始生效；此前月份仍使用原合同。",
                ),
                "YouTube UID": st.column_config.TextColumn("YouTube UID"),
                "YouTube主页": st.column_config.TextColumn("YouTube主页"),
                "YouTube粉丝数": st.column_config.NumberColumn(
                    "YouTube粉丝数", min_value=0, step=1
                ),
                "TikTok UID": st.column_config.TextColumn("TikTok UID"),
                "TikTok主页": st.column_config.TextColumn("TikTok主页"),
                "TikTok粉丝数": st.column_config.NumberColumn(
                    "TikTok粉丝数", min_value=0, step=1
                ),
                "粉丝数可结算": st.column_config.CheckboxColumn("粉丝数可结算"),
                "启用": st.column_config.CheckboxColumn("启用"),
                "备注": st.column_config.TextColumn("备注", width="medium"),
                "粉丝数最后更新时间": st.column_config.TextColumn(
                    "粉丝数最后更新时间"
                ),
            },
        )
        submitted = st.form_submit_button(
            "保存并同步看板与报酬",
            type="primary",
        )

    st.caption(f"当前显示：{len(table):,} / {len(all_records):,} 位达人")
    if submitted:
        if table.empty:
            st.info("当前筛选条件下没有可保存的达人记录。")
        else:
            updated_count, errors = _save_creator_editor_changes(
                service,
                filtered,
                edited,
            )
            if updated_count:
                _reset_linked_page_state(st.session_state)
            if errors:
                if updated_count:
                    st.warning(
                        f"已保存并同步 {updated_count} 位达人；其余记录需要修正后再保存。"
                    )
                for message in errors:
                    st.error(message)
            elif updated_count:
                st.session_state["koc_flash"] = (
                    f"已保存并同步 {updated_count} 位达人；看板和报酬已切换到最新实时数据。"
                )
                st.rerun()
            else:
                st.info("没有检测到需要保存的修改。")

    if st.toggle("显示合同周期", value=False, key="koc_show_contract_periods"):
        _render_contract_period_editor(service, filtered)


_CONTRACT_ACTION_NONE = "不修改合同"
_CONTRACT_ACTION_CORRECT = "更正录入错误"
_CONTRACT_ACTION_CHANGE = "新合同生效"


def _creator_editor_table(records: list[KOCRecord], settings: Settings) -> pd.DataFrame:
    columns = [
        "记录ID",
        "UID",
        "达人名称",
        "合作类别",
        "合同操作",
        "合同类型",
        "合同开始日期",
        "合同截止日期",
        "合同生效月份",
        "合同修改说明",
        "YouTube UID",
        "YouTube主页",
        "YouTube粉丝数",
        "TikTok UID",
        "TikTok主页",
        "TikTok粉丝数",
        "粉丝数可结算",
        "启用",
        "备注",
        "粉丝数最后更新时间",
    ]
    return pd.DataFrame(
        [
            {
                "记录ID": record.id,
                "UID": record.user_id,
                "达人名称": record.koc_name,
                "合作类别": _creator_category_display(record),
                "合同操作": _CONTRACT_ACTION_NONE,
                "合同类型": "、".join(record.contract_types) or "未设置",
                "合同开始日期": record.contract_start_date,
                "合同截止日期": record.contract_end_date,
                "合同生效月份": (
                    record.contract_start_date.strftime("%Y-%m")
                    if record.contract_start_date is not None
                    else date.today().strftime("%Y-%m")
                ),
                "合同修改说明": "",
                "YouTube UID": record.youtube_user_id,
                "YouTube主页": record.youtube_homepage_url,
                "YouTube粉丝数": record.youtube_follower_count,
                "TikTok UID": record.tiktok_user_id,
                "TikTok主页": record.tiktok_homepage_url,
                "TikTok粉丝数": record.tiktok_follower_count,
                "粉丝数可结算": record.settlement_eligible,
                "启用": record.active,
                "备注": record.note,
                "粉丝数最后更新时间": _display_updated_at(
                    record.follower_count_updated_at,
                    settings.timezone,
                ),
            }
            for record in records
        ],
        columns=columns,
    )


def _save_creator_editor_changes(
    service: KOCService,
    records: list[KOCRecord],
    edited: pd.DataFrame,
) -> tuple[int, list[str]]:
    records_by_id = {record.id: record for record in records}
    updated_count = 0
    errors: list[str] = []
    for _, row in edited.iterrows():
        try:
            record_id = int(row["记录ID"])
            record = records_by_id[record_id]
            user_id = _editor_optional_text(row["UID"])
            koc_name = _editor_optional_text(row["达人名称"])
            category = _editor_category(record, row["合作类别"])
            contracts = _editor_contract_types(row["合同类型"])
            contract_action = (
                _editor_optional_text(row.get("合同操作")) or _CONTRACT_ACTION_NONE
            )
            contract_start = _editor_date(row["合同开始日期"])
            contract_end = _editor_date(row["合同截止日期"])
            effective_month = _editor_effective_month(row["合同生效月份"])
            contract_reason = _editor_optional_text(row.get("合同修改说明"))
            youtube_user_id = _editor_optional_text(
                row.get("YouTube UID", record.youtube_user_id)
            )
            youtube_homepage_url = _editor_optional_text(
                row.get("YouTube主页", record.youtube_homepage_url)
            )
            youtube_follower_count = _editor_follower_count(
                row.get("YouTube粉丝数", record.youtube_follower_count)
            )
            tiktok_user_id = _editor_optional_text(
                row.get("TikTok UID", record.tiktok_user_id)
            )
            tiktok_homepage_url = _editor_optional_text(
                row.get("TikTok主页", record.tiktok_homepage_url)
            )
            tiktok_follower_count = _editor_follower_count(
                row.get("TikTok粉丝数", record.tiktok_follower_count)
            )
            settlement_eligible = _editor_bool(row["粉丝数可结算"])
            active = _editor_bool(row["启用"])
            note = _editor_optional_text(row["备注"])
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"表格中有无法读取的记录：{exc}")
            continue

        contract_fields_changed = any(
            (
                category != record.creator_category,
                contracts != record.contract_types,
                contract_start != record.contract_start_date,
                contract_end != record.contract_end_date,
                effective_month != record.contract_start_date,
            )
        )
        if contract_fields_changed and contract_action == _CONTRACT_ACTION_NONE:
            errors.append(
                f"{record.user_id} · {record.koc_name}：合同字段已修改，请选择“更正录入错误”或“新合同生效”。"
            )
            continue
        if contract_action not in {
            _CONTRACT_ACTION_NONE,
            _CONTRACT_ACTION_CORRECT,
            _CONTRACT_ACTION_CHANGE,
        }:
            errors.append(f"{record.user_id} · {record.koc_name}：合同操作无效。")
            continue

        profile_changed = any(
            (
                user_id != record.user_id,
                koc_name != record.koc_name,
                youtube_user_id != record.youtube_user_id,
                youtube_homepage_url != record.youtube_homepage_url,
                youtube_follower_count != record.youtube_follower_count,
                tiktok_user_id != record.tiktok_user_id,
                tiktok_homepage_url != record.tiktok_homepage_url,
                tiktok_follower_count != record.tiktok_follower_count,
                settlement_eligible != record.settlement_eligible,
                active != record.active,
                note != record.note,
            )
        )
        contract_operation = contract_action != _CONTRACT_ACTION_NONE
        if not profile_changed and not contract_operation:
            continue

        try:
            if profile_changed:
                service.update_creator(
                    record_id,
                    user_id=user_id,
                    koc_name=koc_name,
                    creator_category=record.creator_category,
                    contract_types=record.contract_types,
                    homepage_url=record.homepage_url,
                    follower_count=record.follower_count,
                    youtube_user_id=youtube_user_id,
                    youtube_homepage_url=youtube_homepage_url,
                    youtube_follower_count=youtube_follower_count,
                    tiktok_user_id=tiktok_user_id,
                    tiktok_homepage_url=tiktok_homepage_url,
                    tiktok_follower_count=tiktok_follower_count,
                    manual_settlement_eligible=settlement_eligible,
                    active=active,
                    note=note,
                    effective_date=date.today(),
                    contract_start_date=record.contract_start_date,
                    contract_end_date=record.contract_end_date,
                )

            if contract_action == _CONTRACT_ACTION_CORRECT:
                if record.contract_start_date is None:
                    raise ValueError("当前达人没有可纠正的合同周期。")
                corrected_start = effective_month
                corrected_end = contract_end or record.contract_end_date
                if corrected_end is None:
                    raise ValueError("请填写合同截止日期。")
                service.correct_contract_period(
                    record_id,
                    source_effective_date=record.contract_start_date,
                    contract_types=contracts,
                    contract_start_date=corrected_start,
                    contract_end_date=corrected_end,
                    reason=contract_reason or "达人库表格：更正录入错误",
                )
            elif contract_action == _CONTRACT_ACTION_CHANGE:
                service.create_contract_change(
                    record_id,
                    effective_date=effective_month,
                    contract_types=contracts,
                    contract_end_date=contract_end,
                    creator_category=category,
                    reason=contract_reason or "达人库表格：新合同生效",
                )
        except (KOCRepositoryError, ValueError) as exc:
            errors.append(f"{record.user_id} · {record.koc_name}：{exc}")
        else:
            updated_count += 1
    return updated_count, errors


def _contract_period_table(records: list[KOCRecord], history: list) -> pd.DataFrame:
    columns = [
        "记录ID",
        "合同周期ID",
        "达人",
        "UID",
        "变更生效日",
        "合同类型",
        "合同开始日期",
        "合同截止日期",
        "状态",
    ]
    records_by_id = {record.id: record for record in records}
    periods_by_creator: dict[int, list] = {}
    for period in history:
        if period.creator_id in records_by_id:
            periods_by_creator.setdefault(period.creator_id, []).append(period)
    rows: list[dict[str, object]] = []
    for creator_id, periods in periods_by_creator.items():
        record = records_by_id[creator_id]
        unique_periods = {
            (
                item.contract_start_date,
                item.contract_end_date,
                tuple(item.contract_types),
            ): item
            for item in periods
        }
        ordered = sorted(
            unique_periods.values(), key=lambda item: item.contract_start_date
        )
        for index, period in enumerate(ordered):
            next_start = (
                ordered[index + 1].contract_start_date
                if index + 1 < len(ordered)
                else None
            )
            rows.append(
                {
                    "记录ID": record.id,
                    "合同周期ID": period.contract_start_date,
                    "达人": record.koc_name,
                    "UID": record.user_id,
                    "变更生效日": period.contract_start_date,
                    "合同类型": "、".join(period.contract_types) or "未设置",
                    "合同开始日期": period.contract_start_date,
                    "合同截止日期": period.contract_end_date,
                    "状态": _contract_period_status(
                        period.contract_start_date,
                        period.contract_start_date,
                        period.contract_end_date,
                        next_start,
                    ),
                }
            )
    return pd.DataFrame(
        sorted(
            rows,
            key=lambda row: (str(row["达人"]).casefold(), row["变更生效日"]),
            reverse=True,
        ),
        columns=columns,
    )


def _render_contract_revision_history(
    service: KOCService,
    records: list[KOCRecord],
) -> None:
    revisions = service.list_contract_revisions(limit=200)
    visible_ids = {record.id for record in records}
    revisions = [item for item in revisions if item.creator_id in visible_ids]
    if not revisions:
        st.info("当前筛选范围内没有合同修改记录。")
        return
    names = {record.id: record.koc_name for record in records}
    operation_labels = {
        "CORRECTION": "更正错误",
        "CHANGE": "合同变更",
        "DELETE": "删除周期",
        "REVERT": "撤销修改",
    }
    table = pd.DataFrame(
        [
            {
                "修改ID": item.id,
                "达人": names.get(item.creator_id, str(item.creator_id)),
                "操作": operation_labels.get(item.operation_type, item.operation_type),
                "影响开始": item.affected_start_date,
                "影响结束": item.affected_end_date,
                "修改说明": item.reason,
                "已撤销": bool(item.reverted_at),
                "修改时间": item.created_at[:19],
            }
            for item in revisions
        ]
    )
    st.dataframe(table, hide_index=True, width="stretch", height=300)
    reversible = [
        item
        for item in revisions
        if item.operation_type != "REVERT" and not item.reverted_at
    ]
    if not reversible:
        return
    revision_by_id = {item.id: item for item in reversible}
    selected = st.selectbox(
        "选择要撤销的合同修改",
        list(revision_by_id),
        format_func=lambda value: (
            f"#{value} · {names.get(revision_by_id[value].creator_id, '')} · "
            f"{operation_labels.get(revision_by_id[value].operation_type, revision_by_id[value].operation_type)}"
        ),
        key="koc_contract_revision_revert_select",
    )
    if st.button(
        "撤销所选合同修改",
        icon=":material/undo:",
        key="koc_contract_revision_revert_button",
    ):
        try:
            service.revert_contract_revision(int(selected))
        except (KOCRepositoryError, ValueError) as exc:
            st.error(str(exc))
        else:
            _reset_linked_page_state(st.session_state)
            st.session_state["koc_flash"] = "已撤销最近一次合同修改，并同步看板与实时报酬。"
            st.rerun()


def _contract_editor_impact_table(
    records: list[KOCRecord],
    edited: pd.DataFrame,
) -> pd.DataFrame:
    records_by_id = {record.id: record for record in records}
    rows: list[dict[str, object]] = []
    for _, row in edited.iterrows():
        try:
            record = records_by_id[int(row["记录ID"])]
            action = _editor_optional_text(row.get("合同操作"))
            if action not in {_CONTRACT_ACTION_CORRECT, _CONTRACT_ACTION_CHANGE}:
                continue
            new_contracts = _editor_contract_types(row["合同类型"])
            effective = _editor_effective_month(row["合同生效月份"])
            new_end = _editor_date(row["合同截止日期"])
        except (KeyError, TypeError, ValueError):
            continue
        end_candidates = [
            value for value in (record.contract_end_date, new_end) if value is not None
        ]
        rows.append(
            {
                "达人": record.koc_name,
                "操作": action,
                "原合同": "、".join(record.contract_types) or "未设置",
                "新合同": "、".join(new_contracts) or "未设置",
                "影响开始": (
                    min(record.contract_start_date, effective)
                    if action == _CONTRACT_ACTION_CORRECT
                    and record.contract_start_date is not None
                    else effective
                ),
                "影响结束": max(end_candidates) if end_candidates else None,
            }
        )
    return pd.DataFrame(rows)


def _render_creator_editor_v2(
    repository: KOCRepository,
    service: KOCService,
    settings: Settings,
    all_records: list[KOCRecord],
    contract_options: list[str],
) -> None:
    st.subheader("达人列表")
    st.caption(
        "普通资料可直接修改。涉及合同类型、合作类别或合同日期时，必须在同一行选择“更正录入错误”或“新合同生效”。"
    )
    filter_columns = st.columns(2)
    category_filter = filter_columns[0].selectbox(
        "合作类别筛选", [None, *CreatorCategory], format_func=_category_label
    )
    contract_filter_revision = "|".join(
        f"{record.id}:{record.updated_at}" for record in all_records
    ) or "empty"
    contract_filters = filter_columns[1].multiselect(
        "合同类型筛选",
        contract_options,
        placeholder="未选择时显示全部合同类型",
        key=f"koc_contract_filters_{contract_filter_revision}",
    )
    filtered = repository.list(
        creator_category=category_filter,
        contract_types=contract_filters,
    )
    table = _creator_editor_table(filtered, settings)
    if not table.empty:
        table["YouTube粉丝数"] = table["YouTube粉丝数"].astype("Int64")
        table["TikTok粉丝数"] = table["TikTok粉丝数"].astype("Int64")
    editor_key = (
        "koc_master_editor_v2_"
        f"{contract_filter_revision}_{category_filter or 'all'}_"
        f"{'|'.join(contract_filters) or 'all'}"
    )
    with st.form("koc_master_editor_form_v2"):
        edited = st.data_editor(
            table,
            hide_index=True,
            width="stretch",
            height=520,
            num_rows="fixed",
            key=editor_key,
            disabled=["记录ID", "合同开始日期", "粉丝数最后更新时间"],
            column_config={
                "记录ID": None,
                "UID": st.column_config.TextColumn("UID", required=True, pinned=True),
                "达人名称": st.column_config.TextColumn("达人名称", required=True),
                "合作类别": st.column_config.SelectboxColumn(
                    "合作类别", options=["未设置", *CREATOR_CATEGORY_LABELS.values()]
                ),
                "合同操作": st.column_config.SelectboxColumn(
                    "合同操作",
                    options=[
                        _CONTRACT_ACTION_NONE,
                        _CONTRACT_ACTION_CORRECT,
                        _CONTRACT_ACTION_CHANGE,
                    ],
                    help="填错请选择更正；真实换约请选择新合同生效。",
                ),
                "合同类型": st.column_config.TextColumn(
                    "合同类型", help="多个合同请用顿号或逗号分隔。"
                ),
                "合同开始日期": st.column_config.DateColumn(
                    "当前合同开始日期", format="YYYY-MM-DD"
                ),
                "合同截止日期": st.column_config.DateColumn(
                    "合同截止日期", format="YYYY-MM-DD"
                ),
                "合同生效月份": st.column_config.SelectboxColumn(
                    "合同生效月份",
                    options=_effective_month_options(),
                    help="更正时表示修正后的开始月份；变更时表示新合同生效月份。",
                ),
                "合同修改说明": st.column_config.TextColumn(
                    "合同修改说明", help="建议填写填错原因或真实变更依据。"
                ),
                "YouTube UID": st.column_config.TextColumn("YouTube UID"),
                "YouTube主页": st.column_config.TextColumn("YouTube主页"),
                "YouTube粉丝数": st.column_config.NumberColumn(
                    "YouTube粉丝数", min_value=0, step=1
                ),
                "TikTok UID": st.column_config.TextColumn("TikTok UID"),
                "TikTok主页": st.column_config.TextColumn("TikTok主页"),
                "TikTok粉丝数": st.column_config.NumberColumn(
                    "TikTok粉丝数", min_value=0, step=1
                ),
                "粉丝数可结算": st.column_config.CheckboxColumn("粉丝数可结算"),
                "启用": st.column_config.CheckboxColumn("启用"),
                "备注": st.column_config.TextColumn("备注", width="medium"),
            },
        )
        submitted = st.form_submit_button(
            "保存表格修改",
            type="primary",
        )
    st.caption(f"当前显示：{len(table):,} / {len(all_records):,} 位达人")
    pending_key = "koc_pending_contract_editor_changes"
    pending_impact_key = "koc_pending_contract_editor_impacts"
    save_data: pd.DataFrame | None = None
    if submitted:
        impacts = _contract_editor_impact_table(filtered, edited)
        if impacts.empty:
            save_data = edited
        else:
            st.session_state[pending_key] = edited.copy()
            st.session_state[pending_impact_key] = impacts.copy()

    pending_data = st.session_state.get(pending_key)
    pending_impacts = st.session_state.get(pending_impact_key)
    if isinstance(pending_data, pd.DataFrame) and isinstance(
        pending_impacts, pd.DataFrame
    ):
        st.warning("请确认以下合同修改的影响范围。确认后才会写入达人库。")
        st.dataframe(pending_impacts, hide_index=True, width="stretch")
        confirm_column, cancel_column, _ = st.columns([1, 1, 4])
        if confirm_column.button(
            "确认合同修改",
            type="primary",
            key="koc_confirm_contract_editor_changes",
        ):
            save_data = pending_data.copy()
            st.session_state.pop(pending_key, None)
            st.session_state.pop(pending_impact_key, None)
        if cancel_column.button(
            "取消",
            key="koc_cancel_contract_editor_changes",
        ):
            st.session_state.pop(pending_key, None)
            st.session_state.pop(pending_impact_key, None)
            st.rerun()

    if save_data is not None:
        updated_count, errors = _save_creator_editor_changes(
            service,
            all_records,
            save_data,
        )
        if updated_count:
            _reset_linked_page_state(st.session_state)
        if errors:
            if updated_count:
                st.warning(f"已保存 {updated_count} 位达人；其余记录需要修正。")
            for message in errors:
                st.error(message)
        elif updated_count:
            st.session_state["koc_flash"] = (
                f"已保存 {updated_count} 位达人；看板和实时报酬已按合同周期重新读取。"
            )
            st.rerun()
        else:
            st.info("没有检测到需要保存的修改。")

    if st.toggle("显示合同周期", value=False, key="koc_show_contract_periods"):
        st.caption("此处用于纠正已有合同周期；不会被解释为新合同变更。")
        _render_contract_period_editor(service, filtered)
    if st.toggle("显示合同修改记录", value=False, key="koc_show_contract_revisions"):
        _render_contract_revision_history(service, filtered)


def render(settings: Settings) -> None:
    st.title("达人库管理")
    st.caption("维护合作类别、合同、主页和粉丝数；停用记录仍保留。")
    repository = KOCRepository(settings.database_path)
    service = KOCService(repository)
    follower_service = FollowerService(
        repository,
        youtube_api_key=settings.youtube_api_key,
        tiktok_browser_data_dir=settings.tiktok_browser_data_dir,
        tiktok_persistent_headless=settings.tiktok_persistent_headless,
    )
    _show_flash()

    all_records = repository.list(include_inactive=True)
    contract_options = repository.list_contract_type_options()
    _render_creator_editor_v2(
        repository,
        service,
        settings,
        all_records,
        contract_options,
    )

    _add_creator(service, contract_options)
    _batch_import(service)
    _manual_follower_update(service, all_records)

    _follower_controls(settings, follower_service)

    backup = export_koc_master(repository.to_dataframe(include_inactive=True))
    st.download_button(
        "导出达人库备份",
        data=backup,
        file_name=build_koc_master_filename(datetime.now()),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
