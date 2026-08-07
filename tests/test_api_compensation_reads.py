import pandas as pd
from fastapi.testclient import TestClient

from api.main import create_app
from config.settings import Settings
from database.dashboard_repository import DashboardRepository
from database.koc_repository import KOCRepository
from models.enums import ContractType, CreatorCategory

TEAM_PASSWORD = "test-team-password"
PREFIX = "compreaduid-"


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


def _unauthenticated_client(database_path):
    app = create_app(_settings(database_path), environment="development")
    return TestClient(app)


def _seed_creators(database_path):
    repository = KOCRepository(database_path)
    grassroot = repository.create(
        user_id=f"{PREFIX}grassroot",
        koc_name="Grassroot Creator",
        creator_category=CreatorCategory.GRASSROOT,
        contract_type=ContractType.TT,
        follower_count=50_000,
        tiktok_follower_count=50_000,
    )
    long_term = repository.create(
        user_id=f"{PREFIX}long-term",
        koc_name="Long Term Creator",
        creator_category=CreatorCategory.LONG_TERM,
        follower_count=50_000,
    )
    return grassroot, long_term


def _post_row(
    *,
    user_id,
    creator_label,
    creator_category,
    contract_types,
    subtype,
    source_platform,
    publish_date,
    url,
    views,
    is_cross_industry=False,
):
    return {
        "source_file": "file.xlsx",
        "user_id": user_id,
        "creator_key": user_id,
        "creator_label": creator_label,
        "creator_category": creator_category,
        "contract_types": contract_types,
        "matched": True,
        "profile_status": "MATCHED",
        "is_cross_industry": is_cross_industry,
        "compensation_eligible": not is_cross_industry,
        "source_platform": source_platform,
        "subtype": subtype,
        "content_type": subtype,
        "publish_date": publish_date,
        "title": "Post",
        "url": url,
        "views": views,
        "view": views,
        "likes": 1,
        "comment": 1,
        "reposted": 0,
        "collect": 0,
    }


def _seed_posts(database_path, grassroot, long_term):
    dashboard_repository = DashboardRepository(database_path)
    rows = [
        _post_row(
            user_id=grassroot.user_id,
            creator_label=grassroot.koc_name,
            creator_category="GRASSROOT",
            contract_types="TT",
            subtype="tiktok",
            source_platform="TikTok",
            publish_date="2026-06-01",
            url="https://tiktok.example/grassroot-1",
            views=5000,
        ),
        _post_row(
            user_id=long_term.user_id,
            creator_label=long_term.koc_name,
            creator_category="LONG_TERM",
            contract_types="",
            subtype="long",
            source_platform="YouTube",
            publish_date="2026-06-05",
            url="https://youtube.example/long-1",
            views=8000,
        ),
    ]
    dashboard_repository.upsert_posts(pd.DataFrame(rows))


# ---------------------------------------------------------------------------
# Authentication gating
# ---------------------------------------------------------------------------


def test_endpoints_require_authentication(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _unauthenticated_client(database_path)

    for path, params in [
        ("/api/compensation/periods", {}),
        ("/api/compensation/grassroot", {"period_month": "2026-06"}),
        ("/api/compensation/long-term", {"period_month": "2026-06"}),
        ("/api/compensation/commentary", {"period_month": "2026-06"}),
        (
            "/api/compensation/versions",
            {"period_month": "2026-06", "category": "GRASSROOT"},
        ),
        (
            "/api/compensation/commentary/theme-submissions",
            {"period_month": "2026-06"},
        ),
    ]:
        response = client.get(path, params=params)
        assert response.status_code == 401, path
        body = response.json()
        assert body["error"]["code"] == "UNAUTHENTICATED"


# ---------------------------------------------------------------------------
# periods
# ---------------------------------------------------------------------------


def test_periods_lists_post_months(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    dashboard_repository = DashboardRepository(database_path)
    dashboard_repository.save_jpy_to_usd_rate("2026-06", 150.0)
    client = _authenticated_client(database_path)

    response = client.get("/api/compensation/periods")
    assert response.status_code == 200
    months = [entry["period_month"] for entry in response.json()["data"]]
    assert "2026-06" in months
    assert months == sorted(months, reverse=True)


def test_periods_invalid_category(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)
    response = client.get("/api/compensation/periods", params={"category": "BOGUS"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# grassroot preview
# ---------------------------------------------------------------------------


def test_grassroot_missing_rate_returns_422(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/compensation/grassroot", params={"period_month": "2026-06"}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["field_errors"][0]["field"] == "jpy_to_usd_rate"


def test_grassroot_preview_isolates_category(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    dashboard_repository = DashboardRepository(database_path)
    dashboard_repository.save_jpy_to_usd_rate("2026-06", 150.0)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/compensation/grassroot", params={"period_month": "2026-06"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["mode"] == "preview"
    assert body["meta"]["jpy_to_usd_rate"] == 150.0
    creator_keys = {row["creator_key"] for row in body["data"]}
    assert grassroot.user_id in creator_keys
    assert long_term.user_id not in creator_keys


def test_long_term_preview_isolates_category(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    dashboard_repository = DashboardRepository(database_path)
    dashboard_repository.save_jpy_to_usd_rate("2026-06", 150.0)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/compensation/long-term", params={"period_month": "2026-06"}
    )
    assert response.status_code == 200
    body = response.json()
    creator_keys = {row["creator_key"] for row in body["data"]}
    assert long_term.user_id in creator_keys
    assert grassroot.user_id not in creator_keys


def test_commentary_meta_omits_traffic_boost_key(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    dashboard_repository = DashboardRepository(database_path)
    dashboard_repository.save_jpy_to_usd_rate("2026-06", 150.0)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/compensation/commentary", params={"period_month": "2026-06"}
    )
    assert response.status_code == 200
    assert "traffic_boost_enabled" not in response.json()["meta"]


def test_grassroot_bad_version_id_returns_404(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    dashboard_repository = DashboardRepository(database_path)
    dashboard_repository.save_jpy_to_usd_rate("2026-06", 150.0)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/compensation/grassroot",
        params={"period_month": "2026-06", "version_id": 999999},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_grassroot_invalid_sort_returns_422(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    dashboard_repository = DashboardRepository(database_path)
    dashboard_repository.save_jpy_to_usd_rate("2026-06", 150.0)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/compensation/grassroot",
        params={"period_month": "2026-06", "sort": "bogus_field"},
    )
    assert response.status_code == 422


def test_grassroot_invalid_page_size_returns_422(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    dashboard_repository = DashboardRepository(database_path)
    dashboard_repository.save_jpy_to_usd_rate("2026-06", 150.0)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/compensation/grassroot",
        params={"period_month": "2026-06", "page_size": 1000},
    )
    assert response.status_code == 422


def test_grassroot_invalid_period_month_returns_422(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/compensation/grassroot", params={"period_month": "not-a-month"}
    )
    assert response.status_code == 422


def test_grassroot_q_and_pagination(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    dashboard_repository = DashboardRepository(database_path)
    dashboard_repository.save_jpy_to_usd_rate("2026-06", 150.0)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/compensation/grassroot",
        params={
            "period_month": "2026-06",
            "q": grassroot.user_id,
            "page": 1,
            "page_size": 1,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["pagination"]["page_size"] == 1
    assert all(grassroot.user_id in row["creator_key"] for row in body["data"])

    miss_response = client.get(
        "/api/compensation/grassroot",
        params={"period_month": "2026-06", "q": "no-such-creator"},
    )
    assert miss_response.json()["data"] == []


# ---------------------------------------------------------------------------
# versions (draft/locked)
# ---------------------------------------------------------------------------


def test_versions_and_frozen_mode(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    dashboard_repository = DashboardRepository(database_path)
    dashboard_repository.save_jpy_to_usd_rate("2026-06", 150.0)

    draft = dashboard_repository.create_compensation_draft(
        "2026-06",
        jpy_to_usd_rate=150.0,
        details=pd.DataFrame(
            [
                {
                    "user_id": grassroot.user_id,
                    "达人": grassroot.koc_name,
                    "合同类型": "TT",
                    "结算状态": "可结算",
                    "总金额（日元）": 1000,
                    "博主应收（日元）(包含15$手续费)": 1000,
                    "有道应收（日元）（包含服务费）": 1150,
                    "博主应收（美元）": 20.0,
                    "有道应收（美元）（包含服务费）": 23.0,
                    "CPM": 5.0,
                    "计费播放量": 5000,
                    "全部视频类型播放量": 5000,
                }
            ]
        ),
        summary={
            "total_amount_jpy": 1000,
            "creator_receivable_jpy": 1000,
            "youdao_receivable_jpy": 1150,
            "creator_receivable_usd": 20.0,
            "youdao_receivable_usd": 23.0,
            "settled_views": 5000,
            "total_video_views": 5000,
            "overall_cpm": 5.0,
        },
        note="draft note",
    )
    locked = dashboard_repository.lock_compensation_version(draft.id)

    client = _authenticated_client(database_path)

    versions_response = client.get(
        "/api/compensation/versions",
        params={"period_month": "2026-06", "category": "GRASSROOT"},
    )
    assert versions_response.status_code == 200
    versions_body = versions_response.json()["data"]
    assert len(versions_body) == 1
    assert versions_body[0]["status"] == "LOCKED"
    assert versions_body[0]["schema_version"] is None

    frozen_response = client.get(
        "/api/compensation/grassroot",
        params={
            "period_month": "2026-06",
            "version_id": locked.id,
        },
    )
    assert frozen_response.status_code == 200
    frozen_body = frozen_response.json()
    assert frozen_body["meta"]["mode"] == "frozen"
    assert frozen_body["meta"]["version"]["status"] == "LOCKED"
    assert frozen_body["data"][0]["total_amount_jpy"] == 1000


def test_versions_invalid_category(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)
    response = client.get(
        "/api/compensation/versions",
        params={"period_month": "2026-06", "category": "BOGUS"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# commentary theme submissions
# ---------------------------------------------------------------------------


def test_theme_submissions_short_requires_three_links(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = KOCRepository(database_path)
    commentary_creator = repository.create(
        user_id=f"{PREFIX}commentary",
        koc_name="Commentary Creator",
        creator_category=CreatorCategory.COMMENTARY,
        contract_types=["YTB长+TT"],
        follower_count=50_000,
    )

    dashboard_repository = DashboardRepository(database_path)
    with database_path_connection(dashboard_repository) as connection:
        connection.execute(
            """
            INSERT INTO commentary_theme_definition (
                period_month, theme_code, theme_name, description,
                max_per_creator, reward_jpy, enabled
            ) VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            ("2026-06", "THEME1", "Theme One", "", 5, 15000),
        )
        connection.execute(
            """
            INSERT INTO commentary_theme_submission (
                period_month, creator_id, theme_code, content_format,
                urls_json, submitted_date, review_status, note
            ) VALUES (?, ?, ?, 'SHORT', ?, '2026-06-10', 'APPROVED', NULL)
            """,
            (
                "2026-06",
                commentary_creator.id,
                "THEME1",
                '["https://tiktok.example/one", "https://tiktok.example/two"]',
            ),
        )

    client = _authenticated_client(database_path)
    response = client.get(
        "/api/compensation/commentary/theme-submissions",
        params={"period_month": "2026-06"},
    )
    assert response.status_code == 200
    rows = response.json()["data"]
    assert len(rows) == 1
    # Only 2 of 3 required SHORT links -> not eligible.
    assert rows[0]["theme_reward_eligible"] is False
    assert rows[0]["billing_excluded_url_count"] == 0
    assert rows[0]["billing_excluded"] is False


def database_path_connection(dashboard_repository):
    from database.db import connect

    return connect(dashboard_repository.database_path)


def test_theme_submissions_invalid_review_status(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)
    response = client.get(
        "/api/compensation/commentary/theme-submissions",
        params={"period_month": "2026-06", "review_status": "BOGUS"},
    )
    assert response.status_code == 422
