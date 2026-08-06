from pathlib import Path

import pandas as pd

from core.dashboard_bootstrap import ensure_dashboard_seeded
from database.dashboard_repository import DashboardRepository


def _source_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "view": [100],
            "subtype": ["short"],
            "description": ["seed"],
            "title": ["seed post"],
            "userId": [1001],
            "platform": ["YouTube"],
            "url": ["https://example.com/seed"],
            "timestamp": [1780275600000],
            "likes": [10],
            "comment": [2],
            "reposted": [1],
            "collect": [3],
        }
    )


def test_empty_dashboard_is_seeded_from_project_local_exports(tmp_path: Path):
    database_path = tmp_path / "koc.db"
    source_dir = tmp_path / "dashboard"
    source_dir.mkdir()
    _source_frame().to_excel(source_dir / "6月草根数据.xlsx", index=False)

    first = ensure_dashboard_seeded(
        database_path,
        "Asia/Shanghai",
        source_dir=source_dir,
    )
    second = ensure_dashboard_seeded(
        database_path,
        "Asia/Shanghai",
        source_dir=source_dir,
    )

    repository = DashboardRepository(database_path)
    assert first.attempted is True
    assert first.saved_count == 1
    assert first.total_count == 1
    assert second.attempted is False
    assert repository.count_posts() == 1
