from __future__ import annotations

import streamlit as st

from config.settings import load_settings
from database.db import init_db, is_postgres_target
from ui.auth import render_logout, require_team_authentication
from ui.data_processing import render as render_data_processing
from ui.compensation import render as render_compensation
from ui.dashboard import DASHBOARD_CSS, render as render_dashboard
from ui.koc_management import render as render_koc_management
from ui.ai_assistant import render as render_ai_assistant


st.set_page_config(page_title="KOC 数据整理工具", page_icon="📊", layout="wide")
st.markdown(DASHBOARD_CSS, unsafe_allow_html=True)

settings = load_settings()
if not require_team_authentication(settings.team_password):
    st.stop()

init_db(settings.database_path)

with st.sidebar:
    st.header("KOC 数据整理工具")
    active_page = st.radio(
        "功能",
        ["数据整理", "数据看板", "达人库管理", "报酬结算", "AI 助手"],
        key="active_page",
    )
    st.caption("V2.0 · 数据看板与只读 AI 助手")
    database_label = (
        "Supabase PostgreSQL"
        if is_postgres_target(settings.database_path)
        else "本地 SQLite"
    )
    st.caption(f"数据库 · {database_label} 已连接")
    render_logout(settings.team_password)

if active_page == "数据整理":
    render_data_processing(settings.database_path, settings.timezone)
elif active_page == "数据看板":
    render_dashboard(settings)
elif active_page == "达人库管理":
    render_koc_management(settings)
elif active_page == "报酬结算":
    render_compensation(settings)
else:
    render_ai_assistant(settings)
