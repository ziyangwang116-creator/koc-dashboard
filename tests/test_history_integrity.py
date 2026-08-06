from datetime import date

import pandas as pd
import pytest

from core.dashboard_processor import enrich_dashboard_creator_metadata
from core.grassroot_compensation import calculate_grassroot_compensation
from database.dashboard_repository import DashboardRepository
from database.koc_repository import KOCRepository
from models.enums import CreatorCategory
from services.follower_service import FollowerService


def _post(url: str, published: date, title: str) -> dict[str, object]:
    return {
        "source_file": "export.xlsx",
        "source_platform": "YouTube",
        "url": url,
        "user_id": "creator-1",
        "publish_date": published,
        "timestamp": published.isoformat(),
        "title": title,
    }


def test_complete_month_reimport_removes_posts_missing_from_new_export(tmp_path):
    repository = DashboardRepository(tmp_path / "dashboard.db")
    repository.save_monthly_import(
        pd.DataFrame(
            [
                _post("https://example.com/june-old", date(2026, 6, 1), "old"),
                _post("https://example.com/june-keep", date(2026, 6, 2), "keep"),
                _post("https://example.com/july", date(2026, 7, 1), "july"),
            ]
        ),
        replace_months=True,
        source_files=["initial.xlsx"],
        file_hashes={"initial.xlsx": "first"},
    )

    saved = repository.save_monthly_import(
        pd.DataFrame(
            [_post("https://example.com/june-keep", date(2026, 6, 2), "updated")]
        ),
        replace_months=True,
        source_files=["june-complete.xlsx"],
        file_hashes={"june-complete.xlsx": "second"},
    )
    loaded = repository.load_posts()

    assert saved.removed_count == 2
    assert set(loaded["url"]) == {
        "https://example.com/june-keep",
        "https://example.com/july",
    }
    assert repository.list_import_batches().iloc[0]["\u6570\u636e\u6708\u4efd"] == "2026-06"


def test_profile_effective_date_preserves_old_contract_and_settles_each_period(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="creator-1",
        koc_name="before-change",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["TT"],
        follower_count=1_000,
        effective_date=date(2026, 6, 1),
    )
    repository.update(
        record.id,
        user_id=record.user_id,
        koc_name="after-change",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["YTB"],
        homepage_url=None,
        follower_count=1_000,
        active=True,
        note=None,
        effective_date=date(2026, 6, 16),
    )

    raw_posts = pd.DataFrame(
        [
            {"user_id": "creator-1", "publish_date": date(2026, 6, 10), "subtype": "tiktok", "views": 500_000},
            {"user_id": "creator-1", "publish_date": date(2026, 6, 20), "subtype": "long", "views": 1_200_000},
        ]
    )
    enriched = enrich_dashboard_creator_metadata(
        raw_posts,
        repository.list(include_inactive=True),
        repository.list_profile_history(),
    )
    result = calculate_grassroot_compensation(
        enriched,
        repository.list(include_inactive=True),
        jpy_to_usd_rate=0.0062,
    )

    assert enriched["contract_types"].tolist() == ["TT", "YTB"]
    assert len(result.details) == 1
    detail = result.details.iloc[0]
    assert detail["\u5408\u540c\u7c7b\u578b"] == "TT\u3001YTB"
    assert detail["\u8ba1\u8d39\u64ad\u653e\u91cf"] == 1_700_000
    assert detail["rank"] == "D+\u3001S"
    assert detail["\u603b\u91d1\u989d\uff08\u65e5\u5143\uff09"] == 2_200_000


def test_follower_profile_refreshes_do_not_duplicate_grassroot_settlement(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="creator-1",
        koc_name="before-refresh",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["TT"],
        follower_count=1_000,
        effective_date=date(2026, 6, 1),
    )
    data = pd.DataFrame(
        [
            {
                "creator_id": record.id,
                "creator_active": True,
                "profile_status": "MATCHED",
                "profile_effective_date": "2026-06-01",
                "creator_category": "草根",
                "contract_types": "TT",
                "contract_start_date": "2026-05-01",
                "contract_end_date": "2026-10-31",
                "follower_count": 1_000,
                "user_id": record.user_id,
                "koc_name": "before-refresh",
                "publish_date": date(2026, 6, 10),
                "subtype": "tiktok",
                "views": 250_000,
            },
            {
                "creator_id": record.id,
                "creator_active": True,
                "profile_status": "MATCHED",
                "profile_effective_date": "2026-06-20",
                "creator_category": "草根",
                "contract_types": "TT",
                "contract_start_date": "2026-05-01",
                "contract_end_date": "2026-10-31",
                "follower_count": 2_000,
                "user_id": record.user_id,
                "koc_name": "after-refresh",
                "publish_date": date(2026, 6, 25),
                "subtype": "tiktok",
                "views": 250_000,
            },
        ]
    )

    result = calculate_grassroot_compensation(
        data,
        repository.list(include_inactive=True),
        jpy_to_usd_rate=0.0062,
    )

    assert len(result.details) == 1
    detail = result.details.iloc[0]
    assert detail["达人"] == "after-refresh"
    assert detail["粉丝数"] == 2_000
    assert detail["计费播放量"] == 500_000
    assert detail["结算状态"] == "可结算"
    assert detail["rank"] == "D+"


def test_locked_compensation_version_cannot_be_rewritten_by_live_data(tmp_path):
    repository = DashboardRepository(tmp_path / "dashboard.db")
    draft = repository.create_compensation_draft(
        "2026-06",
        jpy_to_usd_rate=0.0062,
        details=pd.DataFrame([{"amount": 200_000}]),
        summary={"creator_receivable_usd": 1_255.0},
    )
    locked = repository.lock_compensation_version(draft.id)

    with pytest.raises(ValueError):
        repository.update_compensation_draft(
            locked.id,
            jpy_to_usd_rate=0.0063,
            details=pd.DataFrame([{"amount": 0}]),
            summary={"creator_receivable_usd": 0.0},
        )

    restored = repository.list_compensation_versions("2026-06")[0]
    assert restored.status == "LOCKED"
    assert restored.jpy_to_usd_rate == 0.0062
    assert restored.details["amount"].tolist() == [200_000]


def test_any_month_tt_contract_is_selected_for_tiktok_update(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="tt-monthly",
        koc_name="monthly-tt",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["6\u6708TT"],
        homepage_url="https://www.tiktok.com/@monthly_tt",
    )
    service = FollowerService(repository, providers={})

    assert service.required_platform_for_record(record) == "TikTok"
    assert [item.id for item in service.tiktok_contract_records()] == [record.id]
