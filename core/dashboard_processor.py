from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from core.file_processor import ExcelFileReadError, UploadedExcel, read_excel_file
from core.koc_mapper import KOCMapper
from core.pipeline import DataPipeline
from core.transformer import DataTransformError
from core.user_id import normalize_user_id
from database.koc_repository import KOCRepository
from models.enums import CREATOR_CATEGORY_LABELS
from models.koc import CreatorProfileSnapshot, KOCRecord


DASHBOARD_DETAIL_COLUMNS = [
    "source_file",
    "user_id",
    "creator_key",
    "creator_id",
    "creator_active",
    "profile_effective_date",
    "profile_status",
    "matched",
    "koc_name",
    "creator_label",
    "kol_name",
    "creator_category",
    "contract_types",
    "contract_start_date",
    "contract_end_date",
    "follower_count",
    "homepage_url",
    "youtube_user_id",
    "youtube_homepage_url",
    "youtube_follower_count",
    "tiktok_user_id",
    "tiktok_homepage_url",
    "tiktok_follower_count",
    "source_platform",
    "content_type",
    "subtype",
    "description",
    "timestamp",
    "publish_date",
    "title",
    "url",
    "view",
    "views",
    "likes",
    "comment",
    "reposted",
    "collect",
    "cross_industry_url_key",
    "is_cross_industry",
    "compensation_eligible",
    "cross_industry_reason",
    "cross_industry_exclusion_id",
]

PROFILE_STATUS_MATCHED = "MATCHED"
PROFILE_STATUS_UNMATCHED = "UNMATCHED"
PROFILE_STATUS_HISTORY_MISSING = "HISTORY_MISSING"

DASHBOARD_FILE_REPORT_COLUMNS = [
    "source_file",
    "original_rows",
    "processed_rows",
    "matched_posts",
    "unmatched_posts",
    "status",
    "error_message",
]

DASHBOARD_UNMATCHED_COLUMNS = [
    "user_id",
    "post_count",
    "source_files",
    "earliest_date",
    "latest_date",
]

CREATOR_SUMMARY_COLUMNS = [
    "creator_key",
    "user_id",
    "creator_label",
    "creator_category",
    "contract_types",
    "follower_count",
    "source_files",
    "source_platforms",
    "post_count",
    "total_views",
    "average_views",
    "max_views",
    "total_likes",
    "total_comments",
    "total_reposts",
    "total_collects",
    "total_interactions",
    "engagement_rate",
    "earliest_date",
    "latest_date",
]


@dataclass(frozen=True)
class DashboardResult:
    data: pd.DataFrame
    file_reports: pd.DataFrame
    unmatched_uids: pd.DataFrame


def _text_values(values: Iterable[object]) -> str:
    ordered: list[str] = []
    for value in values:
        if value is None or pd.isna(value):
            continue
        text = str(value).strip()
        if text and text not in ordered:
            ordered.append(text)
    return "、".join(ordered)


def _content_type_series(raw_data: pd.DataFrame) -> pd.Series:
    if "subtype" in raw_data:
        source = raw_data["subtype"].reset_index(drop=True).astype("string").str.strip()
    else:
        source = pd.Series(pd.NA, index=range(len(raw_data)), dtype="string")
    subtype = source.str.casefold()
    platform = _source_platform_series(raw_data).astype("string").str.casefold()

    result = source.mask(source.isna() | source.eq(""), "未标注")
    tiktok = platform.eq("tiktok")
    result.loc[tiktok] = "tiktok"

    youtube_or_unknown = ~tiktok
    shorts = subtype.isin(["short", "", "nan"]) | subtype.isna()
    result.loc[youtube_or_unknown & shorts] = "YTB shorts"
    result.loc[youtube_or_unknown & subtype.eq("long")] = "long"
    result.loc[youtube_or_unknown & subtype.eq("livestream")] = "livestream"
    return result


def _dashboard_text_series(data: pd.DataFrame, column: str) -> pd.Series:
    """Return a trimmed text column while keeping the original row order."""
    if column not in data:
        return pd.Series(pd.NA, index=data.index, dtype="string")
    return data[column].astype("string").str.strip()


def normalize_dashboard_content_types(data: pd.DataFrame) -> pd.DataFrame:
    """Apply the dashboard content-type labels to new and legacy post data.

    Earlier saved records used Chinese ``content_type`` values and a mix of
    subtype spellings.  Recomputing from both fields lets those records render
    with the current labels without asking the user to import them again.
    """
    if data.empty:
        return data.copy()

    normalized = data.copy()
    raw_subtype = _dashboard_text_series(normalized, "subtype")
    legacy_content_type = _dashboard_text_series(normalized, "content_type")
    platform = _dashboard_text_series(normalized, "source_platform").str.casefold()

    aliases = {
        "short": "short",
        "shorts": "short",
        "short video": "short",
        "short-video": "short",
        "shortform": "short",
        "短视频": "short",
        "ytb shorts": "short",
        "tiktok": "short",
        "long": "long",
        "long video": "long",
        "long-form": "long",
        "长视频": "long",
        "livestream": "livestream",
        "live stream": "livestream",
        "live": "livestream",
        "直播": "livestream",
    }
    subtype_kind = raw_subtype.str.casefold().map(aliases)
    legacy_kind = legacy_content_type.str.casefold().map(aliases)
    kind = subtype_kind.fillna(legacy_kind)

    raw_kind = raw_subtype.str.casefold()
    tiktok = platform.str.contains("tiktok", regex=False, na=False) | raw_kind.eq(
        "tiktok"
    )
    youtube = platform.str.contains("youtube", regex=False, na=False) | platform.eq(
        "ytb"
    ) | raw_kind.eq("ytb shorts")

    result = raw_subtype.mask(raw_subtype.isna() | raw_subtype.eq(""), legacy_content_type)
    result = result.mask(result.isna() | result.eq(""), "未标注")
    result.loc[kind.eq("long")] = "long"
    result.loc[kind.eq("livestream")] = "livestream"
    result.loc[kind.eq("short")] = "shorts"
    result.loc[kind.eq("short") & youtube] = "YTB shorts"
    result.loc[kind.eq("short") & tiktok] = "tiktok"

    normalized["content_type"] = result
    normalized["subtype"] = result
    return normalized


def _source_platform_series(raw_data: pd.DataFrame) -> pd.Series:
    if "platform" not in raw_data:
        return pd.Series("未标注", index=range(len(raw_data)), dtype="string")
    source = raw_data["platform"].reset_index(drop=True).astype("string").str.strip()
    return source.mask(source.isna() | source.eq(""), "未标注")


def _optional_series(raw_data: pd.DataFrame, column: str) -> pd.Series:
    if column in raw_data:
        return raw_data[column].reset_index(drop=True)
    return pd.Series(pd.NA, index=range(len(raw_data)), dtype="object")


def _kol_name_series(
    raw_data: pd.DataFrame,
    fallback: pd.Series,
) -> pd.Series:
    normalized_columns = {
        str(column).strip().casefold(): column for column in raw_data.columns
    }
    for candidate in ("kol name", "kol_name", "kolname"):
        column = normalized_columns.get(candidate)
        if column is None:
            continue
        values = raw_data[column].reset_index(drop=True).astype("string").str.strip()
        return values.mask(values.isna() | values.eq(""), fallback)
    return fallback


def _creator_metadata(record: KOCRecord | CreatorProfileSnapshot | None) -> dict[str, object]:
    if record is None:
        return {
            "creator_id": pd.NA,
            "creator_active": False,
            "profile_effective_date": pd.NA,
            "profile_status": PROFILE_STATUS_UNMATCHED,
            "creator_category": "未匹配",
            "contract_types": "未匹配",
            "contract_start_date": pd.NA,
            "contract_end_date": pd.NA,
            "follower_count": pd.NA,
            "homepage_url": pd.NA,
            "youtube_user_id": pd.NA,
            "youtube_homepage_url": pd.NA,
            "youtube_follower_count": pd.NA,
            "tiktok_user_id": pd.NA,
            "tiktok_homepage_url": pd.NA,
            "tiktok_follower_count": pd.NA,
        }

    categories = "、".join(
        CREATOR_CATEGORY_LABELS[category]
        for category in record.creator_categories
    )
    return {
        "creator_id": record.id if isinstance(record, KOCRecord) else record.creator_id,
        "creator_active": record.active,
        "profile_effective_date": (
            pd.NA
            if isinstance(record, KOCRecord)
            else record.effective_date.isoformat()
        ),
        "profile_status": PROFILE_STATUS_MATCHED,
        "creator_category": categories or "未分类",
        "contract_types": "、".join(record.contract_types) or "未设置",
        "contract_start_date": (
            record.contract_start_date.isoformat()
            if record.contract_start_date
            else pd.NA
        ),
        "contract_end_date": (
            record.contract_end_date.isoformat()
            if record.contract_end_date
            else pd.NA
        ),
        "follower_count": record.follower_count,
        "homepage_url": record.homepage_url,
        "youtube_user_id": record.youtube_user_id,
        "youtube_homepage_url": record.youtube_homepage_url,
        "youtube_follower_count": record.youtube_follower_count,
        "tiktok_user_id": record.tiktok_user_id,
        "tiktok_homepage_url": record.tiktok_homepage_url,
        "tiktok_follower_count": record.tiktok_follower_count,
    }


def _creator_user_ids(
    record: KOCRecord | CreatorProfileSnapshot,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            value
            for value in (
                normalize_user_id(record.user_id),
                normalize_user_id(record.youtube_user_id),
                normalize_user_id(record.tiktok_user_id),
            )
            if value is not None
        )
    )


class DashboardProcessor:
    """Process Rapid Query files while retaining fields needed by the dashboard."""

    def __init__(self, database_path: Path | str, timezone: str) -> None:
        repository = KOCRepository(database_path)
        records = repository.list(include_inactive=True)
        self._records_by_id = {record.id: record for record in records}
        self._creator_id_by_user_id: dict[str, int] = {}
        for record in records:
            for user_id in _creator_user_ids(record):
                self._creator_id_by_user_id.setdefault(user_id, record.id)
        self._history_by_creator_id: dict[int, list[CreatorProfileSnapshot]] = {}
        for snapshot in repository.list_profile_history():
            self._history_by_creator_id.setdefault(snapshot.creator_id, []).append(
                snapshot
            )
            for user_id in _creator_user_ids(snapshot):
                self._creator_id_by_user_id.setdefault(user_id, snapshot.creator_id)
        for snapshots in self._history_by_creator_id.values():
            snapshots.sort(key=lambda item: item.effective_date)
        self._pipeline = DataPipeline(
            mapper=KOCMapper.from_database(database_path),
            timezone=timezone,
        )

    def _profile_for_post(
        self,
        user_id: str,
        publish_date: date | None,
    ) -> tuple[KOCRecord | CreatorProfileSnapshot | None, str]:
        creator_id = self._creator_id_by_user_id.get(user_id)
        current = self._records_by_id.get(creator_id) if creator_id is not None else None
        history = self._history_by_creator_id.get(creator_id, ())
        if history:
            if publish_date is not None:
                candidates = [
                    snapshot
                    for snapshot in history
                    if snapshot.effective_date <= publish_date
                ]
                if candidates:
                    return candidates[-1], PROFILE_STATUS_MATCHED
            # Do not apply a newer master profile to posts that predate the
            # first known profile version. That silently changes history.
            return (
                current,
                PROFILE_STATUS_HISTORY_MISSING,
            )
        return (
            current,
            PROFILE_STATUS_MATCHED if current is not None else PROFILE_STATUS_UNMATCHED,
        )

    def _build_detail_frame(
        self,
        raw_data: pd.DataFrame,
        source_file: str,
    ) -> pd.DataFrame:
        transformed = self._pipeline.process(raw_data).data.reset_index(drop=True)
        user_ids = raw_data["userId"].map(normalize_user_id).reset_index(drop=True)
        user_ids = user_ids.astype("string")
        transformed_dates = pd.to_datetime(
            transformed["publish_date"], errors="coerce"
        )
        profile_matches = [
            self._profile_for_post(
                str(user_id),
                publish_date.to_pydatetime().date()
                if pd.notna(publish_date)
                else None,
            )
            if pd.notna(user_id)
            else (None, PROFILE_STATUS_UNMATCHED)
            for user_id, publish_date in zip(user_ids, transformed_dates)
        ]
        records = [match[0] for match in profile_matches]
        profile_status = pd.Series(
            [match[1] for match in profile_matches],
            index=transformed.index,
            dtype="string",
        )
        matched = pd.Series(
            [record is not None for record in records], index=transformed.index
        )
        mapped_names = pd.Series(
            [
                record.koc_name if record is not None else pd.NA
                for record in records
            ],
            index=transformed.index,
            dtype="string",
        )
        metadata = pd.DataFrame(
            [
                _creator_metadata(record if is_matched else None)
                for record, is_matched in zip(records, matched)
            ]
        )
        missing_history = profile_status.eq(PROFILE_STATUS_HISTORY_MISSING)
        if missing_history.any():
            metadata.loc[missing_history, "profile_effective_date"] = pd.NA
            metadata.loc[missing_history, "profile_status"] = (
                PROFILE_STATUS_HISTORY_MISSING
            )
            for column in (
                "contract_types",
                "contract_start_date",
                "contract_end_date",
                "follower_count",
                "youtube_follower_count",
                "tiktok_follower_count",
            ):
                metadata.loc[missing_history, column] = pd.NA
        unmatched_labels = user_ids.fillna("未提供 UID").map(
            lambda value: f"未匹配 UID：{value}"
        )
        creator_labels = mapped_names.where(matched, unmatched_labels)
        creator_keys = pd.Series(
            [
                record.user_id if record is not None else user_id
                for record, user_id in zip(records, user_ids)
            ],
            index=transformed.index,
            dtype="string",
        ).fillna("未提供 UID")
        content_type = _content_type_series(raw_data)

        detail = pd.DataFrame(
            {
                "source_file": source_file,
                "user_id": user_ids,
                "creator_key": creator_keys,
                "creator_id": metadata["creator_id"],
                "creator_active": metadata["creator_active"],
                "profile_effective_date": metadata["profile_effective_date"],
                "profile_status": profile_status,
                "matched": matched,
                "koc_name": mapped_names,
                "creator_label": creator_labels,
                "kol_name": _kol_name_series(raw_data, creator_labels),
                "creator_category": metadata["creator_category"],
                "contract_types": metadata["contract_types"],
                "contract_start_date": metadata["contract_start_date"],
                "contract_end_date": metadata["contract_end_date"],
                "follower_count": metadata["follower_count"],
                "homepage_url": metadata["homepage_url"],
                "youtube_user_id": metadata["youtube_user_id"],
                "youtube_homepage_url": metadata["youtube_homepage_url"],
                "youtube_follower_count": metadata["youtube_follower_count"],
                "tiktok_user_id": metadata["tiktok_user_id"],
                "tiktok_homepage_url": metadata["tiktok_homepage_url"],
                "tiktok_follower_count": metadata["tiktok_follower_count"],
                "source_platform": _source_platform_series(raw_data),
                "content_type": content_type,
                "subtype": content_type,
                "description": _optional_series(raw_data, "description"),
                "timestamp": _optional_series(raw_data, "timestamp"),
                "publish_date": transformed["publish_date"],
                "title": transformed["title"],
                "url": transformed["url"],
                "view": transformed["views"],
                "views": transformed["views"],
                "likes": transformed["likes"],
                "comment": transformed["comment"],
                "reposted": transformed["reposted"],
                "collect": pd.to_numeric(
                    _optional_series(raw_data, "collect"),
                    errors="coerce",
                ),
            }
        )
        return normalize_dashboard_content_types(detail).reindex(
            columns=DASHBOARD_DETAIL_COLUMNS
        )

    def process(self, files: list[UploadedExcel]) -> DashboardResult:
        detail_frames: list[pd.DataFrame] = []
        report_rows: list[dict[str, object]] = []

        for uploaded in files:
            original_rows = 0
            try:
                raw_data = read_excel_file(uploaded)
                original_rows = len(raw_data)
                detail = self._build_detail_frame(raw_data, uploaded.name)
            except (ExcelFileReadError, DataTransformError) as exc:
                report_rows.append(
                    {
                        "source_file": uploaded.name,
                        "original_rows": original_rows,
                        "processed_rows": 0,
                        "matched_posts": 0,
                        "unmatched_posts": 0,
                        "status": "失败",
                        "error_message": str(exc),
                    }
                )
                continue
            except Exception as exc:
                report_rows.append(
                    {
                        "source_file": uploaded.name,
                        "original_rows": original_rows,
                        "processed_rows": 0,
                        "matched_posts": 0,
                        "unmatched_posts": 0,
                        "status": "失败",
                        "error_message": f"文件处理失败：{exc}",
                    }
                )
                continue

            detail_frames.append(detail)
            report_rows.append(
                {
                    "source_file": uploaded.name,
                    "original_rows": original_rows,
                    "processed_rows": len(detail),
                    "matched_posts": int(detail["matched"].sum()),
                    "unmatched_posts": int((~detail["matched"]).sum()),
                    "status": "成功",
                    "error_message": "",
                }
            )

        data = (
            pd.concat(detail_frames, ignore_index=True)
            if detail_frames
            else pd.DataFrame(columns=DASHBOARD_DETAIL_COLUMNS)
        )
        file_reports = pd.DataFrame(
            report_rows,
            columns=DASHBOARD_FILE_REPORT_COLUMNS,
        )
        return build_dashboard_result(data, file_reports)


def build_unmatched_summary(data: pd.DataFrame) -> pd.DataFrame:
    unmatched = data.loc[~data["matched"]].copy()
    if unmatched.empty:
        return pd.DataFrame(columns=DASHBOARD_UNMATCHED_COLUMNS)

    rows: list[dict[str, object]] = []
    for creator_key, group in unmatched.groupby("creator_key", sort=True):
        user_ids = group["user_id"].dropna()
        rows.append(
            {
                "user_id": (
                    str(user_ids.iloc[0]) if not user_ids.empty else str(creator_key)
                ),
                "post_count": len(group),
                "source_files": _text_values(group["source_file"]),
                "earliest_date": group["publish_date"].min(),
                "latest_date": group["publish_date"].max(),
            }
        )
    return pd.DataFrame(rows, columns=DASHBOARD_UNMATCHED_COLUMNS)


def build_dashboard_result(
    data: pd.DataFrame,
    file_reports: pd.DataFrame | None = None,
) -> DashboardResult:
    normalized = data.reindex(columns=DASHBOARD_DETAIL_COLUMNS).copy()
    normalized = normalize_dashboard_content_types(normalized)
    if not normalized.empty:
        normalized["publish_date"] = pd.to_datetime(
            normalized["publish_date"],
            errors="coerce",
        ).dt.date
        normalized["matched"] = (
            normalized["matched"].astype("boolean").fillna(False).astype(bool)
        )
        normalized["is_cross_industry"] = (
            normalized["is_cross_industry"]
            .astype("boolean")
            .fillna(False)
            .astype(bool)
        )
        normalized["compensation_eligible"] = (
            normalized["compensation_eligible"]
            .astype("boolean")
            .fillna(True)
            .astype(bool)
        )
    reports = (
        file_reports.reindex(columns=DASHBOARD_FILE_REPORT_COLUMNS)
        if file_reports is not None
        else pd.DataFrame(columns=DASHBOARD_FILE_REPORT_COLUMNS)
    )
    return DashboardResult(
        data=normalized,
        file_reports=reports,
        unmatched_uids=build_unmatched_summary(normalized),
    )


def enrich_dashboard_creator_metadata(
    data: pd.DataFrame,
    creator_records: Iterable[KOCRecord],
    profile_history: Iterable[CreatorProfileSnapshot] = (),
) -> pd.DataFrame:
    """Refresh each post from the creator profile effective on its publish date."""
    enriched = data.copy()
    if "kol_name" not in enriched:
        enriched["kol_name"] = pd.NA
    if "profile_status" not in enriched:
        enriched["profile_status"] = pd.NA
    for column in (
        "youtube_user_id",
        "youtube_homepage_url",
        "youtube_follower_count",
        "tiktok_user_id",
        "tiktok_homepage_url",
        "tiktok_follower_count",
    ):
        if column not in enriched:
            enriched[column] = pd.Series(pd.NA, index=enriched.index, dtype="object")
        else:
            enriched[column] = enriched[column].astype("object")
    for column in (
        "creator_active",
        "profile_effective_date",
        "profile_status",
        "contract_start_date",
        "contract_end_date",
    ):
        if column in enriched:
            enriched[column] = enriched[column].astype("object")
    records_by_id = {record.id: record for record in creator_records}
    creator_id_by_user_id: dict[str, int] = {}
    for record in creator_records:
        for alias in _creator_user_ids(record):
            creator_id_by_user_id.setdefault(alias, record.id)
    history_by_creator_id: dict[int, list[CreatorProfileSnapshot]] = {}
    for snapshot in profile_history:
        history_by_creator_id.setdefault(snapshot.creator_id, []).append(snapshot)
        for alias in _creator_user_ids(snapshot):
            creator_id_by_user_id.setdefault(alias, snapshot.creator_id)
    for snapshots in history_by_creator_id.values():
        snapshots.sort(key=lambda item: item.effective_date)

    if enriched.empty or (not creator_id_by_user_id and not history_by_creator_id):
        return enriched

    for index, raw_user_id in enriched["user_id"].items():
        user_id = normalize_user_id(raw_user_id)
        if user_id is None:
            continue
        post_date = pd.to_datetime(
            enriched.at[index, "publish_date"], errors="coerce"
        )
        creator_id = creator_id_by_user_id.get(user_id)
        current = records_by_id.get(creator_id) if creator_id is not None else None
        history = history_by_creator_id.get(creator_id, ())
        effective_record: KOCRecord | CreatorProfileSnapshot | None = None
        if not pd.isna(post_date):
            candidates = [
                snapshot
                for snapshot in history
                if snapshot.effective_date <= post_date.date()
            ]
            if candidates:
                effective_record = candidates[-1]
        if history and effective_record is None:
            # History exists, but no version covers this post date. Preserve
            # its identity for repair while refusing to use today's contract.
            if current is None:
                enriched.at[index, "profile_status"] = PROFILE_STATUS_HISTORY_MISSING
                enriched.at[index, "matched"] = False
                continue
            metadata = _creator_metadata(current)
            source_platform_value = (
                enriched.at[index, "source_platform"]
                if "source_platform" in enriched
                else ""
            )
            source_platform = (
                "" if pd.isna(source_platform_value) else str(source_platform_value)
            )
            enriched.at[index, "user_id"] = current.user_id_for_platform(
                source_platform
            )
            enriched.at[index, "koc_name"] = current.koc_name
            enriched.at[index, "creator_label"] = current.koc_name
            enriched.at[index, "creator_category"] = metadata["creator_category"]
            enriched.at[index, "contract_types"] = pd.NA
            enriched.at[index, "contract_start_date"] = pd.NA
            enriched.at[index, "contract_end_date"] = pd.NA
            enriched.at[index, "follower_count"] = pd.NA
            enriched.at[index, "homepage_url"] = metadata["homepage_url"]
            enriched.at[index, "youtube_user_id"] = metadata["youtube_user_id"]
            enriched.at[index, "youtube_homepage_url"] = metadata[
                "youtube_homepage_url"
            ]
            enriched.at[index, "youtube_follower_count"] = pd.NA
            enriched.at[index, "tiktok_user_id"] = metadata["tiktok_user_id"]
            enriched.at[index, "tiktok_homepage_url"] = metadata[
                "tiktok_homepage_url"
            ]
            enriched.at[index, "tiktok_follower_count"] = pd.NA
            enriched.at[index, "creator_key"] = current.user_id
            enriched.at[index, "creator_id"] = current.id
            enriched.at[index, "creator_active"] = current.active
            enriched.at[index, "profile_effective_date"] = pd.NA
            enriched.at[index, "profile_status"] = PROFILE_STATUS_HISTORY_MISSING
            enriched.at[index, "matched"] = True
            raw_kol_name = enriched.at[index, "kol_name"]
            if raw_kol_name is None or pd.isna(raw_kol_name) or not str(
                raw_kol_name
            ).strip():
                enriched.at[index, "kol_name"] = current.koc_name
            continue

        record = effective_record or current
        if record is None:
            continue
        metadata = _creator_metadata(record)
        # Follower refreshes create profile-only snapshots. When a contract is
        # later backdated, those snapshots can still carry the old contract.
        # The current master contract is authoritative from its saved start
        # date, while the snapshot continues to provide the historical name,
        # UID, and follower fields.
        if (
            current is not None
            and current.contract_start_date is not None
            and post_date.date() >= current.contract_start_date
            and record.contract_start_date is not None
            and record.contract_start_date < current.contract_start_date
        ):
            current_contract_metadata = _creator_metadata(current)
            metadata["creator_category"] = current_contract_metadata[
                "creator_category"
            ]
            metadata["contract_types"] = current_contract_metadata[
                "contract_types"
            ]
            metadata["contract_start_date"] = current_contract_metadata[
                "contract_start_date"
            ]
            metadata["contract_end_date"] = current_contract_metadata[
                "contract_end_date"
            ]
        record_id = record.id if isinstance(record, KOCRecord) else record.creator_id
        source_platform_value = (
            enriched.at[index, "source_platform"]
            if "source_platform" in enriched
            else ""
        )
        source_platform = (
            "" if pd.isna(source_platform_value) else str(source_platform_value)
        )
        enriched.at[index, "user_id"] = record.user_id_for_platform(
            source_platform
        )
        enriched.at[index, "koc_name"] = record.koc_name
        enriched.at[index, "creator_label"] = record.koc_name
        enriched.at[index, "creator_category"] = metadata["creator_category"]
        enriched.at[index, "contract_types"] = metadata["contract_types"]
        enriched.at[index, "contract_start_date"] = metadata["contract_start_date"]
        enriched.at[index, "contract_end_date"] = metadata["contract_end_date"]
        enriched.at[index, "follower_count"] = metadata["follower_count"]
        enriched.at[index, "homepage_url"] = metadata["homepage_url"]
        enriched.at[index, "youtube_user_id"] = metadata["youtube_user_id"]
        enriched.at[index, "youtube_homepage_url"] = metadata[
            "youtube_homepage_url"
        ]
        enriched.at[index, "youtube_follower_count"] = metadata[
            "youtube_follower_count"
        ]
        enriched.at[index, "tiktok_user_id"] = metadata["tiktok_user_id"]
        enriched.at[index, "tiktok_homepage_url"] = metadata[
            "tiktok_homepage_url"
        ]
        enriched.at[index, "tiktok_follower_count"] = metadata[
            "tiktok_follower_count"
        ]
        enriched.at[index, "creator_key"] = record.user_id
        enriched.at[index, "creator_id"] = record_id
        enriched.at[index, "creator_active"] = metadata["creator_active"]
        enriched.at[index, "profile_effective_date"] = metadata[
            "profile_effective_date"
        ]
        enriched.at[index, "profile_status"] = PROFILE_STATUS_MATCHED
        enriched.at[index, "matched"] = True
        raw_kol_name = enriched.at[index, "kol_name"]
        kol_name = (
            ""
            if raw_kol_name is None or pd.isna(raw_kol_name)
            else str(raw_kol_name).strip()
        )
        if not kol_name or kol_name.startswith("未匹配 UID"):
            enriched.at[index, "kol_name"] = record.koc_name
    return enriched


def date_bounds(data: pd.DataFrame) -> tuple[date | None, date | None]:
    if data.empty or "publish_date" not in data:
        return None, None
    values = pd.to_datetime(data["publish_date"], errors="coerce").dropna()
    if values.empty:
        return None, None
    return values.min().date(), values.max().date()


def filter_dashboard_data(
    data: pd.DataFrame,
    *,
    creator_categories: Iterable[str] | None = None,
    source_platforms: Iterable[str] | None = None,
    content_types: Iterable[str] | None = None,
    creator_keys: Iterable[str] | None = None,
    creator_query: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    filtered = data.copy()

    def apply_values(column: str, values: Iterable[str] | None) -> None:
        nonlocal filtered
        if values is None:
            return
        selected = [values] if isinstance(values, str) else list(values)
        if selected:
            filtered = filtered.loc[filtered[column].isin(selected)]

    apply_values("creator_category", creator_categories)
    apply_values("source_platform", source_platforms)
    apply_values("content_type", content_types)
    apply_values("creator_key", creator_keys)

    query = (creator_query or "").strip().casefold()
    if query:
        search_columns = (
            "creator_label",
            "koc_name",
            "kol_name",
            "user_id",
        )
        matches = pd.Series(False, index=filtered.index)
        for column in search_columns:
            if column not in filtered:
                continue
            matches |= filtered[column].astype("string").str.casefold().str.contains(
                query,
                regex=False,
                na=False,
            )
        filtered = filtered.loc[matches]

    if start_date is not None or end_date is not None:
        dates = pd.to_datetime(filtered["publish_date"], errors="coerce").dt.date
        mask = dates.notna()
        if start_date is not None:
            mask &= dates >= start_date
        if end_date is not None:
            mask &= dates <= end_date
        filtered = filtered.loc[mask]
    return filtered.reset_index(drop=True)


def _numeric_values(data: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(data[column], errors="coerce")


def build_creator_summary(
    data: pd.DataFrame,
    creator_records: Iterable[KOCRecord] | None = None,
) -> pd.DataFrame:
    if data.empty:
        summary = pd.DataFrame(columns=CREATOR_SUMMARY_COLUMNS)
    else:
        prepared = data.copy()
        for column in ("views", "likes", "comment", "reposted", "collect"):
            prepared[f"_{column}"] = _numeric_values(prepared, column)
        prepared["_interactions"] = prepared[
            ["_likes", "_comment", "_reposted", "_collect"]
        ].fillna(0).sum(axis=1)

        group_columns = [
            "creator_key",
            "user_id",
            "creator_label",
            "creator_category",
            "contract_types",
            "follower_count",
        ]
        summary = (
            prepared.groupby(group_columns, dropna=False)
            .agg(
                source_files=("source_file", _text_values),
                source_platforms=("source_platform", _text_values),
                post_count=("creator_key", "size"),
                total_views=("_views", "sum"),
                average_views=("_views", "mean"),
                max_views=("_views", "max"),
                total_likes=("_likes", "sum"),
                total_comments=("_comment", "sum"),
                total_reposts=("_reposted", "sum"),
                total_collects=("_collect", "sum"),
                total_interactions=("_interactions", "sum"),
                earliest_date=("publish_date", "min"),
                latest_date=("publish_date", "max"),
            )
            .reset_index()
        )
        summary["engagement_rate"] = summary["total_interactions"].div(
            summary["total_views"].where(summary["total_views"] > 0)
        )

    if creator_records is not None:
        existing_keys = set(summary["creator_key"].astype(str))
        zero_rows: list[dict[str, object]] = []
        for record in creator_records:
            if record.user_id in existing_keys:
                continue
            metadata = _creator_metadata(record)
            zero_rows.append(
                {
                    "creator_key": record.user_id,
                    "user_id": record.user_id,
                    "creator_label": record.koc_name,
                    "creator_category": metadata["creator_category"],
                    "contract_types": metadata["contract_types"],
                    "follower_count": metadata["follower_count"],
                    "source_files": "",
                    "source_platforms": "",
                    "post_count": 0,
                    "total_views": 0,
                    "average_views": 0,
                    "max_views": 0,
                    "total_likes": 0,
                    "total_comments": 0,
                    "total_reposts": 0,
                    "total_collects": 0,
                    "total_interactions": 0,
                    "engagement_rate": 0.0,
                    "earliest_date": None,
                    "latest_date": None,
                }
            )
        if zero_rows:
            summary = pd.concat([summary, pd.DataFrame(zero_rows)], ignore_index=True)

    if summary.empty:
        return summary.reindex(columns=CREATOR_SUMMARY_COLUMNS)
    return summary.reindex(columns=CREATOR_SUMMARY_COLUMNS).sort_values(
        ["post_count", "total_views", "creator_label"],
        ascending=[False, False, True],
        kind="stable",
    ).reset_index(drop=True)


def build_daily_summary(data: pd.DataFrame) -> pd.DataFrame:
    columns = ["publish_date", "post_count", "total_views", "total_interactions"]
    if data.empty:
        return pd.DataFrame(columns=columns)

    prepared = data.copy()
    prepared["publish_date"] = pd.to_datetime(
        prepared["publish_date"], errors="coerce"
    ).dt.date
    prepared = prepared.loc[prepared["publish_date"].notna()].copy()
    if prepared.empty:
        return pd.DataFrame(columns=columns)

    prepared["_views"] = _numeric_values(prepared, "views")
    for column in ("likes", "comment", "reposted", "collect"):
        prepared[f"_{column}"] = _numeric_values(prepared, column)
    prepared["_interactions"] = prepared[
        ["_likes", "_comment", "_reposted", "_collect"]
    ].fillna(0).sum(axis=1)
    return (
        prepared.groupby("publish_date", as_index=False)
        .agg(
            post_count=("creator_key", "size"),
            total_views=("_views", "sum"),
            total_interactions=("_interactions", "sum"),
        )
        .sort_values("publish_date", kind="stable")
        .reset_index(drop=True)
    )


def build_dimension_summary(data: pd.DataFrame, dimension: str) -> pd.DataFrame:
    columns = [dimension, "post_count", "total_views", "total_interactions"]
    if data.empty:
        return pd.DataFrame(columns=columns)
    if dimension not in data:
        raise ValueError(f"看板数据不存在维度：{dimension}")

    prepared = data.copy()
    prepared["_views"] = _numeric_values(prepared, "views")
    for column in ("likes", "comment", "reposted", "collect"):
        prepared[f"_{column}"] = _numeric_values(prepared, column)
    prepared["_interactions"] = prepared[
        ["_likes", "_comment", "_reposted", "_collect"]
    ].fillna(0).sum(axis=1)
    return (
        prepared.groupby(dimension, as_index=False, dropna=False)
        .agg(
            post_count=("creator_key", "size"),
            total_views=("_views", "sum"),
            total_interactions=("_interactions", "sum"),
        )
        .sort_values(["post_count", dimension], ascending=[False, True], kind="stable")
        .reset_index(drop=True)
    )
