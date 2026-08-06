from __future__ import annotations

from uuid import uuid4

import streamlit as st

from config.settings import Settings
from database.ai_repository import AIRepository
from services.ai_agent_service import AIAgentService, AIAgentServiceError


def _ensure_chat_state(settings: Settings) -> None:
    if "ai_session_id" not in st.session_state:
        st.session_state.ai_session_id = str(uuid4())
    if "ai_conversation_id" not in st.session_state:
        st.session_state.ai_conversation_id = str(uuid4())
    if "ai_chat_messages" not in st.session_state:
        repository = AIRepository(settings.database_path)
        st.session_state.ai_chat_messages = repository.list_messages(
            st.session_state.ai_conversation_id,
            limit=30,
        )


def _new_conversation() -> None:
    st.session_state.ai_conversation_id = str(uuid4())
    st.session_state.ai_chat_messages = []


def render(settings: Settings) -> None:
    st.title("AI 助手")
    st.caption("只读查询 · 数据来自达人库、投稿明细与已保存结算版本")
    _ensure_chat_state(settings)

    toolbar = st.columns([1, 5])
    toolbar[0].button(
        "新建对话",
        icon=":material/add_comment:",
        use_container_width=True,
        on_click=_new_conversation,
    )
    provider_label = "DeepSeek" if settings.ai_provider == "deepseek" else "OpenAI"
    toolbar[1].caption(f"{provider_label} · {settings.ai_model}")

    if not settings.ai_configured:
        key_name = (
            "DEEPSEEK_API_KEY"
            if settings.ai_provider == "deepseek"
            else "OPENAI_API_KEY"
        )
        st.warning(
            "AI 服务尚未配置。请在本地 .env 或 Streamlit Secrets 中设置 "
            f"{key_name}。"
        )

    for message in st.session_state.ai_chat_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input(
        "查询达人、播放量、合同或结算数据",
        disabled=not settings.ai_configured,
    )
    if not prompt:
        return

    st.session_state.ai_chat_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            with st.spinner("正在核对数据库..."):
                service = AIAgentService(
                    settings.database_path,
                    api_key=settings.ai_api_key,
                    model=settings.ai_model,
                    provider=settings.ai_provider,
                    base_url=settings.ai_base_url,
                )
                response = service.ask(
                    conversation_id=st.session_state.ai_conversation_id,
                    session_id=st.session_state.ai_session_id,
                    message=prompt,
                )
            st.markdown(response.answer)
            if response.tool_calls:
                with st.expander("本次查询依据", expanded=False):
                    for index, item in enumerate(response.tool_calls, start=1):
                        st.markdown(f"**{index}. `{item['tool_name']}`**")
                        st.json(item["summary"], expanded=False)
            st.session_state.ai_chat_messages.append(
                {"role": "assistant", "content": response.answer}
            )
        except AIAgentServiceError as exc:
            st.error(str(exc))
