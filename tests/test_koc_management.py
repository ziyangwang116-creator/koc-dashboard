from datetime import date

import pandas as pd
from streamlit.testing.v1 import AppTest

from database.koc_repository import KOCRepository
from models.enums import CreatorCategory
from services.koc_service import KOCService
from ui.koc_management import (
    _contract_period_table,
    _filter_contract_period_table,
    _save_contract_period_changes,
    _save_creator_editor_changes,
)


def _open_management_page() -> AppTest:
    app = AppTest.from_file("app.py", default_timeout=30).run()
    app.radio[0].set_value("达人库管理")
    app.run()
    return app


def test_koc_management_page_renders_new_filters_and_actions():
    app = _open_management_page()

    assert len(app.exception) == 0
    assert app.title[0].value == "达人库管理"
    selectbox_labels = {widget.label for widget in app.selectbox}
    multiselect_labels = {widget.label for widget in app.multiselect}
    assert "合作类别筛选" in selectbox_labels
    assert "合同类型筛选" in multiselect_labels
    assert "启用状态筛选" not in selectbox_labels
    assert "粉丝数更新状态筛选" not in multiselect_labels
    assert "粉丝来源筛选" not in multiselect_labels
    assert "结算资格筛选" not in selectbox_labels
    assert "人工确认筛选" not in selectbox_labels
    button_labels = {button.label for button in app.button}
    assert "全选合同类型" not in button_labels
    assert "清空合同类型筛选" not in button_labels
    assert "初始化 TikTok 登录" not in button_labels
    assert "测试 TikTok 登录状态" not in button_labels
    assert "测试单个 TikTok 达人" in button_labels
    assert "保存表格修改" in button_labels
    assert "保存手动粉丝数" in button_labels
    assert "保存历史合同版本" not in button_labels
    assert "更新全部 TikTok 达人粉丝数" in button_labels
    assert "更新全部 YouTube 达人粉丝数" in button_labels
    assert any(
        metric.label == "YouTube Data API" for metric in app.metric
    )
    assert any(metric.label == "TikTok 公开主页" for metric in app.metric)
    assert any("当前显示：" in caption.value for caption in app.caption)
    assert len(app.download_button) == 1


def test_contract_filter_is_multiselect_and_defaults_to_no_limit():
    app = _open_management_page()
    contract_filter = next(
        widget for widget in app.multiselect if widget.label == "合同类型筛选"
    )
    assert contract_filter.value == []


def test_contract_period_editor_renders_search_filters_and_delete_action():
    app = _open_management_page()
    toggle = next(widget for widget in app.toggle if widget.label == "显示合同周期")
    toggle.set_value(True)
    app.run()

    assert len(app.exception) == 0
    assert any(widget.label == "搜索合同周期" for widget in app.text_input)
    assert any(widget.label == "周期状态筛选" for widget in app.multiselect)
    assert any(button.label == "删除所选周期" for button in app.button)


def test_main_creator_table_does_not_show_internal_follower_status_fields():
    source = open("ui/koc_management.py", encoding="utf-8").read()
    assert '"更新单个达人粉丝数"' in source
    table_source = source[source.index('st.subheader("达人列表")') :]
    assert "st.data_editor(" in table_source
    assert '"保存表格修改"' in table_source
    assert '"合同操作"' in table_source
    assert '"合同生效月份"' in table_source
    assert 'st.toggle("显示合同周期"' in table_source
    assert '"保存合同周期"' in source
    assert '"搜索合同周期"' in source
    assert '"周期状态筛选"' in source
    assert '"删除所选周期"' in source
    assert '"follower_source":' not in table_source
    assert '"follower_sync_status":' not in table_source
    assert '"follower_sync_error":' not in table_source


def test_direct_table_contract_edit_creates_an_effective_contract_version(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="table-edit-creator",
        koc_name="table edit creator",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["TT"],
        effective_date=date(2026, 5, 1),
    )
    edited = pd.DataFrame(
        [
            {
                "记录ID": record.id,
                "UID": record.user_id,
                "达人名称": record.koc_name,
                "合作类别": "草根",
                "合同操作": "新合同生效",
                "合同类型": "YTB shorts",
                "合同开始日期": date(2026, 5, 1),
                "合同截止日期": date(2026, 10, 31),
                "合同生效月份": "2026-07",
                "合同修改说明": "7月真实换约",
                "主页链接": None,
                "粉丝数": None,
                "粉丝数可结算": False,
                "启用": True,
                "备注": None,
                "粉丝数最后更新时间": "-",
            }
        ]
    )

    updated_count, errors = _save_creator_editor_changes(
        KOCService(repository),
        [record],
        edited,
    )

    assert (updated_count, errors) == (1, [])
    updated = repository.get(record.id)
    assert updated is not None
    assert updated.contract_types == ("YTB shorts",)
    assert updated.contract_start_date == date(2026, 7, 1)
    assert [
        (snapshot.effective_date, snapshot.contract_types, snapshot.contract_end_date)
        for snapshot in repository.list_profile_history_for_creator(record.id)
    ] == [
        (date(2026, 5, 1), ("TT",), date(2026, 6, 30)),
        (date(2026, 7, 1), ("YTB shorts",), date(2026, 10, 31)),
    ]


def test_contract_period_table_merges_profile_only_snapshots_and_syncs_master(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="contract-period-creator",
        koc_name="contract period creator",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["TT"],
        effective_date=date(2026, 5, 1),
    )
    repository.update(
        record.id,
        user_id=record.user_id,
        koc_name=record.koc_name,
        creator_category=record.creator_category,
        contract_types=record.contract_types,
        homepage_url=record.homepage_url,
        follower_count=record.follower_count,
        active=record.active,
        note=record.note,
        effective_date=date(2026, 6, 15),
    )
    current = repository.get(record.id)
    assert current is not None
    periods = _contract_period_table(
        [current],
        repository.list_contract_periods(record.id),
    )
    assert len(periods) == 1

    edited = periods.copy()
    edited.loc[0, "合同类型"] = "YTB"
    edited.loc[0, "合同截止日期"] = date(2026, 8, 31)
    updated_count, errors = _save_contract_period_changes(
        KOCService(repository),
        [current],
        periods,
        edited,
    )

    assert (updated_count, errors) == (1, [])
    reloaded = repository.get(record.id)
    assert reloaded is not None
    assert reloaded.contract_types == ("YTB",)
    assert reloaded.contract_end_date == date(2026, 8, 31)
    assert [
        (snapshot.contract_types, snapshot.contract_start_date, snapshot.contract_end_date)
        for snapshot in repository.list_profile_history_for_creator(record.id)
    ] == [
        (("YTB",), date(2026, 5, 1), date(2026, 8, 31)),
        (("YTB",), date(2026, 5, 1), date(2026, 8, 31)),
    ]


def test_contract_period_search_and_filters_can_be_combined():
    table = pd.DataFrame(
        [
            {
                "达人": "Alpha Creator",
                "UID": "yt-alpha",
                "合同类型": "YTB shorts",
                "状态": "当前",
            },
            {
                "达人": "Beta Creator",
                "UID": "tt-beta",
                "合同类型": "5月TT",
                "状态": "已替换",
            },
            {
                "达人": "Gamma Creator",
                "UID": "yt-gamma",
                "合同类型": "YTB",
                "状态": "已结束",
            },
        ]
    )

    searched = _filter_contract_period_table(table, search="alpha")
    assert searched["UID"].tolist() == ["yt-alpha"]

    filtered = _filter_contract_period_table(
        table,
        search="creator",
        contract_types=["5月TT"],
        statuses=["已替换"],
    )
    assert filtered["UID"].tolist() == ["tt-beta"]
