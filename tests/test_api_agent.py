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
            "read_only": True,
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
            answer="7 月投稿量为 10。",
            tool_calls=(
                {
                    "tool_name": "audit_month_data",
                    "arguments": {"period_month": "2026-07"},
                    "summary": {"status": "ok", "post_count": 10},
                    "duration_ms": 12,
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
    assert body["answer"] == "7 月投稿量为 10。"
    assert body["tool_calls"] == [
        {
            "tool_name": "audit_month_data",
            "summary": {"status": "ok", "post_count": 10},
            "duration_ms": 12,
        }
    ]
    assert "arguments" not in body["tool_calls"][0]

    messages = client.get(f"/api/agent/conversations/{conversation_id}/messages")
    assert messages.status_code == 200


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
