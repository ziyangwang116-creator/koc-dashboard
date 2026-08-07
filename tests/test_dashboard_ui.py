from datetime import date

import pandas as pd
from streamlit.testing.v1 import AppTest

from ui.dashboard import (
    _comparison_frame,
    _comparison_month_options,
    _creator_video_type_comparison,
)


def test_dashboard_page_renders_persisted_dashboard_and_update_control():
    app = AppTest.from_file("app.py", default_timeout=30).run()
    app.radio[0].set_value("数据看板")
    app.run()

    assert len(app.exception) == 0
    assert app.file_uploader[0].label == "上传月度完整导出文件"
    assert any(button.label == "导入并更新看板" for button in app.button)
    assert any(widget.label == "搜索达人或 UID" for widget in app.text_input)
    assert {widget.label for widget in app.multiselect} >= {
        "达人",
        "合作类别",
        "平台",
        "内容形式",
    }
    include_external = next(
        widget for widget in app.toggle if widget.label == "包含异业数据"
    )
    assert include_external.value is False
    assert any(
        widget.label == "异业视频链接" for widget in app.text_area
    )
    assert any(button.label == "识别链接" for button in app.button)
    dashboard_view = next(
        widget for widget in app.segmented_control if widget.label == "看板视图"
    )
    assert set(dashboard_view.options) == {
        "总览",
        "月度对比",
        "结构分析",
        "达人与明细",
    }
    assert len(app.metric) >= 7


def test_month_comparison_uses_calendar_months_and_marks_new_dimensions():
    options = _comparison_month_options(
        pd.DataFrame(
            {
                "publish_date": [date(2026, 5, 1), date(2026, 7, 1)],
            }
        )
    )
    assert options == [date(2026, 7, 1), date(2026, 6, 1), date(2026, 5, 1)]

    comparison = _comparison_frame(
        pd.DataFrame(
            [{"source_platform": "YouTube", "post_count": 3, "total_views": 300}]
        ),
        pd.DataFrame(
            [{"source_platform": "TikTok", "post_count": 2, "total_views": 200}]
        ),
        key="source_platform",
        label="source_platform",
    )
    youtube = comparison.loc[
        comparison["source_platform"].eq("YouTube")
    ].iloc[0]
    assert youtube["当前播放量"] == 300
    assert youtube["对比播放量"] == 0
    assert pd.isna(youtube["播放量增长率"])


def test_creator_month_comparison_includes_video_type_posts_and_decline_alerts():
    base_columns = {
        "user_id": "creator-a",
        "creator_label": "达人 A",
        "creator_category": "草根",
        "contract_types": "YTB",
        "follower_count": 1_000,
        "source_file": "monthly.xlsx",
        "source_platform": "YouTube",
        "likes": 0,
        "comment": 0,
        "reposted": 0,
        "collect": 0,
        "publish_date": date(2026, 7, 1),
    }
    current = pd.DataFrame(
        [
            {**base_columns, "creator_key": "creator-a", "content_type": "long", "views": 60},
            {**base_columns, "creator_key": "creator-a", "content_type": "YTB shorts", "views": 500},
            {
                **base_columns,
                "creator_key": "creator-b",
                "user_id": "creator-b",
                "creator_label": "达人 B",
                "content_type": "tiktok",
                "views": 80,
            },
        ]
    )
    baseline = pd.DataFrame(
        [
            {**base_columns, "creator_key": "creator-a", "content_type": "long", "views": 50},
            {**base_columns, "creator_key": "creator-a", "content_type": "long", "views": 50},
            {**base_columns, "creator_key": "creator-a", "content_type": "YTB shorts", "views": 200},
        ]
    )

    comparison = _creator_video_type_comparison(current, baseline, [])
    creator_a = comparison.loc[comparison["creator_key"].eq("creator-a")].iloc[0]
    creator_b = comparison.loc[comparison["creator_key"].eq("creator-b")].iloc[0]

    assert creator_a["Long播放量（本月）"] == 60
    assert creator_a["Long播放量（对比）"] == 100
    assert creator_a["Long播放量变化"] == -40
    assert creator_a["Long播放量变化率"] == -40.0
    assert creator_a["Long投稿数（本月）"] == 1
    assert creator_a["Long投稿数（对比）"] == 2
    assert creator_a["Long投稿数变化率"] == -50.0
    assert creator_a["预警"] == "下降超过30%"
    assert creator_b["达人状态"] == "新增达人"
