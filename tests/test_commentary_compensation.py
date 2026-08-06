from datetime import date

import pandas as pd

from core.commentary_compensation import calculate_commentary_compensation
from database.dashboard_repository import DashboardRepository
from database.koc_repository import KOCRepository
from models.enums import CreatorCategory


def _creator(
    repository: KOCRepository,
    *,
    contract: str = "YTB长+YTBshorts",
    youtube_followers: int | None = 100_000,
    tiktok_followers: int | None = None,
):
    return repository.create(
        user_id=f"commentary-{contract}",
        koc_name=f"commentary {contract}",
        creator_category=CreatorCategory.COMMENTARY,
        contract_types=[contract],
        contract_start_date=date(2026, 7, 1),
        contract_end_date=date(2026, 8, 31),
        youtube_homepage_url="https://www.youtube.com/@commentary",
        youtube_follower_count=youtube_followers,
        tiktok_homepage_url=(
            "https://www.tiktok.com/@commentary"
            if tiktok_followers is not None
            else None
        ),
        tiktok_follower_count=tiktok_followers,
        effective_date=date(2026, 7, 1),
    )


def _post(
    record_id: int,
    *,
    url: str,
    subtype: str,
    views: int,
    platform: str = "YouTube",
    contract: str = "YTB长+YTBshorts",
    likes: int = 10_000,
):
    return {
        "creator_id": record_id,
        "user_id": f"commentary-{contract}",
        "koc_name": f"commentary {contract}",
        "creator_active": True,
        "creator_category": "解说",
        "contract_types": contract,
        "contract_start_date": date(2026, 7, 1),
        "contract_end_date": date(2026, 8, 31),
        "youtube_follower_count": 100_000,
        "tiktok_follower_count": 100_000,
        "follower_count": 100_000,
        "source_platform": platform,
        "subtype": subtype,
        "publish_date": date(2026, 7, 10),
        "views": views,
        "likes": likes,
        "title": url,
        "url": url,
    }


def test_commentary_rank_is_capped_by_followers_and_uses_115_percent_fee(tmp_path):
    creators = KOCRepository(tmp_path / "koc.db")
    record = _creator(creators, youtube_followers=60_000)
    data = pd.DataFrame(
        [
            _post(record.id, url="long", subtype="long", views=310_000),
            _post(record.id, url="short", subtype="shorts", views=1_700_000),
        ]
    )

    result = calculate_commentary_compensation(
        data,
        creators.list(include_inactive=True),
        period_month="2026-07",
        jpy_to_usd_rate=0.0062,
        profile_history=creators.list_profile_history(),
    )
    detail = result.details.iloc[0]

    assert detail["长视频播放等级"] == "SS"
    assert detail["长视频最终等级"] == "S"
    assert detail["短视频最终等级"] == "S"
    assert detail["并用奖金等级"] == "S"
    assert detail["解说含税总额（日元）"] == 710_000
    assert detail["博主应收（美元）"] == 4_417.0
    assert round(detail["有道应收（美元）（包含服务费）"], 2) == 5_079.55


def test_commentary_excludes_cross_industry_video_from_views_and_combined_bonus(
    tmp_path,
):
    creators = KOCRepository(tmp_path / "koc.db")
    record = _creator(creators)
    regular = _post(record.id, url="regular-long", subtype="long", views=160_000)
    regular["is_cross_industry"] = False
    external = _post(
        record.id,
        url="external-short",
        subtype="shorts",
        views=1_700_000,
    )
    external["is_cross_industry"] = True

    result = calculate_commentary_compensation(
        pd.DataFrame([regular, external]),
        creators.list(include_inactive=True),
        period_month="2026-07",
        jpy_to_usd_rate=0.0062,
        profile_history=creators.list_profile_history(),
    )
    detail = result.details.iloc[0]

    assert detail["长视频播放量"] == 160_000
    assert detail["短视频播放量"] == 0
    assert detail["并用奖金（日元）"] == 0
    assert detail["全部已付费内容播放量"] == 160_000


def test_commentary_ytb_long_tt_counts_tiktok_but_not_youtube_shorts(tmp_path):
    creators = KOCRepository(tmp_path / "koc.db")
    record = _creator(
        creators,
        contract="YTB长+TT",
        youtube_followers=100_000,
        tiktok_followers=100_000,
    )
    data = pd.DataFrame(
        [
            _post(
                record.id,
                url="long",
                subtype="long",
                views=160_000,
                contract="YTB长+TT",
            ),
            _post(
                record.id,
                url="youtube-short",
                subtype="shorts",
                views=2_000_000,
                contract="YTB长+TT",
            ),
            _post(
                record.id,
                url="tiktok",
                subtype="tiktok",
                views=500_000,
                platform="TikTok",
                contract="YTB长+TT",
            ),
        ]
    )

    result = calculate_commentary_compensation(
        data,
        creators.list(include_inactive=True),
        period_month="2026-07",
        jpy_to_usd_rate=0.0062,
        profile_history=creators.list_profile_history(),
    )
    detail = result.details.iloc[0]

    assert detail["短视频平台"] == "TikTok"
    assert detail["短视频播放量"] == 500_000
    assert detail["解说含税总额（日元）"] == 530_000


def test_approved_theme_is_excluded_from_regular_views_and_added_separately(tmp_path):
    creators = KOCRepository(tmp_path / "koc.db")
    record = _creator(creators)
    data = pd.DataFrame(
        [
            _post(record.id, url="regular", subtype="long", views=160_000),
            _post(record.id, url="theme", subtype="long", views=1_000_000),
        ]
    )

    result = calculate_commentary_compensation(
        data,
        creators.list(include_inactive=True),
        period_month="2026-07",
        jpy_to_usd_rate=0.0062,
        profile_history=creators.list_profile_history(),
        theme_submissions=[
            {
                "creator_id": record.id,
                "theme_code": "NEW_MODE",
                "content_format": "LONG",
                "urls": ["theme"],
                "submitted_date": "2026-07-31",
                "review_status": "APPROVED",
            }
        ],
        theme_definitions={
            "NEW_MODE": {
                "reward_jpy": 15_000,
                "max_per_creator": 1,
                "enabled": True,
            }
        },
    )
    detail = result.details.iloc[0]

    assert detail["长视频播放量"] == 160_000
    assert detail["指定主题件数"] == 1
    assert detail["指定主题报酬（日元）"] == 15_000
    assert detail["解说含税总额（日元）"] == 265_000
    assert detail["全部已付费内容播放量"] == 160_000
    assert "指定主题视频播放量" not in result.details.columns


def test_approved_short_theme_matches_three_normalized_video_urls(tmp_path):
    creators = KOCRepository(tmp_path / "koc.db")
    record = _creator(creators)
    data = pd.DataFrame(
        [
            _post(
                record.id,
                url=f"https://www.youtube.com/shorts/video-{index}",
                subtype="shorts",
                views=100_000,
            )
            for index in range(1, 4)
        ]
    )

    result = calculate_commentary_compensation(
        data,
        creators.list(include_inactive=True),
        period_month="2026-07",
        jpy_to_usd_rate=0.0062,
        profile_history=creators.list_profile_history(),
        theme_submissions=[
            {
                "creator_id": record.id,
                "theme_code": "NEW_MODE",
                "content_format": "SHORT",
                "urls": [
                    "https://youtu.be/video-1?si=share",
                    "https://www.youtube.com/watch?v=video-2&utm_source=test",
                    "https://www.youtube.com/shorts/video-3?feature=share",
                ],
                "submitted_date": "2026-07-31",
                "review_status": "APPROVED",
            }
        ],
        theme_definitions={
            "NEW_MODE": {
                "reward_jpy": 99_999,
                "max_per_creator": 1,
                "enabled": True,
            }
        },
    )
    detail = result.details.iloc[0]

    assert detail["短视频播放量"] == 0
    assert detail["指定主题件数"] == 1
    assert detail["指定主题报酬（日元）"] == 15_000
    assert detail["全部已付费内容播放量"] == 0


def test_approved_theme_counts_even_when_links_are_not_in_monthly_data(tmp_path):
    creators = KOCRepository(tmp_path / "koc.db")
    record = _creator(creators)

    result = calculate_commentary_compensation(
        pd.DataFrame(),
        creators.list(include_inactive=True),
        period_month="2026-07",
        jpy_to_usd_rate=0.0062,
        profile_history=creators.list_profile_history(),
        theme_submissions=[
            {
                "creator_id": record.id,
                "theme_code": "NEW_MODE",
                "content_format": "SHORT",
                "urls": [
                    "https://www.youtube.com/shorts/not-imported-1",
                    "https://www.youtube.com/shorts/not-imported-2",
                    "https://www.youtube.com/shorts/not-imported-3",
                ],
                "review_status": "APPROVED",
            }
        ],
        theme_definitions={
            "NEW_MODE": {
                "reward_jpy": 15_000,
                "max_per_creator": 1,
                "enabled": True,
            }
        },
    )
    detail = result.details.iloc[0]

    assert detail["指定主题件数"] == 1
    assert detail["指定主题报酬（日元）"] == 15_000
    assert detail["解说含税总额（日元）"] == 15_000
    assert detail["全部已付费内容播放量"] == 0


def test_approved_theme_counts_when_approval_is_recorded_after_month_end(tmp_path):
    creators = KOCRepository(tmp_path / "koc.db")
    record = _creator(creators)
    data = pd.DataFrame(
        [_post(record.id, url="late-approved-theme", subtype="long", views=310_000)]
    )

    result = calculate_commentary_compensation(
        data,
        creators.list(include_inactive=True),
        period_month="2026-07",
        jpy_to_usd_rate=0.0062,
        profile_history=creators.list_profile_history(),
        theme_submissions=[
            {
                "creator_id": record.id,
                "theme_code": "NEW_MODE",
                "content_format": "LONG",
                "urls": ["late-approved-theme"],
                "submitted_date": "2026-08-03",
                "review_status": "APPROVED",
            }
        ],
        theme_definitions={
            "NEW_MODE": {
                "reward_jpy": 15_000,
                "max_per_creator": 1,
                "enabled": True,
            }
        },
    )
    detail = result.details.iloc[0]

    assert detail["长视频播放量"] == 0
    assert detail["指定主题件数"] == 1
    assert detail["指定主题报酬（日元）"] == 15_000
    assert detail["全部已付费内容播放量"] == 0


def test_pending_theme_does_not_remove_regular_billable_views(tmp_path):
    creators = KOCRepository(tmp_path / "koc.db")
    record = _creator(creators)
    data = pd.DataFrame(
        [_post(record.id, url="pending-theme", subtype="long", views=310_000)]
    )

    result = calculate_commentary_compensation(
        data,
        creators.list(include_inactive=True),
        period_month="2026-07",
        jpy_to_usd_rate=0.0062,
        profile_history=creators.list_profile_history(),
        theme_submissions=[
            {
                "creator_id": record.id,
                "theme_code": "NEW_MODE",
                "content_format": "LONG",
                "urls": ["pending-theme"],
                "review_status": "PENDING",
            }
        ],
        theme_definitions={
            "NEW_MODE": {
                "reward_jpy": 15_000,
                "max_per_creator": 1,
                "enabled": True,
            }
        },
    )
    detail = result.details.iloc[0]

    assert detail["长视频播放量"] == 310_000
    assert detail["指定主题件数"] == 0
    assert detail["指定主题报酬（日元）"] == 0


def test_commentary_uses_raw_views_without_validity_review(tmp_path):
    creators = KOCRepository(tmp_path / "koc.db")
    record = _creator(creators)
    data = pd.DataFrame(
        [_post(record.id, url="long", subtype="long", views=310_000)]
    )

    result = calculate_commentary_compensation(
        data,
        creators.list(include_inactive=True),
        period_month="2026-07",
        jpy_to_usd_rate=0.0062,
        profile_history=creators.list_profile_history(),
    )

    detail = result.details.iloc[0]
    assert detail["结算状态"] == "可结算"
    assert detail["长视频播放量"] == 310_000
    assert detail["解说含税总额（日元）"] == 500_000


def test_commentary_manual_inputs_and_locked_version_are_persisted(tmp_path):
    repository = DashboardRepository(tmp_path / "dashboard.db")
    repository.replace_commentary_theme_submissions(
        "2026-07",
        [
            {
                "creator_id": 1,
                "theme_code": "NEW_MODE",
                "content_format": "LONG",
                "urls": ["https://example.com/video"],
                "submitted_date": "2026-07-31",
                "review_status": "APPROVED",
            }
        ],
    )
    assert repository.list_commentary_theme_submissions("2026-07")[0][
        "theme_code"
    ] == "NEW_MODE"

    details = pd.DataFrame([{"达人": "frozen", "金额": 100}])
    draft = repository.create_commentary_compensation_draft(
        "2026-07",
        jpy_to_usd_rate=0.0062,
        details=details,
        summary={"total_amount_jpy": 100},
    )
    repository.lock_commentary_compensation_version(draft.id)
    locked = repository.list_commentary_compensation_versions("2026-07")[0]
    assert locked.status == "LOCKED"
    assert locked.details.iloc[0]["金额"] == 100
