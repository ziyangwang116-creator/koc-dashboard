from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


BLANK_SUBTYPE_LABEL = "（空白）"


def blank_mask(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype("string").str.strip().eq("")


@dataclass(frozen=True)
class ValidationReport:
    original_count: int
    final_count: int
    koc_count: int
    unmatched_uids: list[str]
    subtype_counts: dict[str, int]
    blank_subtype_to_shorts_count: int
    missing_url_count: int
    missing_title_count: int
    duplicate_url_count: int


def build_validation_report(
    raw_data: pd.DataFrame,
    final_data: pd.DataFrame,
    normalized_user_ids: pd.Series,
    mapped_names: pd.Series,
) -> ValidationReport:
    subtype_blanks = blank_mask(raw_data["subtype"])
    subtype_labels = raw_data["subtype"].astype("object").copy()
    subtype_labels.loc[subtype_blanks] = BLANK_SUBTYPE_LABEL
    subtype_counts = {
        str(label): int(count)
        for label, count in subtype_labels.value_counts(dropna=False).items()
    }

    unmatched_mask = normalized_user_ids.notna() & mapped_names.isna()
    unmatched_uids = list(
        dict.fromkeys(normalized_user_ids.loc[unmatched_mask].astype(str).tolist())
    )

    url_blanks = blank_mask(raw_data["url"])
    valid_urls = raw_data.loc[~url_blanks, "url"].astype("string").str.strip()
    duplicate_url_count = int(valid_urls.duplicated(keep=False).sum())

    return ValidationReport(
        original_count=len(raw_data),
        final_count=len(final_data),
        koc_count=int(mapped_names.dropna().nunique()),
        unmatched_uids=unmatched_uids,
        subtype_counts=subtype_counts,
        blank_subtype_to_shorts_count=int(subtype_blanks.sum()),
        missing_url_count=int(url_blanks.sum()),
        missing_title_count=int(blank_mask(raw_data["title"]).sum()),
        duplicate_url_count=duplicate_url_count,
    )

