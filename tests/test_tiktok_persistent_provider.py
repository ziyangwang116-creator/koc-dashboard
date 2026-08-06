from __future__ import annotations

import asyncio

from followers.tiktok_persistent_provider import (
    TikTokBrowserQueryError,
    TikTokPersistentBrowserProvider,
)
from followers.value_parser import ParsedFollowerValue
from models.enums import FollowerSource


def test_persistent_browser_provider_saves_exact_follower_count(monkeypatch, tmp_path):
    provider = TikTokPersistentBrowserProvider(user_data_dir=tmp_path / "browser_data")

    async def read_profile(_profile):
        return ParsedFollowerValue(12500, "12,500", False)

    monkeypatch.setattr(provider, "_read_profile", read_profile)

    result = provider.fetch("https://www.tiktok.com/@sample_creator")

    assert result.success is True
    assert result.follower_count == 12500
    assert result.raw_display_value == "12,500"
    assert result.is_estimated is False
    assert result.source is FollowerSource.TIKTOK_BROWSER
    assert result.profile_id == "sample_creator"


def test_persistent_browser_provider_preserves_timeout_reason(monkeypatch, tmp_path):
    provider = TikTokPersistentBrowserProvider(user_data_dir=tmp_path / "browser_data")

    async def read_profile(_profile):
        raise TikTokBrowserQueryError(
            "TIKTOK_LOGIN_REQUIRED",
            "请在弹出的本地浏览器中登录 TikTok，然后重试读取粉丝数。",
        )

    monkeypatch.setattr(provider, "_read_profile", read_profile)

    result = provider.fetch("@sample_creator")

    assert result.success is False
    assert result.error_code == "TIKTOK_LOGIN_REQUIRED"
    assert result.source is FollowerSource.TIKTOK_BROWSER


def test_persistent_browser_provider_rejects_invalid_tiktok_url(tmp_path):
    result = TikTokPersistentBrowserProvider(
        user_data_dir=tmp_path / "browser_data"
    ).fetch("https://example.com/@sample_creator")

    assert result.success is False
    assert result.error_code == "INVALID_TIKTOK_URL"


def test_persistent_browser_provider_can_run_inside_an_event_loop(monkeypatch, tmp_path):
    provider = TikTokPersistentBrowserProvider(user_data_dir=tmp_path / "browser_data")

    async def read_profile(_profile):
        return ParsedFollowerValue(42, "42", False)

    monkeypatch.setattr(provider, "_read_profile", read_profile)

    async def fetch_from_running_loop():
        return provider.fetch("@sample_creator")

    result = asyncio.run(fetch_from_running_loop())

    assert result.success is True
    assert result.follower_count == 42
