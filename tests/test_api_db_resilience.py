"""Tests for the bounded database-connection retry/resilience behavior.

These tests never connect to a real Postgres/Supabase instance: they attach a
throwaway GET route to the real app and raise synthetic driver exceptions to
exercise the retry/scrubbing logic added in api/main.py and database/db.py.
"""
from __future__ import annotations

import logging

import psycopg
from fastapi.testclient import TestClient

from api.main import create_app
from config.settings import Settings
from database.db import CONNECTION_LOST_ERRORS, sanitize_db_error_marker

FAKE_DSN = "postgresql://fakeuser:fakepass@fakehost/fakedb"


def _settings(database_path):
    return Settings(
        timezone="Asia/Shanghai",
        database_path=database_path,
        output_dir="data/output",
        youtube_api_key=None,
        tiktok_browser_data_dir="data/tiktok_browser_data",
        tiktok_persistent_headless=False,
        team_password="team-secret",
    )


def _app_with_flaky_route(tmp_path, *, fail_times: int):
    app = create_app(_settings(tmp_path / "koc.db"), environment="development")
    calls = {"n": 0}

    @app.get("/api/_test/flaky")
    def flaky() -> dict:
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise psycopg.OperationalError(f"connection lost: {FAKE_DSN}")
        return {"data": "ok"}

    return app, calls


def test_sanitize_db_error_marker_never_returns_raw_exception_text():
    exc = psycopg.OperationalError(f"connection failed: {FAKE_DSN}")

    marker = sanitize_db_error_marker(exc)

    assert marker == "OperationalError"
    assert "fakeuser" not in marker
    assert "fakepass" not in marker
    assert "fakehost" not in marker


def test_connection_lost_errors_include_operational_and_interface_errors():
    assert psycopg.OperationalError in CONNECTION_LOST_ERRORS
    assert psycopg.InterfaceError in CONNECTION_LOST_ERRORS


def test_get_request_retries_once_after_simulated_lost_connection(tmp_path):
    app, calls = _app_with_flaky_route(tmp_path, fail_times=1)
    client = TestClient(app)

    response = client.get("/api/_test/flaky")

    assert response.status_code == 200
    assert response.json() == {"data": "ok"}
    assert calls["n"] == 2  # one failed attempt + one successful retry


def test_get_request_never_retries_more_than_once(tmp_path):
    app, calls = _app_with_flaky_route(tmp_path, fail_times=99)
    client = TestClient(app)

    response = client.get("/api/_test/flaky")

    assert response.status_code == 500
    assert calls["n"] == 2  # initial attempt + exactly one bounded retry, then stop


def test_persistent_failure_returns_generic_500_without_sensitive_details(tmp_path):
    app, calls = _app_with_flaky_route(tmp_path, fail_times=99)
    client = TestClient(app)

    response = client.get("/api/_test/flaky")

    assert response.status_code == 500
    body = response.json()
    assert body == {
        "error": {"code": "INTERNAL_ERROR", "message": "服务器内部错误，请稍后重试。"}
    }
    raw_text = response.text
    assert "fakeuser" not in raw_text
    assert "fakepass" not in raw_text
    assert "fakehost" not in raw_text
    assert "fakedb" not in raw_text


def test_generic_500_log_marker_never_contains_dsn_shaped_text(tmp_path, caplog):
    app, calls = _app_with_flaky_route(tmp_path, fail_times=99)
    client = TestClient(app)

    with caplog.at_level(logging.ERROR, logger="api.db_resilience"):
        client.get("/api/_test/flaky")

    logged_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "fakeuser" not in logged_text
    assert "fakepass" not in logged_text
    assert "fakehost" not in logged_text
    assert "fakedb" not in logged_text


def test_post_requests_are_never_retried_even_on_lost_connection(tmp_path):
    app = create_app(_settings(tmp_path / "koc.db"), environment="development")
    calls = {"n": 0}

    @app.post("/api/_test/flaky-write")
    def flaky_write() -> dict:
        calls["n"] += 1
        raise psycopg.OperationalError(f"connection lost: {FAKE_DSN}")

    client = TestClient(app)

    response = client.post("/api/_test/flaky-write", json={})

    assert response.status_code == 500
    assert calls["n"] == 1  # no retry for write paths, ever
