from fastapi.testclient import TestClient
from unittest.mock import patch

from api.main import create_app
from config.settings import Settings
from database.dashboard_repository import DashboardRepository
from database.db import connect
from database.koc_repository import KOCRepository
from models.enums import ContractType, CreatorCategory

import pandas as pd

TEAM_PASSWORD = "test-team-password"
PREFIX = "dashreaduid-"


def _settings(database_path):
    return Settings(
        timezone="Asia/Shanghai",
        database_path=database_path,
        output_dir="data/output",
        youtube_api_key=None,
        tiktok_browser_data_dir="data/tiktok_browser_data",
        tiktok_persistent_headless=False,
        team_password=TEAM_PASSWORD,
    )


def _authenticated_client(database_path):
    app = create_app(_settings(database_path), environment="development")
    client = TestClient(app)
    login_response = client.post("/api/auth/login", json={"password": TEAM_PASSWORD})
    assert login_response.status_code == 200
    return client


def test_dashboard_reads_reuse_prepared_data_until_database_changes(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _authenticated_client(database_path)

    with patch(
        "api.dashboard.build_dashboard_result",
        wraps=__import__("api.dashboard", fromlist=["build_dashboard_result"]).build_dashboard_result,
    ) as build_result:
        first = client.get("/api/dashboard/filter-options")
        second = client.get(
            "/api/dashboard/summary",
            params={"period_mode": "month", "period_month": "2026-07"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert build_result.call_count == 2


def _seed_creators(database_path):
    repository = KOCRepository(database_path)
    grassroot = repository.create(
        user_id=f"{PREFIX}grassroot",
        koc_name="Grassroot Creator",
        creator_category=CreatorCategory.GRASSROOT,
        contract_type=ContractType.TT,
    )
    long_term = repository.create(
        user_id=f"{PREFIX}long-term",
        koc_name="Long Term Creator",
        creator_category=CreatorCategory.LONG_TERM,
    )
    return grassroot, long_term


def _seed_posts(database_path, grassroot, long_term, *, cross_industry_row=False):
    dashboard_repository = DashboardRepository(database_path)
    rows = [
        {
            "source_file": "file-a.xlsx",
            "user_id": grassroot.user_id,
            "creator_key": grassroot.user_id,
            "creator_label": grassroot.koc_name,
            "creator_category": "GRASSROOT",
            "contract_types": "TT",
            "matched": True,
            "profile_status": "MATCHED",
            "is_cross_industry": False,
            "compensation_eligible": True,
            "source_platform": "TikTok",
            "subtype": "tiktok",
            "content_type": "tiktok",
            "publish_date": "2026-07-01",
            "title": "Post A",
            "url": "https://tiktok.example/a",
            "views": 100,
            "view": 100,
            "likes": 10,
            "comment": 1,
            "reposted": 0,
            "collect": 0,
        },
        {
            "source_file": "file-b.xlsx",
            "user_id": long_term.user_id,
            "creator_key": long_term.user_id,
            "creator_label": long_term.koc_name,
            "creator_category": "LONG_TERM",
            "contract_types": "",
            "matched": True,
            "profile_status": "MATCHED",
            "is_cross_industry": False,
            "compensation_eligible": True,
            "source_platform": "YouTube",
            "subtype": "long",
            "content_type": "long",
            "publish_date": "2026-07-15",
            "title": "Post B",
            "url": "https://youtube.example/b",
            "views": 200,
            "view": 200,
            "likes": 20,
            "comment": 2,
            "reposted": 0,
            "collect": 0,
        },
        {
            "source_file": "file-c.xlsx",
            "user_id": long_term.user_id,
            "creator_key": long_term.user_id,
            "creator_label": long_term.koc_name,
            "creator_category": "LONG_TERM",
            "contract_types": "",
            "matched": True,
            "profile_status": "MATCHED",
            "is_cross_industry": bool(cross_industry_row),
            "compensation_eligible": not cross_industry_row,
            "source_platform": "YouTube",
            "subtype": "livestream",
            "content_type": "livestream",
            "publish_date": "2026-08-03",
            "title": "Post C",
            "url": "https://youtube.example/c",
            "views": 300,
            "view": 300,
            "likes": 30,
            "comment": 3,
            "reposted": 0,
            "collect": 0,
        },
    ]
    dashboard_repository.upsert_posts(pd.DataFrame(rows))


# ---------------------------------------------------------------------------
# Authentication gating
# ---------------------------------------------------------------------------


def test_summary_requires_authentication(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    app = create_app(_settings(database_path), environment="development")
    client = TestClient(app)

    response = client.get(
        "/api/dashboard/summary", params={"period_mode": "month", "period_month": "2026-07"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_posts_requires_authentication(tmp_path):
    database_path = tmp_path / "koc.db"
    app = create_app(_settings(database_path), environment="development")
    client = TestClient(app)

    response = client.get(
        "/api/dashboard/posts", params={"period_mode": "month", "period_month": "2026-07"}
    )

    assert response.status_code == 401


def test_comparison_requires_authentication(tmp_path):
    database_path = tmp_path / "koc.db"
    app = create_app(_settings(database_path), environment="development")
    client = TestClient(app)

    response = client.post(
        "/api/dashboard/comparison",
        json={
            "periods": [
                {"period_mode": "month", "period_month": "2026-07"},
                {"period_mode": "month", "period_month": "2026-08"},
            ],
            "dimension": "platform",
        },
    )

    assert response.status_code == 401


def test_rankings_requires_authentication(tmp_path):
    database_path = tmp_path / "koc.db"
    app = create_app(_settings(database_path), environment="development")
    client = TestClient(app)

    response = client.get(
        "/api/dashboard/rankings",
        params={
            "ranking_type": "creator_views_top10",
            "period_mode": "month",
            "period_month": "2026-07",
        },
    )

    assert response.status_code == 401


def test_import_batches_requires_authentication(tmp_path):
    database_path = tmp_path / "koc.db"
    app = create_app(_settings(database_path), environment="development")
    client = TestClient(app)

    response = client.get("/api/dashboard/import-batches")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/dashboard/summary - periods and validation
# ---------------------------------------------------------------------------


def test_summary_month_period_returns_creator_rows(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/dashboard/summary", params={"period_mode": "month", "period_month": "2026-07"}
    )

    assert response.status_code == 200
    body = response.json()
    active_rows = [row for row in body["data"] if row["post_count"] > 0]
    creator_keys = {row["creator_key"] for row in active_rows}
    assert creator_keys == {grassroot.user_id, long_term.user_id}
    for row in active_rows:
        assert "view" in row and "original_views" in row and "traffic_boost_views" in row and "boosted_views" in row


def test_summary_week_period_requires_monday_week_start(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/dashboard/summary", params={"period_mode": "week", "week_start": "2026-07-02"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_summary_week_period_valid_monday(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/dashboard/summary", params={"period_mode": "week", "week_start": "2026-08-03"}
    )

    assert response.status_code == 200
    body = response.json()
    assert {row["creator_key"] for row in body["data"] if row["post_count"] > 0} == {long_term.user_id}


def test_summary_custom_period_valid_range(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/dashboard/summary",
        params={"period_mode": "custom", "start_date": "2026-07-01", "end_date": "2026-07-31"},
    )

    assert response.status_code == 200
    body = response.json()
    assert {row["creator_key"] for row in body["data"] if row["post_count"] > 0} == {
        grassroot.user_id,
        long_term.user_id,
    }


def test_summary_custom_period_end_before_start_is_invalid(tmp_path):
    database_path = tmp_path / "koc.db"
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/dashboard/summary",
        params={"period_mode": "custom", "start_date": "2026-07-31", "end_date": "2026-07-01"},
    )

    assert response.status_code == 422


def test_summary_missing_period_mode_is_invalid(tmp_path):
    database_path = tmp_path / "koc.db"
    client = _authenticated_client(database_path)

    response = client.get("/api/dashboard/summary")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_summary_conflicting_period_params_is_invalid(tmp_path):
    database_path = tmp_path / "koc.db"
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/dashboard/summary",
        params={
            "period_mode": "month",
            "period_month": "2026-07",
            "start_date": "2026-07-01",
        },
    )

    assert response.status_code == 422


def test_summary_invalid_month_format_is_invalid(tmp_path):
    database_path = tmp_path / "koc.db"
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/dashboard/summary", params={"period_mode": "month", "period_month": "not-a-month"}
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def test_summary_filters_by_creator_category(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/dashboard/summary",
        params={
            "period_mode": "custom",
            "start_date": "2026-07-01",
            "end_date": "2026-08-31",
            "creator_category": "GRASSROOT",
        },
    )

    body = response.json()
    assert {row["creator_key"] for row in body["data"]} == {grassroot.user_id}


def test_summary_include_cross_industry_toggle(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term, cross_industry_row=True)
    dashboard_repository = DashboardRepository(database_path)
    dashboard_repository.save_cross_industry_exclusions(["https://youtube.example/c"])
    client = _authenticated_client(database_path)

    excluded_response = client.get(
        "/api/dashboard/posts",
        params={
            "period_mode": "custom",
            "start_date": "2026-07-01",
            "end_date": "2026-08-31",
        },
    )
    excluded_titles = {row["title"] for row in excluded_response.json()["data"]}
    assert "Post C" not in excluded_titles

    included_response = client.get(
        "/api/dashboard/posts",
        params={
            "period_mode": "custom",
            "start_date": "2026-07-01",
            "end_date": "2026-08-31",
            "include_cross_industry": "true",
        },
    )
    included_titles = {row["title"] for row in included_response.json()["data"]}
    assert "Post C" in included_titles


# ---------------------------------------------------------------------------
# Traffic boost modes
# ---------------------------------------------------------------------------


def test_traffic_boost_mode_original_forces_original_views(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    dashboard_repository = DashboardRepository(database_path)
    dashboard_repository.save_traffic_boost_enabled("2026-07", True)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/dashboard/posts",
        params={
            "period_mode": "month",
            "period_month": "2026-07",
            "traffic_boost_mode": "original",
        },
    )

    body = response.json()
    for row in body["data"]:
        assert row["views"] == row["original_views"]


def test_traffic_boost_mode_boosted_preview_forces_boosted_views(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/dashboard/posts",
        params={
            "period_mode": "month",
            "period_month": "2026-07",
            "traffic_boost_mode": "boosted_preview",
        },
    )

    body = response.json()
    for row in body["data"]:
        assert row["views"] == row["boosted_views"]


def test_traffic_boost_mode_saved_setting_reads_saved_flag(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    dashboard_repository = DashboardRepository(database_path)
    dashboard_repository.save_traffic_boost_enabled("2026-07", True)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/dashboard/posts",
        params={
            "period_mode": "month",
            "period_month": "2026-07",
            "traffic_boost_mode": "saved_setting",
        },
    )

    body = response.json()
    for row in body["data"]:
        assert row["views"] == row["boosted_views"]


def test_traffic_boost_modes_never_write_to_setting_table(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _authenticated_client(database_path)

    for mode in ("saved_setting", "original", "boosted_preview"):
        response = client.get(
            "/api/dashboard/posts",
            params={
                "period_mode": "month",
                "period_month": "2026-07",
                "traffic_boost_mode": mode,
            },
        )
        assert response.status_code == 200

    with connect(database_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM dashboard_traffic_boost_setting"
        ).fetchone()["count"]
    assert count == 0


def test_invalid_traffic_boost_mode_is_rejected(tmp_path):
    database_path = tmp_path / "koc.db"
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/dashboard/posts",
        params={
            "period_mode": "month",
            "period_month": "2026-07",
            "traffic_boost_mode": "bogus",
        },
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/dashboard/comparison
# ---------------------------------------------------------------------------


def test_comparison_requires_at_least_two_periods(tmp_path):
    database_path = tmp_path / "koc.db"
    client = _authenticated_client(database_path)

    response = client.post(
        "/api/dashboard/comparison",
        json={"periods": [{"period_mode": "month", "period_month": "2026-07"}], "dimension": "platform"},
    )

    assert response.status_code == 422


def test_comparison_creator_dimension_breakdown_and_warning(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    dashboard_repository = DashboardRepository(database_path)
    rows = [
        {
            "source_file": "file-a.xlsx",
            "user_id": long_term.user_id,
            "creator_key": long_term.user_id,
            "creator_label": long_term.koc_name,
            "creator_category": "LONG_TERM",
            "contract_types": "",
            "matched": True,
            "profile_status": "MATCHED",
            "is_cross_industry": False,
            "compensation_eligible": True,
            "source_platform": "YouTube",
            "subtype": "long",
            "content_type": "long",
            "publish_date": "2026-07-15",
            "title": "July Long Post",
            "url": "https://youtube.example/july-long",
            "views": 1000,
            "view": 1000,
            "likes": 10,
            "comment": 1,
            "reposted": 0,
            "collect": 0,
        },
        {
            "source_file": "file-b.xlsx",
            "user_id": long_term.user_id,
            "creator_key": long_term.user_id,
            "creator_label": long_term.koc_name,
            "creator_category": "LONG_TERM",
            "contract_types": "",
            "matched": True,
            "profile_status": "MATCHED",
            "is_cross_industry": False,
            "compensation_eligible": True,
            "source_platform": "YouTube",
            "subtype": "long",
            "content_type": "long",
            "publish_date": "2026-08-15",
            "title": "August Long Post",
            "url": "https://youtube.example/august-long",
            "views": 100,
            "view": 100,
            "likes": 1,
            "comment": 0,
            "reposted": 0,
            "collect": 0,
        },
    ]
    dashboard_repository.upsert_posts(pd.DataFrame(rows))
    client = _authenticated_client(database_path)

    response = client.post(
        "/api/dashboard/comparison",
        json={
            "periods": [
                {"period_mode": "month", "period_month": "2026-07"},
                {"period_mode": "month", "period_month": "2026-08"},
            ],
            "dimension": "creator",
        },
    )

    assert response.status_code == 200
    body = response.json()["data"]
    series = {entry["group_key"]: entry for entry in body["series"]}
    entry = series[long_term.user_id]
    assert entry["warning"] is True
    assert entry["change_rate"] < -0.3
    long_breakdown = entry["breakdown"]["long"]
    assert long_breakdown["points"][0]["value"] == 1000
    assert long_breakdown["points"][1]["value"] == 100
    assert long_breakdown["warning"] is True
    for key in ("livestream", "shorts", "tiktok"):
        assert key in entry["breakdown"]


def test_comparison_invalid_dimension_is_rejected(tmp_path):
    database_path = tmp_path / "koc.db"
    client = _authenticated_client(database_path)

    response = client.post(
        "/api/dashboard/comparison",
        json={
            "periods": [
                {"period_mode": "month", "period_month": "2026-07"},
                {"period_mode": "month", "period_month": "2026-08"},
            ],
            "dimension": "bogus",
        },
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/dashboard/rankings
# ---------------------------------------------------------------------------


RANKING_TYPES = [
    "creator_views_top10",
    "creator_posts_top10",
    "creator_ytb_top30",
    "creator_tt_top30",
    "video_ytb_top20",
    "video_tt_top20",
]


def test_rankings_support_all_six_types(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _authenticated_client(database_path)

    for ranking_type in RANKING_TYPES:
        response = client.get(
            "/api/dashboard/rankings",
            params={
                "ranking_type": ranking_type,
                "period_mode": "custom",
                "start_date": "2026-07-01",
                "end_date": "2026-08-31",
            },
        )
        assert response.status_code == 200, ranking_type
        body = response.json()["data"]
        assert body["ranking_type"] == ranking_type
        assert isinstance(body["items"], list)


def test_rankings_invalid_ranking_type_is_rejected(tmp_path):
    database_path = tmp_path / "koc.db"
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/dashboard/rankings",
        params={
            "ranking_type": "bogus_type",
            "period_mode": "month",
            "period_month": "2026-07",
        },
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/dashboard/import-batches
# ---------------------------------------------------------------------------


def test_import_batches_default_limit_and_descending_order(tmp_path):
    database_path = tmp_path / "koc.db"
    dashboard_repository = DashboardRepository(database_path)
    for index in range(3):
        dashboard_repository.save_monthly_import(
            pd.DataFrame(
                [
                    {
                        "source_file": f"file-{index}.xlsx",
                        "user_id": f"{PREFIX}u{index}",
                        "creator_key": f"{PREFIX}u{index}",
                        "creator_label": "Creator",
                        "matched": False,
                        "is_cross_industry": False,
                        "compensation_eligible": True,
                        "source_platform": "TikTok",
                        "content_type": "tiktok",
                        "publish_date": "2026-07-01",
                        "title": "Post",
                        "url": f"https://tiktok.example/{index}",
                        "views": 10,
                        "view": 10,
                    }
                ]
            ),
            replace_months=["2026-07"],
            source_files=[f"file-{index}.xlsx"],
            file_hashes=[f"hash-{index}"],
        )
    client = _authenticated_client(database_path)

    response = client.get("/api/dashboard/import-batches")

    assert response.status_code == 200
    data = response.json()["data"]
    ids = [row["batch_id"] for row in data]
    assert ids == sorted(ids, reverse=True)
    assert data[0]["mode"] == "REPLACE_MONTHS"
    assert isinstance(data[0]["period_months"], list)
    assert isinstance(data[0]["source_files"], list)


def test_import_batches_limit_boundary(tmp_path):
    database_path = tmp_path / "koc.db"
    client = _authenticated_client(database_path)

    ok_response = client.get("/api/dashboard/import-batches", params={"limit": 200})
    assert ok_response.status_code == 200

    too_large_response = client.get("/api/dashboard/import-batches", params={"limit": 201})
    assert too_large_response.status_code == 422

    too_small_response = client.get("/api/dashboard/import-batches", params={"limit": 0})
    assert too_small_response.status_code == 422
