from pathlib import Path

from core.dashboard_processor import DASHBOARD_DETAIL_COLUMNS
from database.postgres_schema import (
    POSTGRES_IMPORT_ROLLBACK_AND_LOCK_AUDIT_STATEMENTS,
    POSTGRES_SCHEMA_STATEMENTS,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

CREATOR_PLATFORM_FIELDS = {
    "youtube_user_id",
    "youtube_homepage_url",
    "youtube_follower_count",
    "tiktok_user_id",
    "tiktok_homepage_url",
    "tiktok_follower_count",
    "settlement_eligible",
}

POST_DETAIL_FIELDS = set(DASHBOARD_DETAIL_COLUMNS) | {
    "original_views",
    "traffic_boost_views",
    "boosted_views",
}


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_postgres_forward_schema_covers_import_rollback_and_lock_audit():
    schema = "\n".join(POSTGRES_SCHEMA_STATEMENTS)
    forward = "\n".join(POSTGRES_IMPORT_ROLLBACK_AND_LOCK_AUDIT_STATEMENTS)

    assert "CREATE TABLE IF NOT EXISTS dashboard_import_batch_snapshot" in schema
    assert "rolled_back_at TEXT" in schema
    assert "CREATE TABLE IF NOT EXISTS dashboard_import_batch_snapshot" in forward
    assert "ADD COLUMN IF NOT EXISTS rolled_back_at" in forward
    for table in (
        "grassroot_compensation_version",
        "long_term_compensation_version",
        "commentary_compensation_version",
    ):
        assert f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS lock_note" in forward
        assert f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS locked_by" in forward


def test_creator_platform_fields_map_through_api_types_and_edit_ui():
    serializer = _read("api/serializers.py")
    update_api = _read("api/creators.py")
    frontend_types = _read("frontend/src/lib/types.ts")
    creator_page = _read("frontend/src/app/creators/page.tsx")

    for field in CREATOR_PLATFORM_FIELDS:
        assert f'"{field}"' in serializer
        write_field = (
            "manual_settlement_eligible"
            if field == "settlement_eligible"
            else field
        )
        assert f'"{write_field}"' in update_api
        assert field in frontend_types
        assert field in creator_page


def test_dashboard_post_fields_map_through_api_types_and_configurable_table():
    serializer = _read("api/dashboard.py")
    frontend_types = _read("frontend/src/lib/types.ts")
    dashboard_page = _read("frontend/src/app/dashboard/page.tsx")

    for field in POST_DETAIL_FIELDS:
        assert f'"{field}"' in serializer, f"API missing {field}"
        assert field in frontend_types, f"TypeScript type missing {field}"
        assert f'key: "{field}"' in dashboard_page, f"table column missing {field}"


def test_dashboard_comparison_and_all_rankings_are_wired_to_frontend():
    dashboard_page = _read("frontend/src/app/dashboard/page.tsx")
    assert "dashboardApi.comparison" in dashboard_page
    for ranking_type in (
        "creator_views_top10",
        "creator_posts_top10",
        "creator_ytb_top30",
        "creator_tt_top30",
        "video_ytb_top20",
        "video_tt_top20",
    ):
        assert ranking_type in dashboard_page


def test_all_compensation_fields_and_lock_audit_are_visible():
    columns = _read("frontend/src/app/compensation/columns.tsx")
    page = _read("frontend/src/app/compensation/page.tsx")
    api = _read("api/compensation.py")
    frontend_types = _read("frontend/src/lib/types.ts")

    required_columns = {
        "youtube_followers",
        "tiktok_followers",
        "cpm_views_no_boost",
        "creator_receivable_jpy",
        "youdao_receivable_jpy",
        "creator_receivable_usd",
        "youdao_receivable_usd",
        "expected_cpm_jpy",
        "youtube_uid",
        "tiktok_uid",
        "long_view_rank",
        "long_follower_cap_rank",
        "long_reward_jpy",
        "short_view_rank",
        "short_follower_cap_rank",
        "short_reward_jpy",
        "combined_bonus_rank",
        "total_jpy_tax_incl",
    }
    for field in required_columns:
        assert f'key: "{field}"' in columns
    for field in ("lock_note", "locked_by"):
        assert field in page
        assert f'"{field}"' in api
        assert field in frontend_types
