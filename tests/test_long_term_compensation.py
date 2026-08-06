from dataclasses import replace
from datetime import date

import pandas as pd

from core.long_term_compensation import calculate_long_term_compensation
from database.koc_repository import KOCRepository
from models.enums import CreatorCategory


def _long_term_creator(
    repository: KOCRepository,
    *,
    user_id: str = "long-term-1",
    followers: int | None = 150_000,
):
    return repository.create(
        user_id=user_id,
        koc_name="long term creator",
        creator_category=CreatorCategory.LONG_TERM,
        contract_types=["长包"],
        follower_count=followers,
        effective_date=date(2026, 5, 1),
    )


def _post(
    record_id: int,
    *,
    subtype: str,
    views: int,
    platform: str = "YouTube",
    publish_date: date = date(2026, 7, 10),
    follower_count: int | None = 150_000,
):
    return {
        "creator_id": record_id,
        "user_id": "long-term-1",
        "koc_name": "long term creator",
        "creator_label": "long term creator",
        "creator_active": True,
        "profile_status": "MATCHED",
        "creator_category": "长包",
        "contract_types": "长包",
        "contract_start_date": date(2026, 5, 1),
        "contract_end_date": date(2026, 12, 31),
        "follower_count": follower_count,
        "source_platform": platform,
        "subtype": subtype,
        "publish_date": publish_date,
        "views": views,
    }


def test_long_term_uses_all_youtube_types_and_applies_grassroot_fee_formula(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = _long_term_creator(repository)
    data = pd.DataFrame(
        [
            _post(record.id, subtype="long", views=2_000_000),
            _post(record.id, subtype="livestream", views=1_000_000),
            _post(record.id, subtype="YTB shorts", views=1_000_000),
            _post(record.id, subtype="tiktok", views=9_000_000, platform="TikTok"),
        ]
    )

    result = calculate_long_term_compensation(
        data,
        repository.list(include_inactive=True),
        jpy_to_usd_rate=0.0062,
        event_counts={record.id: 2},
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
    )
    detail = result.details.iloc[0]

    assert detail["YouTube 投稿数"] == 3
    assert detail["月度新投稿播放量"] == 4_000_000
    assert detail["rank"] == "A+"
    assert detail["rank金额"] == 1_500_000
    assert detail["总金额（日元）"] == 1_500_000
    assert detail["博主应收（美元）"] == 9_315.0
    assert detail["有道应收（美元）（包含服务费）"] == 10_712.25
    assert round(detail["CPM"], 2) == 2.68


def test_long_term_excludes_cross_industry_posts_from_rank_and_post_count(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = _long_term_creator(repository)
    regular = _post(record.id, subtype="long", views=2_000_000)
    regular["is_cross_industry"] = False
    external = _post(record.id, subtype="YTB shorts", views=4_000_000)
    external["is_cross_industry"] = True

    result = calculate_long_term_compensation(
        pd.DataFrame([regular, external]),
        repository.list(include_inactive=True),
        jpy_to_usd_rate=0.0062,
        event_counts={record.id: 2},
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
    )
    detail = result.details.iloc[0]

    assert detail["YouTube 投稿数"] == 1
    assert detail["月度新投稿播放量"] == 2_000_000
    assert detail["rank"] == "B+"


def test_long_term_rank_falls_to_tier_without_event_requirement(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = _long_term_creator(repository)
    data = pd.DataFrame([_post(record.id, subtype="long", views=4_000_000)])

    result = calculate_long_term_compensation(
        data,
        repository.list(include_inactive=True),
        jpy_to_usd_rate=0.0062,
        event_counts={record.id: 0},
    )
    detail = result.details.iloc[0]

    assert detail["rank"] == "C+"
    assert detail["活动数门槛"] is None
    assert detail["rank金额"] == 400_000


def test_long_term_requires_an_explicit_activity_input(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = _long_term_creator(repository)
    data = pd.DataFrame([_post(record.id, subtype="long", views=4_000_000)])

    result = calculate_long_term_compensation(
        data,
        repository.list(include_inactive=True),
        jpy_to_usd_rate=0.0062,
        event_counts={},
    )
    detail = result.details.iloc[0]

    assert detail["结算状态"] == "待填写活动数"
    assert detail["总金额（日元）"] == 0
    assert detail["有道应收（美元）（包含服务费）"] == 0


def test_long_term_uses_post_profile_instead_of_a_later_current_category(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = _long_term_creator(repository)
    later_record = replace(
        record,
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=("TT",),
    )
    data = pd.DataFrame([_post(record.id, subtype="long", views=4_000_000)])

    result = calculate_long_term_compensation(
        data,
        [later_record],
        jpy_to_usd_rate=0.0062,
        event_counts={record.id: 2},
    )
    detail = result.details.iloc[0]

    assert detail["合同类型"] == "长包"
    assert detail["rank"] == "A+"


def test_long_term_cpm_uses_original_views_when_july_boost_is_enabled(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = _long_term_creator(repository)
    post = _post(record.id, subtype="long", views=4_000_000)
    post["description"] = "campaign #手記の加筆"
    post["title"] = "手記の加筆 long"

    result = calculate_long_term_compensation(
        pd.DataFrame([post]),
        repository.list(include_inactive=True),
        jpy_to_usd_rate=0.0062,
        event_counts={record.id: 2},
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        traffic_boost_enabled=True,
    )
    detail = result.details.iloc[0]

    assert detail["月度新投稿播放量"] == 4_200_000
    assert detail["CPM计算播放量（无加成）"] == 4_000_000
    assert round(detail["CPM"], 6) == round(10_712.25 / 4_000_000 * 1_000, 6)
    assert result.total_video_views == 4_000_000
