from datetime import date

import pandas as pd

from core.dashboard_processor import build_creator_summary
from database.koc_repository import KOCRepository


def test_creator_summary_includes_master_creators_without_posts(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    repository.create(user_id="1001", koc_name="has-post", contract_types=["YTB"])
    repository.create(user_id="2001", koc_name="no-post", contract_types=["TT"])
    data = pd.DataFrame(
        [
            {
                "creator_key": "1001",
                "user_id": "1001",
                "creator_label": "has-post",
                "creator_category": "GRASSROOT",
                "contract_types": "YTB",
                "follower_count": 0,
                "source_file": "june.xlsx",
                "source_platform": "YouTube",
                "publish_date": date(2026, 6, 1),
                "views": 100,
                "likes": 1,
                "comment": 0,
                "reposted": 0,
                "collect": 0,
            }
        ]
    )

    summary = build_creator_summary(data, repository.list())
    zero_creator = summary.loc[summary["user_id"] == "2001"].iloc[0]

    assert zero_creator["post_count"] == 0
    assert zero_creator["total_views"] == 0
    assert zero_creator["total_interactions"] == 0
    assert zero_creator["engagement_rate"] == 0
