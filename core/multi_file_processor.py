from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from core.file_processor import ExcelFileReadError, UploadedExcel, read_excel_file
from core.koc_mapper import KOCMapper
from core.pipeline import DataPipeline
from core.transformer import DataTransformError, OUTPUT_COLUMNS
from core.user_id import normalize_user_id
from core.validator import blank_mask


FILE_REPORT_COLUMNS = [
    "source_file",
    "original_rows",
    "processed_rows",
    "unmatched_uid",
    "duplicate_url",
    "status",
    "error_message",
]

EXCEPTION_COLUMNS = [
    "issue_type",
    "source_file",
    "userId",
    "koc_name",
    "publish_date",
    "title",
    "url",
    "detail",
]


@dataclass(frozen=True)
class OverallReport:
    uploaded_files: int
    successful_files: int
    failed_files: int
    original_rows: int
    merged_rows: int
    koc_count: int
    earliest_date: date | None
    latest_date: date | None
    unmatched_uid_count: int
    duplicate_url_count: int
    missing_url_count: int
    missing_title_count: int
    invalid_timestamp_count: int
    blank_subtype_to_shorts_count: int
    removed_duplicate_count: int


@dataclass(frozen=True)
class MultiFileResult:
    data: pd.DataFrame
    file_reports: pd.DataFrame
    exceptions: pd.DataFrame
    unmatched_uids: pd.DataFrame
    overall: OverallReport


class MultiFileProcessor:
    def __init__(self, database_path: Path | str, timezone: str) -> None:
        mapper = KOCMapper.from_database(database_path)
        self.pipeline = DataPipeline(mapper=mapper, timezone=timezone)

    @staticmethod
    def _issue_row(
        row: pd.Series,
        issue_type: str,
        detail: str,
    ) -> dict[str, Any]:
        return {
            "issue_type": issue_type,
            "source_file": row.get("_source_file"),
            "userId": row.get("_user_id"),
            "koc_name": row.get("koc_name"),
            "publish_date": row.get("publish_date"),
            "title": row.get("title"),
            "url": row.get("url"),
            "detail": detail,
        }

    @staticmethod
    def _duplicate_mask(internal: pd.DataFrame) -> pd.Series:
        if internal.empty:
            return pd.Series(False, index=internal.index, dtype=bool)

        url_blank = blank_mask(internal["url"])
        platform = internal["platform"].astype("string").str.strip().str.casefold()
        url = internal["url"].astype("string").str.strip()
        url_key = platform.fillna("") + "|" + url.fillna("")
        duplicate = (~url_blank) & url_key.duplicated(keep=False)

        name = internal["koc_name"].astype("string").str.strip().str.casefold()
        title = internal["title"].astype("string").str.strip().str.casefold()
        published = internal["publish_date"].astype("string")
        fallback_complete = (
            url_blank
            & name.notna()
            & name.ne("")
            & title.notna()
            & title.ne("")
            & internal["publish_date"].notna()
        )
        fallback_key = name.fillna("") + "|" + title.fillna("") + "|" + published
        duplicate |= fallback_complete & fallback_key.duplicated(keep=False)
        return duplicate.fillna(False)

    @staticmethod
    def _url_dedup_mask(internal: pd.DataFrame) -> pd.Series:
        if internal.empty:
            return pd.Series(False, index=internal.index, dtype=bool)
        url_blank = blank_mask(internal["url"])
        platform = internal["platform"].astype("string").str.strip().str.casefold()
        url = internal["url"].astype("string").str.strip()
        key = platform.fillna("") + "|" + url.fillna("")
        return (~url_blank) & key.duplicated(keep="first")

    def process(
        self,
        files: list[UploadedExcel],
        *,
        deduplicate_urls: bool = False,
    ) -> MultiFileResult:
        internal_frames: list[pd.DataFrame] = []
        file_report_rows: list[dict[str, Any]] = []
        issue_rows: list[dict[str, Any]] = []
        successful_raw_rows = 0
        blank_subtype_count = 0

        for uploaded in files:
            original_rows = 0
            try:
                raw = read_excel_file(uploaded)
                original_rows = len(raw)
                successful_raw_rows += original_rows
                transformed = self.pipeline.process(raw)
            except Exception as exc:
                message = (
                    str(exc)
                    if isinstance(exc, (ExcelFileReadError, DataTransformError))
                    else f"文件处理失败：{exc}"
                )
                file_report_rows.append(
                    {
                        "source_file": uploaded.name,
                        "original_rows": original_rows,
                        "processed_rows": 0,
                        "unmatched_uid": 0,
                        "duplicate_url": 0,
                        "status": "失败",
                        "error_message": message,
                    }
                )
                issue_rows.append(
                    {
                        "issue_type": "FILE_ERROR",
                        "source_file": uploaded.name,
                        "userId": None,
                        "koc_name": None,
                        "publish_date": None,
                        "title": None,
                        "url": None,
                        "detail": message,
                    }
                )
                continue

            internal = transformed.data.copy().reset_index(drop=True)
            internal["_source_file"] = uploaded.name
            internal["_source_row"] = range(2, len(internal) + 2)
            internal["_user_id"] = raw["userId"].map(normalize_user_id).reset_index(drop=True)
            internal["_raw_timestamp"] = raw["timestamp"].reset_index(drop=True)
            internal["_raw_subtype"] = raw["subtype"].reset_index(drop=True)
            internal_frames.append(internal)

            blank_subtype_count += transformed.report.blank_subtype_to_shorts_count
            unmatched_count = len(transformed.report.unmatched_uids)
            file_report_rows.append(
                {
                    "source_file": uploaded.name,
                    "original_rows": original_rows,
                    "processed_rows": len(internal),
                    "unmatched_uid": unmatched_count,
                    "duplicate_url": 0,
                    "status": "成功",
                    "error_message": "",
                }
            )

            for _, row in internal.iterrows():
                if row["_user_id"] is not None and pd.isna(row["koc_name"]):
                    issue_rows.append(
                        self._issue_row(row, "UNMATCHED_USER_ID", "UID 未在启用的达人库中找到")
                    )
                if bool(blank_mask(pd.Series([row["url"]])).iloc[0]):
                    issue_rows.append(self._issue_row(row, "MISSING_URL", "URL 为空"))
                if bool(blank_mask(pd.Series([row["title"]])).iloc[0]):
                    issue_rows.append(self._issue_row(row, "MISSING_TITLE", "title 为空"))
                if pd.isna(row["publish_date"]):
                    issue_rows.append(
                        self._issue_row(row, "INVALID_TIMESTAMP", "timestamp 无法转换为日期")
                    )

        if internal_frames:
            internal_all = pd.concat(internal_frames, ignore_index=True)
        else:
            internal_all = pd.DataFrame(columns=OUTPUT_COLUMNS + ["_source_file"])

        duplicate_mask = self._duplicate_mask(internal_all)
        for _, row in internal_all.loc[duplicate_mask].iterrows():
            detail = (
                "platform + url 重复"
                if not bool(blank_mask(pd.Series([row["url"]])).iloc[0])
                else "URL 为空，koc_name + title + publish_date 重复"
            )
            issue_rows.append(self._issue_row(row, "DUPLICATE_URL", detail))

        duplicate_by_file = (
            internal_all.loc[duplicate_mask, "_source_file"].value_counts().to_dict()
            if not internal_all.empty
            else {}
        )
        for report_row in file_report_rows:
            report_row["duplicate_url"] = int(
                duplicate_by_file.get(report_row["source_file"], 0)
            )

        removed_duplicate_count = 0
        exported_internal = internal_all
        if deduplicate_urls and not internal_all.empty:
            remove_mask = self._url_dedup_mask(internal_all)
            removed_duplicate_count = int(remove_mask.sum())
            exported_internal = internal_all.loc[~remove_mask].copy()

        data = exported_internal.reindex(columns=OUTPUT_COLUMNS).reset_index(drop=True)
        exceptions = pd.DataFrame(issue_rows, columns=EXCEPTION_COLUMNS)
        file_reports = pd.DataFrame(file_report_rows, columns=FILE_REPORT_COLUMNS)

        if internal_all.empty:
            unmatched = pd.DataFrame(columns=["userId", "出现次数", "来源文件"])
        else:
            unmatched_mask = internal_all["_user_id"].notna() & internal_all["koc_name"].isna()
            unmatched_source = internal_all.loc[unmatched_mask, ["_user_id", "_source_file"]]
            rows = []
            for uid, group in unmatched_source.groupby("_user_id", sort=True):
                rows.append(
                    {
                        "userId": str(uid),
                        "出现次数": len(group),
                        "来源文件": "、".join(dict.fromkeys(group["_source_file"].astype(str))),
                    }
                )
            unmatched = pd.DataFrame(rows, columns=["userId", "出现次数", "来源文件"])

        dates = pd.Series(data["publish_date"]).dropna()
        successful_files = int((file_reports["status"] == "成功").sum()) if not file_reports.empty else 0
        overall = OverallReport(
            uploaded_files=len(files),
            successful_files=successful_files,
            failed_files=len(files) - successful_files,
            original_rows=successful_raw_rows,
            merged_rows=len(data),
            koc_count=int(data["koc_name"].dropna().nunique()),
            earliest_date=dates.min() if not dates.empty else None,
            latest_date=dates.max() if not dates.empty else None,
            unmatched_uid_count=len(unmatched),
            duplicate_url_count=int(duplicate_mask.sum()),
            missing_url_count=int(blank_mask(internal_all["url"]).sum()) if not internal_all.empty else 0,
            missing_title_count=int(blank_mask(internal_all["title"]).sum()) if not internal_all.empty else 0,
            invalid_timestamp_count=int(internal_all["publish_date"].isna().sum()) if not internal_all.empty else 0,
            blank_subtype_to_shorts_count=blank_subtype_count,
            removed_duplicate_count=removed_duplicate_count,
        )
        return MultiFileResult(
            data=data,
            file_reports=file_reports,
            exceptions=exceptions,
            unmatched_uids=unmatched,
            overall=overall,
        )
