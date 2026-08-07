from unittest.mock import patch

import pandas as pd

from database import db
from database.dashboard_repository import DashboardRepository
from ui.dashboard_cache import dashboard_cache_token


def test_database_initialization_runs_once_per_process_target(tmp_path):
    database_path = tmp_path / "cached-init.db"
    db._init_db_once.cache_clear()

    with patch("database.db.apply_migrations", wraps=db.apply_migrations) as mocked:
        db.init_db(database_path)
        db.init_db(database_path)

    assert mocked.call_count == 1


def test_dashboard_cache_token_changes_after_post_write(tmp_path):
    database_path = tmp_path / "dashboard-cache.db"
    repository = DashboardRepository(database_path)
    before = dashboard_cache_token(database_path)

    repository.upsert_posts(
        pd.DataFrame(
            [
                {
                    "source_platform": "ytb",
                    "url": "https://www.youtube.com/watch?v=cache-test",
                    "publish_date": "2026-07-01",
                    "views": 100,
                }
            ]
        )
    )

    assert dashboard_cache_token(database_path) != before
