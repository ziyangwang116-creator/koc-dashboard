from __future__ import annotations

import hmac

import streamlit as st


AUTHENTICATED_KEY = "team_authenticated"
AUTH_ERROR_KEY = "team_auth_error"


AUTH_CSS = """
<style>
div[data-testid="stForm"] {
    border-radius: 8px;
}
.team-login-heading {
    margin-top: 10vh;
    text-align: center;
}
.team-login-heading h1 {
    font-size: 2rem;
    letter-spacing: 0;
    margin-bottom: 0.35rem;
}
.team-login-heading p {
    color: var(--text-color);
    opacity: 0.68;
    margin-bottom: 1.5rem;
}
</style>
"""


def password_matches(expected: str, submitted: str) -> bool:
    """Compare the shared password without exposing it to timing differences."""
    return hmac.compare_digest(
        expected.encode("utf-8"),
        submitted.encode("utf-8"),
    )


def require_team_authentication(team_password: str | None) -> bool:
    """Render the shared-password gate and return whether access is allowed."""
    if not team_password:
        return True
    if st.session_state.get(AUTHENTICATED_KEY) is True:
        return True

    st.markdown(AUTH_CSS, unsafe_allow_html=True)
    left, center, right = st.columns([1, 1.05, 1])
    del left, right
    with center:
        st.markdown(
            """
            <div class="team-login-heading">
                <h1>KOC 数据协作平台</h1>
                <p>团队访问</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.form("team_login_form", clear_on_submit=True):
            submitted_password = st.text_input(
                "团队密码",
                type="password",
                autocomplete="current-password",
            )
            submitted = st.form_submit_button(
                "登录",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            if password_matches(team_password, submitted_password):
                st.session_state[AUTHENTICATED_KEY] = True
                st.session_state.pop(AUTH_ERROR_KEY, None)
                st.rerun()
            st.session_state[AUTH_ERROR_KEY] = "团队密码不正确。"

        error = st.session_state.get(AUTH_ERROR_KEY)
        if error:
            st.error(error)
    return False


def render_logout(team_password: str | None) -> None:
    if not team_password or st.session_state.get(AUTHENTICATED_KEY) is not True:
        return
    st.divider()
    if st.button("退出登录", use_container_width=True):
        st.session_state.clear()
        st.rerun()
