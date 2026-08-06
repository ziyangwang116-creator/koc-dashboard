from urllib.parse import parse_qs, urlparse

import pytest

from followers.youtube_provider import (
    YouTubeOfficialProvider,
    YouTubeRequestError,
)
from models.enums import FollowerSource


def test_missing_api_key_returns_configuration_message_without_crash(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    result = YouTubeOfficialProvider(api_key=None).fetch(
        "https://www.youtube.com/@creator"
    )
    assert result.success is False
    assert result.error_code == "MISSING_API_KEY"
    assert result.follower_count is None


@pytest.mark.parametrize(
    ("homepage_url", "parameter", "expected"),
    [
        ("https://www.youtube.com/@creator", "forHandle", "creator"),
        ("https://www.youtube.com/channel/UC123", "id", "UC123"),
        ("https://www.youtube.com/user/legacy", "forUsername", "legacy"),
    ],
)
def test_official_api_uses_supported_channel_lookup(
    homepage_url, parameter, expected
):
    requested = {}

    def fake_fetcher(url, timeout):
        requested["url"] = url
        requested["timeout"] = timeout
        return {
            "items": [
                {
                    "id": "UC-result",
                    "snippet": {"title": "公开频道"},
                    "statistics": {
                        "subscriberCount": "123456",
                        "hiddenSubscriberCount": False,
                    },
                }
            ]
        }

    result = YouTubeOfficialProvider(
        api_key="test-key", json_fetcher=fake_fetcher
    ).fetch(homepage_url)
    query = parse_qs(urlparse(requested["url"]).query)

    assert query[parameter] == [expected]
    assert query["part"] == ["snippet,statistics"]
    assert result.success is True
    assert result.follower_count == 123456
    assert result.raw_display_value == "123456"
    assert result.is_estimated is True
    assert result.source is FollowerSource.YOUTUBE_API
    assert result.settlement_eligible is True
    assert result.profile_id == "UC-result"
    assert result.profile_title == "公开频道"


def test_provider_does_not_turn_hidden_count_into_zero():
    result = YouTubeOfficialProvider(
        api_key="test-key",
        json_fetcher=lambda url, timeout: {
            "items": [{"statistics": {"hiddenSubscriberCount": True}}]
        },
    ).fetch("https://www.youtube.com/channel/UC123")

    assert result.success is False
    assert result.follower_count is None
    assert result.error_code == "HIDDEN_SUBSCRIBER_COUNT"
    assert result.settlement_eligible is False


@pytest.mark.parametrize(
    ("status", "reason", "expected_code"),
    [
        (400, "keyInvalid", "API_KEY_INVALID"),
        (403, "forbidden", "API_FORBIDDEN"),
        (403, "quotaExceeded", "QUOTA_EXCEEDED"),
    ],
)
def test_official_api_errors_are_distinguished(status, reason, expected_code):
    def failed_fetcher(url, timeout):
        raise YouTubeRequestError(status, reason)

    result = YouTubeOfficialProvider(
        api_key="super-secret-key", json_fetcher=failed_fetcher
    ).fetch("https://www.youtube.com/@creator")

    assert result.error_code == expected_code
    assert "super-secret-key" not in (result.error_message or "")


def test_invalid_youtube_url_is_rejected_without_request():
    result = YouTubeOfficialProvider(
        api_key="test-key",
        json_fetcher=lambda url, timeout: pytest.fail("不应发起 API 请求"),
    ).fetch("https://www.youtube.com/c/custom-name")

    assert result.error_code == "INVALID_YOUTUBE_URL"
