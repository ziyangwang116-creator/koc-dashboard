from datetime import date

import pandas as pd

from core.traffic_boost import annotate_july_traffic_boost


def test_youtube_boost_requires_tag_in_description_and_text_in_title():
    data = pd.DataFrame(
        [
            {
                "publish_date": date(2026, 7, 10),
                "source_platform": "YouTube",
                "description": "campaign #手記の加筆",
                "title": "手記の加筆を公開",
                "views": 100,
            },
            {
                "publish_date": date(2026, 7, 10),
                "source_platform": "YouTube",
                "description": "campaign #手記の加筆",
                "title": "通常動画",
                "views": 100,
            },
            {
                "publish_date": date(2026, 7, 10),
                "source_platform": "TikTok",
                "description": "campaign #手記の加筆",
                "title": "通常動画",
                "views": 100,
            },
        ]
    )

    annotated = annotate_july_traffic_boost(data)

    assert annotated["is_july_traffic_boost"].tolist() == [True, False, True]
    assert annotated["boosted_views"].tolist() == [105, 100, 105]
    assert annotated.loc[0, "traffic_boost_rule"] == (
        "YTB：description #手記の加筆 + title 手記の加筆"
    )
