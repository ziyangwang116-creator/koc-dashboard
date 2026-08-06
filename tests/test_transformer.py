from datetime import date

import pandas as pd
import pytest

from core.koc_mapper import KOCMapper
from core.transformer import DataTransformError, OUTPUT_COLUMNS, transform_data


@pytest.fixture
def mapper():
    return KOCMapper({"107258": "ゆい / のん", "246924": "ルイ幹雄"})


def make_raw_data():
    timestamp = pd.Timestamp("2024-01-01T16:00:00Z").value // 1_000_000
    return pd.DataFrame(
        {
            "view": [100, 200, 300],
            "subtype": [None, "short", "video"],
            "title": ["A", "", None],
            "userId": [107258.0, "999999", 246924],
            "platform": ["youtube", "wrong", "ignored"],
            "url": ["https://a", "https://a", None],
            "timestamp": [timestamp, timestamp, timestamp],
            "likes": [10, None, 30],
            "comment": [None, 2, 3],
        }
    )


def test_transform_applies_required_rules_and_keeps_all_rows(mapper):
    result = transform_data(make_raw_data(), mapper, "Asia/Shanghai")

    assert list(result.data.columns) == OUTPUT_COLUMNS
    assert len(result.data) == 3
    assert result.data["koc_name"].iloc[0] == "ゆい / のん"
    assert pd.isna(result.data["koc_name"].iloc[1])
    assert result.data["platform"].tolist() == ["shorts", "shorts", "video"]
    assert result.data["publish_date"].iloc[0] == date(2024, 1, 2)
    assert result.data["views"].tolist() == [100.0, 200.0, 300.0]
    assert result.data["remark"].isna().all()
    assert result.data["reposted"].isna().all()
    assert pd.isna(result.data["likes"].iloc[1])
    assert pd.isna(result.data["comment"].iloc[0])


def test_validation_report_flags_unmatched_and_data_quality(mapper):
    report = transform_data(make_raw_data(), mapper, "Asia/Shanghai").report

    assert report.original_count == 3
    assert report.final_count == 3
    assert report.koc_count == 2
    assert report.unmatched_uids == ["999999"]
    assert report.subtype_counts == {"（空白）": 1, "short": 1, "video": 1}
    assert report.blank_subtype_to_shorts_count == 1
    assert report.missing_url_count == 1
    assert report.missing_title_count == 2
    assert report.duplicate_url_count == 2


def test_unmatched_uid_is_exported_as_exception(mapper):
    result = transform_data(make_raw_data(), mapper, "Asia/Shanghai")

    assert result.exceptions["异常类型"].tolist() == ["未匹配 UID"]
    assert result.exceptions["userId"].tolist() == ["999999"]
    assert result.exceptions["原始行号"].tolist() == [3]


def test_reposted_values_are_preserved(mapper):
    raw = make_raw_data()
    raw["reposted"] = [1, "", None]

    result = transform_data(raw, mapper, "Asia/Shanghai")

    assert result.data["reposted"].iloc[0] == 1
    assert pd.isna(result.data["reposted"].iloc[1])
    assert pd.isna(result.data["reposted"].iloc[2])


def test_tiktok_raw_platform_overrides_subtype(mapper):
    raw = make_raw_data()
    raw["subtype"] = ["short", "long", None]
    raw["platform"] = ["YouTube", "TikTok", " tiktok "]

    result = transform_data(raw, mapper, "Asia/Shanghai")

    assert result.data["platform"].tolist() == ["shorts", "TikTok", "TikTok"]


def test_rule3_normalizes_every_blank_nan_and_short_variant(mapper):
    subtypes = [None, pd.NA, float("nan"), "", "   ", "NaN", "short", " Short ", "shorts", "long"]
    row_count = len(subtypes)
    raw = pd.DataFrame(
        {
            "view": [1] * row_count,
            "subtype": subtypes,
            "title": ["test"] * row_count,
            "userId": [107258] * row_count,
            "platform": ["YouTube"] * row_count,
            "url": [f"https://example.com/{index}" for index in range(row_count)],
            "timestamp": [0] * row_count,
            "likes": [0] * row_count,
            "comment": [0] * row_count,
        }
    )

    result = transform_data(raw, mapper, "Asia/Shanghai")

    assert result.data["platform"].tolist() == ["shorts"] * 9 + ["long"]
    assert "short" not in result.data["platform"].astype("string").str.casefold().tolist()


def test_tiktok_override_has_priority_over_all_subtype_rules(mapper):
    raw = make_raw_data()
    raw["subtype"] = [None, "short", "long"]
    raw["platform"] = ["TikTok", "TIKTOK", " tiktok "]

    result = transform_data(raw, mapper, "Asia/Shanghai")

    assert result.data["platform"].tolist() == ["TikTok", "TikTok", "TikTok"]


def test_missing_timestamp_and_explicit_date_fails_instead_of_using_url(mapper):
    raw = make_raw_data().iloc[[0]].copy()
    raw["platform"] = "TikTok"
    raw["timestamp"] = pd.NA
    raw["url"] = (
        "https://www.tiktok.com/@namikari73/video/7665632070991039765"
    )

    with pytest.raises(DataTransformError, match="1 条投稿缺少有效发布日期"):
        transform_data(raw, mapper, "Asia/Shanghai")


def test_explicit_date_column_is_used_when_timestamp_is_blank(mapper):
    raw = make_raw_data().iloc[[0]].copy()
    raw = raw.drop(columns="timestamp")
    raw["date"] = [pd.Timestamp("2026-07-12")]
    raw["url"] = "https://example.com/no-date-in-url"

    result = transform_data(raw, mapper, "Asia/Shanghai")

    assert result.data["publish_date"].iloc[0] == date(2026, 7, 12)


def test_raw_platform_column_remains_optional(mapper):
    raw = make_raw_data().drop(columns="platform")

    result = transform_data(raw, mapper, "Asia/Shanghai")

    assert result.data["platform"].tolist() == ["shorts", "shorts", "video"]


def test_missing_required_columns_get_readable_error(mapper):
    raw = make_raw_data().drop(columns=["userId", "timestamp"])

    with pytest.raises(DataTransformError, match="缺少必要字段：userId、timestamp"):
        transform_data(raw, mapper, "Asia/Shanghai")


def test_invalid_timezone_gets_readable_error(mapper):
    with pytest.raises(DataTransformError, match="时区.*无效"):
        transform_data(make_raw_data(), mapper, "Asia/Not-A-Place")
