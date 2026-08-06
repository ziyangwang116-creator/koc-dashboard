from streamlit.testing.v1 import AppTest


def test_compensation_page_is_a_top_level_function_with_settlement_controls():
    app = AppTest.from_file("app.py", default_timeout=30).run()
    app.radio[0].set_value("报酬结算")
    app.run()

    assert len(app.exception) == 0
    assert any("KOL报酬看板" in item.value for item in app.markdown)
    assert any(widget.label == "结算月份" for widget in app.selectbox)
    assert any(widget.label == "JPY → USD 汇率（当月3日）" for widget in app.number_input)
    assert any(button.label == "保存汇率" for button in app.button)
    assert any(button.label == "更新草根粉丝数（可选）" for button in app.button)
    assert not any(button.label == "手动更新后重新结算" for button in app.button)
    assert any(widget.label == "搜索达人（名称或 UID）" for widget in app.text_input)
    assert not any(metric.label == "缺少历史合同" for metric in app.metric)


def test_compensation_page_contains_a_separate_long_term_settlement_section():
    source = open("ui/compensation.py", encoding="utf-8").read()

    assert 'st.tabs(' in source
    assert '["草根达人结算", "长包达人结算", "解说达人结算"]' in source
    assert 'st.subheader("长包活动数录入")' in source
    assert '"保存活动数并重新计算"' in source
    assert '"更新长包 YouTube 粉丝数（可选）"' in source
    assert '"本项目有效活动数"' in source
    assert 'cpm_label="长包总体 CPM"' in source
    assert '"跨赛道活动结算明细"' in source
    assert '"跨赛道加成后播放量"' in source
    assert '"CPM计算播放量（无加成）"' in source
    assert "投稿奖励与播放等级奖励分别判定" in source
    assert 'st.subheader("解说达人月度报酬")' in source
    assert 'st.subheader("有效播放量审核")' not in source
    assert 'st.subheader("指定主题视频申报")' in source
    assert "_commentary_records(creator_records)" in source
    assert "parse_pasted_urls(raw_urls)" in source
    assert 'columns=["指定主题视频播放量"], errors="ignore"' in source
    assert source.count('"结算版本"') == 2
    assert '"保存解说结算表修改"' in source
    assert "切换月份不会删除其他月份的结算数据" in source
    assert "_commentary_result_from_details" in source
    assert '"更新解说 YouTube 粉丝数（可选）"' in source
    assert '"更新解说 TikTok 粉丝数（可选）"' in source
