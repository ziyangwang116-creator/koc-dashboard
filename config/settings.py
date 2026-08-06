from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = Path(__file__).with_name("settings.json")
ENV_FILE = PROJECT_ROOT / ".env"


@dataclass(frozen=True)
class Settings:
    timezone: str
    database_path: Path | str
    output_dir: Path
    youtube_api_key: str | None
    tiktok_browser_data_dir: Path
    tiktok_persistent_headless: bool
    team_password: str | None = field(default=None, repr=False)
    ai_provider: str = "deepseek"
    deepseek_api_key: str | None = field(default=None, repr=False)
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    openai_api_key: str | None = field(default=None, repr=False)
    openai_model: str = "gpt-5.6-sol"

    @property
    def youtube_api_configured(self) -> bool:
        return bool(self.youtube_api_key)

    @property
    def team_password_configured(self) -> bool:
        return bool(self.team_password)

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key and self.openai_model)

    @property
    def ai_api_key(self) -> str | None:
        return (
            self.deepseek_api_key
            if self.ai_provider == "deepseek"
            else self.openai_api_key
        )

    @property
    def ai_model(self) -> str:
        return (
            self.deepseek_model
            if self.ai_provider == "deepseek"
            else self.openai_model
        )

    @property
    def ai_base_url(self) -> str | None:
        return self.deepseek_base_url if self.ai_provider == "deepseek" else None

    @property
    def ai_configured(self) -> bool:
        return bool(self.ai_api_key and self.ai_model)

def _project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_local_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _streamlit_secret_value(name: str) -> str:
    try:
        import streamlit as st

        value = st.secrets.get(name, "")
    except Exception:
        return ""
    return str(value).strip() if value is not None else ""


def _env_value(name: str, file_values: dict[str, str], default: str = "") -> str:
    environment_value = os.environ.get(name, "").strip()
    if environment_value:
        return environment_value
    file_value = file_values.get(name, "").strip()
    if file_value:
        return file_value
    secret_value = _streamlit_secret_value(name)
    return secret_value or default.strip()


def _env_bool(name: str, file_values: dict[str, str], default: bool) -> bool:
    raw = _env_value(name, file_values, "true" if default else "false").casefold()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} 必须是 true 或 false。")


def _env_float(
    name: str,
    file_values: dict[str, str],
    default: float,
) -> float:
    raw = _env_value(name, file_values, str(default))
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是数字。") from exc


def load_settings(path: Path = SETTINGS_FILE, env_path: Path = ENV_FILE) -> Settings:
    with path.open("r", encoding="utf-8") as file:
        values = json.load(file)

    env_values = _read_local_env(env_path)
    youtube_api_key = _env_value("YOUTUBE_API_KEY", env_values) or None
    database_url = _env_value("DATABASE_URL", env_values)
    team_password = _env_value("TEAM_PASSWORD", env_values) or None
    ai_provider = _env_value("AI_PROVIDER", env_values, "deepseek").casefold()
    if ai_provider not in {"deepseek", "openai"}:
        raise ValueError("AI_PROVIDER 必须是 deepseek 或 openai。")
    deepseek_api_key = _env_value("DEEPSEEK_API_KEY", env_values) or None
    deepseek_model = _env_value(
        "DEEPSEEK_MODEL", env_values, "deepseek-v4-flash"
    )
    deepseek_base_url = _env_value(
        "DEEPSEEK_BASE_URL", env_values, "https://api.deepseek.com"
    ).rstrip("/")
    openai_api_key = _env_value("OPENAI_API_KEY", env_values) or None
    openai_model = _env_value("OPENAI_MODEL", env_values, "gpt-5.6-sol")
    return Settings(
        timezone=values.get("timezone", "Asia/Shanghai"),
        database_path=(
            database_url
            if database_url
            else _project_path(values.get("database_path", "data/koc.db"))
        ),
        output_dir=_project_path(values.get("output_dir", "data/output")),
        youtube_api_key=youtube_api_key,
        tiktok_browser_data_dir=_project_path(
            values.get("tiktok_browser_data_dir", "data/tiktok_browser_data")
        ),
        tiktok_persistent_headless=_env_bool(
            "TIKTOK_PERSISTENT_HEADLESS", env_values, False
        ),
        team_password=team_password,
        ai_provider=ai_provider,
        deepseek_api_key=deepseek_api_key,
        deepseek_model=deepseek_model,
        deepseek_base_url=deepseek_base_url,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
    )
