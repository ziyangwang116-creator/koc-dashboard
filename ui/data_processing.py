from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from pandas.api.types import is_scalar

from core.file_processor import UploadedExcel
from core.multi_file_processor import MultiFileProcessor, OverallReport
from core.transformer import TRANSFORM_RULE_VERSION
from exporters.excel_exporter import (
    build_multi_file_download_filename,
    export_multi_file_excel,
)


def _format_metric_value(value: Any) -> str | None:
    """Return only value types accepted by ``st.metric``."""
    if value is None:
        return None

    if is_scalar(value):
        try:
            if bool(pd.isna(value)):
                return None
        except (TypeError, ValueError):
            pass

    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _display_overall_metrics(report: OverallReport) -> None:
    rows = [
        ("上传文件数量", report.uploaded_files),
        ("成功处理文件", report.successful_files),
        ("失败文件", report.failed_files),
        ("原始总行数", report.original_rows),
        ("合并后总行数", report.merged_rows),
        ("不同达人数量", report.koc_count),
        ("最早日期", report.earliest_date),
        ("最晚日期", report.latest_date),
        ("未匹配 UID 数量", report.unmatched_uid_count),
        ("重复记录涉及行数", report.duplicate_url_count),
        ("缺失 URL", report.missing_url_count),
        ("缺失 title", report.missing_title_count),
        ("无法转换 timestamp", report.invalid_timestamp_count),
        ("空白 subtype → shorts", report.blank_subtype_to_shorts_count),
    ]

    for start in range(0, len(rows), 4):
        columns = st.columns(4)
        for column, (label, value) in zip(columns, rows[start : start + 4]):
            column.metric(label=label, value=_format_metric_value(value))


def render(database_path: Path, default_timezone: str) -> None:
    st.title("KOC 数据整理工具")
    st.caption("V1.7 · 单个或多个 Rapid Query Excel → 统一标准 Excel")

    with st.sidebar:
        st.subheader("处理设置")
        timezone = st.text_input(
            "时间戳时区",
            value=default_timezone,
            help="默认使用北京时间 Asia/Shanghai；也可填写其他 IANA 时区名称。",
            key="processing_timezone",
        )

    uploaded_files = st.file_uploader(
        "上传一个或多个 Rapid Query xlsx 文件",
        type=["xlsx"],
        accept_multiple_files=True,
        key="rapid_query_files",
    )
    deduplicate_urls = st.checkbox(
        "导出时去除完全重复的 URL",
        value=False,
        help="默认关闭。勾选后按 platform + url 保留第一次出现的记录；空 URL 不会因此被删除。",
    )
    if deduplicate_urls:
        st.info("当前去重策略：按 platform + url 去重，保留上传顺序中第一次出现的记录。")

    if not uploaded_files:
        st.info("请上传至少一个 .xlsx 文件；单个文件和多个文件使用同一处理流程。")
        return

    file_list = pd.DataFrame(
        [
            {
                "文件名": uploaded.name,
                "文件大小 (KB)": round(uploaded.size / 1024, 1),
                "状态": "等待处理",
            }
            for uploaded in uploaded_files
        ]
    )
    st.subheader("已上传文件")
    st.dataframe(file_list, hide_index=True, width="stretch")

    signature = (
        tuple((uploaded.name, uploaded.size) for uploaded in uploaded_files),
        timezone,
        deduplicate_urls,
        TRANSFORM_RULE_VERSION,
    )
    if st.session_state.get("processing_signature") != signature:
        st.session_state["processing_signature"] = signature
        for key in ("batch_result", "batch_excel", "batch_filename"):
            st.session_state.pop(key, None)

    if st.button("开始整理", type="primary", width="stretch"):
        files = [
            UploadedExcel(name=uploaded.name, content=uploaded.getvalue())
            for uploaded in uploaded_files
        ]
        with st.spinner("正在逐个读取、整理并合并文件……"):
            try:
                result = MultiFileProcessor(database_path, timezone).process(
                    files, deduplicate_urls=deduplicate_urls
                )
                excel_bytes = export_multi_file_excel(
                    result.data, result.file_reports, result.exceptions
                )
            except Exception as exc:
                st.error(f"整理任务无法完成：{exc}")
            else:
                st.session_state["batch_result"] = result
                st.session_state["batch_excel"] = excel_bytes
                st.session_state["batch_filename"] = build_multi_file_download_filename(
                    datetime.now()
                )

    result = st.session_state.get("batch_result")
    if result is None:
        return

    st.subheader("总体处理结果")
    _display_overall_metrics(result.overall)
    if result.overall.removed_duplicate_count:
        st.warning(
            f"已按用户选择从导出明细中移除 {result.overall.removed_duplicate_count} 条重复 URL；异常表仍保留重复记录信息。"
        )

    st.subheader("逐文件处理报告")
    st.dataframe(result.file_reports, hide_index=True, width="stretch")

    if not result.unmatched_uids.empty:
        st.warning("存在未匹配 UID；相关投稿已保留，koc_name 为空。可在达人库管理中补充后重新整理。")
        st.dataframe(result.unmatched_uids, hide_index=True, width="stretch")
        if st.button("前往达人库管理", key="go_to_koc_management"):
            st.session_state["active_page"] = "达人库管理"
            st.rerun()
    else:
        st.success("未匹配 UID：无")

    st.subheader("整理结果预览")
    st.dataframe(result.data.head(100), width="stretch")
    st.caption(f"当前导出 {len(result.data):,} 条数据，预览前 100 条。")

    st.subheader("异常数据预览")
    if result.exceptions.empty:
        st.success("未发现异常。")
    else:
        st.dataframe(result.exceptions.head(200), hide_index=True, width="stretch")

    st.download_button(
        "下载统一标准 Excel",
        data=st.session_state["batch_excel"],
        file_name=st.session_state["batch_filename"],
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        width="stretch",
    )
