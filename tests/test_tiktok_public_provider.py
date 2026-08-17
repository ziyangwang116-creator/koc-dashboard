import json
from urllib.error import HTTPError

import pytest

from followers.tiktok_public_provider import (
    TikTokPublicProfileProvider,
    extract_public_tiktok_follower_count,
)
from models.enums import FollowerSource


class _Response:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self._body


def _universal_page(username: str, follower_count: int) -> str:
    payload = {
        "__DEFAULT_SCOPE__": {
            "webapp.user-detail": {
                "userInfo": {
                    "user": {"uniqueId": username},
                    "stats": {"followerCount": follower_count},
                }
            }
        }
    }
    return (
        '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" '
        f'type="application/json">{json.dumps(payload)}</script>'
    )


def test_extracts_requested_profile_from_universal_payload():
    body = _universal_page("sample_creator", 123456)

    assert extract_public_tiktok_follower_count(body, "sample_creator") == 123456


def test_extracts_requested_profile_from_sigi_user_module():
    payload = {
        "UserModule": {
            "users": {"123": {"id": "123", "uniqueId": "sample_creator"}},
            "stats": {"123": {"followerCount": 9876}},
        }
    }
    body = f'<script id="SIGI_STATE">{json.dumps(payload)}</script>'

    assert extract_public_tiktok_follower_count(body, "sample_creator") == 9876


def test_does_not_accept_another_profiles_count():
    body = _universal_page("different_creator", 555)

    with pytest.raises(ValueError):
        extract_public_tiktok_follower_count(body, "sample_creator")


def test_provider_reads_public_page_without_browser_or_login():
    provider = TikTokPublicProfileProvider(
        opener=lambda request, timeout: _Response(
            _universal_page("sample_creator", 24680)
        )
    )

    result = provider.fetch("https://www.tiktok.com/@sample_creator")

    assert result.success is True
    assert result.follower_count == 24680
    assert result.profile_id == "sample_creator"
    assert result.source is FollowerSource.TIKTOK_API


def test_provider_preserves_data_when_tiktok_restricts_cloud_access():
    def blocked(request, timeout):
        raise HTTPError(request.full_url, 429, "rate limited", {}, None)

    result = TikTokPublicProfileProvider(opener=blocked).fetch(
        "https://www.tiktok.com/@sample_creator"
    )

    assert result.success is False
    assert result.error_code == "ACCESS_RESTRICTED"
    assert result.follower_count is None


def test_provider_rejects_non_tiktok_url_without_requesting_it():
    provider = TikTokPublicProfileProvider(
        opener=lambda request, timeout: pytest.fail("request must not be sent")
    )

    result = provider.fetch("https://example.com/not-tiktok")

    assert result.success is False
    assert result.error_code == "INVALID_TIKTOK_URL"
