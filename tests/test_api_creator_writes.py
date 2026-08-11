"""Tests for the first batch of creator/contract write endpoints (19.1)."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from api.main import create_app
from config.settings import Settings
from database.db import connect
from database.koc_repository import KOCRepository
from models.enums import ContractType, CreatorCategory

TEAM_PASSWORD = "test-team-password"
PREFIX = "writetestuid-"


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
    login_response = client.post(
        "/api/auth/login",
        json={"password": TEAM_PASSWORD, "operator_name": "张三"},
    )
    assert login_response.status_code == 200
    return client


def _seed_creator(database_path, **overrides):
    repository = KOCRepository(database_path)
    kwargs = dict(
        user_id=f"{PREFIX}base",
        koc_name="Base Creator",
        creator_category=CreatorCategory.GRASSROOT,
        contract_type=ContractType.TT,
        follower_count=1000,
    )
    kwargs.update(overrides)
    record = repository.create(**kwargs)
    return repository, record


# ---------------------------------------------------------------------------
# 1. POST /api/creators
# ---------------------------------------------------------------------------


def test_create_creator_success(tmp_path):
    database_path = tmp_path / "koc.db"
    KOCRepository(database_path)
    client = _authenticated_client(database_path)

    response = client.post(
        "/api/creators",
        json={
            "user_id": f"{PREFIX}new1",
            "koc_name": "New Creator",
            "creator_category": "GRASSROOT",
            "contract_types": ["TT"],
            "follower_count": 500,
        },
    )

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["user_id"] == f"{PREFIX}new1"
    assert body["contract_types"] == ["TT"]
    assert "contract_periods" in body


def test_create_creator_duplicate_user_id_returns_409(tmp_path):
    database_path = tmp_path / "koc.db"
    _seed_creator(database_path)
    client = _authenticated_client(database_path)

    response = client.post(
        "/api/creators",
        json={
            "user_id": f"{PREFIX}base",
            "koc_name": "Duplicate",
            "creator_category": "GRASSROOT",
            "contract_types": ["TT"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_create_creator_rejects_client_supplied_operator_name(tmp_path):
    database_path = tmp_path / "koc.db"
    KOCRepository(database_path)
    client = _authenticated_client(database_path)

    response = client.post(
        "/api/creators",
        json={
            "user_id": f"{PREFIX}newop",
            "koc_name": "New Creator",
            "creator_category": "GRASSROOT",
            "contract_types": ["TT"],
            "operator_name": "李四",
        },
    )

    assert response.status_code == 201
    # operator_name is silently ignored, never stored as a creator field.
    assert "operator_name" not in response.json()["data"]


def test_create_creator_idempotency_key_returns_cached_result(tmp_path):
    database_path = tmp_path / "koc.db"
    KOCRepository(database_path)
    client = _authenticated_client(database_path)
    body = {
        "user_id": f"{PREFIX}idem1",
        "koc_name": "Idempotent Creator",
        "creator_category": "GRASSROOT",
        "contract_types": ["TT"],
    }

    first = client.post("/api/creators", json=body, headers={"Idempotency-Key": "key-1"})
    second = client.post("/api/creators", json=body, headers={"Idempotency-Key": "key-1"})

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()

    repository = KOCRepository(database_path)
    records = repository.list(search=f"{PREFIX}idem1")
    assert len(records) == 1


# ---------------------------------------------------------------------------
# 2. PUT /api/creators/{id}
# ---------------------------------------------------------------------------


def test_update_creator_basic_profile_success(tmp_path):
    database_path = tmp_path / "koc.db"
    _, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)

    response = client.put(
        f"/api/creators/{record.id}",
        json={
            "user_id": record.user_id,
            "koc_name": "Renamed Creator",
            "creator_category": "GRASSROOT",
            "contract_types": ["TT"],
            "homepage_url": None,
            "follower_count": 2000,
            "active": True,
            "manual_follower_update": True,
        },
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["koc_name"] == "Renamed Creator"
    assert body["follower_count"] == 2000


def test_update_creator_not_found_returns_404(tmp_path):
    database_path = tmp_path / "koc.db"
    KOCRepository(database_path)
    client = _authenticated_client(database_path)

    response = client.put(
        "/api/creators/999999",
        json={
            "user_id": "does-not-exist",
            "koc_name": "X",
            "creator_category": "GRASSROOT",
            "contract_types": ["TT"],
            "homepage_url": None,
            "follower_count": 1,
            "active": True,
        },
    )

    assert response.status_code == 404


def test_update_creator_rejects_implicit_contract_change(tmp_path):
    database_path = tmp_path / "koc.db"
    _, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)

    response = client.put(
        f"/api/creators/{record.id}",
        json={
            "user_id": record.user_id,
            "koc_name": record.koc_name,
            "creator_category": "GRASSROOT",
            "contract_types": ["TT", "YTB"],
            "homepage_url": None,
            "follower_count": record.follower_count,
            "active": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_update_creator_stale_if_unmodified_since_returns_409(tmp_path):
    database_path = tmp_path / "koc.db"
    _, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)

    response = client.put(
        f"/api/creators/{record.id}",
        json={
            "user_id": record.user_id,
            "koc_name": "Changed elsewhere",
            "creator_category": "GRASSROOT",
            "contract_types": ["TT"],
            "homepage_url": None,
            "follower_count": record.follower_count,
            "active": True,
        },
        headers={"If-Unmodified-Since": "2000-01-01T00:00:00+00:00"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


# ---------------------------------------------------------------------------
# 3. PATCH /api/creators/{id}/active
# ---------------------------------------------------------------------------


def test_set_active_success(tmp_path):
    database_path = tmp_path / "koc.db"
    _, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)

    response = client.patch(f"/api/creators/{record.id}/active", json={"active": False})

    assert response.status_code == 200
    assert response.json()["data"]["active"] is False


def test_set_active_not_found(tmp_path):
    database_path = tmp_path / "koc.db"
    KOCRepository(database_path)
    client = _authenticated_client(database_path)

    response = client.patch("/api/creators/999999/active", json={"active": False})

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 4. POST /api/creators/{id}/contract-changes
# ---------------------------------------------------------------------------


def test_create_contract_change_success(tmp_path):
    database_path = tmp_path / "koc.db"
    _, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)

    response = client.post(
        f"/api/creators/{record.id}/contract-changes",
        json={
            "effective_date": "2026-09-01",
            "contract_types": ["TT", "YTB"],
            "reason": "9月起新增YTB合同",
        },
    )

    assert response.status_code == 201
    body = response.json()["data"]
    periods = body["contract_periods"]
    assert any(p["contract_types"] == ["TT", "YTB"] for p in periods)


def test_create_contract_change_conflict_on_existing_period(tmp_path):
    database_path = tmp_path / "koc.db"
    _, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)

    response = client.post(
        f"/api/creators/{record.id}/contract-changes",
        json={
            "effective_date": record.contract_start_date.isoformat(),
            "contract_types": ["TT"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_create_contract_change_idempotency_key_dedupes(tmp_path):
    database_path = tmp_path / "koc.db"
    repository, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)
    body = {"effective_date": "2026-09-01", "contract_types": ["TT", "YTB"]}

    first = client.post(
        f"/api/creators/{record.id}/contract-changes",
        json=body,
        headers={"Idempotency-Key": "chg-1"},
    )
    second = client.post(
        f"/api/creators/{record.id}/contract-changes",
        json=body,
        headers={"Idempotency-Key": "chg-1"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    revisions = repository.list_contract_revisions(record.id)
    change_revisions = [r for r in revisions if r.operation_type == "CHANGE"]
    assert len(change_revisions) == 1


def test_create_contract_change_and_correction_produce_distinct_operation_types(tmp_path):
    database_path = tmp_path / "koc.db"
    repository, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)

    client.post(
        f"/api/creators/{record.id}/contract-changes",
        json={"effective_date": "2026-09-01", "contract_types": ["TT", "YTB"]},
    )
    client.post(
        f"/api/creators/{record.id}/contract-corrections",
        json={
            "source_effective_date": "2026-09-01",
            "contract_types": ["YTB"],
            "contract_start_date": "2026-09-01",
            "contract_end_date": "2026-10-31",
            "reason": "录入错误，实际仅YTB",
        },
    )

    revisions = repository.list_contract_revisions(record.id)
    operation_types = {r.operation_type for r in revisions}
    assert "CHANGE" in operation_types
    assert "CORRECTION" in operation_types


# ---------------------------------------------------------------------------
# 5. POST /api/creators/{id}/contract-corrections
# ---------------------------------------------------------------------------


def test_create_contract_correction_success(tmp_path):
    database_path = tmp_path / "koc.db"
    _, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)
    source_date = record.contract_start_date.isoformat()

    response = client.post(
        f"/api/creators/{record.id}/contract-corrections",
        json={
            "source_effective_date": source_date,
            "contract_types": ["YTB"],
            "contract_start_date": source_date,
            "contract_end_date": record.contract_end_date.isoformat(),
            "reason": "原录入错误",
        },
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert any(p["contract_types"] == ["YTB"] for p in body["contract_periods"])


def test_create_contract_correction_no_change_flag(tmp_path):
    database_path = tmp_path / "koc.db"
    repository, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)
    source_date = record.contract_start_date.isoformat()
    end_date = record.contract_end_date.isoformat()

    payload = {
        "source_effective_date": source_date,
        "contract_types": ["TT"],
        "contract_start_date": source_date,
        "contract_end_date": end_date,
        "reason": "重复提交确认",
    }
    response = client.post(
        f"/api/creators/{record.id}/contract-corrections", json=payload
    )

    assert response.status_code == 200
    assert response.json()["data"].get("no_change") is True
    revisions = repository.list_contract_revisions(record.id)
    assert not any(r.operation_type == "CORRECTION" for r in revisions)


def test_create_contract_correction_overlap_returns_409(tmp_path):
    database_path = tmp_path / "koc.db"
    repository, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)
    repository.create_contract_change(
        record.id,
        effective_date="2026-11-01",
        contract_types=["TT"],
        contract_end_date="2026-12-31",
    )
    source_date = record.contract_start_date.isoformat()

    response = client.post(
        f"/api/creators/{record.id}/contract-corrections",
        json={
            "source_effective_date": source_date,
            "contract_types": ["TT"],
            "contract_start_date": source_date,
            "contract_end_date": "2026-11-15",
            "reason": "test overlap",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_create_contract_correction_stale_expected_updated_at_returns_409(tmp_path):
    database_path = tmp_path / "koc.db"
    _, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)
    source_date = record.contract_start_date.isoformat()

    response = client.post(
        f"/api/creators/{record.id}/contract-corrections",
        json={
            "source_effective_date": source_date,
            "contract_types": ["YTB"],
            "contract_start_date": source_date,
            "contract_end_date": record.contract_end_date.isoformat(),
            "reason": "changed by someone else",
            "expected_updated_at": "2000-01-01T00:00:00+00:00",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REVISION_EXPIRED"


# ---------------------------------------------------------------------------
# 6. DELETE /api/creators/{id}/contract-periods/{source_effective_date}
# ---------------------------------------------------------------------------


def test_delete_contract_period_success_and_audit_trail(tmp_path):
    database_path = tmp_path / "koc.db"
    repository, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)
    repository.create_contract_change(
        record.id,
        effective_date="2026-09-01",
        contract_types=["TT", "YTB"],
        contract_end_date="2026-10-31",
    )
    source_date = record.contract_start_date.isoformat()

    response = client.request(
        "DELETE",
        f"/api/creators/{record.id}/contract-periods/{source_date}",
        json={"reason": "录入失误产生的多余周期"},
    )

    assert response.status_code == 200
    revisions = repository.list_contract_revisions(record.id)
    assert any(r.operation_type == "DELETE" for r in revisions)


def test_delete_contract_period_twice_returns_404(tmp_path):
    database_path = tmp_path / "koc.db"
    repository, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)
    repository.create_contract_change(
        record.id,
        effective_date="2026-09-01",
        contract_types=["TT", "YTB"],
        contract_end_date="2026-10-31",
    )
    repository.create_contract_change(
        record.id,
        effective_date="2026-12-01",
        contract_types=["TT"],
        contract_end_date="2027-01-31",
    )
    source_date = record.contract_start_date.isoformat()

    first = client.request(
        "DELETE", f"/api/creators/{record.id}/contract-periods/{source_date}"
    )
    second = client.request(
        "DELETE", f"/api/creators/{record.id}/contract-periods/{source_date}"
    )

    assert first.status_code == 200
    assert second.status_code == 404


def test_delete_last_remaining_period_returns_422(tmp_path):
    database_path = tmp_path / "koc.db"
    _, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)
    source_date = record.contract_start_date.isoformat()

    response = client.request(
        "DELETE", f"/api/creators/{record.id}/contract-periods/{source_date}"
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 7. POST /api/creators/{id}/contract-revisions/{revision_id}/revert
# ---------------------------------------------------------------------------


def test_revert_contract_revision_success_and_creates_revert_record(tmp_path):
    database_path = tmp_path / "koc.db"
    repository, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)
    updated = repository.create_contract_change(
        record.id,
        effective_date="2026-09-01",
        contract_types=["TT", "YTB"],
        contract_end_date="2026-10-31",
    )
    revisions = repository.list_contract_revisions(record.id)
    latest = max(revisions, key=lambda r: r.id)

    response = client.post(
        f"/api/creators/{record.id}/contract-revisions/{latest.id}/revert",
        json={"reason": "误操作，实际不应新增该合同变更"},
    )

    assert response.status_code == 200
    revisions_after = repository.list_contract_revisions(record.id)
    assert any(r.operation_type == "REVERT" for r in revisions_after)
    reverted_original = next(r for r in revisions_after if r.id == latest.id)
    assert reverted_original.reverted_at is not None


def test_revert_contract_revision_requires_reason(tmp_path):
    database_path = tmp_path / "koc.db"
    repository, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)
    repository.create_contract_change(
        record.id,
        effective_date="2026-09-01",
        contract_types=["TT", "YTB"],
        contract_end_date="2026-10-31",
    )
    latest = max(repository.list_contract_revisions(record.id), key=lambda r: r.id)

    response = client.post(
        f"/api/creators/{record.id}/contract-revisions/{latest.id}/revert",
        json={"reason": ""},
    )

    assert response.status_code == 422


def test_revert_contract_revision_rejects_over_500_chars(tmp_path):
    database_path = tmp_path / "koc.db"
    repository, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)
    repository.create_contract_change(
        record.id,
        effective_date="2026-09-01",
        contract_types=["TT", "YTB"],
        contract_end_date="2026-10-31",
    )
    latest = max(repository.list_contract_revisions(record.id), key=lambda r: r.id)

    response = client.post(
        f"/api/creators/{record.id}/contract-revisions/{latest.id}/revert",
        json={"reason": "x" * 501},
    )

    assert response.status_code == 422


def test_revert_contract_revision_idempotency_key_dedupes(tmp_path):
    database_path = tmp_path / "koc.db"
    repository, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)
    repository.create_contract_change(
        record.id,
        effective_date="2026-09-01",
        contract_types=["TT", "YTB"],
        contract_end_date="2026-10-31",
    )
    latest = max(repository.list_contract_revisions(record.id), key=lambda r: r.id)
    body = {"reason": "误操作"}

    first = client.post(
        f"/api/creators/{record.id}/contract-revisions/{latest.id}/revert",
        json=body,
        headers={"Idempotency-Key": "revert-1"},
    )
    second = client.post(
        f"/api/creators/{record.id}/contract-revisions/{latest.id}/revert",
        json=body,
        headers={"Idempotency-Key": "revert-1"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    revert_records = [
        r for r in repository.list_contract_revisions(record.id) if r.operation_type == "REVERT"
    ]
    assert len(revert_records) == 1


def test_revert_contract_revision_non_latest_returns_409(tmp_path):
    database_path = tmp_path / "koc.db"
    repository, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)
    repository.create_contract_change(
        record.id,
        effective_date="2026-09-01",
        contract_types=["TT", "YTB"],
        contract_end_date="2026-10-31",
    )
    first_change = min(repository.list_contract_revisions(record.id), key=lambda r: r.id)
    repository.create_contract_change(
        record.id,
        effective_date="2026-12-01",
        contract_types=["TT"],
        contract_end_date="2027-01-31",
    )

    response = client.post(
        f"/api/creators/{record.id}/contract-revisions/{first_change.id}/revert",
        json={"reason": "尝试跳跃式撤销"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


# ---------------------------------------------------------------------------
# 7b. GET /api/creators/{id}/contract-revisions
# ---------------------------------------------------------------------------


def test_list_contract_revisions_returns_mixed_operation_types_with_flags(tmp_path):
    database_path = tmp_path / "koc.db"
    repository, record = _seed_creator(database_path)
    client = _authenticated_client(database_path)

    repository.create_contract_change(
        record.id,
        effective_date="2026-09-01",
        contract_types=["TT", "YTB"],
        contract_end_date="2026-10-31",
        reason="新增YTB合同",
    )
    repository.correct_contract_period(
        record.id,
        source_effective_date="2026-09-01",
        contract_types=["YTB"],
        contract_start_date="2026-09-01",
        contract_end_date="2026-10-31",
        reason="录入错误更正",
    )
    repository.delete_authoritative_contract_period(
        record.id,
        source_effective_date=record.contract_start_date.isoformat(),
        reason="清除多余周期",
    )
    revisions_before = repository.list_contract_revisions(record.id)
    latest_change = max(
        (r for r in revisions_before if r.operation_type == "CHANGE"),
        key=lambda r: r.id,
    )
    # The only revertable revision is the most recent un-reverted, non-REVERT
    # one; here that's the DELETE — revert it to also exercise REVERT rows.
    client.post(
        f"/api/creators/{record.id}/contract-revisions/"
        f"{max(revisions_before, key=lambda r: r.id).id}/revert",
        json={"reason": "撤销删除，恢复周期"},
    )

    response = client.get(f"/api/creators/{record.id}/contract-revisions")

    assert response.status_code == 200
    data = response.json()["data"]
    operation_types = {row["operation_type"] for row in data}
    assert {"CHANGE", "CORRECTION", "DELETE", "REVERT"} <= operation_types

    delete_rows = [row for row in data if row["operation_type"] == "DELETE"]
    assert delete_rows, "expected the deleted contract period to be present"
    assert all(row["is_deleted_period"] is True for row in delete_rows)
    assert all(row["revertable"] is False for row in delete_rows)
    assert all(row["status"] == "REVERTED" for row in delete_rows)

    revert_rows = [row for row in data if row["operation_type"] == "REVERT"]
    assert revert_rows
    assert all(row["revertable"] is False for row in revert_rows)
    assert all(row["status"] == "REVERT_RECORD" for row in revert_rows)

    # Snapshot content: before/after periods survive the round trip.
    change_row = next(row for row in data if row["id"] == latest_change.id)
    assert change_row["before_periods"] == list(latest_change.before_periods)
    assert change_row["after_periods"] == list(latest_change.after_periods)
    assert change_row["reason"] == "录入错误更正" or change_row["reason"] == "新增YTB合同"

    revertable_rows = [row for row in data if row["revertable"] is True]
    assert len(revertable_rows) == 1
    assert revertable_rows[0]["status"] == "REVERTABLE"


def test_list_contract_revisions_not_found_returns_404(tmp_path):
    database_path = tmp_path / "koc.db"
    KOCRepository(database_path)
    client = _authenticated_client(database_path)

    response = client.get("/api/creators/999999/contract-revisions")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_list_contract_revisions_requires_authentication(tmp_path):
    database_path = tmp_path / "koc.db"
    _, record = _seed_creator(database_path)
    app = create_app(_settings(database_path), environment="development")
    client = TestClient(app)

    response = client.get(f"/api/creators/{record.id}/contract-revisions")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 8. LOCKED settlement versions must never be touched by creator/contract writes
# ---------------------------------------------------------------------------


def _insert_locked_grassroot_version(database_path):
    with connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO grassroot_compensation_version (
                period_month, version_no, status, jpy_to_usd_rate,
                details_json, summary_json, note
            ) VALUES (?, ?, 'LOCKED', ?, ?, ?, ?)
            """,
            (
                "2026-05",
                1,
                150.0,
                json.dumps({"rows": []}),
                json.dumps({"total": 0}),
                "locked fixture",
            ),
        )
        version_id = int(cursor.lastrowid)
        row = connection.execute(
            "SELECT * FROM grassroot_compensation_version WHERE id = ?",
            (version_id,),
        ).fetchone()
        return version_id, dict(row)


def test_creator_writes_never_affect_locked_settlement_versions(tmp_path):
    database_path = tmp_path / "koc.db"
    repository, record = _seed_creator(database_path)
    version_id, before_snapshot = _insert_locked_grassroot_version(database_path)
    client = _authenticated_client(database_path)

    client.put(
        f"/api/creators/{record.id}",
        json={
            "user_id": record.user_id,
            "koc_name": "Renamed For Lock Test",
            "creator_category": "GRASSROOT",
            "contract_types": ["TT"],
            "homepage_url": None,
            "follower_count": 9999,
            "active": True,
            "manual_follower_update": True,
        },
    )
    client.post(
        f"/api/creators/{record.id}/contract-changes",
        json={"effective_date": "2026-09-01", "contract_types": ["TT", "YTB"]},
    )
    client.patch(f"/api/creators/{record.id}/active", json={"active": False})

    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM grassroot_compensation_version WHERE id = ?",
            (version_id,),
        ).fetchone()
        after_snapshot = dict(row)

    assert after_snapshot == before_snapshot
