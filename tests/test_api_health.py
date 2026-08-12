from fastapi.testclient import TestClient

from api.main import create_app
from config.settings import Settings


def _settings(database_path):
    return Settings(
        timezone="Asia/Shanghai",
        database_path=database_path,
        output_dir="data/output",
        youtube_api_key=None,
        tiktok_browser_data_dir="data/tiktok_browser_data",
        tiktok_persistent_headless=False,
        team_password="team-secret",
        deepseek_api_key="deepseek-secret",
        openai_api_key="openai-secret",
    )


def test_health_reports_sqlite_target_without_requiring_auth(tmp_path):
    app = create_app(_settings(tmp_path / "koc.db"))
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "data": {
            "status": "ok",
            "database": "sqlite",
            "database_ready": True,
            "supabase_ipv4_preferred": False,
        }
    }


def test_health_reports_postgres_target(monkeypatch, tmp_path):
    database_url = "postgresql://user:secret-password@db.example.test/postgres"
    app = create_app(_settings(database_url))
    client = TestClient(app)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, sql):
            assert sql == "SELECT 1"
            return self

        def fetchone(self):
            return (1,)

    monkeypatch.setattr("api.main.connect", lambda _target: FakeConnection())

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "data": {
            "status": "ok",
            "database": "postgres",
            "database_ready": True,
            "supabase_ipv4_preferred": False,
        }
    }


def test_health_response_never_leaks_credentials_or_keys(monkeypatch, tmp_path):
    database_url = "postgresql://user:super-secret-password@db.example.test/postgres"
    app = create_app(_settings(database_url))
    client = TestClient(app)
    monkeypatch.setattr("api.main.connect", lambda _target: _HealthConnection())

    response = client.get("/api/health")

    raw_body = response.text
    assert "super-secret-password" not in raw_body
    assert "db.example.test" not in raw_body
    assert "team-secret" not in raw_body
    assert "deepseek-secret" not in raw_body
    assert "openai-secret" not in raw_body


class _HealthConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql):
        return self

    def fetchone(self):
        return (1,)


def test_health_returns_generic_503_when_database_is_unavailable(monkeypatch, tmp_path):
    app = create_app(_settings(tmp_path / "koc.db"))
    client = TestClient(app)

    def failing_connect(_target):
        raise RuntimeError("postgresql://user:secret@db.example.test/postgres")

    monkeypatch.setattr("api.main.connect", failing_connect)

    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "INTERNAL_ERROR", "message": "服务器内部错误，请稍后重试。"}
    }


def test_health_endpoint_requires_no_authentication_cookie(tmp_path):
    app = create_app(_settings(tmp_path / "koc.db"))
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
