"""Tests for the follower-update write/async-job endpoints (19.4).

All external YouTube/TikTok fetch calls are stubbed -- these tests never hit
the real network. Uses a temp sqlite DB + synthetic creators only.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from config.settings import Settings
from database.koc_repository import KOCRepository
from followers.base import FollowerFetchResult
from models.enums import FollowerSource
from services.follower_service import FollowerService

TEAM_PASSWORD = "test-team-password"


class StubYouTubeProvider:
    def __init__(self, *, count=50000, fail=False):
        self.count = count
        self.fail = fail
        self.calls = 0
        self.last_url = None

    def fetch(self, homepage_url):
        self.calls += 1
        self.last_url = homepage_url
        if self.fail:
            return FollowerFetchResult(
                False, None, "YouTube", "2026-08-10T00:00:00+00:00",
                "FOLLOWER_COUNT_UNAVAILABLE", "无法获取粉丝数",
                source=FollowerSource.YOUTUBE_API,
            )
        return FollowerFetchResult(
            True, self.count, "YouTube", "2026-08-10T00:00:00+00:00",
            source=FollowerSource.YOUTUBE_API,
        )


class StubTikTokProvider:
    def __init__(self, *, count=8000):
        self.count = count
        self.calls = 0

    def fetch(self, homepage_url):
        self.calls += 1
        return FollowerFetchResult(
            True, self.count, "TikTok", "2026-08-10T00:00:00+00:00",
            source=FollowerSource.TIKTOK_BROWSER,
        )


class ExplodingTikTokProvider:
    def __init__(self):
        self.calls = 0

    def fetch(self, homepage_url):
        self.calls += 1
        raise RuntimeError("provider exploded")


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


def _app(database_path, providers):
    def factory():
        return FollowerService(KOCRepository(database_path), providers=providers)

    return create_app(
        _settings(database_path), environment="development", followers_service_factory=factory
    )


def _authenticated_client(database_path, providers):
    app = _app(database_path, providers)
    client = TestClient(app)
    login_response = client.post(
        "/api/auth/login",
        json={"password": TEAM_PASSWORD, "operator_name": "张三"},
    )
    assert login_response.status_code == 200
    return client


def _poll_job(client, job_id, *, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/followers/batch-update-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()["data"]
        if body["status"] in ("SUCCEEDED", "FAILED"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not reach a terminal status in time")


# ---------------------------------------------------------------------------
# Manual single-creator follower-count input.
# ---------------------------------------------------------------------------


def test_manual_follower_update_success(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = KOCRepository(database_path)
    record = repository.create(
        user_id="manual1", koc_name="人工达人", contract_types=["TT专属"],
        tiktok_user_id="tt_manual1", homepage_url="https://example.com/manual1",
    )
    client = _authenticated_client(database_path, {"YouTube": StubYouTubeProvider(), "TikTok": StubTikTokProvider()})

    response = client.post(
        f"/api/followers/{record.id}/manual-update",
        json={"youtube_follower_count": "12,345", "tiktok_follower_count": 6789},
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["record_id"] == record.id
    assert body["results"]["youtube_follower_count"]["status"] == "成功"
    assert body["results"]["youtube_follower_count"]["follower_count"] == 12345
    assert body["results"]["tiktok_follower_count"]["status"] == "成功"
    assert body["results"]["tiktok_follower_count"]["follower_count"] == 6789

    updated = repository.get(record.id)
    assert updated.youtube_follower_count == 12345
    assert updated.tiktok_follower_count == 6789

    # operator_name audit was recorded (per 19.6.7).
    audit = repository.list_follower_audit(updated.user_id)
    assert not audit.empty
    assert "operator_name" in audit.columns
    assert (audit["operator_name"] == "张三").any()


def test_manual_follower_update_invalid_value_records_failure(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = KOCRepository(database_path)
    record = repository.create(user_id="manual2", koc_name="人工达人2")
    client = _authenticated_client(database_path, {"YouTube": StubYouTubeProvider(), "TikTok": StubTikTokProvider()})

    response = client.post(
        f"/api/followers/{record.id}/manual-update",
        json={"youtube_follower_count": "not-a-number"},
    )
    assert response.status_code == 200
    result = response.json()["data"]["results"]["youtube_follower_count"]
    assert result["status"] == "失败"
    assert result["error_code"] == "INVALID_FOLLOWER_VALUE"


def test_manual_follower_update_missing_creator_404(tmp_path):
    database_path = tmp_path / "koc.db"
    KOCRepository(database_path)
    client = _authenticated_client(database_path, {})

    response = client.post(
        "/api/followers/999/manual-update",
        json={"youtube_follower_count": 100},
    )
    assert response.status_code == 404


def test_manual_follower_update_requires_at_least_one_platform(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = KOCRepository(database_path)
    record = repository.create(user_id="manual3", koc_name="人工达人3")
    client = _authenticated_client(database_path, {})

    response = client.post(f"/api/followers/{record.id}/manual-update", json={})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Async batch-update job: create + poll + per-creator results.
# ---------------------------------------------------------------------------


def test_batch_job_create_and_progress_reaches_completed(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = KOCRepository(database_path)
    r1 = repository.create(
        user_id="batch1", koc_name="达人1", contract_types=["YTB长"],
        youtube_user_id="yt1", homepage_url="https://youtube.com/batch1",
    )
    r2 = repository.create(
        user_id="batch2", koc_name="达人2", contract_types=["YTB长"],
        youtube_user_id="yt2", homepage_url="https://youtube.com/batch2",
    )
    providers = {"YouTube": StubYouTubeProvider(count=1000), "TikTok": StubTikTokProvider()}
    client = _authenticated_client(database_path, providers)

    response = client.post(
        "/api/followers/batch-update-jobs",
        json={"record_ids": [r1.id, r2.id], "required_platform": "YouTube"},
    )
    assert response.status_code == 202
    job = response.json()["data"]
    assert job["status"] in ("PENDING", "RUNNING")
    assert job["total"] == 2

    final = _poll_job(client, job["job_id"])
    assert final["status"] == "SUCCEEDED"
    assert final["processed"] == 2
    assert final["success"] == 2
    assert final["youtube_success"] == 2

    results = client.get(f"/api/followers/batch-update-jobs/{job['job_id']}/results")
    assert results.status_code == 200
    rows = results.json()["data"]["rows"]
    assert len(rows) == 2
    assert {row["user_id"] for row in rows} == {"batch1", "batch2"}
    assert all(row["status"] == "成功" for row in rows)


def test_batch_job_empty_record_ids_rejected(tmp_path):
    database_path = tmp_path / "koc.db"
    KOCRepository(database_path)
    client = _authenticated_client(database_path, {})

    response = client.post("/api/followers/batch-update-jobs", json={"record_ids": []})
    assert response.status_code == 422


def test_batch_job_unknown_job_id_404(tmp_path):
    database_path = tmp_path / "koc.db"
    KOCRepository(database_path)
    client = _authenticated_client(database_path, {})

    assert client.get("/api/followers/batch-update-jobs/does-not-exist").status_code == 404
    assert client.get("/api/followers/batch-update-jobs/does-not-exist/results").status_code == 404


def test_batch_job_one_creator_exception_does_not_stop_others(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = KOCRepository(database_path)
    ok = repository.create(
        user_id="ok1", koc_name="正常达人", contract_types=["TT专属"],
        tiktok_user_id="tt_ok1", homepage_url="https://tiktok.com/ok1",
    )
    boom = repository.create(
        user_id="boom1", koc_name="异常达人", contract_types=["TT专属"],
        tiktok_user_id="tt_boom1", homepage_url="https://tiktok.com/boom1",
    )
    ok2 = repository.create(
        user_id="ok2", koc_name="正常达人2", contract_types=["TT专属"],
        tiktok_user_id="tt_ok2", homepage_url="https://tiktok.com/ok2",
    )
    providers = {"YouTube": StubYouTubeProvider(), "TikTok": ExplodingTikTokProvider()}
    client = _authenticated_client(database_path, providers)

    response = client.post(
        "/api/followers/batch-update-jobs",
        json={"record_ids": [ok.id, boom.id, ok2.id], "required_platform": "TikTok"},
    )
    job_id = response.json()["data"]["job_id"]
    final = _poll_job(client, job_id)
    # The job as a whole must still complete even though every fetch raised.
    assert final["status"] == "SUCCEEDED"
    assert final["processed"] == 3
    assert final["failed"] == 3

    rows = client.get(f"/api/followers/batch-update-jobs/{job_id}/results").json()["data"]["rows"]
    assert len(rows) == 3
    assert all(row["status"] == "失败" for row in rows)
    # No auto-retry: the stub provider is called exactly once per creator.
    assert providers["TikTok"].calls == 3


def test_batch_job_no_auto_retry_on_failure(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = KOCRepository(database_path)
    record = repository.create(
        user_id="retrycheck", koc_name="重试检测", contract_types=["YTB长"],
        youtube_user_id="yt_retry", homepage_url="https://youtube.com/retrycheck",
    )
    youtube_provider = StubYouTubeProvider(fail=True)
    client = _authenticated_client(database_path, {"YouTube": youtube_provider, "TikTok": StubTikTokProvider()})

    response = client.post(
        "/api/followers/batch-update-jobs",
        json={"record_ids": [record.id], "required_platform": "YouTube"},
    )
    job_id = response.json()["data"]["job_id"]
    final = _poll_job(client, job_id)
    assert final["status"] == "SUCCEEDED"
    assert final["failed"] == 1
    assert youtube_provider.calls == 1  # no retry after the failure


def test_batch_job_reports_safe_job_level_failure(tmp_path):
    database_path = tmp_path / "koc.db"
    KOCRepository(database_path)

    def failing_factory():
        raise RuntimeError("private failure detail must not reach the API")

    app = create_app(
        _settings(database_path),
        environment="development",
        followers_service_factory=failing_factory,
    )
    client = TestClient(app)
    assert client.post(
        "/api/auth/login",
        json={"password": TEAM_PASSWORD, "operator_name": "tester"},
    ).status_code == 200

    response = client.post(
        "/api/followers/batch-update-jobs",
        json={"record_ids": [1], "required_platform": "YouTube"},
    )
    final = _poll_job(client, response.json()["data"]["job_id"])

    assert final["status"] == "FAILED"
    assert final["processed"] == 0
    assert final["error_code"] == "JOB_EXECUTION_FAILED"
    assert "RuntimeError" in final["error_message"]
    assert "private failure detail" not in final["error_message"]
    assert final["last_progress_at"] is not None


# ---------------------------------------------------------------------------
# 19.4.4 all-tiktok / all-youtube candidate routing.
# ---------------------------------------------------------------------------


def test_all_tiktok_job_includes_new_tt_contract_string(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = KOCRepository(database_path)
    # A brand-new contract-type string never seen before, but containing "TT".
    record = repository.create(
        user_id="newtt", koc_name="新合同达人", contract_types=["6月TT专项合作"],
        tiktok_user_id="tt_newtt", homepage_url="https://tiktok.com/newtt",
    )
    providers = {"YouTube": StubYouTubeProvider(), "TikTok": StubTikTokProvider(count=4321)}
    client = _authenticated_client(database_path, providers)

    response = client.post("/api/followers/batch-update-jobs/all-tiktok")
    assert response.status_code == 202
    job_id = response.json()["data"]["job_id"]
    final = _poll_job(client, job_id)
    assert final["status"] == "SUCCEEDED"
    assert final["total"] == 1
    assert final["success"] == 1

    rows = client.get(f"/api/followers/batch-update-jobs/{job_id}/results").json()["data"]["rows"]
    assert [row["user_id"] for row in rows] == ["newtt"]
    assert rows[0]["follower_count"] == 4321

    updated = repository.get(record.id)
    assert updated.tiktok_follower_count == 4321


def test_all_tiktok_job_excludes_non_tt_contract(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = KOCRepository(database_path)
    repository.create(
        user_id="ytbonly", koc_name="纯YTB达人", contract_types=["YTB长"],
        youtube_user_id="yt_only", homepage_url="https://youtube.com/ytbonly",
    )
    providers = {"YouTube": StubYouTubeProvider(), "TikTok": StubTikTokProvider()}
    client = _authenticated_client(database_path, providers)

    response = client.post("/api/followers/batch-update-jobs/all-tiktok")
    job_id = response.json()["data"]["job_id"]
    final = _poll_job(client, job_id)
    assert final["status"] == "SUCCEEDED"
    assert final["total"] == 0

    rows = client.get(f"/api/followers/batch-update-jobs/{job_id}/results").json()["data"]["rows"]
    assert rows == []


def test_all_tiktok_job_uses_homepage_without_tiktok_user_id(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = KOCRepository(database_path)
    missing = repository.create(
        user_id="missinguid", koc_name="缺UID达人", contract_types=["TT专属"],
        homepage_url="https://www.tiktok.com/@missinguid",
    )
    fine = repository.create(
        user_id="hasuid", koc_name="有UID达人", contract_types=["TT专属"],
        tiktok_user_id="tt_hasuid", homepage_url="https://tiktok.com/hasuid",
    )
    providers = {"YouTube": StubYouTubeProvider(), "TikTok": StubTikTokProvider(count=999)}
    client = _authenticated_client(database_path, providers)

    response = client.post("/api/followers/batch-update-jobs/all-tiktok")
    job_id = response.json()["data"]["job_id"]
    final = _poll_job(client, job_id)
    assert final["status"] == "SUCCEEDED"
    assert final["total"] == 2
    assert final["success"] == 2
    assert final["skipped"] == 0

    rows = client.get(f"/api/followers/batch-update-jobs/{job_id}/results").json()["data"]["rows"]
    by_user = {row["user_id"]: row for row in rows}
    assert by_user["missinguid"]["status"] == "成功"
    assert by_user["missinguid"]["follower_count"] == 999
    assert by_user["hasuid"]["status"] == "成功"
    assert by_user["hasuid"]["follower_count"] == 999


def test_all_youtube_job_routes_by_current_contract(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = KOCRepository(database_path)
    repository.create(
        user_id="ytbcreator", koc_name="YTB达人", contract_types=["YTB长"],
        youtube_user_id="yt_creator", homepage_url="https://youtube.com/ytbcreator",
    )
    repository.create(
        user_id="ttcreator", koc_name="TT达人", contract_types=["TT专属"],
        tiktok_user_id="tt_creator", homepage_url="https://tiktok.com/ttcreator",
    )
    providers = {"YouTube": StubYouTubeProvider(count=555), "TikTok": StubTikTokProvider()}
    client = _authenticated_client(database_path, providers)

    response = client.post("/api/followers/batch-update-jobs/all-youtube")
    job_id = response.json()["data"]["job_id"]
    final = _poll_job(client, job_id)
    assert final["status"] == "SUCCEEDED"
    assert final["total"] == 1

    rows = client.get(f"/api/followers/batch-update-jobs/{job_id}/results").json()["data"]["rows"]
    assert [row["user_id"] for row in rows] == ["ytbcreator"]
    assert rows[0]["follower_count"] == 555


def test_youtube_update_requires_youtube_homepage_url(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = KOCRepository(database_path)
    record = repository.create(
        user_id="youtubeonly",
        koc_name="YouTube主页缺失",
        contract_types=["YTB长"],
        youtube_user_id="UC1234567890123456789012",
        homepage_url="https://www.tiktok.com/@wrong-platform",
    )
    youtube_provider = StubYouTubeProvider(count=321)
    service = FollowerService(
        repository,
        providers={"YouTube": youtube_provider, "TikTok": StubTikTokProvider()},
    )

    outcome = service.update_one(record.id, required_platform="YouTube")

    assert outcome.status == "跳过"
    assert outcome.result.error_code == "MISSING_URL"
    assert youtube_provider.last_url is None
    assert repository.get(record.id).youtube_follower_count is None


def test_tiktok_update_requires_tiktok_homepage_url(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = KOCRepository(database_path)
    record = repository.create(
        user_id="tiktokonly",
        koc_name="TikTok主页缺失",
        contract_types=["TT专属"],
        homepage_url="https://www.youtube.com/@wrong-platform",
    )
    tiktok_provider = StubTikTokProvider(count=321)
    service = FollowerService(
        repository,
        providers={"YouTube": StubYouTubeProvider(), "TikTok": tiktok_provider},
    )

    outcome = service.update_one(record.id, required_platform="TikTok")

    assert outcome.status == "跳过"
    assert outcome.result.error_code == "MISSING_URL"
    assert tiktok_provider.calls == 0
    assert repository.get(record.id).tiktok_follower_count is None
