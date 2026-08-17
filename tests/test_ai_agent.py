from __future__ import annotations

import json
import subprocess
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from ai.tools import AIToolError, AIToolRegistry
from ai.visualizations import build_tool_visualizations, sanitize_visualizations
from api.followers import JobStore
from api.imports import PreviewStore
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
    assert {"ai_conversation", "ai_message", "ai_tool_audit", "ai_pending_action"} <= tables


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


def test_operational_summary_is_database_backed_and_contains_ranked_metrics(tmp_path):
    database_path = tmp_path / "ai.db"
    _seed_ai_database(database_path)
    result = AIToolRegistry(database_path).execute(
        "get_operational_summary",
        {"period_month": "2026-07", "include_cross_industry": False},
    )

    assert result["status"] == "ok"
    assert result["source"] == "database_tool_result"
    assert result["creator_count"] == 1
    assert result["summary"]["post_count"] == 1
    assert result["summary"]["views"] == 1000
    assert result["summary"]["by_platform"][0]["source_platform"] == "YouTube"
    assert result["top_creators_by_views"][0]["views"] == 1000
    assert result["data_quality"]["unmatched_post_count"] == 0


def test_month_comparison_visualizations_use_only_tool_result_values():
    result = {
        "status": "ok",
        "creator": {"creator_id": 7, "koc_name": "白黑女神"},
        "current_month": "2026-07",
        "baseline_month": "2026-06",
        "current": {
            "post_count": 38,
            "views": 77307,
            "by_subtype": [
                {"subtype": "long", "post_count": 3, "views": 62969},
                {"subtype": "YTB shorts", "post_count": 3, "views": 10294},
                {"subtype": "livestream", "post_count": 32, "views": 4044},
            ],
        },
        "baseline": {
            "post_count": 31,
            "views": 26249,
            "by_subtype": [
                {"subtype": "long", "post_count": 0, "views": 0},
                {"subtype": "shorts", "post_count": 1, "views": 1659},
                {"subtype": "livestream", "post_count": 30, "views": 24590},
            ],
        },
    }

    charts = build_tool_visualizations("compare_creator_months", result)

    assert len(charts) == 4
    assert charts[0]["data"] == [
        {
            "category": "投稿数量",
            "baseline": 31,
            "current": 38,
            "change": 7,
            "change_rate": round(7 / 31, 6),
            "decline_over_30_percent": False,
        }
    ]
    subtype_views = charts[3]["data"]
    assert subtype_views == [
        {
            "category": "long",
            "baseline": 0,
            "current": 62969,
            "change": 62969,
            "change_rate": None,
            "decline_over_30_percent": False,
        },
        {
            "category": "shorts",
            "baseline": 1659,
            "current": 10294,
            "change": 8635,
            "change_rate": round(8635 / 1659, 6),
            "decline_over_30_percent": False,
        },
        {
            "category": "livestream",
            "baseline": 24590,
            "current": 4044,
            "change": -20546,
            "change_rate": round(-20546 / 24590, 6),
            "decline_over_30_percent": True,
        },
    ]
    assert subtype_views[-1]["decline_over_30_percent"] is True
    assert charts[3]["warnings"][0]["level"] == "danger"
    assert charts[3]["source"]["database_backed"] is True


def test_visualization_sanitizer_rejects_model_authored_or_invalid_payloads():
    unsafe = {
        "kind": "grouped_bar",
        "id": "<script>alert(1)</script>",
        "title": "fake",
        "series": [
            {"key": "baseline", "label": "A", "color": "#000"},
            {"key": "current", "label": "B", "color": "#111"},
        ],
        "data": [{"category": "x", "baseline": 1, "current": 2}],
        "source": {"tool": "model_output", "database_backed": False},
    }

    assert sanitize_visualizations([unsafe]) == []


def test_visualization_sanitizer_recalculates_derived_values_from_database_values():
    chart = build_tool_visualizations(
        "compare_creator_months",
        {
            "status": "ok",
            "creator": {"creator_id": 7, "koc_name": "白黑女神"},
            "current_month": "2026-07",
            "baseline_month": "2026-06",
            "current": {"post_count": 7, "views": 700, "by_subtype": []},
            "baseline": {"post_count": 10, "views": 1000, "by_subtype": []},
        },
    )[0]
    chart["data"][0].update(
        {
            "change": 999,
            "change_rate": 99,
            "decline_over_30_percent": True,
        }
    )

    sanitized = sanitize_visualizations([chart])

    assert sanitized[0]["data"][0] == {
        "category": "投稿数量",
        "baseline": 10,
        "current": 7,
        "change": -3,
        "change_rate": -0.3,
        "decline_over_30_percent": False,
    }


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


class _FakeComparisonChatCompletions:
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
                                    id="compare-1",
                                    function=SimpleNamespace(
                                        name="compare_creator_months",
                                        arguments=json.dumps(
                                            {
                                                "query": "AI测试达人",
                                                "current_month": "2026-07",
                                                "baseline_month": "2026-06",
                                                "include_cross_industry": False,
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
                        content="## 月度对比\n\n7 月播放量低于 6 月。",
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


def test_agent_persists_database_backed_comparison_visualizations(tmp_path):
    database_path = tmp_path / "ai.db"
    _seed_ai_database(database_path)
    fake_chat = _FakeComparisonChatCompletions()
    service = AIAgentService(
        database_path,
        api_key=None,
        model="deepseek-chat",
        provider="deepseek",
        client=SimpleNamespace(chat=SimpleNamespace(completions=fake_chat)),
    )

    response = service.ask(
        conversation_id="comparison-conversation",
        session_id="session-1",
        message="比较 AI测试达人 2026-06 和 2026-07",
    )

    assert len(response.visualizations) == 4
    assert response.visualizations[0]["source"]["tool"] == "compare_creator_months"
    assert response.visualizations[1]["data"][0]["baseline"] == 2000
    assert response.visualizations[1]["data"][0]["current"] == 1000
    stored = AIRepository(database_path).list_messages("comparison-conversation")
    assistant = stored[-1]
    assert len(assistant["metadata"]["visualizations"]) == 4
    assert assistant["metadata"]["visualizations"][1]["data"][0][
        "decline_over_30_percent"
    ] is True


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


def test_agent_write_requires_confirmation_then_updates_creator(tmp_path):
    database_path = tmp_path / "ai-write.db"
    creator = _seed_ai_database(database_path)
    AIRepository(database_path).ensure_conversation("write-conversation", "session-1")
    tools = AIToolRegistry(
        database_path,
        conversation_id="write-conversation",
        session_id="session-1",
        operator_name="张三",
    )
    arguments = {
        "query": creator.koc_name,
        "koc_name": None,
        "homepage_url": None,
        "youtube_homepage_url": None,
        "tiktok_homepage_url": None,
        "follower_count": None,
        "youtube_follower_count": 12345,
        "tiktok_follower_count": None,
        "note": None,
        "active": None,
        "settlement_eligible": None,
        "expected_updated_at": creator.updated_at,
        "reason": "Agent 测试更新粉丝",
    }

    pending = tools.execute("update_creator_profile", arguments)

    assert pending["status"] == "confirmation_required"
    action_id = pending["action"]["action_id"]
    assert KOCRepository(database_path).get(creator.id).youtube_follower_count == 5000

    service = AIAgentService(
        database_path,
        api_key=None,
        model="test-model",
        provider="deepseek",
        client=SimpleNamespace(),
        session_id="session-1",
        operator_name="张三",
    )
    result = service.confirm_action(
        conversation_id="write-conversation",
        session_id="session-1",
        action_id=action_id,
        approve=True,
    )

    assert result["status"] == "executed"
    assert KOCRepository(database_path).get(creator.id).youtube_follower_count == 12345
    pending_row = AIRepository(database_path).get_pending_action(
        action_id,
        conversation_id="write-conversation",
        session_id="session-1",
    )
    assert pending_row["status"] == "EXECUTED"


def test_agent_write_rejects_secrets_and_can_cancel_pending_action(tmp_path):
    database_path = tmp_path / "ai-reject.db"
    _seed_ai_database(database_path)
    AIRepository(database_path).ensure_conversation("reject-conversation", "session-1")
    tools = AIToolRegistry(
        database_path,
        conversation_id="reject-conversation",
        session_id="session-1",
    )
    with pytest.raises(AIToolError, match="密钥"):
        tools.execute(
            "modify_project_file",
            {
                "path": ".env",
                "old_text": "A",
                "new_text": "B",
                "expected_sha256": None,
                "max_replacements": 1,
                "reason": "不应允许",
            },
        )

    arguments = {
        "period_month": "2026-07",
        "jpy_to_usd_rate": 0.0062,
    }
    pending = tools.execute("save_exchange_rate", arguments)
    service = AIAgentService(
        database_path,
        api_key=None,
        model="test-model",
        provider="deepseek",
        client=SimpleNamespace(),
        session_id="session-1",
    )
    result = service.confirm_action(
        conversation_id="reject-conversation",
        session_id="session-1",
        action_id=pending["action"]["action_id"],
        approve=False,
    )
    assert result["status"] == "rejected"
    assert DashboardRepository(database_path).get_jpy_to_usd_rate("2026-07") is None


def test_agent_import_preview_requires_confirmation_and_replaces_month(tmp_path):
    database_path = tmp_path / "agent-import.db"
    init_db(database_path)
    preview_store = PreviewStore()
    data = pd.DataFrame(
        [
            {
                "source_file": "2026-07.xlsx",
                "user_id": "creator-1",
                "publish_date": "2026-07-05",
                "source_platform": "YouTube",
                "url": "https://youtube.test/new",
                "views": 123,
            }
        ]
    )
    token = preview_store.create(
        data=data,
        unmatched_rows=[],
        period_months=["2026-07"],
        source_files=["2026-07.xlsx"],
        input_row_count=1,
        matched_row_count=1,
        cross_industry_flagged_count=0,
        column_warnings=[],
    )
    tools = AIToolRegistry(
        database_path,
        conversation_id="conversation-import",
        session_id="session-1",
        import_preview_store=preview_store,
    )
    arguments = {
        "preview_token": token,
        "mode": "replace_months",
        "reason": "导入 7 月完整数据",
    }

    pending = tools.execute("import_posts_from_preview", arguments)
    assert pending["status"] == "confirmation_required"
    assert DashboardRepository(database_path).count_posts() == 0

    result = tools.execute("import_posts_from_preview", arguments, allow_writes=True)
    assert result["mode"] == "REPLACE_MONTHS"
    assert result["saved_count"] == 1
    assert DashboardRepository(database_path).count_posts() == 1


def test_agent_import_preview_supports_append_or_update(tmp_path):
    database_path = tmp_path / "agent-import-append.db"
    repository = DashboardRepository(database_path)
    repository.upsert_posts(
        pd.DataFrame(
            [{"publish_date": "2026-07-01", "source_platform": "YouTube", "url": "https://x/old"}]
        )
    )
    preview_store = PreviewStore()
    token = preview_store.create(
        data=pd.DataFrame(
            [{"publish_date": "2026-07-02", "source_platform": "YouTube", "url": "https://x/new"}]
        ),
        unmatched_rows=[],
        period_months=["2026-07"],
        source_files=["supplement.xlsx"],
        input_row_count=1,
        matched_row_count=1,
        cross_industry_flagged_count=0,
        column_warnings=[],
    )
    tools = AIToolRegistry(
        database_path,
        conversation_id="conversation-import-append",
        session_id="session-1",
        import_preview_store=preview_store,
    )
    arguments = {
        "preview_token": token,
        "mode": "append_or_update",
        "reason": "补充一条投稿",
    }

    pending = tools.execute("import_posts_from_preview", arguments)
    assert pending["action"]["preview"]["mode"] == "APPEND_OR_UPDATE"
    result = tools.execute("import_posts_from_preview", arguments, allow_writes=True)
    assert result["mode"] == "APPEND_OR_UPDATE"
    assert repository.count_posts() == 2


def test_agent_can_preview_and_rollback_latest_monthly_import(tmp_path):
    database_path = tmp_path / "agent-rollback.db"
    repository = DashboardRepository(database_path)
    first = repository.save_monthly_import(
        pd.DataFrame(
            [{"publish_date": "2026-07-01", "source_platform": "YouTube", "url": "https://x/old"}]
        ),
        replace_months=True,
        source_files=["old.xlsx"],
        file_hashes={"old.xlsx": ""},
    )
    second = repository.save_monthly_import(
        pd.DataFrame(
            [{"publish_date": "2026-07-02", "source_platform": "YouTube", "url": "https://x/new"}]
        ),
        replace_months=True,
        source_files=["new.xlsx"],
        file_hashes={"new.xlsx": ""},
    )
    assert first.batch_id != second.batch_id
    tools = AIToolRegistry(
        database_path,
        conversation_id="conversation-rollback",
        session_id="session-1",
    )
    arguments = {"batch_id": second.batch_id, "reason": "误导入"}

    pending = tools.execute("rollback_post_import", arguments)
    assert pending["action"]["preview"]["period_months"] == ["2026-07"]
    result = tools.execute("rollback_post_import", arguments, allow_writes=True)
    assert result["restored_count"] == 1
    assert DashboardRepository(database_path).load_posts().iloc[0]["url"] == "https://x/old"


def test_agent_starts_and_reports_batch_follower_update(tmp_path):
    database_path = tmp_path / "agent-followers.db"
    init_db(database_path)
    record = SimpleNamespace(id=1)

    class FakeRepository:
        def list(self, active=True):
            return [record]

    class FakeFollowerService:
        repository = FakeRepository()

        @staticmethod
        def has_youtube_contract(item):
            return True

        @staticmethod
        def has_tiktok_contract(item):
            return False

        @staticmethod
        def _homepage_for_platform(item, platform):
            return "https://youtube.com/@creator"

        @staticmethod
        def _detail_row(outcome):
            return {"status": outcome.status, "platform": outcome.result.platform}

        def update_many(self, record_ids, *, required_platform, progress_callback):
            outcome = SimpleNamespace(
                status="成功",
                result=SimpleNamespace(platform=required_platform),
            )
            progress_callback(1, 1, record, outcome)

    job_store = JobStore()
    tools = AIToolRegistry(
        database_path,
        conversation_id="conversation-followers",
        session_id="session-1",
        follower_service_factory=FakeFollowerService,
        follower_job_store=job_store,
    )
    arguments = {"platform": "YouTube", "reason": "月度更新"}
    pending = tools.execute("start_follower_batch_update", arguments)
    assert pending["action"]["preview"]["total_attempts"] == 1

    accepted = tools.execute("start_follower_batch_update", arguments, allow_writes=True)
    for _ in range(50):
        job = tools.execute(
            "get_follower_update_job",
            {"job_id": accepted["job_id"], "include_results": True},
        )["job"]
        if job["status"] in {"SUCCEEDED", "FAILED"}:
            break
        time.sleep(0.01)
    assert job["status"] == "SUCCEEDED"
    assert job["processed"] == 1


def test_agent_git_commit_stages_only_confirmed_paths(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=project_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Agent Test"], cwd=project_root, check=True)
    subprocess.run(["git", "config", "user.email", "agent@example.test"], cwd=project_root, check=True)
    tracked = project_root / "README.md"
    tracked.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=project_root, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=project_root, check=True, capture_output=True)
    tracked.write_text("after\n", encoding="utf-8")

    tools = AIToolRegistry(
        tmp_path / "git-agent.db",
        conversation_id="conversation-git",
        session_id="session-1",
        project_root=project_root,
        git_enabled=True,
    )
    arguments = {
        "paths": ["README.md"],
        "commit_message": "Update readme",
        "push": False,
        "deploy": False,
    }
    pending = tools.execute("publish_project_changes", arguments)
    assert pending["action"]["preview"]["paths"] == ["README.md"]

    result = tools.execute("publish_project_changes", arguments, allow_writes=True)
    assert result["push_status"] == "not_requested"
    subject = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert subject == "Update readme"


def test_agent_github_api_backend_can_publish_without_local_git(tmp_path):
    project_root = tmp_path / "cloud-source"
    project_root.mkdir()
    (project_root / "README.md").write_text("cloud update\n", encoding="utf-8")
    tools = AIToolRegistry(
        tmp_path / "github-agent.db",
        conversation_id="conversation-github",
        session_id="session-1",
        project_root=project_root,
        git_enabled=True,
    )
    tools.github_repository = "owner/repository"
    tools.github_token = "test-token-never-returned"
    calls = []

    def fake_request(method, path, payload=None, *, allow_not_found=False):
        calls.append((method, path, payload, allow_not_found))
        if path.startswith("contents/"):
            return {"sha": "remote-old-sha"}
        if path.startswith("git/ref/heads/"):
            return {"object": {"sha": "parent-sha"}}
        if path == "git/commits/parent-sha":
            return {"tree": {"sha": "base-tree-sha"}}
        if path == "git/blobs":
            return {"sha": "blob-sha"}
        if path == "git/trees":
            return {"sha": "tree-sha"}
        if path == "git/commits":
            return {"sha": "new-commit-sha"}
        return {}

    tools._github_request = fake_request
    arguments = {
        "paths": ["README.md"],
        "commit_message": "Publish cloud update",
        "push": True,
        "deploy": True,
    }
    pending = tools.execute("publish_project_changes", arguments)
    assert pending["action"]["preview"]["backend"] == "github_api"

    result = tools.execute("publish_project_changes", arguments, allow_writes=True)
    assert result["commit_sha"] == "new-commit-sha"
    assert result["push_status"] == "succeeded"
    assert result["deploy_status"] == "triggered_by_git_push"
    assert "test-token-never-returned" not in json.dumps(result)
    assert any(method == "PATCH" and path.startswith("git/refs/heads/") for method, path, _, _ in calls)
