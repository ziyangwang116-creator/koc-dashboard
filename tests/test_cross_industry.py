from datetime import date

import pandas as pd

from core.cross_industry import (
    exclude_cross_industry_posts,
    normalize_video_url,
    parse_pasted_urls,
)
from database.dashboard_repository import DashboardRepository


def _post(url: str, views: int = 100) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_file": "2026-07.xlsx",
                "source_platform": "YouTube",
                "url": url,
                "user_id": "1001",
                "publish_date": date(2026, 7, 1),
                "title": "异业投稿",
                "views": views,
            }
        ]
    )


def test_video_url_normalization_matches_common_youtube_and_tiktok_variants():
    youtube_watch = normalize_video_url(
        "https://www.youtube.com/watch?v=abc123&utm_source=test"
    )
    youtube_shorts = normalize_video_url("https://youtube.com/shorts/abc123?si=x")
    tiktok = normalize_video_url(
        "https://www.tiktok.com/@creator/video/7654321?is_from_webapp=1"
    )

    assert youtube_watch is not None
    assert youtube_shorts is not None
    assert youtube_watch.url_key == youtube_shorts.url_key == "youtube:abc123"
    assert tiktok is not None
    assert tiktok.url_key == "tiktok:7654321"


def test_pasted_urls_are_extracted_and_deduplicated_in_order():
    assert parse_pasted_urls(
        "第一条 https://example.com/a\nhttps://example.com/a，https://example.com/b"
    ) == ["https://example.com/a", "https://example.com/b"]


def test_cross_industry_marks_survive_month_reimport_and_can_be_restored(tmp_path):
    repository = DashboardRepository(tmp_path / "dashboard.db")
    original_url = "https://www.youtube.com/watch?v=abc123&utm_source=first"
    replacement_url = "https://www.youtube.com/shorts/abc123?si=second"
    repository.save_monthly_import(
        _post(original_url, 500_000),
        replace_months=True,
        source_files=["first.xlsx"],
        file_hashes={"first.xlsx": "first"},
    )
    repository.save_cross_industry_exclusions(
        [original_url],
        reason="异业活动",
    )

    first = repository.annotate_cross_industry_posts(repository.load_posts())
    assert first["is_cross_industry"].tolist() == [True]
    assert exclude_cross_industry_posts(first).empty

    repository.save_monthly_import(
        _post(replacement_url, 600_000),
        replace_months=True,
        source_files=["replacement.xlsx"],
        file_hashes={"replacement.xlsx": "replacement"},
    )
    replaced = repository.annotate_cross_industry_posts(repository.load_posts())
    assert replaced["is_cross_industry"].tolist() == [True]
    assert replaced["cross_industry_reason"].tolist() == ["异业活动"]

    exclusion_id = int(repository.list_cross_industry_exclusions().iloc[0]["id"])
    assert repository.deactivate_cross_industry_exclusions([exclusion_id]) == 1
    restored = repository.annotate_cross_industry_posts(repository.load_posts())
    assert restored["is_cross_industry"].tolist() == [False]
    assert len(exclude_cross_industry_posts(restored)) == 1


def test_unmatched_cross_industry_url_is_retained_for_future_import(tmp_path):
    repository = DashboardRepository(tmp_path / "dashboard.db")
    pending_url = "https://www.tiktok.com/@creator/video/987654321"

    repository.save_cross_industry_exclusions([pending_url])
    assert repository.list_cross_industry_exclusions()["url_key"].tolist() == [
        "tiktok:987654321"
    ]

    repository.upsert_posts(
        pd.DataFrame(
            [
                {
                    "source_file": "later.xlsx",
                    "source_platform": "TikTok",
                    "url": pending_url,
                    "user_id": "tt-1",
                    "publish_date": date(2026, 8, 1),
                    "views": 123,
                }
            ]
        )
    )
    annotated = repository.annotate_cross_industry_posts(repository.load_posts())
    assert annotated["is_cross_industry"].tolist() == [True]
