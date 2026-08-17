from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.main import create_app
from config.settings import Settings
from services.ai_agent_service import AIAgentResponse, AIAgentServiceError


TEAM_PASSWORD = "test-team-password"


def _settings(database_path, *, configured: bool = True) -> Settings:
    return Settings(
        timezone="Asia/Shanghai",
        database_path=database_path,
        output_dir="data/output",
        youtube_api_key=None,
        tiktok_browser_data_dir="data/tiktok_browser_data",
        tiktok_persistent_headless=False,
        team_password=TEAM_PASSWORD,
        ai_provider="deepseek",
        deepseek_api_key="test-secret-key" if configured else None,
        deepseek_model="deepseek-test-model",
        deepseek_base_url="https://api.deepseek.test",
    )


def _client(database_path, *, service=None, configured: bool = True) -> TestClient:
    factory = (lambda: service) if service is not None else None
    return TestClient(
        create_app(
            _settings(database_path, configured=configured),
            environment="development",
            agent_service_factory=factory,
        )
    )


def _login(client: TestClient, operator_name: str = "测试人员") -> None:
    response = client.post(
        "/api/auth/login",
        json={"password": TEAM_PASSWORD, "operator_name": operator_name},
    )
    assert response.status_code == 200


def _new_conversation(client: TestClient) -> str:
    response = client.post("/api/agent/conversations")
    assert response.status_code == 201
    return response.json()["data"]["conversation_id"]


def test_agent_endpoints_require_authentication(tmp_path):
    client = _client(tmp_path / "agent.db", configured=False)

    response = client.get("/api/agent/status")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_agent_status_exposes_configuration_without_secrets(tmp_path):
    client = _client(tmp_path / "agent.db")
    _login(client)

    response = client.get("/api/agent/status")

    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "configured": True,
            "provider": "deepseek",
            "provider_label": "DeepSeek",
            "model": "deepseek-test-model",
            "read_only": False,
            "write_enabled": True,
            "writes_require_confirmation": True,
        }
    }
    assert "test-secret-key" not in response.text
    assert "api.deepseek.test" not in response.text


def test_agent_status_reports_unconfigured_provider(tmp_path):
    client = _client(tmp_path / "agent.db", configured=False)
    _login(client)

    response = client.get("/api/agent/status")

    assert response.status_code == 200
    assert response.json()["data"]["configured"] is False


def test_agent_conversation_and_messages_round_trip(tmp_path):
    service = SimpleNamespace(
        ask=lambda **_kwargs: AIAgentResponse(
            answer="## 7 月分析\n\n| 指标 | 数值 |\n|---|---:|\n| 投稿 | 10 |",
            tool_calls=(
                {
                    "tool_name": "audit_month_data",
                    "arguments": {"period_month": "2026-07"},
                    "summary": {"status": "ok", "post_count": 10},
                    "duration_ms": 12,
                },
            ),
            visualizations=(
                {
                    "schema_version": 1,
                    "id": "creator-1-posts",
                    "kind": "grouped_bar",
                    "title": "达人投稿数量对比",
                    "subtitle": "2026-06 vs 2026-07",
                    "category_key": "category",
                    "value_format": "integer",
                    "series": [
                        {"key": "baseline", "label": "2026-06", "color": "#64748b"},
                        {"key": "current", "label": "2026-07", "color": "#0f9b9b"},
                    ],
                    "data": [
                        {
                            "category": "投稿数量",
                            "baseline": 8,
                            "current": 10,
                            "change": 2,
                            "change_rate": 0.25,
                            "decline_over_30_percent": False,
                        }
                    ],
                    "warnings": [],
                    "source": {
                        "tool": "compare_creator_months",
                        "database_backed": True,
                        "creator_id": 1,
                        "creator_name": "达人",
                        "periods": ["2026-06", "2026-07"],
                    },
                },
            ),
        )
    )
    client = _client(tmp_path / "agent.db", service=service)
    _login(client)
    conversation_id = _new_conversation(client)

    response = client.post(
        f"/api/agent/conversations/{conversation_id}/messages",
        json={"message": "分析 2026-07 数据"},
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["answer"].startswith("## 7 月分析")
    assert body["tool_calls"] == [
        {
            "tool_name": "audit_month_data",
            "summary": {"status": "ok", "post_count": 10},
            "duration_ms": 12,
        }
    ]
    assert "arguments" not in body["tool_calls"][0]
    assert body["visualizations"][0]["source"] == {
        "tool": "compare_creator_months",
        "database_backed": True,
        "creator_id": 1,
        "creator_name": "达人",
        "periods": ["2026-06", "2026-07"],
    }

    messages = client.get(f"/api/agent/conversations/{conversation_id}/messages")
    assert messages.status_code == 200


def test_agent_message_history_returns_only_sanitized_visualization_metadata(tmp_path):
    from database.ai_repository import AIRepository

    database_path = tmp_path / "agent.db"
    client = _client(database_path)
    _login(client)
    conversation_id = _new_conversation(client)
    repository = AIRepository(database_path)
    repository.add_message(
        conversation_id,
        "assistant",
        "历史回答",
        metadata={
            "secret": "must-not-leak",
            "visualizations": [
                {
                    "kind": "grouped_bar",
                    "id": "safe-chart",
                    "title": "真实对比",
                    "subtitle": "2026-06 vs 2026-07",
                    "series": [
                        {"key": "baseline", "label": "2026-06", "color": "#64748b"},
                        {"key": "current", "label": "2026-07", "color": "#0f9b9b"},
                    ],
                    "data": [{"category": "投稿", "baseline": 3, "current": 2, "change": -1, "change_rate": -0.333333, "decline_over_30_percent": True}],
                    "warnings": [{"level": "danger", "message": "投稿下降 33.3%"}],
                    "source": {"tool": "compare_creator_months", "database_backed": True, "creator_id": 1, "creator_name": "达人", "periods": ["2026-06", "2026-07"]},
                }
            ],
        },
    )

    response = client.get(f"/api/agent/conversations/{conversation_id}/messages")

    assert response.status_code == 200
    payload = response.json()["data"][-1]
    assert "metadata" not in payload
    assert "must-not-leak" not in response.text
    assert payload["visualizations"][0]["data"][0]["decline_over_30_percent"] is True


def test_agent_rejects_empty_message(tmp_path):
    client = _client(tmp_path / "agent.db")
    _login(client)
    conversation_id = _new_conversation(client)

    response = client.post(
        f"/api/agent/conversations/{conversation_id}/messages",
        json={"message": "   "},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_agent_conversations_are_isolated_between_sessions(tmp_path):
    database_path = tmp_path / "agent.db"
    app = create_app(_settings(database_path), environment="development")
    first = TestClient(app)
    second = TestClient(app)
    _login(first, "成员一")
    _login(second, "成员二")
    conversation_id = _new_conversation(first)

    response = second.get(f"/api/agent/conversations/{conversation_id}/messages")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


def test_agent_provider_errors_are_sanitized(tmp_path):
    class FailingService:
        def ask(self, **_kwargs):
            raise AIAgentServiceError(
                "DeepSeek API 当前限流（429），secret-host.example sk-private"
            )

    client = _client(tmp_path / "agent.db", service=FailingService())
    _login(client)
    conversation_id = _new_conversation(client)

    response = client.post(
        f"/api/agent/conversations/{conversation_id}/messages",
        json={"message": "分析本月"},
    )

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "AI_RATE_LIMITED",
        "message": "AI 服务当前限流，请稍后再试。",
    }
    assert "secret-host.example" not in response.text
    assert "sk-private" not in response.text


def test_agent_write_action_requires_explicit_confirmation(tmp_path):
    class ActionService:
        def __init__(self):
            self.confirmed = []

        def ask(self, **_kwargs):
            return AIAgentResponse(
                answer="请确认写入。",
                tool_calls=(),
                pending_actions=(
                    {
                        "action_id": "action-1",
                        "tool_name": "save_exchange_rate",
                        "preview": {
                            "period_month": "2026-07",
                            "jpy_to_usd_rate": 0.0062,
                        },
                        "expires_in_seconds": 600,
                    },
                ),
            )

        def confirm_action(self, **kwargs):
            self.confirmed.append(kwargs)
            return {"status": "executed", "action_id": kwargs["action_id"]}

    service = ActionService()
    client = _client(tmp_path / "agent.db", service=service)
    _login(client)
    conversation_id = _new_conversation(client)

    response = client.post(
        f"/api/agent/conversations/{conversation_id}/messages",
        json={"message": "保存 7 月汇率"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["pending_actions"][0]["action_id"] == "action-1"

    confirmed = client.post(
        f"/api/agent/conversations/{conversation_id}/actions/action-1/confirm",
        json={"approve": True},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == "executed"
    assert service.confirmed[0]["session_id"]
