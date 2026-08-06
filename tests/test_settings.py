from config.settings import load_settings


def test_default_timezone_is_beijing_time():
    assert load_settings().timezone == "Asia/Shanghai"


def test_youtube_key_and_tiktok_browser_settings_load_from_env_file(tmp_path, monkeypatch):
    for name in (
        "YOUTUBE_API_KEY",
        "TIKTOK_PERSISTENT_HEADLESS",
    ):
        monkeypatch.delenv(name, raising=False)
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "YOUTUBE_API_KEY=test-only-key\n"
        "TIKTOK_PERSISTENT_HEADLESS=true\n",
        encoding="utf-8",
    )

    settings = load_settings(settings_file, env_file)

    assert settings.youtube_api_key == "test-only-key"
    assert settings.youtube_api_configured is True
    assert settings.tiktok_persistent_headless is True
    assert settings.tiktok_browser_data_dir.name == "tiktok_browser_data"


def test_tiktok_browser_visibility_can_be_overridden_by_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TIKTOK_PERSISTENT_HEADLESS", "false")
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}", encoding="utf-8")

    settings = load_settings(settings_file, tmp_path / ".env")

    assert settings.tiktok_persistent_headless is False
