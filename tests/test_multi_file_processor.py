from io import BytesIO

import pandas as pd

from core.file_processor import UploadedExcel
from core.multi_file_processor import MultiFileProcessor
from core.transformer import OUTPUT_COLUMNS


def _timestamp(value: str = "2024-01-01T16:00:00Z") -> int:
    return pd.Timestamp(value).value // 1_000_000


def _raw(
    *,
    user_id=107258,
    title="标题",
    url="https://example.com/a",
    subtype="short",
    platform="YouTube",
    timestamp=None,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "view": [100],
            "subtype": [subtype],
            "title": [title],
            "userId": [user_id],
            "platform": [platform],
            "url": [url],
            "timestamp": [_timestamp() if timestamp is None else timestamp],
            "likes": [10],
            "comment": [2],
            "reposted": [None],
        }
    )


def _file(name: str, dataframe: pd.DataFrame) -> UploadedExcel:
    output = BytesIO()
    dataframe.to_excel(output, index=False, engine="openpyxl")
    return UploadedExcel(name=name, content=output.getvalue())


def test_multiple_normal_excel_files_are_merged(tmp_path):
    first = _raw(url="https://example.com/a")
    second = _raw(url="https://example.com/b", title="第二条")

    result = MultiFileProcessor(tmp_path / "koc.db", "Asia/Shanghai").process(
        [_file("week1.xlsx", first), _file("week2.xlsx", second)]
    )

    assert len(result.data) == 2
    assert result.overall.successful_files == 2
    assert result.overall.failed_files == 0
    assert result.file_reports["processed_rows"].tolist() == [1, 1]
    assert list(result.data.columns) == OUTPUT_COLUMNS


def test_single_file_uses_same_batch_pipeline(tmp_path):
    result = MultiFileProcessor(tmp_path / "koc.db", "Asia/Shanghai").process(
        [_file("single.xlsx", _raw())]
    )

    assert result.overall.uploaded_files == 1
    assert result.overall.successful_files == 1
    assert len(result.data) == 1
    assert result.smart_import_files[0]["column_mapping"]["timestamp"] == "timestamp"
    assert result.smart_import_files[0]["date_method_counts"] == {"unix_ms": 1}


def test_smart_import_reports_aliases_and_actual_date_range(tmp_path):
    dataframe = _raw().rename(
        columns={
            "view": "播放量",
            "subtype": "视频类型",
            "title": "视频标题",
            "userId": "达人ID",
            "url": "视频链接",
            "timestamp": "发布日期",
        }
    )
    dataframe["发布日期"] = pd.Timestamp("2026-07-12")

    result = MultiFileProcessor(tmp_path / "koc.db", "Asia/Shanghai").process(
        [_file("supplement.xlsx", dataframe)]
    )

    diagnostic = result.smart_import_files[0]
    assert result.overall.successful_files == 1
    assert diagnostic["column_mapping"]["timestamp"] == "发布日期"
    assert diagnostic["date_method_counts"] == {"excel_datetime": 1}
    assert diagnostic["date_min"] == "2026-07-12"
    assert diagnostic["date_max"] == "2026-07-12"


def test_invalid_date_is_a_row_issue_instead_of_a_file_failure(tmp_path):
    dataframe = _raw(timestamp="not-a-date")

    result = MultiFileProcessor(tmp_path / "koc.db", "Asia/Shanghai").process(
        [_file("invalid-date.xlsx", dataframe)]
    )

    assert result.overall.successful_files == 1
    assert result.overall.invalid_timestamp_count == 1
    assert result.exceptions["issue_type"].tolist() == ["INVALID_TIMESTAMP"]


def test_corrupt_file_does_not_block_other_file(tmp_path):
    result = MultiFileProcessor(tmp_path / "koc.db", "Asia/Shanghai").process(
        [UploadedExcel("broken.xlsx", b"not an xlsx"), _file("good.xlsx", _raw())]
    )

    assert len(result.data) == 1
    assert result.overall.successful_files == 1
    assert result.overall.failed_files == 1
    assert result.file_reports["status"].tolist() == ["失败", "成功"]
    assert "FILE_ERROR" in result.exceptions["issue_type"].tolist()


def test_missing_optional_columns_are_filled_with_blanks(tmp_path):
    dataframe = _raw().drop(columns=["likes", "comment", "reposted"])

    result = MultiFileProcessor(tmp_path / "koc.db", "Asia/Shanghai").process(
        [_file("optional.xlsx", dataframe)]
    )

    assert result.overall.successful_files == 1
    assert pd.isna(result.data.loc[0, "likes"])
    assert pd.isna(result.data.loc[0, "comment"])
    assert pd.isna(result.data.loc[0, "reposted"])


def test_missing_required_column_has_clear_per_file_error(tmp_path):
    dataframe = _raw().drop(columns="timestamp")

    result = MultiFileProcessor(tmp_path / "koc.db", "Asia/Shanghai").process(
        [_file("missing.xlsx", dataframe)]
    )

    assert result.overall.failed_files == 1
    assert result.data.empty
    assert "缺少必要字段：timestamp" in result.file_reports.loc[0, "error_message"]


def test_numeric_user_id_timestamp_subtype_and_platform_rules(tmp_path):
    dataframe = pd.concat(
        [
            _raw(user_id=107258.0, subtype=None, url="https://a"),
            _raw(user_id=107258, subtype="video", platform="TikTok", url="https://b"),
        ],
        ignore_index=True,
    )

    result = MultiFileProcessor(tmp_path / "koc.db", "Asia/Shanghai").process(
        [_file("rules.xlsx", dataframe)]
    )

    assert result.data["koc_name"].notna().all()
    assert result.data["platform"].tolist() == ["shorts", "TikTok"]
    assert str(result.data.loc[0, "publish_date"]) == "2024-01-02"
    assert result.overall.blank_subtype_to_shorts_count == 1


def test_unmatched_uid_is_kept_and_reported_with_source(tmp_path):
    result = MultiFileProcessor(tmp_path / "koc.db", "Asia/Shanghai").process(
        [_file("unknown.xlsx", _raw(user_id=99999999))]
    )

    assert len(result.data) == 1
    assert pd.isna(result.data.loc[0, "koc_name"])
    assert result.unmatched_uids.to_dict("records") == [
        {"userId": "99999999", "出现次数": 1, "来源文件": "unknown.xlsx"}
    ]


def test_duplicate_url_is_reported_but_not_removed_by_default(tmp_path):
    result = MultiFileProcessor(tmp_path / "koc.db", "Asia/Shanghai").process(
        [_file("one.xlsx", _raw()), _file("two.xlsx", _raw(title="重复"))]
    )

    assert len(result.data) == 2
    assert result.overall.duplicate_url_count == 2
    assert result.exceptions["issue_type"].tolist().count("DUPLICATE_URL") == 2


def test_optional_duplicate_removal_keeps_first_url_record(tmp_path):
    result = MultiFileProcessor(tmp_path / "koc.db", "Asia/Shanghai").process(
        [_file("one.xlsx", _raw()), _file("two.xlsx", _raw(title="重复"))],
        deduplicate_urls=True,
    )

    assert len(result.data) == 1
    assert result.data.loc[0, "title"] == "标题"
    assert result.overall.removed_duplicate_count == 1
