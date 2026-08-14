from io import BytesIO
from datetime import date

import pandas as pd

from core.dashboard_processor import (
    DashboardProcessor,
    build_dashboard_result,
    build_creator_summary,
    date_bounds,
    enrich_dashboard_creator_metadata,
    filter_dashboard_data,
)
from core.file_processor import UploadedExcel
from database.koc_repository import KOCRepository
from models.enums import CreatorCategory
from ui.dashboard import _monthly_master_display_frame


def _timestamp(value: str) -> int:
    return pd.Timestamp(value).value // 1_000_000


def _raw(
    *,
    user_ids: list[int],
    views: list[int],
    platform: str = "YouTube",
) -> pd.DataFrame:
    rows = len(user_ids)
    return pd.DataFrame(
        {
            "view": views,
            "subtype": ["short", "long", "livestream"][:rows],
            "description": [f"描述 {index}" for index in range(rows)],
            "title": [f"投稿 {index}" for index in range(rows)],
            "userId": user_ids,
            "platform": [platform] * rows,
            "url": [f"https://example.com/{index}" for index in range(rows)],
            "timestamp": [
                _timestamp(f"2026-06-{index + 1:02d}T01:00:00Z")
                for index in range(rows)
            ],
            "likes": [10] * rows,
            "comment": [2] * rows,
            "reposted": [1] * rows,
            "collect": [3] * rows,
        }
    )


def _file(name: str, dataframe: pd.DataFrame) -> UploadedExcel:
    output = BytesIO()
    dataframe.to_excel(output, index=False, engine="openpyxl")
    return UploadedExcel(name=name, content=output.getvalue())


def _repository(tmp_path) -> KOCRepository:
    repository = KOCRepository(tmp_path / "koc.db")
    repository.create(
        user_id=1001,
        koc_name="草根达人",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["YTB"],
        follower_count=100,
    )
    repository.create(
        user_id=2001,
        koc_name="长包达人",
        creator_category=CreatorCategory.LONG_TERM,
        contract_types=["长包"],
        follower_count=200,
    )
    return repository


def test_dashboard_processor_uses_database_categories_and_keeps_unmatched(tmp_path):
    repository = _repository(tmp_path)
    data = _raw(user_ids=[1001, 2001, 9999], views=[100, 200, 300])

    result = DashboardProcessor(repository.database_path, "Asia/Shanghai").process(
        [_file("june.xlsx", data)]
    )

    assert result.file_reports.loc[0, "status"] == "成功"
    assert result.data["creator_label"].tolist() == [
        "草根达人",
        "长包达人",
        "未匹配 UID：9999",
    ]
    assert result.data["creator_category"].tolist() == ["草根", "长包", "未匹配"]
    assert result.data["content_type"].tolist() == [
        "YTB shorts",
        "long",
        "livestream",
    ]
    assert result.data["subtype"].tolist() == [
        "YTB shorts",
        "long",
        "livestream",
    ]
    assert result.data["description"].tolist() == ["描述 0", "描述 1", "描述 2"]
    assert result.data["view"].tolist() == [100, 200, 300]
    assert result.data["kol_name"].tolist() == [
        "草根达人",
        "长包达人",
        "未匹配 UID：9999",
    ]
    assert result.unmatched_uids.to_dict("records") == [
        {
            "user_id": "9999",
            "post_count": 1,
            "source_files": "june.xlsx",
            "earliest_date": pd.Timestamp("2026-06-03").date(),
            "latest_date": pd.Timestamp("2026-06-03").date(),
        }
    ]


def test_dashboard_processor_matches_tiktok_posts_by_platform_uid(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="910468899",
        youtube_user_id="910468899",
        tiktok_user_id="922195549",
        koc_name="platform uid creator",
        creator_category=CreatorCategory.COMMENTARY,
        contract_types=["YTB长+TT"],
        effective_date=date(2026, 5, 1),
    )
    data = _raw(user_ids=[922195549], views=[500_000], platform="TikTok")

    result = DashboardProcessor(repository.database_path, "Asia/Shanghai").process(
        [_file("tiktok.xlsx", data)]
    )
    detail = result.data.iloc[0]

    assert detail["creator_id"] == record.id
    assert detail["creator_label"] == "platform uid creator"
    assert detail["creator_key"] == "910468899"
    assert detail["user_id"] == "922195549"
    assert detail["youtube_user_id"] == "910468899"
    assert detail["tiktok_user_id"] == "922195549"


def test_dashboard_processor_uses_creator_history_when_platform_uid_is_added_later(
    tmp_path,
):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="youtube-main-id",
        youtube_user_id="youtube-main-id",
        koc_name="later platform uid creator",
        creator_category=CreatorCategory.COMMENTARY,
        contract_types=["YTB长+TT"],
        effective_date=date(2026, 7, 1),
        contract_start_date=date(2026, 7, 1),
    )
    repository.update(
        record.id,
        user_id=record.user_id,
        koc_name=record.koc_name,
        creator_category=record.creator_category,
        contract_types=record.contract_types,
        homepage_url=record.homepage_url,
        follower_count=record.follower_count,
        active=record.active,
        note=record.note,
        youtube_user_id=record.youtube_user_id,
        tiktok_user_id="later-tiktok-id",
        effective_date=date(2026, 8, 1),
        contract_start_date=record.contract_start_date,
        contract_end_date=record.contract_end_date,
    )
    raw = _raw(user_ids=["later-tiktok-id"], views=[500_000], platform="TikTok")
    raw["timestamp"] = pd.NA
    raw["date"] = [pd.Timestamp("2026-07-23")]
    raw["url"] = [
        "https://www.tiktok.com/@creator/video/7665632070991039765"
    ]

    result = DashboardProcessor(repository.database_path, "Asia/Shanghai").process(
        [_file("tiktok-supplement.xlsx", raw)]
    )
    detail = result.data.iloc[0]

    assert detail["publish_date"] == date(2026, 7, 23)
    assert detail["creator_id"] == record.id
    assert detail["creator_label"] == "later platform uid creator"
    assert detail["contract_types"] == "YTB长+TT"
    assert detail["profile_status"] == "MATCHED"


def test_creator_summary_and_filters_calculate_monthly_submission_metrics(tmp_path):
    repository = _repository(tmp_path)
    data = _raw(user_ids=[1001, 1001, 2001], views=[100, 300, 200])
    result = DashboardProcessor(repository.database_path, "Asia/Shanghai").process(
        [_file("june.xlsx", data)]
    )

    summary = build_creator_summary(result.data)
    grassroot = summary.loc[summary["creator_label"] == "草根达人"].iloc[0]
    assert grassroot["post_count"] == 2
    assert grassroot["total_views"] == 400
    assert grassroot["average_views"] == 200
    assert grassroot["total_interactions"] == 32
    assert grassroot["engagement_rate"] == 0.08
    assert date_bounds(result.data) == (
        pd.Timestamp("2026-06-01").date(),
        pd.Timestamp("2026-06-03").date(),
    )

    filtered = filter_dashboard_data(
        result.data,
        creator_categories=["草根"],
        start_date=pd.Timestamp("2026-06-02").date(),
        end_date=pd.Timestamp("2026-06-02").date(),
    )
    assert filtered["creator_label"].tolist() == ["草根达人"]
    assert filtered["views"].tolist() == [300]


def test_bad_dashboard_file_does_not_block_valid_file(tmp_path):
    repository = _repository(tmp_path)
    result = DashboardProcessor(repository.database_path, "Asia/Shanghai").process(
        [
            UploadedExcel(name="broken.xlsx", content=b"not an xlsx"),
            _file("valid.xlsx", _raw(user_ids=[1001], views=[100])),
        ]
    )

    assert result.file_reports["status"].tolist() == ["失败", "成功"]
    assert len(result.data) == 1


def test_monthly_master_keeps_requested_post_fields(tmp_path):
    repository = _repository(tmp_path)
    result = DashboardProcessor(repository.database_path, "Asia/Shanghai").process(
        [_file("june.xlsx", _raw(user_ids=[1001], views=[100]))]
    )

    master = _monthly_master_display_frame(result.data)

    assert master.columns.tolist() == [
        "kol name",
        "subtype",
        "description",
        "comment",
        "collect",
        "userId",
        "platform",
        "url",
        "是否异业",
        "是否计费",
        "排除原因",
        "reposted",
        "timestamp",
        "likes",
        "title",
        "日期",
        "koc",
        "view",
    ]
    assert master.loc[0, "kol name"] == "草根达人"
    assert master.loc[0, "subtype"] == "YTB shorts"
    assert master.loc[0, "koc"] == "草根达人"
    assert master.loc[0, "是否异业"] == "否"
    assert master.loc[0, "是否计费"] == "计费"


def test_dashboard_content_type_labels_cover_youtube_tiktok_and_saved_legacy_rows(
    tmp_path,
):
    repository = _repository(tmp_path)
    tiktok = DashboardProcessor(repository.database_path, "Asia/Shanghai").process(
        [_file("tiktok.xlsx", _raw(user_ids=[1001], views=[100], platform="TikTok"))]
    )
    assert tiktok.data["subtype"].tolist() == ["tiktok"]

    legacy = pd.DataFrame(
        [
            {
                "source_platform": "YouTube",
                "subtype": "shorts",
                "content_type": "\u77ed\u89c6\u9891",
            },
            {
                "source_platform": "TikTok",
                "subtype": "TikTok",
                "content_type": "\u77ed\u89c6\u9891",
            },
            {
                "source_platform": "YouTube",
                "subtype": "livestream",
                "content_type": "\u76f4\u64ad",
            },
        ]
    )
    result = build_dashboard_result(legacy)
    assert result.data["subtype"].tolist() == [
        "YTB shorts",
        "tiktok",
        "livestream",
    ]


def test_saved_legacy_rows_restore_creator_identity_from_unique_name(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    first = repository.create(
        user_id="legacy-first",
        koc_name="Legacy First",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["YTB"],
    )
    second = repository.create(
        user_id="legacy-second",
        koc_name="Legacy Second",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["TT"],
    )
    legacy = pd.DataFrame(
        [
            {
                "koc_name": first.koc_name,
                "platform": "long",
                "publish_date": "2026-05-01",
                "url": "https://youtube.example/legacy-first",
                "views": 100,
                "likes": 10,
                "comment": 1,
                "reposted": 0,
            },
            {
                "koc_name": second.koc_name,
                "platform": "TikTok",
                "publish_date": "2026-05-02",
                "url": "https://tiktok.example/legacy-second",
                "views": 200,
                "likes": 20,
                "comment": 2,
                "reposted": 0,
            },
        ]
    )

    normalized = build_dashboard_result(legacy).data
    enriched = enrich_dashboard_creator_metadata(
        normalized,
        repository.list(include_inactive=True),
        repository.list_profile_history(),
    )
    summary = build_creator_summary(enriched)

    assert enriched["creator_key"].tolist() == [first.user_id, second.user_id]
    assert enriched["creator_label"].tolist() == [first.koc_name, second.koc_name]
    assert enriched["source_platform"].tolist() == ["YouTube", "TikTok"]
    assert enriched["content_type"].tolist() == ["long", "tiktok"]
    assert summary["post_count"].sum() == 2
    assert summary["total_views"].sum() == 300
    assert summary["creator_key"].nunique() == 2


def test_creator_query_filters_name_and_uid(tmp_path):
    repository = _repository(tmp_path)
    result = DashboardProcessor(repository.database_path, "Asia/Shanghai").process(
        [_file("june.xlsx", _raw(user_ids=[1001, 2001], views=[100, 200]))]
    )

    by_name = filter_dashboard_data(result.data, creator_query="草根")
    by_uid = filter_dashboard_data(result.data, creator_query="2001")

    assert by_name["user_id"].tolist() == ["1001"]
    assert by_uid["creator_label"].tolist() == ["长包达人"]
