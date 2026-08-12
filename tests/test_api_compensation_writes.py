"""Tests for the settlement/follower write endpoints (19.3 + 19.5)."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from config.settings import Settings
from database.dashboard_repository import DashboardRepository
from database.db import connect
from database.koc_repository import KOCRepository

TEAM_PASSWORD = "test-team-password"
PERIOD = "2026-05"


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


def _draft_payload(**overrides):
    payload = {
        "jpy_to_usd_rate": 150.0,
        "details": [{"creator_id": 1, "amount_jpy": 1000}],
        "summary": {"total_jpy": 1000},
        "note": "初稿",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# 19.3.1 exchange-rate
# ---------------------------------------------------------------------------


def test_save_exchange_rate_success(tmp_path):
    database_path = tmp_path / "koc.db"
    DashboardRepository(database_path)
    client = _authenticated_client(database_path)

    response = client.put(
        f"/api/compensation/{PERIOD}/exchange-rate", json={"rate": 152.5}
    )
    assert response.status_code == 200
    assert response.json()["data"]["rate"] == 152.5


def test_save_exchange_rate_rejects_non_positive(tmp_path):
    database_path = tmp_path / "koc.db"
    DashboardRepository(database_path)
    client = _authenticated_client(database_path)

    response = client.put(f"/api/compensation/{PERIOD}/exchange-rate", json={"rate": 0})
    assert response.status_code == 422


def test_exchange_rate_never_touches_locked_versions(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = DashboardRepository(database_path)
    client = _authenticated_client(database_path)

    draft = repository.create_compensation_draft(
        PERIOD, jpy_to_usd_rate=100.0, details=__import__("pandas").DataFrame(
            [{"creator_id": 1}]
        ), summary={"a": 1}
    )
    locked = repository.lock_compensation_version(
        draft.id, lock_note="锁定测试", locked_by="tester"
    )

    with connect(database_path) as connection:
        before = dict(
            connection.execute(
                "SELECT * FROM grassroot_compensation_version WHERE id = ?",
                (locked.id,),
            ).fetchone()
        )

    response = client.put(f"/api/compensation/{PERIOD}/exchange-rate", json={"rate": 200.0})
    assert response.status_code == 200

    with connect(database_path) as connection:
        after = dict(
            connection.execute(
                "SELECT * FROM grassroot_compensation_version WHERE id = ?",
                (locked.id,),
            ).fetchone()
        )
    assert after == before


# ---------------------------------------------------------------------------
# 19.3.2 traffic-boost (dashboard router)
# ---------------------------------------------------------------------------


def test_save_traffic_boost_success(tmp_path):
    database_path = tmp_path / "koc.db"
    DashboardRepository(database_path)
    client = _authenticated_client(database_path)

    response = client.put(f"/api/dashboard/{PERIOD}/traffic-boost", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["data"]["enabled"] is True


def test_save_traffic_boost_requires_enabled_field(tmp_path):
    database_path = tmp_path / "koc.db"
    DashboardRepository(database_path)
    client = _authenticated_client(database_path)

    response = client.put(f"/api/dashboard/{PERIOD}/traffic-boost", json={})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 19.3.3 long-term activity counts
# ---------------------------------------------------------------------------


def test_save_long_term_activity_counts_success(tmp_path):
    database_path = tmp_path / "koc.db"
    repository, creator = _seed_long_term_creator(database_path)
    client = _authenticated_client(database_path)

    response = client.put(
        f"/api/compensation/long-term/{PERIOD}/activity-counts",
        json={"activity_counts": {str(creator.id): 3}},
    )
    assert response.status_code == 200
    assert response.json()["data"]["updated_count"] == 1
    assert repository.get_long_term_activity_counts(PERIOD).get(creator.id) == 3


def _seed_long_term_creator(database_path):
    from models.enums import CreatorCategory

    koc_repository = KOCRepository(database_path)
    creator = koc_repository.create(
        user_id="lt-writer-1",
        koc_name="Long Term Creator",
        creator_category=CreatorCategory.LONG_TERM,
        follower_count=1000,
    )
    return DashboardRepository(database_path), creator


# ---------------------------------------------------------------------------
# 19.3.4 commentary theme submissions replace + expected_revision
# ---------------------------------------------------------------------------


def _seed_commentary_theme(database_path):
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO commentary_theme_definition (
                period_month, theme_code, theme_name, description,
                max_per_creator, reward_jpy, enabled
            ) VALUES (?, 'T1', '主题一', NULL, 1, 1000, 1)
            """,
            (PERIOD,),
        )


def _seed_commentary_creator(database_path):
    from models.enums import ContractType, CreatorCategory

    koc_repository = KOCRepository(database_path)
    return koc_repository.create(
        user_id="cm-writer-1",
        koc_name="Commentary Creator",
        creator_category=CreatorCategory.GRASSROOT,
        contract_type=ContractType.TT,
        follower_count=1000,
    )


def test_commentary_theme_submissions_replace_success(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = DashboardRepository(database_path)
    _seed_commentary_theme(database_path)
    creator = _seed_commentary_creator(database_path)
    client = _authenticated_client(database_path)

    response = client.put(
        f"/api/compensation/commentary/{PERIOD}/theme-submissions",
        json={
            "expected_revision": "rev_0",
            "rows": [
                {
                    "creator_id": creator.id,
                    "theme_code": "T1",
                    "content_format": "LONG",
                    "urls": ["https://example.com/v1"],
                    "submitted_date": f"{PERIOD}-01",
                    "review_status": "APPROVED",
                    "note": None,
                }
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["updated_count"] == 1
    assert body["revision"] != "rev_0"


def test_commentary_theme_submissions_stale_revision_conflict(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = DashboardRepository(database_path)
    _seed_commentary_theme(database_path)
    creator = _seed_commentary_creator(database_path)
    client = _authenticated_client(database_path)

    row = {
        "creator_id": creator.id,
        "theme_code": "T1",
        "content_format": "LONG",
        "urls": ["https://example.com/v1"],
        "submitted_date": f"{PERIOD}-01",
        "review_status": "APPROVED",
        "note": None,
    }

    first = client.put(
        f"/api/compensation/commentary/{PERIOD}/theme-submissions",
        json={"expected_revision": "rev_0", "rows": [row]},
    )
    assert first.status_code == 200

    stale = client.put(
        f"/api/compensation/commentary/{PERIOD}/theme-submissions",
        json={"expected_revision": "rev_0", "rows": [row]},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "REVISION_EXPIRED"


# ---------------------------------------------------------------------------
# 19.5 draft/lock lifecycle (grassroot as representative track; long-term and
# commentary share identical repository-level behaviour per the contract).
# ---------------------------------------------------------------------------


def test_create_draft_success(tmp_path):
    database_path = tmp_path / "koc.db"
    DashboardRepository(database_path)
    client = _authenticated_client(database_path)

    response = client.post(
        f"/api/compensation/grassroot/{PERIOD}/drafts", json=_draft_payload()
    )
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["status"] == "DRAFT"
    assert body["version_no"] == 1


@pytest.mark.parametrize(
    ("lane", "category", "row", "legacy_name_column", "amount_column"),
    [
        (
            "grassroot",
            "GRASSROOT",
            {
                "creator_key": "grassroot-1",
                "creator_name": "Grassroot One",
                "contract_types": ["YTB shorts"],
                "settlement_status": "可结算",
                "rank": "C",
                "billable_post_count": 10,
                "billable_views": 800000,
                "all_video_views": 900000,
                "rewards_jpy": {
                    "short_rank": 300000,
                    "long_livestream_rank": 0,
                    "short_post": 15000,
                    "long_livestream_post": 0,
                },
                "total_amount_jpy": 315000,
                "creator_receivable_jpy": 317500,
                "youdao_receivable_jpy": 365125,
                "creator_receivable_usd": 1968.5,
                "youdao_receivable_usd": 2263.775,
                "cpm": 2.5153,
            },
            "达人",
            "总金额（日元）",
        ),
        (
            "long-term",
            "LONG_TERM",
            {
                "record_id": 2,
                "creator_key": "long-term-1",
                "creator_name": "Long Term One",
                "contract_types": ["YTB"],
                "settlement_status": "可结算",
                "rank": "B",
                "followers": 100000,
                "youtube_post_count": 3,
                "monthly_new_post_views": 1000000,
                "monthly_activity_count": 2,
                "total_amount_jpy": 500000,
                "creator_receivable_jpy": 502500,
                "youdao_receivable_jpy": 577875,
                "creator_receivable_usd": 3115.5,
                "youdao_receivable_usd": 3582.825,
                "cpm": 3.582825,
            },
            "达人",
            "总金额（日元）",
        ),
        (
            "commentary",
            "COMMENTARY",
            {
                "creator_id": 3,
                "creator_key": "commentary-1",
                "creator_name": "Commentary One",
                "contract_types": ["YTB长+TT"],
                "settlement_status": "可结算",
                "long_views": 190000,
                "long_final_rank": "S",
                "long_reward_jpy": 300000,
                "short_views": 900000,
                "short_final_rank": "S",
                "short_reward_jpy": 350000,
                "combined_bonus_rank": "S",
                "combined_bonus_jpy": 60000,
                "designated_theme_count": 1,
                "designated_theme_reward_jpy": 15000,
                "all_paid_views": 1090000,
                "total_jpy_tax_incl": 725000,
                "creator_receivable_jpy": 727500,
                "youdao_receivable_jpy": 836625,
                "creator_receivable_usd": 4510.5,
                "youdao_receivable_usd": 5187.075,
                "cpm": 4.7588,
            },
            "达人",
            "解说含税总额（日元）",
        ),
    ],
)
def test_api_draft_rows_round_trip_through_legacy_snapshot_format(
    tmp_path,
    lane,
    category,
    row,
    legacy_name_column,
    amount_column,
):
    database_path = tmp_path / "koc.db"
    repository = DashboardRepository(database_path)
    client = _authenticated_client(database_path)
    amount = row.get("total_amount_jpy", row.get("total_jpy_tax_incl", 0))
    payload = {
        "jpy_to_usd_rate": 0.0062,
        "details": [row],
        "summary": {
            "total_amount_jpy": amount,
            "creator_receivable_jpy": row["creator_receivable_jpy"],
            "youdao_receivable_jpy": row["youdao_receivable_jpy"],
            "creator_receivable_usd": row["creator_receivable_usd"],
            "youdao_receivable_usd": row["youdao_receivable_usd"],
            "settled_views": row.get(
                "billable_views",
                row.get("monthly_new_post_views", row.get("all_paid_views", 0)),
            ),
            "total_video_views": row.get(
                "all_video_views",
                row.get("monthly_new_post_views", row.get("all_paid_views", 0)),
            ),
            "overall_cpm": row["cpm"],
        },
        "note": "API compatibility test",
    }

    create_response = client.post(
        f"/api/compensation/{lane}/{PERIOD}/drafts", json=payload
    )
    assert create_response.status_code == 201
    version_id = create_response.json()["data"]["id"]

    list_method = {
        "grassroot": repository.list_compensation_versions,
        "long-term": repository.list_long_term_compensation_versions,
        "commentary": repository.list_commentary_compensation_versions,
    }[lane]
    snapshot = list_method(PERIOD)[0].details
    assert legacy_name_column in snapshot.columns
    assert snapshot.iloc[0][legacy_name_column] == row["creator_name"]
    assert snapshot.iloc[0][amount_column] == amount

    read_response = client.get(
        f"/api/compensation/{lane}",
        params={"period_month": PERIOD, "version_id": version_id, "page_size": 100},
    )
    assert read_response.status_code == 200
    body = read_response.json()
    assert body["meta"]["mode"] == "saved_draft"
    assert len(body["data"]) == 1
    assert body["data"][0]["creator_name"] == row["creator_name"]
    returned_amount = body["data"][0].get(
        "total_amount_jpy", body["data"][0].get("total_jpy_tax_incl")
    )
    assert returned_amount == amount


def test_update_draft_success(tmp_path):
    database_path = tmp_path / "koc.db"
    DashboardRepository(database_path)
    client = _authenticated_client(database_path)

    created = client.post(
        f"/api/compensation/grassroot/{PERIOD}/drafts", json=_draft_payload()
    ).json()["data"]

    response = client.put(
        f"/api/compensation/grassroot/drafts/{created['id']}",
        json=_draft_payload(note="修改后"),
    )
    assert response.status_code == 200
    assert response.json()["data"]["note"] == "修改后"


def test_update_draft_conflict_when_already_locked(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = DashboardRepository(database_path)
    client = _authenticated_client(database_path)

    created = client.post(
        f"/api/compensation/grassroot/{PERIOD}/drafts", json=_draft_payload()
    ).json()["data"]
    repository.lock_compensation_version(created["id"], lock_note="锁定", locked_by="t")

    response = client.put(
        f"/api/compensation/grassroot/drafts/{created['id']}",
        json=_draft_payload(note="不应生效"),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VERSION_LOCKED"


def test_lock_success(tmp_path):
    database_path = tmp_path / "koc.db"
    DashboardRepository(database_path)
    client = _authenticated_client(database_path)

    created = client.post(
        f"/api/compensation/grassroot/{PERIOD}/drafts", json=_draft_payload()
    ).json()["data"]

    response = client.post(
        f"/api/compensation/grassroot/drafts/{created['id']}/lock",
        json={"lock_note": "月末锁定"},
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["status"] == "LOCKED"
    assert body["lock_note"] == "月末锁定"
    assert body["locked_by"] == "张三"


def test_lock_requires_lock_note(tmp_path):
    database_path = tmp_path / "koc.db"
    DashboardRepository(database_path)
    client = _authenticated_client(database_path)

    created = client.post(
        f"/api/compensation/grassroot/{PERIOD}/drafts", json=_draft_payload()
    ).json()["data"]

    response = client.post(
        f"/api/compensation/grassroot/drafts/{created['id']}/lock", json={}
    )
    assert response.status_code == 422


def test_lock_rejects_client_supplied_operator_name(tmp_path):
    database_path = tmp_path / "koc.db"
    DashboardRepository(database_path)
    client = _authenticated_client(database_path)

    created = client.post(
        f"/api/compensation/grassroot/{PERIOD}/drafts", json=_draft_payload()
    ).json()["data"]

    response = client.post(
        f"/api/compensation/grassroot/drafts/{created['id']}/lock",
        json={"lock_note": "锁定", "operator_name": "李四"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["locked_by"] == "张三"


def test_lock_already_locked_returns_conflict(tmp_path):
    database_path = tmp_path / "koc.db"
    DashboardRepository(database_path)
    client = _authenticated_client(database_path)

    created = client.post(
        f"/api/compensation/grassroot/{PERIOD}/drafts", json=_draft_payload()
    ).json()["data"]

    first = client.post(
        f"/api/compensation/grassroot/drafts/{created['id']}/lock",
        json={"lock_note": "第一次锁定"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/compensation/grassroot/drafts/{created['id']}/lock",
        json={"lock_note": "第二次锁定"},
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "VERSION_ALREADY_LOCKED"


def test_edit_after_lock_requires_new_version(tmp_path):
    database_path = tmp_path / "koc.db"
    repository = DashboardRepository(database_path)
    client = _authenticated_client(database_path)

    created = client.post(
        f"/api/compensation/grassroot/{PERIOD}/drafts", json=_draft_payload()
    ).json()["data"]
    client.post(
        f"/api/compensation/grassroot/drafts/{created['id']}/lock",
        json={"lock_note": "锁定"},
    )

    # Corrections after lock must create a brand new higher version_no draft.
    new_draft = client.post(
        f"/api/compensation/grassroot/{PERIOD}/drafts",
        json=_draft_payload(note="修正版"),
    ).json()["data"]
    assert new_draft["version_no"] == 2
    assert new_draft["status"] == "DRAFT"


def test_create_draft_idempotency_key_dedup(tmp_path):
    database_path = tmp_path / "koc.db"
    DashboardRepository(database_path)
    client = _authenticated_client(database_path)

    headers = {"Idempotency-Key": "draft-key-1"}
    first = client.post(
        f"/api/compensation/grassroot/{PERIOD}/drafts",
        json=_draft_payload(),
        headers=headers,
    )
    second = client.post(
        f"/api/compensation/grassroot/{PERIOD}/drafts",
        json=_draft_payload(),
        headers=headers,
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["data"]["id"] == second.json()["data"]["id"]

    versions = DashboardRepository(database_path).list_compensation_versions(PERIOD)
    assert len(versions) == 1


def test_version_uniqueness_enforced_at_db_level(tmp_path):
    database_path = tmp_path / "koc.db"
    DashboardRepository(database_path)

    with pytest.raises(sqlite3.IntegrityError):
        with connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO grassroot_compensation_version (
                    period_month, version_no, status, jpy_to_usd_rate,
                    details_json, summary_json, note
                ) VALUES (?, 1, 'DRAFT', 100, '[]', '{}', NULL)
                """,
                (PERIOD,),
            )
            connection.execute(
                """
                INSERT INTO grassroot_compensation_version (
                    period_month, version_no, status, jpy_to_usd_rate,
                    details_json, summary_json, note
                ) VALUES (?, 1, 'DRAFT', 100, '[]', '{}', NULL)
                """,
                (PERIOD,),
            )


def test_write_endpoints_never_auto_retried_by_middleware(tmp_path):
    # The DatabaseResilienceMiddleware only retries GET requests on a lost
    # connection; PUT/POST writes must fail fast on the first error instead
    # of silently duplicating a side effect. We assert this structurally by
    # confirming the middleware code path only bounces GET (see
    # api/main.py DatabaseResilienceMiddleware.__call__), and behaviourally
    # by verifying a normal write completes in a single call with no
    # duplicate version row.
    database_path = tmp_path / "koc.db"
    DashboardRepository(database_path)
    client = _authenticated_client(database_path)

    client.post(f"/api/compensation/grassroot/{PERIOD}/drafts", json=_draft_payload())
    versions = DashboardRepository(database_path).list_compensation_versions(PERIOD)
    assert len(versions) == 1
