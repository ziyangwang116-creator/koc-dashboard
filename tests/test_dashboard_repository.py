from datetime import date

import pandas as pd

from database.dashboard_repository import DashboardRepository


def _posts(title: str = "首条投稿") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_file": "2026-06.xlsx",
                "source_platform": "YouTube",
                "url": "https://example.com/post",
                "user_id": "1001",
                "timestamp": 1780275600000,
                "publish_date": date(2026, 6, 1),
                "title": title,
                "koc_name": "测试达人",
                "matched": True,
                "view": 100,
            }
        ]
    )


def test_posts_persist_and_reimport_updates_same_url(tmp_path):
    database_path = tmp_path / "dashboard.db"
    repository = DashboardRepository(database_path)

    first = repository.upsert_posts(_posts())
    second = repository.upsert_posts(_posts("修正后的标题"))
    reloaded = DashboardRepository(database_path).load_posts()

    assert first.input_count == 1
    assert first.saved_count == 1
    assert first.total_count == 1
    assert second.saved_count == 1
    assert second.total_count == 1
    assert reloaded["title"].tolist() == ["修正后的标题"]
    assert reloaded["publish_date"].tolist() == ["2026-06-01"]


def test_posts_without_url_use_creator_time_title_key_and_can_be_cleared(tmp_path):
    repository = DashboardRepository(tmp_path / "dashboard.db")
    posts = _posts().assign(url=pd.NA)

    saved = repository.upsert_posts(posts)
    deleted = repository.clear_posts()

    assert saved.total_count == 1
    assert deleted == 1
    assert repository.count_posts() == 0


def test_monthly_jpy_to_usd_rate_is_saved_per_settlement_month(tmp_path):
    repository = DashboardRepository(tmp_path / "dashboard.db")

    assert repository.get_jpy_to_usd_rate("2026-07") is None
    repository.save_jpy_to_usd_rate("2026-07", 0.0062)
    repository.save_jpy_to_usd_rate("2026-06", 0.0061)
    repository.save_jpy_to_usd_rate("2026-07", 0.00625)

    assert repository.get_jpy_to_usd_rate("2026-06") == 0.0061
    assert repository.get_jpy_to_usd_rate("2026-07") == 0.00625


def test_monthly_contract_snapshots_preserve_any_contract_until_corrected(tmp_path):
    repository = DashboardRepository(tmp_path / "dashboard.db")

    first = repository.ensure_grassroot_contract_snapshots(
        "2026-07", [(7, ("YTB shorts",))]
    )
    after_master_change = repository.ensure_grassroot_contract_snapshots(
        "2026-07", [(7, ("6月YTB",))]
    )

    assert first == {7: ("YTB shorts",)}
    assert after_master_change == {7: ("YTB shorts",)}

    repository.save_grassroot_contract_snapshot("2026-07", 7, ("6月YTB",))
    assert repository.get_grassroot_contract_snapshots("2026-07") == {
        7: ("6月YTB",)
    }


def test_long_term_activity_inputs_are_editable_and_versions_are_independent(tmp_path):
    repository = DashboardRepository(tmp_path / "dashboard.db")

    repository.save_long_term_activity_counts("2026-07", {7: 2, 8: 0})
    assert repository.get_long_term_activity_counts("2026-07") == {7: 2, 8: 0}
    repository.save_long_term_activity_counts("2026-07", {7: None})
    assert repository.get_long_term_activity_counts("2026-07") == {8: 0}

    details = pd.DataFrame([{"达人": "长包达人", "每月活动数": 2, "rank": "A+"}])
    summary = {"creator_receivable_usd": 100.0}
    draft = repository.create_long_term_compensation_draft(
        "2026-07",
        jpy_to_usd_rate=0.0062,
        details=details,
        summary=summary,
    )
    locked = repository.lock_long_term_compensation_version(draft.id)

    assert locked.status == "LOCKED"
    assert repository.list_long_term_compensation_versions("2026-07")[0].details[
        "每月活动数"
    ].tolist() == [2]
