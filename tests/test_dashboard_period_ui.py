from streamlit.testing.v1 import AppTest


def test_dashboard_exposes_monthly_and_weekly_period_controls():
    app = AppTest.from_file("app.py", default_timeout=30).run()
    app.radio[0].set_value("数据看板")
    app.run()

    assert len(app.exception) == 0
    assert any(widget.label == "统计周期" for widget in app.radio)
    assert any(widget.label == "月份" for widget in app.selectbox)
