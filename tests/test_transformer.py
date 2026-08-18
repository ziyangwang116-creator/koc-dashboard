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


def test_invalid_timestamp_is_retained_for_row_level_review(mapper):
    raw = make_raw_data().iloc[[0]].copy()
    raw["platform"] = "TikTok"
    raw["timestamp"] = pd.NA
    raw["url"] = (
        "https://www.tiktok.com/@namikari73/video/7665632070991039765"
    )

    result = transform_data(raw, mapper, "Asia/Shanghai")

    assert pd.isna(result.data.loc[0, "publish_date"])
    assert "有 1 条投稿缺少有效发布日期。" in result.diagnostics.warnings


def test_explicit_date_column_is_used_when_timestamp_is_blank(mapper):
    raw = make_raw_data().iloc[[0]].copy()
    raw = raw.drop(columns="timestamp")
    raw["date"] = [pd.Timestamp("2026-07-12")]
    raw["url"] = "https://example.com/no-date-in-url"

    result = transform_data(raw, mapper, "Asia/Shanghai")

    assert result.data["publish_date"].iloc[0] == date(2026, 7, 12)


@pytest.mark.parametrize(
    ("timestamp", "expected_date", "expected_method"),
    [
        (pd.Timestamp("2026-07-12"), date(2026, 7, 12), "excel_datetime"),
        (1783785600, date(2026, 7, 12), "unix_s"),
        (46215, date(2026, 7, 12), "excel_serial"),
        (20260712, date(2026, 7, 12), "yyyymmdd"),
        ("2026/07/12", date(2026, 7, 12), "date_text"),
    ],
)
def test_smart_import_recognizes_common_date_formats(
    mapper, timestamp, expected_date, expected_method
):
    raw = make_raw_data().iloc[[0]].copy()
    raw["timestamp"] = timestamp

    result = transform_data(raw, mapper, "Asia/Shanghai")

    assert result.data.loc[0, "publish_date"] == expected_date
    assert result.diagnostics.date_method_counts == {expected_method: 1}


def test_smart_import_recognizes_chinese_column_aliases(mapper):
    raw = pd.DataFrame(
        {
            "播放量": [123],
            "视频类型": ["short"],
            "视频标题": ["智能导入"],
            "达人ID": [107258],
            "视频链接": ["https://example.com/smart"],
            "发布日期": [pd.Timestamp("2026-07-12")],
            "点赞数": [9],
        }
    )

    result = transform_data(raw, mapper, "Asia/Shanghai")

    assert result.data.loc[0, "views"] == 123
    assert result.data.loc[0, "publish_date"] == date(2026, 7, 12)
    assert result.diagnostics.column_mapping["timestamp"] == "发布日期"
    assert "timestamp" in result.diagnostics.auto_mapped_columns


def test_manual_mapping_overrides_existing_canonical_column(mapper):
    raw = make_raw_data().iloc[[0]].copy()
    raw["发布日期"] = pd.Timestamp("2026-07-12")
    raw["timestamp"] = "not-a-date"

    result = transform_data(
        raw,
        mapper,
        "Asia/Shanghai",
        column_mapping={"timestamp": "发布日期"},
    )

    assert result.data.loc[0, "publish_date"] == date(2026, 7, 12)
    assert result.diagnostics.column_mapping["timestamp"] == "发布日期"


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
