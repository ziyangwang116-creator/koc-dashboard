from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from ai.tools import AIToolRegistry
from database.ai_repository import AIRepository
from database.dashboard_repository import DashboardRepository
from database.db import connect, init_db
from database.koc_repository import KOCRepository
from services.ai_agent_service import AIAgentService, AIAgentServiceError


def _seed_ai_database(database_path):
    init_db(database_path)
    creator = KOCRepository(database_path).create(
        user_id="ai-creator-uid",
        koc_name="AI测试达人",
        creator_category="GRASSROOT",
        contract_types=["YTB shorts"],
        follower_count=5000,
        contract_start_date="2026-05-01",
        contract_end_date="2026-10-31",
    )
    posts = pd.DataFrame(
        [
            {
                "source_file": "7月完整导出.xlsx",
                "user_id": "ai-creator-uid",
                "koc_name": "AI测试达人",
                "kol_name": "AI测试达人",
                "matched": True,
                "source_platform": "YouTube",
                "subtype": "shorts",
                "content_type": "shorts",
                "publish_date": "2026-07-05",
                "title": "测试视频",
                "url": "https://youtube.test/short-1",
                "views": 1000,
                "view": 1000,
                "likes": 20,
                "comment": 3,
                "reposted": 2,
            },
            {
                "source_file": "6月完整导出.xlsx",
                "user_id": "ai-creator-uid",
                "koc_name": "AI测试达人",
                "kol_name": "AI测试达人",
                "matched": True,
                "source_platform": "YouTube",
                "subtype": "shorts",
                "content_type": "shorts",
                "publish_date": "2026-06-05",
                "title": "上月视频",
                "url": "https://youtube.test/short-0",
                "views": 2000,
                "view": 2000,
                "likes": 30,
                "comment": 4,
                "reposted": 1,
            },
        ]
    )
    DashboardRepository(database_path).upsert_posts(posts)
    return creator


def test_ai_storage_migration_and_conversation_round_trip(tmp_path):
    database_path = tmp_path / "ai.db"
    init_db(database_path)
    repository = AIRepository(database_path)

    repository.ensure_conversation("conversation-1", "session-1", title="测试")
    repository.add_message("conversation-1", "user", "查询达人")
    repository.add_message("conversation-1", "assistant", "已查询")

    assert [item["role"] for item in repository.list_messages("conversation-1")] == [
        "user",
        "assistant",
    ]
    with connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {"ai_conversation", "ai_message", "ai_tool_audit"} <= tables


def test_read_only_tools_use_creator_database_and_persisted_versions(tmp_path):
    database_path = tmp_path / "ai.db"
    creator = _seed_ai_database(database_path)
    dashboard = DashboardRepository(database_path)
    dashboard.create_compensation_draft(
        "2026-07",
        jpy_to_usd_rate=0.0062,
        details=pd.DataFrame(
            [
                {
                    "creator_id": creator.id,
                    "达人": creator.koc_name,
                    "rank": "D",
                    "计费播放量": 1000,
                    "博主应收（美元）": 77.0,
                }
            ]
        ),
        summary={"creator_count": 1},
    )
    tools = AIToolRegistry(database_path)

    profile = tools.execute("get_creator_profile", {"query": "AI测试达人"})
    performance = tools.execute(
        "get_creator_monthly_performance",
        {
            "query": "AI测试达人",
            "period_month": "2026-07",
            "include_cross_industry": False,
        },
    )
    comparison = tools.execute(
        "compare_creator_months",
        {
            "query": "AI测试达人",
            "current_month": "2026-07",
            "baseline_month": "2026-06",
            "include_cross_industry": False,
        },
    )
    compensation = tools.execute(
        "get_compensation_breakdown",
        {
            "query": "AI测试达人",
            "period_month": "2026-07",
            "settlement_type": "auto",
        },
    )

    assert profile["creator"]["creator_id"] == creator.id
    assert performance["performance"]["post_count"] == 1
    assert performance["performance"]["views"] == 1000
    assert comparison["overall_change"]["views"]["decline_over_30_percent"] is True
    assert compensation["source"] == "persisted_compensation_versions_only"
    assert compensation["settlements"][0]["details"]["rank"] == "D"


class _FakeResponses:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return SimpleNamespace(
                id="response-1",
                output=[
                    SimpleNamespace(
                        type="function_call",
                        call_id="call-1",
                        name="search_creators",
                        arguments=json.dumps(
                            {
                                "search": "AI测试达人",
                                "creator_category": None,
                                "contract_type": None,
                                "active_only": True,
                                "limit": 10,
                            },
                            ensure_ascii=False,
                        ),
                    )
                ],
                output_text="",
            )
        return SimpleNamespace(
            id="response-2",
            output=[],
            output_text="AI测试达人当前在达人库中。",
        )


class _FakeChatCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    id="call-1",
                                    function=SimpleNamespace(
                                        name="search_creators",
                                        arguments=json.dumps(
                                            {
                                                "search": "AI测试达人",
                                                "creator_category": None,
                                                "contract_type": None,
                                                "active_only": True,
                                                "limit": 10,
                                            },
                                            ensure_ascii=False,
                                        ),
                                    ),
                                )
                            ],
                        )
                    )
                ]
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="AI测试达人当前在达人库中。",
                        tool_calls=[],
                    )
                )
            ]
        )


def test_agent_service_executes_tools_and_writes_sanitized_audit(tmp_path):
    database_path = tmp_path / "ai.db"
    _seed_ai_database(database_path)
    fake_responses = _FakeResponses()
    client = SimpleNamespace(responses=fake_responses)
    service = AIAgentService(
        database_path,
        api_key=None,
        model="test-model",
        provider="deepseek",
        base_url="https://api.deepseek.com",
        client=client,
    )

    response = service.ask(
        conversation_id="conversation-1",
        session_id="session-1",
        message="查询 AI测试达人",
    )

    assert response.answer == "AI测试达人当前在达人库中。"
    assert response.tool_calls[0]["tool_name"] == "search_creators"
    assert "previous_response_id" not in fake_responses.calls[1]
    second_input = fake_responses.calls[1]["input"]
    assert any(item.get("type") == "function_call" for item in second_input)
    assert any(item.get("type") == "function_call_output" for item in second_input)
    with connect(database_path) as connection:
        audit = connection.execute(
            "SELECT tool_name, status, arguments_json FROM ai_tool_audit"
        ).fetchone()
    assert audit["tool_name"] == "search_creators"
    assert audit["status"] == "SUCCESS"
    assert "API_KEY" not in audit["arguments_json"]


def test_deepseek_agent_uses_chat_completions_tool_loop(tmp_path):
    database_path = tmp_path / "ai.db"
    _seed_ai_database(database_path)
    fake_chat = _FakeChatCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=fake_chat))
    service = AIAgentService(
        database_path,
        api_key=None,
        model="deepseek-chat",
        provider="deepseek",
        base_url="https://api.deepseek.com",
        client=client,
    )

    response = service.ask(
        conversation_id="conversation-deepseek",
        session_id="session-1",
        message="查询 AI测试达人",
    )

    assert response.answer == "AI测试达人当前在达人库中。"
    assert response.tool_calls[0]["tool_name"] == "search_creators"
    assert len(fake_chat.calls) == 2
    assert fake_chat.calls[0]["tool_choice"] == "auto"
    assert fake_chat.calls[0]["tools"][0]["type"] == "function"
    assert any(item["role"] == "tool" for item in fake_chat.calls[1]["messages"])


def test_agent_service_surfaces_wrapped_rate_limit_errors(tmp_path):
    class _RateLimitedResponses:
        def create(self, **_kwargs):
            raise RuntimeError("exceeded retry limit, last status: 429 Too Many Requests")

    service = AIAgentService(
        tmp_path / "ai.db",
        api_key=None,
        model="test-model",
        provider="deepseek",
        base_url="https://api.deepseek.com",
        client=SimpleNamespace(responses=_RateLimitedResponses()),
    )

    with pytest.raises(AIAgentServiceError, match="限流（429）"):
        service.ask(
            conversation_id="conversation-1",
            session_id="session-1",
            message="查询达人",
        )
