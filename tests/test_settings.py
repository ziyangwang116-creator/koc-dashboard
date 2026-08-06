import config.settings as settings_module
from config.settings import load_settings


def test_default_timezone_is_beijing_time():
    assert load_settings().timezone == "Asia/Shanghai"


def test_youtube_key_and_tiktok_browser_settings_load_from_env_file(tmp_path, monkeypatch):
    for name in (
        "DATABASE_URL",
        "TEAM_PASSWORD",
        "YOUTUBE_API_KEY",
        "TIKTOK_PERSISTENT_HEADLESS",
        "AI_PROVIDER",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "YOUTUBE_API_KEY=test-only-key\n"
        "TEAM_PASSWORD=test-team-password\n"
        "TIKTOK_PERSISTENT_HEADLESS=true\n"
        "AI_PROVIDER=deepseek\n"
        "DEEPSEEK_API_KEY=test-deepseek-key\n"
        "DEEPSEEK_MODEL=deepseek-test-model\n"
        "DEEPSEEK_BASE_URL=https://deepseek.example.test/\n"
        "OPENAI_API_KEY=test-openai-key\n"
        "OPENAI_MODEL=test-model\n",
        encoding="utf-8",
    )

    settings = load_settings(settings_file, env_file)

    assert settings.youtube_api_key == "test-only-key"
    assert settings.youtube_api_configured is True
    assert settings.team_password == "test-team-password"
    assert settings.team_password_configured is True
    assert settings.tiktok_persistent_headless is True
    assert settings.ai_provider == "deepseek"
    assert settings.deepseek_api_key == "test-deepseek-key"
    assert settings.deepseek_model == "deepseek-test-model"
    assert settings.deepseek_base_url == "https://deepseek.example.test"
    assert settings.ai_api_key == "test-deepseek-key"
    assert settings.ai_model == "deepseek-test-model"
    assert settings.ai_configured is True
    assert settings.openai_api_key == "test-openai-key"
    assert settings.openai_model == "test-model"
    assert settings.openai_configured is True
    assert settings.tiktok_browser_data_dir.name == "tiktok_browser_data"


def test_database_url_overrides_local_sqlite_path(tmp_path, monkeypatch):
    database_url = "postgresql://postgres.example:secret@db.example.test/postgres"
    monkeypatch.setenv("DATABASE_URL", database_url)
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        '{"database_path": "data/local.db"}',
        encoding="utf-8",
    )

    settings = load_settings(settings_file, tmp_path / ".env")

    assert settings.database_path == database_url


def test_team_password_is_not_exposed_in_settings_repr(tmp_path, monkeypatch):
    monkeypatch.setenv("TEAM_PASSWORD", "private-team-password")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "private-deepseek-key")
    monkeypatch.setenv("OPENAI_API_KEY", "private-openai-key")
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}", encoding="utf-8")

    settings = load_settings(settings_file, tmp_path / ".env")

    assert "private-team-password" not in repr(settings)
    assert "private-deepseek-key" not in repr(settings)
    assert "private-openai-key" not in repr(settings)


def test_streamlit_secrets_are_used_when_environment_and_env_file_are_empty(
    tmp_path,
    monkeypatch,
):
    for name in (
        "DATABASE_URL",
        "TEAM_PASSWORD",
        "YOUTUBE_API_KEY",
        "AI_PROVIDER",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    secret_values = {
        "DATABASE_URL": "postgresql://cloud.example.test/postgres",
        "TEAM_PASSWORD": "cloud-team-password",
        "YOUTUBE_API_KEY": "cloud-youtube-key",
        "AI_PROVIDER": "deepseek",
        "DEEPSEEK_API_KEY": "cloud-deepseek-key",
        "DEEPSEEK_MODEL": "deepseek-cloud-model",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.example.test",
        "OPENAI_API_KEY": "cloud-openai-key",
        "OPENAI_MODEL": "cloud-model",
    }
    monkeypatch.setattr(
        settings_module,
        "_streamlit_secret_value",
        lambda name: secret_values.get(name, ""),
    )
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}", encoding="utf-8")

    settings = load_settings(settings_file, tmp_path / ".env")

    assert settings.database_path == secret_values["DATABASE_URL"]
    assert settings.team_password == secret_values["TEAM_PASSWORD"]
    assert settings.youtube_api_key == secret_values["YOUTUBE_API_KEY"]
    assert settings.ai_provider == "deepseek"
    assert settings.deepseek_api_key == secret_values["DEEPSEEK_API_KEY"]
    assert settings.deepseek_model == secret_values["DEEPSEEK_MODEL"]
    assert settings.deepseek_base_url == secret_values["DEEPSEEK_BASE_URL"]
    assert settings.ai_configured is True
    assert settings.openai_api_key == secret_values["OPENAI_API_KEY"]
    assert settings.openai_model == secret_values["OPENAI_MODEL"]


def test_openai_can_be_selected_as_fallback_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "fallback-openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "fallback-model")
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}", encoding="utf-8")

    settings = load_settings(settings_file, tmp_path / ".env")

    assert settings.ai_provider == "openai"
    assert settings.ai_api_key == "fallback-openai-key"
    assert settings.ai_model == "fallback-model"
    assert settings.ai_base_url is None


def test_tiktok_browser_visibility_can_be_overridden_by_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TIKTOK_PERSISTENT_HEADLESS", "false")
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}", encoding="utf-8")

    settings = load_settings(settings_file, tmp_path / ".env")

    assert settings.tiktok_persistent_headless is False
