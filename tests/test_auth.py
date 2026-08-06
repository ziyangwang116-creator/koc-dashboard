from streamlit.testing.v1 import AppTest

from ui.auth import password_matches


def test_password_matches_requires_an_exact_value():
    assert password_matches("shared-secret", "shared-secret") is True
    assert password_matches("shared-secret", "Shared-secret") is False
    assert password_matches("shared-secret", "shared-secret ") is False


def test_team_login_rejects_wrong_password_and_accepts_correct_password(tmp_path):
    app_file = tmp_path / "auth_app.py"
    app_file.write_text(
        """
import streamlit as st
from ui.auth import require_team_authentication

st.set_page_config(page_title="Auth test")
if require_team_authentication("shared-secret"):
    st.success("ACCESS_GRANTED")
""",
        encoding="utf-8",
    )

    app = AppTest.from_file(str(app_file), default_timeout=10).run()
    assert app.text_input[0].label == "团队密码"
    assert not any(item.value == "ACCESS_GRANTED" for item in app.success)

    app.text_input[0].set_value("wrong-password")
    app.button[0].click().run()
    assert any(item.value == "团队密码不正确。" for item in app.error)

    app.text_input[0].set_value("shared-secret")
    app.button[0].click().run()
    assert any(item.value == "ACCESS_GRANTED" for item in app.success)
