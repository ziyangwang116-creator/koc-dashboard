from fastapi.testclient import TestClient

from api.main import create_app
from config.settings import Settings
from database.koc_repository import KOCRepository
from models.enums import ContractType, CreatorCategory

TEAM_PASSWORD = "test-team-password"
PREFIX = "apitestuid-"


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
    active_grassroot = repository.create(
        user_id=f"{PREFIX}active-grassroot",
        koc_name="Zzz Active Grassroot",
        creator_category=CreatorCategory.GRASSROOT,
        contract_type=ContractType.TT,
        follower_count=1000,
    )
    active_long_term = repository.create(
        user_id=f"{PREFIX}active-long",
        koc_name="Aaa Active Long Term",
        creator_category=CreatorCategory.LONG_TERM,
        follower_count=5000,
    )
    inactive_creator = repository.create(
        user_id=f"{PREFIX}inactive",
        koc_name="Mmm Inactive Creator",
        creator_category=CreatorCategory.GRASSROOT,
        contract_type=ContractType.YTB_SHORTS,
        follower_count=200,
    )
    repository.set_active(inactive_creator.id, False)
    return repository, active_grassroot, active_long_term, inactive_creator


# ---------------------------------------------------------------------------
# Authentication gating
# ---------------------------------------------------------------------------


def test_creators_list_requires_authentication(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    app = create_app(_settings(database_path), environment="development")
    client = TestClient(app)

    response = client.get("/api/creators")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_creator_detail_requires_authentication(tmp_path):
    database_path = tmp_path / "koc.db"
    _, active_grassroot, _, _ = _seed_creators(database_path)
    app = create_app(_settings(database_path), environment="development")
    client = TestClient(app)

    response = client.get(f"/api/creators/{active_grassroot.id}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_contract_types_requires_authentication(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    app = create_app(_settings(database_path), environment="development")
    client = TestClient(app)

    response = client.get("/api/meta/contract-types")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


# ---------------------------------------------------------------------------
# GET /api/creators
# ---------------------------------------------------------------------------


def test_list_creators_defaults_to_active_and_inactive(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get("/api/creators", params={"q": PREFIX})

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["pagination"]["total_items"] == 3
    user_ids = {item["user_id"] for item in body["data"]}
    assert user_ids == {
        f"{PREFIX}active-grassroot",
        f"{PREFIX}active-long",
        f"{PREFIX}inactive",
    }


def test_list_creators_active_true_excludes_inactive(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get("/api/creators", params={"q": PREFIX, "active": "true"})

    body = response.json()
    user_ids = {item["user_id"] for item in body["data"]}
    assert user_ids == {f"{PREFIX}active-grassroot", f"{PREFIX}active-long"}
    assert all(item["active"] is True for item in body["data"])


def test_list_creators_active_false_returns_only_inactive(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get("/api/creators", params={"q": PREFIX, "active": "false"})

    body = response.json()
    user_ids = {item["user_id"] for item in body["data"]}
    assert user_ids == {f"{PREFIX}inactive"}
    assert body["data"][0]["active"] is False


def test_list_creators_rejects_invalid_active_value(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get("/api/creators", params={"active": "maybe"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_creators_filters_by_platform(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    youtube_response = client.get(
        "/api/creators", params={"q": PREFIX, "platform": "youtube"}
    )
    tiktok_response = client.get(
        "/api/creators", params={"q": PREFIX, "platform": "tiktok"}
    )

    assert youtube_response.status_code == 200
    assert {item["user_id"] for item in youtube_response.json()["data"]} == {
        f"{PREFIX}inactive"
    }
    assert tiktok_response.status_code == 200
    assert {item["user_id"] for item in tiktok_response.json()["data"]} == {
        f"{PREFIX}active-grassroot"
    }


def test_list_creators_rejects_invalid_platform(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get("/api/creators", params={"platform": "other"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_creators_filters_by_q(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get("/api/creators", params={"q": f"{PREFIX}active-long"})

    body = response.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["user_id"] == f"{PREFIX}active-long"


def test_list_creators_filters_by_creator_category(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/creators", params={"q": PREFIX, "creator_category": "LONG_TERM"}
    )

    body = response.json()
    assert {item["user_id"] for item in body["data"]} == {f"{PREFIX}active-long"}


def test_list_creators_rejects_invalid_creator_category(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get("/api/creators", params={"creator_category": "NOT_REAL"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_creators_filters_by_contract_type_dynamic_string(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/creators", params={"q": PREFIX, "contract_type": "TT"}
    )

    body = response.json()
    assert {item["user_id"] for item in body["data"]} == {f"{PREFIX}active-grassroot"}
    assert body["data"][0]["contract_types"] == ["TT"]


def test_list_creators_pagination(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get(
        "/api/creators", params={"q": PREFIX, "page": 1, "page_size": 2}
    )

    body = response.json()
    assert len(body["data"]) == 2
    assert body["meta"]["pagination"] == {
        "page": 1,
        "page_size": 2,
        "total_items": 3,
        "total_pages": 2,
    }


def test_list_creators_rejects_page_size_over_limit(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get("/api/creators", params={"page_size": 101})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_creators_sort_koc_name_ascending(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get("/api/creators", params={"q": PREFIX, "sort": "koc_name"})

    names = [item["koc_name"] for item in response.json()["data"]]
    assert names == sorted(names)
    assert names == ["Aaa Active Long Term", "Mmm Inactive Creator", "Zzz Active Grassroot"]


def test_list_creators_rejects_sort_not_in_whitelist(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get("/api/creators", params={"sort": "note"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_creators_does_not_return_operational_only_fields(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get("/api/creators", params={"q": PREFIX})

    for item in response.json()["data"]:
        assert "follower_error_code" not in item
        assert "follower_sync_error" not in item
        assert "follower_source_url" not in item
        assert "follower_profile_url" not in item
        assert "contract_periods" not in item


# ---------------------------------------------------------------------------
# GET /api/creators/{id}
# ---------------------------------------------------------------------------


def test_get_creator_detail_returns_extended_fields_and_contract_periods(tmp_path):
    database_path = tmp_path / "koc.db"
    _, active_grassroot, _, _ = _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get(f"/api/creators/{active_grassroot.id}")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["id"] == active_grassroot.id
    assert body["user_id"] == f"{PREFIX}active-grassroot"
    assert "follower_error_code" in body
    assert "follower_sync_error" in body
    assert "follower_source_url" in body
    assert "follower_profile_url" in body
    assert "contract_periods" in body
    assert isinstance(body["contract_periods"], list)
    assert body["contract_periods"][0]["contract_types"] == ["TT"]


def test_get_creator_detail_returns_404_for_unknown_id(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get("/api/creators/999999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# GET /api/meta/contract-types
# ---------------------------------------------------------------------------


def test_contract_types_returns_newly_seeded_dynamic_types_in_order(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creators(database_path)
    client = _authenticated_client(database_path)

    response = client.get("/api/meta/contract-types")

    assert response.status_code == 200
    contract_types = response.json()["data"]["contract_types"]
    tt_index = contract_types.index("TT")
    ytb_shorts_index = contract_types.index("YTB_SHORTS")
    assert tt_index < ytb_shorts_index


def test_contract_types_does_not_hardcode_a_fixed_enum(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = KOCRepository(database_path)
    repository.create(
        user_id=f"{PREFIX}only-one",
        koc_name="Only One",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["CUSTOM_UNSEEN_CONTRACT_TYPE"],
    )
    client = _authenticated_client(database_path)

    response = client.get("/api/meta/contract-types")

    assert "CUSTOM_UNSEEN_CONTRACT_TYPE" in response.json()["data"]["contract_types"]
