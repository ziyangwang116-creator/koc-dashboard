from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from core.user_id import normalize_user_id


IMPORT_COLUMN_ALIASES = {
    "NAME": "koc_name",
    "UID": "user_id",
    "达人名称": "koc_name",
    "KOC_NAME": "koc_name",
    "USER_ID": "user_id",
    "CREATOR_CATEGORY": "creator_category",
    "CONTRACT_TYPE": "contract_type",
    "CONTRACT_START_DATE": "contract_start_date",
    "CONTRACT_END_DATE": "contract_end_date",
    "\u5408\u540c\u5f00\u59cb\u65e5\u671f": "contract_start_date",
    "\u5408\u540c\u622a\u6b62\u65e5\u671f": "contract_end_date",
    "类型": "contract_type",
    "HOMEPAGE_URL": "homepage_url",
    "主页链接": "homepage_url",
    "FOLLOWER_COUNT": "follower_count",
    "粉丝数": "follower_count",
    "YOUTUBE_USER_ID": "youtube_user_id",
    "YOUTUBE UID": "youtube_user_id",
    "YOUTUBE_UID": "youtube_user_id",
    "YTB UID": "youtube_user_id",
    "YOUTUBE_HOMEPAGE_URL": "youtube_homepage_url",
    "YOUTUBE主页": "youtube_homepage_url",
    "YOUTUBE_FOLLOWER_COUNT": "youtube_follower_count",
    "YOUTUBE粉丝数": "youtube_follower_count",
    "TIKTOK_USER_ID": "tiktok_user_id",
    "TIKTOK UID": "tiktok_user_id",
    "TIKTOK_UID": "tiktok_user_id",
    "TT UID": "tiktok_user_id",
    "TIKTOK_HOMEPAGE_URL": "tiktok_homepage_url",
    "TIKTOK主页": "tiktok_homepage_url",
    "TIKTOK_FOLLOWER_COUNT": "tiktok_follower_count",
    "TIKTOK粉丝数": "tiktok_follower_count",
    "ACTIVE": "active",
    "NOTE": "note",
}

KOC_IMPORT_COLUMNS = [
    "user_id",
    "koc_name",
    "creator_category",
    "contract_type",
    "contract_start_date",
    "contract_end_date",
    "homepage_url",
    "follower_count",
    "youtube_user_id",
    "youtube_homepage_url",
    "youtube_follower_count",
    "tiktok_user_id",
    "tiktok_homepage_url",
    "tiktok_follower_count",
    "active",
    "note",
]


class KOCImportFormatError(ValueError):
    pass


@dataclass(frozen=True)
class KOCImportPreview:
    total_records: int
    duplicate_uid_count: int
    duplicate_uid_rows: int
    empty_uid_count: int
    empty_name_count: int
    empty_contract_type_count: int
    duplicate_uid_details: pd.DataFrame
    contract_types: tuple[str, ...]


def normalize_import_columns(dataframe: pd.DataFrame) -> pd.DataFrame:
    mapped: dict[Any, str] = {}
    seen: set[str] = set()
    for column in dataframe.columns:
        normalized = str(column).strip().upper()
        canonical = IMPORT_COLUMN_ALIASES.get(normalized, str(column).strip())
        if canonical in seen:
            raise KOCImportFormatError(f"导入文件存在重复字段：{canonical}。")
        seen.add(canonical)
        mapped[column] = canonical
    return dataframe.rename(columns=mapped).copy()


def analyze_import_dataframe(dataframe: pd.DataFrame) -> KOCImportPreview:
    """Inspect every source row without deduplicating UID or contract records."""
    prepared = normalize_import_columns(dataframe)
    missing = [
        column for column in ("user_id", "koc_name")
        if column not in prepared.columns
    ]
    if missing:
        raise KOCImportFormatError(
            "达人库 Excel 缺少必要字段：" + "、".join(missing) + "。"
        )

    rows = prepared.loc[~prepared.isna().all(axis=1)].copy()
    if "contract_type" not in rows.columns:
        rows["contract_type"] = None

    rows["_normalized_uid"] = rows["user_id"].map(normalize_user_id)
    rows["_normalized_name"] = rows["koc_name"].map(
        lambda value: (
            None
            if value is None or pd.isna(value) or not str(value).strip()
            else str(value).strip()
        )
    )
    rows["_normalized_contract"] = rows["contract_type"].map(
        lambda value: (
            None
            if value is None or pd.isna(value) or not str(value).strip()
            else str(value).strip()
        )
    )

    duplicate_details: list[dict[str, Any]] = []
    valid_uid_rows = rows.loc[rows["_normalized_uid"].notna()]
    for uid, group in valid_uid_rows.groupby("_normalized_uid", sort=False):
        if len(group) < 2:
            continue
        contract_labels = [
            value if value is not None else "未设置合同类型"
            for value in group["_normalized_contract"].tolist()
        ]
        duplicate_details.append(
            {
                "user_id": uid,
                "record_count": len(group),
                "contract_types": "、".join(contract_labels),
            }
        )

    contract_types = tuple(
        dict.fromkeys(
            value
            for value in rows["_normalized_contract"].tolist()
            if value is not None
        )
    )
    duplicate_uid_rows = sum(
        int(detail["record_count"]) for detail in duplicate_details
    )
    return KOCImportPreview(
        total_records=len(rows),
        duplicate_uid_count=len(duplicate_details),
        duplicate_uid_rows=duplicate_uid_rows,
        empty_uid_count=int(rows["_normalized_uid"].isna().sum()),
        empty_name_count=int(rows["_normalized_name"].isna().sum()),
        empty_contract_type_count=int(rows["_normalized_contract"].isna().sum()),
        duplicate_uid_details=pd.DataFrame(
            duplicate_details,
            columns=["user_id", "record_count", "contract_types"],
        ),
        contract_types=contract_types,
    )


def extract_basic_creator_records(
    dataframe: pd.DataFrame,
) -> tuple[tuple[str, str, str | None], ...]:
    prepared = normalize_import_columns(dataframe)
    missing = [
        column for column in ("user_id", "koc_name") if column not in prepared.columns
    ]
    if missing:
        raise KOCImportFormatError(
            "达人库 Excel 缺少必要字段：" + "、".join(missing) + "。"
        )

    records: list[tuple[str, str, str | None]] = []
    for _, row in prepared.iterrows():
        uid = normalize_user_id(row.get("user_id"))
        raw_name = row.get("koc_name")
        if uid is None or raw_name is None or pd.isna(raw_name):
            continue
        name = str(raw_name).strip()
        if not name:
            continue
        raw_contract = row.get("contract_type")
        contract = (
            None
            if raw_contract is None or pd.isna(raw_contract)
            else str(raw_contract).strip() or None
        )
        records.append((uid, name, contract))
    return tuple(records)
