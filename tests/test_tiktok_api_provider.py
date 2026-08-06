from __future__ import annotations

import asyncio

from followers.tiktok_api_provider import TikTokApiProvider
from models.enums import FollowerSource


class FakeUser:
    def __init__(self, payload):
        self.payload = payload

    async def info(self):
        return self.payload


class FakeApi:
    def __init__(self, payload):
        self.payload = payload
        self.session_options = None
        self.username = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, _type, _value, _traceback):
        return None

    async def create_sessions(self, **kwargs):
        self.session_options = kwargs

    def user(self, username):
        self.username = username
        return FakeUser(self.payload)


def test_tiktok_api_provider_uses_ms_token_session_and_reads_follower_count():
    api = FakeApi({"userInfo": {"stats": {"followerCount": 12500}}})
    provider = TikTokApiProvider(
        ms_token="test-only-token",
        browser="firefox",
        api_factory=lambda: api,
    )

    result = provider.fetch("https://www.tiktok.com/@sample_creator")

    assert result.success is True
    assert result.follower_count == 12500
    assert result.raw_display_value == "12500"
    assert result.is_estimated is False
    assert result.source is FollowerSource.TIKTOK_API
    assert result.profile_id == "sample_creator"
    assert api.username == "sample_creator"
    assert api.session_options == {
        "ms_tokens": ["test-only-token"],
        "num_sessions": 1,
        "sleep_after": 3,
        "browser": "firefox",
        "headless": True,
    }


def test_tiktok_api_provider_requires_a_local_ms_token():
    result = TikTokApiProvider().fetch("https://www.tiktok.com/@sample_creator")

    assert result.success is False
    assert result.error_code == "MISSING_TIKTOK_MS_TOKEN"
    assert result.source is FollowerSource.TIKTOK_API


def test_tiktok_api_provider_rejects_invalid_user_info_response():
    api = FakeApi({"userInfo": {"stats": {}}})
    provider = TikTokApiProvider(ms_token="test-only-token", api_factory=lambda: api)

    result = provider.fetch("@sample_creator")

    assert result.success is False
    assert result.error_code == "TIKTOK_API_RESPONSE_INVALID"


def test_tiktok_api_provider_can_run_from_an_existing_event_loop():
    api = FakeApi({"userInfo": {"stats": {"followerCount": 42}}})
    provider = TikTokApiProvider(ms_token="test-only-token", api_factory=lambda: api)

    async def fetch_from_running_loop():
        return provider.fetch("@sample_creator")

    result = asyncio.run(fetch_from_running_loop())

    assert result.success is True
    assert result.follower_count == 42


def test_tiktok_api_provider_does_not_expose_session_exception_details():
    class BrokenApi:
        async def __aenter__(self):
            raise RuntimeError("token=test-only-token")

        async def __aexit__(self, _type, _value, _traceback):
            return None

    provider = TikTokApiProvider(
        ms_token="test-only-token",
        api_factory=BrokenApi,
    )

    result = provider.fetch("@sample_creator")

    assert result.success is False
    assert result.error_code == "TIKTOK_API_SESSION_FAILED"
    assert "test-only-token" not in (result.error_message or "")


def test_tiktok_api_provider_labels_empty_responses_without_exposing_details():
    class EmptyResponseException(Exception):
        pass

    class EmptyResponseApi:
        async def __aenter__(self):
            raise EmptyResponseException("response body omitted")

        async def __aexit__(self, _type, _value, _traceback):
            return None

    result = TikTokApiProvider(
        ms_token="test-only-token",
        api_factory=EmptyResponseApi,
    ).fetch("@sample_creator")

    assert result.success is False
    assert result.error_code == "TIKTOK_EMPTY_RESPONSE"
    assert "已重试用户详情请求" in (result.error_message or "")
