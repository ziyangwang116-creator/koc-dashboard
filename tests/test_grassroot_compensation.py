from dataclasses import replace

import pandas as pd

from core.grassroot_compensation import calculate_grassroot_compensation
from database.koc_repository import KOCRepository
from followers.base import FollowerFetchResult
from models.enums import CreatorCategory


def _creator(
    repository: KOCRepository,
    *,
    user_id: str,
    name: str,
    contract: str,
    followers: int | None,
    youtube_followers: int | None = None,
    tiktok_followers: int | None = None,
) -> None:
    repository.create(
        user_id=user_id,
        koc_name=name,
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=[contract],
        follower_count=followers,
        youtube_follower_count=youtube_followers,
        tiktok_follower_count=tiktok_followers,
    )


def test_ytb_shorts_only_counts_ytb_shorts_subtype_and_adds_usd_fee(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    _creator(
        repository,
        user_id="short-1",
        name="shorts creator",
        contract="YTB shorts",
        followers=5_000,
    )
    details = pd.DataFrame(
        [
            {"user_id": "short-1", "subtype": "YTB shorts", "views": 1_000_000},
            {"user_id": "short-1", "subtype": "shorts", "views": 0},
            {"user_id": "short-1", "subtype": "long", "views": 9_000_000},
            {"user_id": "short-1", "subtype": "livestream", "views": 9_000_000},
        ]
    )

    result = calculate_grassroot_compensation(
        details,
        repository.list(include_inactive=False),
        jpy_to_usd_rate=0.0062,
    )
    creator = result.details.iloc[0]

    assert creator["计费 subtype"] == "shorts"
    assert creator["计费播放量"] == 1_000_000
    assert creator["全部视频类型播放量"] == 19_000_000
    assert creator["投稿数"] == 2
    assert creator["rank"] == "C"
    assert creator["short rank金额"] == 300_000
    assert creator["long+livestreamrank金额"] == 0
    assert creator["总金额（日元）"] == 300_000
    assert creator["博主应收（美元）"] == 1_875.0
    assert creator["有道应收（美元）（包含服务费）"] == 2_156.25
    assert round(creator["CPM"], 2) == 0.11


def test_grassroot_excludes_cross_industry_views_posts_rewards_and_cpm(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    _creator(
        repository,
        user_id="cross-industry-long",
        name="cross industry creator",
        contract="YTB",
        followers=100_000,
    )
    details = pd.DataFrame(
        [
            {
                "user_id": "cross-industry-long",
                "subtype": "long",
                "views": 1_200_000,
                "is_cross_industry": False,
            },
            {
                "user_id": "cross-industry-long",
                "subtype": "long",
                "views": 9_000_000,
                "is_cross_industry": True,
            },
        ]
    )

    result = calculate_grassroot_compensation(
        details,
        repository.list(include_inactive=False),
        jpy_to_usd_rate=0.0062,
    )
    creator = result.details.iloc[0]

    assert creator["计费播放量"] == 1_200_000
    assert creator["全部视频类型播放量"] == 1_200_000
    assert creator["投稿数"] == 1
    assert creator["long+livestream投稿数奖励"] == 0


def test_monthly_contract_snapshot_overrides_a_later_master_contract_change(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    _creator(
        repository,
        user_id="contract-snapshot",
        name="creator",
        contract="TT",
        followers=1_000,
    )
    original_record = repository.list(include_inactive=False)[0]
    master_record_after_change = replace(
        original_record,
        contract_types=("YTB",),
    )

    result = calculate_grassroot_compensation(
        pd.DataFrame(
            [
                {
                    "user_id": "contract-snapshot",
                    "subtype": "tiktok",
                    "views": 500_000,
                },
                {
                    "user_id": "contract-snapshot",
                    "subtype": "long",
                    "views": 1_200_000,
                },
            ]
        ),
        [master_record_after_change],
        jpy_to_usd_rate=0.0062,
        contract_type_snapshots={original_record.id: ("TT",)},
    )
    creator = result.details.iloc[0]

    assert creator["合同类型"] == "TT"
    assert creator["计费播放量"] == 500_000
    assert creator["rank"] == "D+"
    assert creator["总金额（日元）"] == 200_000


def test_long_contract_only_counts_long_and_livestream_with_highest_post_tier(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    _creator(
        repository,
        user_id="long-1",
        name="long creator",
        contract="YTB",
        followers=100,
    )
    details = pd.DataFrame(
        [
            {"user_id": "long-1", "subtype": "long", "views": 1_200_000},
            *[
                {"user_id": "long-1", "subtype": "livestream", "views": 0}
                for _ in range(29)
            ],
            {"user_id": "long-1", "subtype": "YTB shorts", "views": 5_000_000},
        ]
    )

    result = calculate_grassroot_compensation(
        details,
        repository.list(include_inactive=False),
        jpy_to_usd_rate=0.0062,
    )
    creator = result.details.iloc[0]

    assert creator["计费 subtype"] == "long + livestream"
    assert creator["计费播放量"] == 1_200_000
    assert creator["全部视频类型播放量"] == 6_200_000
    assert creator["投稿数"] == 30
    assert creator["rank"] == "S"
    assert creator["long+livestreamrank金额"] == 2_000_000
    assert creator["long+livestream投稿数奖励"] == 100_000
    assert creator["总金额（日元）"] == 2_100_000


def test_any_monthly_ytb_contract_uses_long_and_livestream(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    _creator(
        repository,
        user_id="june-ytb",
        name="monthly ytb creator",
        contract="6月YTB",
        followers=None,
    )

    result = calculate_grassroot_compensation(
        pd.DataFrame(
            [
                {"user_id": "june-ytb", "subtype": "long", "views": 1_200_000},
                {"user_id": "june-ytb", "subtype": "livestream", "views": 0},
                {"user_id": "june-ytb", "subtype": "tiktok", "views": 9_000_000},
            ]
        ),
        repository.list(include_inactive=False),
        jpy_to_usd_rate=0.0062,
    )
    creator = result.details.iloc[0]

    assert creator["合同类型"] == "6月YTB"
    assert creator["计费 subtype"] == "long + livestream"
    assert creator["计费播放量"] == 1_200_000
    assert creator["rank"] == "S"


def test_short_contract_without_follower_count_needs_manual_value(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    _creator(
        repository,
        user_id="tt-1",
        name="tiktok creator",
        contract="TT",
        followers=None,
    )
    details = pd.DataFrame(
        [{"user_id": "tt-1", "subtype": "tiktok", "views": 10_000_000}]
    )

    result = calculate_grassroot_compensation(
        details,
        repository.list(include_inactive=False),
        jpy_to_usd_rate=0.0062,
    )
    creator = result.details.iloc[0]

    assert creator["结算状态"] == "待补充粉丝数"
    assert creator["总金额（日元）"] == 0
    assert creator["博主应收（日元）(包含15$手续费)"] == 0
    assert creator["有道应收（美元）（包含服务费）"] == 0
    assert pd.isna(creator["CPM"])


def test_failed_refresh_keeps_historical_follower_count_available_for_settlement(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    _creator(
        repository,
        user_id="tt-history",
        name="tiktok creator",
        contract="TT",
        followers=1_000,
    )
    record = repository.list(include_inactive=False)[0]
    repository.apply_follower_failure(
        record.id,
        FollowerFetchResult(
            success=False,
            follower_count=None,
            platform="tiktok",
            fetched_at="2026-07-28T00:00:00+00:00",
            error_code="TIKTOK_EMPTY_RESPONSE",
            error_message="No public follower value returned.",
        ),
    )

    result = calculate_grassroot_compensation(
        pd.DataFrame(
            [{"user_id": "tt-history", "subtype": "tiktok", "views": 500_000}]
        ),
        repository.list(include_inactive=False),
        jpy_to_usd_rate=0.0062,
    )
    creator = result.details.iloc[0]

    assert creator["结算状态"] == "可结算"
    assert creator["rank"] == "D+"
    assert creator["总金额（日元）"] == 200_000


def test_long_contract_settles_without_a_follower_count(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    _creator(
        repository,
        user_id="long-no-follower",
        name="long creator",
        contract="YTB",
        followers=None,
    )

    result = calculate_grassroot_compensation(
        pd.DataFrame(
            [{"user_id": "long-no-follower", "subtype": "long", "views": 1_200_000}]
        ),
        repository.list(include_inactive=False),
        jpy_to_usd_rate=0.0062,
    )
    creator = result.details.iloc[0]

    assert creator["结算状态"] == "可结算"
    assert creator["rank"] == "S"
    assert creator["总金额（日元）"] == 2_000_000


def test_monthly_tiktok_contract_uses_all_video_views_for_cpm(
    tmp_path,
):
    repository = KOCRepository(tmp_path / "koc.db")
    _creator(
        repository,
        user_id="tt-2",
        name="tiktok creator",
        contract="4月TT",
        followers=1_000,
    )
    details = pd.DataFrame(
        [
            {"user_id": "tt-2", "subtype": "tiktok", "views": 500_000},
            {"user_id": "tt-2", "subtype": "YTB shorts", "views": 9_000_000},
        ]
    )

    result = calculate_grassroot_compensation(
        details,
        repository.list(include_inactive=False),
        jpy_to_usd_rate=0.0062,
    )
    creator = result.details.iloc[0]

    assert creator["rank"] == "D+"
    assert creator["合同类型"] == "4月TT"
    assert creator["计费播放量"] == 500_000
    assert creator["全部视频类型播放量"] == 9_500_000
    assert creator["总金额（日元）"] == 200_000
    assert result.settled_views == 500_000
    assert result.total_video_views == 9_500_000
    assert result.overall_cpm == creator["CPM"]


def test_profile_only_revision_without_period_uses_matching_contract_term():
    details = pd.DataFrame(
        [
            {
                "user_id": "profile-term",
                "creator_id": 1,
                "creator_category": "GRASSROOT",
                "contract_types": "YTB shorts",
                "contract_start_date": None,
                "contract_end_date": None,
                "follower_count": 5_000,
                "creator_active": True,
                "profile_effective_date": "2026-07-01",
                "publish_date": "2026-07-10",
                "subtype": "shorts",
                "views": 800_000,
            },
            {
                "user_id": "profile-term",
                "creator_id": 1,
                "creator_category": "GRASSROOT",
                "contract_types": "YTB shorts",
                "contract_start_date": "2026-07-01",
                "contract_end_date": "2026-10-31",
                "follower_count": 5_000,
                "creator_active": True,
                "profile_effective_date": "2026-07-30",
                "publish_date": "2026-07-30",
                "subtype": "shorts",
                "views": 100_000,
            },
        ]
    )

    result = calculate_grassroot_compensation(
        details,
        [],
        jpy_to_usd_rate=0.0062,
    )
    creator = result.details.iloc[0]

    assert len(result.details) == 1
    assert creator["rank"] == "C"
    assert creator["计费播放量"] == 900_000
    assert creator["short rank金额"] == 300_000


def test_july_cross_lane_post_reward_does_not_require_a_view_rank(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    _creator(
        repository,
        user_id="july-cross-posts",
        name="cross lane creator",
        contract="YTB shorts",
        followers=5_000,
        youtube_followers=5_000,
    )
    details = pd.DataFrame(
        [
            {
                "user_id": "july-cross-posts",
                "subtype": "shorts",
                "views": 800_000,
                "publish_date": "2026-07-05",
                "source_platform": "YouTube",
                "description": "normal shorts",
                "title": "normal shorts",
            },
            *[
                {
                    "user_id": "july-cross-posts",
                    "subtype": "long",
                    "views": 1_000,
                    "publish_date": f"2026-07-{day:02d}",
                    "source_platform": "YouTube",
                    "description": "campaign #手記の加筆",
                    "title": "手記の加筆",
                    "url": f"https://youtube.test/long-{day}",
                }
                for day in range(10, 20)
            ],
        ]
    )

    result = calculate_grassroot_compensation(
        details,
        repository.list(include_inactive=False),
        jpy_to_usd_rate=0.0062,
        traffic_boost_enabled=True,
    )
    creator = result.details.iloc[0]

    assert creator["合同内计费播放量"] == 800_000
    assert creator["跨赛道类型"] == "long + livestream"
    assert creator["跨赛道活动投稿数"] == 10
    assert creator["跨赛道原始播放量"] == 10_000
    assert creator["跨赛道加成后播放量"] == 10_500
    assert creator["跨赛道 rank"] == "long + livestream：无等级"
    assert creator["跨赛道 rank金额"] == 0
    assert creator["跨赛道投稿数奖励"] == 50_000
    assert creator["跨赛道结算金额"] == 50_000
    assert creator["计费播放量"] == 810_500
    assert creator["全部视频类型播放量"] == 810_000
    assert creator["CPM计算播放量（无加成）"] == 810_000
    assert creator["总金额（日元）"] == 350_000
    assert round(creator["CPM"], 6) == round(2_512.75 / 810_000 * 1_000, 6)


def test_july_cross_lane_covers_all_non_contract_lanes_and_platform_followers(
    tmp_path,
):
    repository = KOCRepository(tmp_path / "koc.db")
    _creator(
        repository,
        user_id="july-all-lanes",
        name="all lane creator",
        contract="TT",
        followers=100_000,
        youtube_followers=5_000,
        tiktok_followers=500,
    )
    details = pd.DataFrame(
        [
            {
                "user_id": "july-all-lanes",
                "subtype": "tiktok",
                "views": 250_000,
                "publish_date": "2026-07-02",
                "source_platform": "TikTok",
                "description": "normal",
                "title": "normal",
            },
            {
                "user_id": "july-all-lanes",
                "subtype": "shorts",
                "views": 800_000,
                "publish_date": "2026-07-03",
                "source_platform": "YouTube",
                "description": "campaign #手記の加筆",
                "title": "手記の加筆 shorts",
            },
            {
                "user_id": "july-all-lanes",
                "subtype": "long",
                "views": 60_000,
                "publish_date": "2026-07-04",
                "source_platform": "YouTube",
                "description": "campaign #手記の加筆",
                "title": "手記の加筆 long",
            },
            {
                "user_id": "july-all-lanes",
                "subtype": "long",
                "views": 9_000_000,
                "publish_date": "2026-07-05",
                "source_platform": "YouTube",
                "description": "normal",
                "title": "normal",
            },
        ]
    )

    result = calculate_grassroot_compensation(
        details,
        repository.list(include_inactive=False),
        jpy_to_usd_rate=0.0062,
        traffic_boost_enabled=True,
    )
    creator = result.details.iloc[0]

    assert creator["YouTube粉丝数"] == 5_000
    assert creator["TikTok粉丝数"] == 500
    assert creator["跨赛道类型"] == "long + livestream；YTB shorts"
    assert creator["跨赛道原始播放量"] == 860_000
    assert creator["跨赛道加成后播放量"] == 903_000
    assert creator["跨赛道 rank金额"] == 400_000
    assert creator["跨赛道结算金额"] == 400_000
    assert creator["计费播放量"] == 1_153_000
    assert creator["全部视频类型播放量"] == 10_110_000
    assert creator["总金额（日元）"] == 500_000
