from fastapi.testclient import TestClient

from api.main import SESSION_COOKIE_NAME, SESSION_MAX_AGE_SECONDS, create_app
from api.session_store import SessionStore
from config.settings import Settings


def _settings(team_password="test-team-password"):
    return Settings(
        timezone="Asia/Shanghai",
        database_path="data/koc.db",
        output_dir="data/output",
        youtube_api_key=None,
        tiktok_browser_data_dir="data/tiktok_browser_data",
        tiktok_persistent_headless=False,
        team_password=team_password,
    )


def _client(environment="development", team_password="test-team-password"):
    app = create_app(_settings(team_password), environment=environment)
    return TestClient(app)


def test_login_with_correct_password_succeeds_and_sets_cookie():
    client = _client()

    response = client.post("/api/auth/login", json={"password": "test-team-password"})

    assert response.status_code == 200
    assert response.json() == {"data": {"authenticated": True}}
    assert SESSION_COOKIE_NAME in response.cookies


def test_login_response_never_contains_the_password_itself():
    client = _client()

    response = client.post("/api/auth/login", json={"password": "test-team-password"})

    assert "test-team-password" not in response.text


def test_login_with_wrong_password_returns_401():
    client = _client()

    response = client.post("/api/auth/login", json={"password": "wrong-password"})

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "INVALID_CREDENTIALS"
    assert SESSION_COOKIE_NAME not in response.cookies


def test_login_with_missing_password_returns_422():
    client = _client()

    response = client.post("/api/auth/login", json={})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["field_errors"][0]["field"] == "password"


def test_login_with_empty_password_returns_422():
    client = _client()

    response = client.post("/api/auth/login", json={"password": ""})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_login_cookie_is_httponly_and_samesite_lax_in_development():
    client = _client(environment="development")

    response = client.post("/api/auth/login", json={"password": "test-team-password"})

    set_cookie = response.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Secure" not in set_cookie
    assert f"Max-Age={SESSION_MAX_AGE_SECONDS}" in set_cookie


def test_login_cookie_is_secure_in_production():
    client = _client(environment="production")

    response = client.post("/api/auth/login", json={"password": "test-team-password"})

    set_cookie = response.headers.get("set-cookie", "")
    assert "Secure" in set_cookie
    assert "HttpOnly" in set_cookie


def test_logout_clears_cookie_and_returns_authenticated_false():
    client = _client()
    client.post("/api/auth/login", json={"password": "test-team-password"})

    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"data": {"authenticated": False}}
    set_cookie = response.headers.get("set-cookie", "")
    assert "Max-Age=0" in set_cookie


def test_logout_without_prior_login_is_idempotent():
    client = _client()

    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"data": {"authenticated": False}}


def test_session_store_marks_session_invalid_after_expiry(monkeypatch):
    store = SessionStore(ttl_seconds=60)
    current_time = [1_000_000.0]
    monkeypatch.setattr("api.session_store.time.time", lambda: current_time[0])

    session_id = store.create()
    assert store.is_valid(session_id) is True

    current_time[0] += 61
    assert store.is_valid(session_id) is False


def test_session_store_delete_invalidates_session():
    store = SessionStore(ttl_seconds=60)
    session_id = store.create()

    store.delete(session_id)

    assert store.is_valid(session_id) is False


def test_session_store_rejects_unknown_or_missing_session_id():
    store = SessionStore(ttl_seconds=60)

    assert store.is_valid(None) is False
    assert store.is_valid("not-a-real-session") is False
