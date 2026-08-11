from fastapi.testclient import TestClient

from api.main import create_app
from config.settings import Settings
from database.dashboard_repository import DashboardRepository
from database.koc_repository import KOCRepository
from models.enums import ContractType, CreatorCategory

import pandas as pd

TEAM_PASSWORD = "test-team-password"
PREFIX = "dashfilteruid-"


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


def _seed_posts(database_path, grassroot, long_term):
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
            "is_cross_industry": False,
            "compensation_eligible": True,
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


def test_filter_options_requires_authentication(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    app = create_app(_settings(database_path), environment="development")
    client = TestClient(app)

    response = client.get("/api/dashboard/filter-options")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


# ---------------------------------------------------------------------------
# GET /api/dashboard/filter-options
# ---------------------------------------------------------------------------


def test_filter_options_returns_dynamic_creators(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _authenticated_client(database_path)

    response = client.get("/api/dashboard/filter-options")

    assert response.status_code == 200
    data = response.json()["data"]
    creator_keys = {creator["creator_key"] for creator in data["creators"]}
    assert creator_keys == {grassroot.user_id, long_term.user_id}
    for creator in data["creators"]:
        if creator["creator_key"] == grassroot.user_id:
            assert creator["creator_label"] == grassroot.koc_name
        if creator["creator_key"] == long_term.user_id:
            assert creator["creator_label"] == long_term.koc_name


def test_filter_options_returns_creator_categories_present_in_data(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _authenticated_client(database_path)

    response = client.get("/api/dashboard/filter-options")

    data = response.json()["data"]
    assert set(data["creator_categories"]) == {"GRASSROOT", "LONG_TERM"}


def test_filter_options_returns_source_platforms_from_actual_posts(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _authenticated_client(database_path)

    response = client.get("/api/dashboard/filter-options")

    data = response.json()["data"]
    assert set(data["source_platforms"]) == {"TikTok", "YouTube"}


def test_filter_options_content_types_use_real_subtype_mapping(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _authenticated_client(database_path)

    response = client.get("/api/dashboard/filter-options")

    data = response.json()["data"]
    # tiktok post with blank subtype -> "tiktok"; long -> "long"; livestream -> "livestream"
    assert set(data["content_types"]) == {"tiktok", "long", "livestream"}


def test_filter_options_available_months_reflect_actual_publish_dates(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _authenticated_client(database_path)

    response = client.get("/api/dashboard/filter-options")

    data = response.json()["data"]
    assert data["available_months"] == ["2026-07", "2026-08"]


def test_filter_options_available_weeks_only_contain_weeks_with_data(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _authenticated_client(database_path)

    response = client.get("/api/dashboard/filter-options")

    data = response.json()["data"]
    # 2026-07-01 is a Wednesday -> week 2026-06-29 to 2026-07-05
    # 2026-07-15 is a Wednesday -> week 2026-07-13 to 2026-07-19
    # 2026-08-03 is a Monday -> week 2026-08-03 to 2026-08-09
    assert {
        "week_start": "2026-06-29",
        "week_end": "2026-07-05",
    } in data["available_weeks"]
    assert {
        "week_start": "2026-07-13",
        "week_end": "2026-07-19",
    } in data["available_weeks"]
    assert {
        "week_start": "2026-08-03",
        "week_end": "2026-08-09",
    } in data["available_weeks"]
    assert len(data["available_weeks"]) == 3


def test_filter_options_does_not_write_traffic_boost_setting(tmp_path):
    database_path = tmp_path / "koc.db"
    grassroot, long_term = _seed_creators(database_path)
    _seed_posts(database_path, grassroot, long_term)
    client = _authenticated_client(database_path)

    response = client.get("/api/dashboard/filter-options")

    assert response.status_code == 200
    dashboard_repository = DashboardRepository(database_path)
    assert dashboard_repository.get_traffic_boost_enabled("2026-07") is False


def test_filter_options_returns_empty_options_with_no_posts(tmp_path):
    database_path = tmp_path / "koc.db"
    client = _authenticated_client(database_path)

    response = client.get("/api/dashboard/filter-options")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data == {
        "creators": [],
        "creator_categories": [],
        "source_platforms": [],
        "content_types": [],
        "available_months": [],
        "available_weeks": [],
    }
