import pandas as pd

from ui.dashboard import (
    _platform_posts,
    _platform_top_ranking,
    _platform_video_top_ranking,
    _rank_creator_summary,
)


def _post(creator: str, platform: str, views: int) -> dict[str, object]:
    return {
        "creator_key": creator,
        "user_id": creator,
        "creator_label": creator,
        "creator_category": "grassroot",
        "contract_types": "YTB",
        "follower_count": 0,
        "source_file": "june.xlsx",
        "source_platform": platform,
        "views": views,
        "likes": 0,
        "comment": 0,
        "reposted": 0,
        "collect": 0,
        "publish_date": pd.Timestamp("2026-06-01").date(),
    }


def test_creator_ranking_is_descending_and_limited_to_ten():
    data = pd.DataFrame(
        [_post(f"creator-{index:02d}", "YouTube", index) for index in range(1, 13)]
    )

    ranked = _rank_creator_summary(data, "total_views", limit=10)

    assert ranked["creator_label"].tolist() == [
        f"creator-{index:02d}" for index in range(12, 2, -1)
    ]
    assert ranked["total_views"].tolist() == list(range(12, 2, -1))


def test_ytb_ranking_filters_youtube_and_caps_at_top_thirty():
    data = pd.DataFrame(
        [_post(f"ytb-{index:02d}", "YouTube", index) for index in range(1, 32)]
        + [_post("tt-only", "TikTok", 999)]
    )

    ranked = _platform_top_ranking(data, "ytb", "total_views")

    assert len(ranked) == 30
    assert ranked.iloc[0]["creator_label"] == "ytb-31"
    assert "tt-only" not in ranked["creator_label"].tolist()


def test_tt_ranking_accepts_tiktok_and_tt_platform_values():
    data = pd.DataFrame(
        [
            _post("tt-name", "TikTok", 10),
            _post("tt-code", "tt", 20),
            _post("ytb", "YouTube", 30),
        ]
    )

    posts = _platform_posts(data, "tt")
    ranked = _platform_top_ranking(data, "tt", "post_count")

    assert posts["creator_label"].tolist() == ["tt-name", "tt-code"]
    assert ranked["creator_label"].tolist() == ["tt-code", "tt-name"]


def test_platform_video_ranking_is_limited_to_top_twenty_per_platform():
    data = pd.DataFrame(
        [_post(f"ytb-{index:02d}", "YouTube", index) for index in range(1, 22)]
        + [_post("tt-only", "TikTok", 999)]
    )

    ranked = _platform_video_top_ranking(data, "ytb")

    assert len(ranked) == 20
    assert ranked.iloc[0]["creator_label"] == "ytb-21"
    assert ranked.iloc[-1]["creator_label"] == "ytb-02"
    assert "tt-only" not in ranked["creator_label"].tolist()
