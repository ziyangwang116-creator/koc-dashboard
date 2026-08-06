from __future__ import annotations

from contextlib import contextmanager

import pytest

from followers.tiktok_provider import (
    FOLLOWER_COUNT_SELECTORS,
    FollowerSemanticCandidate,
    TikTokBrowserProvider,
    TikTokPageQueryResult,
    TikTokSemanticError,
    build_tiktok_profile,
    extract_tiktok_follower_value,
)
from followers.value_parser import ParsedFollowerValue
from models.enums import FollowerSource


@pytest.mark.parametrize(
    ("value", "username"),
    [
        ("https://www.tiktok.com/@sample_creator", "sample_creator"),
        ("https://www.tiktok.com/@sample.creator/", "sample.creator"),
        ("@sample_creator", "sample_creator"),
        ("sample_creator", "sample_creator"),
    ],
)
def test_tiktok_username_inputs_are_supported(value, username):
    profile = build_tiktok_profile(value)
    assert profile is not None
    assert profile.username == username
    assert profile.profile_url == f"https://www.tiktok.com/@{username}"


@pytest.mark.parametrize(
    "value",
    ["", "https://example.com/@name", "https://www.tiktok.com/video/1", "bad name"],
)
def test_invalid_tiktok_inputs_are_rejected(value):
    assert build_tiktok_profile(value) is None


def test_semantic_reader_uses_followers_and_ignores_following_and_likes():
    parsed = extract_tiktok_follower_value(
        [
            FollowerSemanticCandidate("Following", "789", "following-count"),
            FollowerSemanticCandidate("Followers", "12.5K", "followers-count"),
            FollowerSemanticCandidate("Likes", "3.4M", "likes-count"),
        ]
    )
    assert parsed.follower_count == 12500
    assert parsed.raw_display_value == "12.5K"
    assert parsed.is_estimated is True


@pytest.mark.parametrize(
    ("raw", "expected", "estimated"),
    [
        ("1234", 1234, False),
        ("1,234", 1234, False),
        ("12.5K", 12500, True),
        ("3.2M", 3200000, True),
        ("1.5万", 15000, True),
    ],
)
def test_tiktok_follower_formats(raw, expected, estimated):
    parsed = extract_tiktok_follower_value(
        [FollowerSemanticCandidate("Followers", raw, "followers-count")]
    )
    assert parsed.follower_count == expected
    assert parsed.is_estimated is estimated


def test_page_structure_change_does_not_guess_an_unlabelled_number():
    with pytest.raises(TikTokSemanticError) as error:
        extract_tiktok_follower_value(
            [FollowerSemanticCandidate("Likes", "999999", "likes-count")]
        )
    assert error.value.error_code == "PAGE_STRUCTURE_CHANGED"


def test_conflicting_follower_values_are_rejected():
    with pytest.raises(TikTokSemanticError) as error:
        extract_tiktok_follower_value(
            [
                FollowerSemanticCandidate("Followers", "1.2K", "first"),
                FollowerSemanticCandidate("粉丝", "1.3K", "second"),
            ]
        )
    assert error.value.error_code == "PAGE_STRUCTURE_CHANGED"


def test_invalid_follower_value_is_rejected():
    with pytest.raises(TikTokSemanticError) as error:
        extract_tiktok_follower_value(
            [FollowerSemanticCandidate("Followers", "很多", "followers-count")]
        )
    assert error.value.error_code == "INVALID_FOLLOWER_VALUE"


def test_selector_set_targets_followers_not_other_stats():
    joined = " ".join(FOLLOWER_COUNT_SELECTORS).casefold()
    assert "followers" in joined
    assert "following-count" not in joined
    assert "likes-count" not in joined


def test_browser_launch_options_use_a_fresh_anonymous_context():
    provider = TikTokBrowserProvider(headless=True)
    options = provider.browser_launch_options()
    assert options == {"headless": True}
    assert "user_data_dir" not in options


def test_provider_success_uses_browser_source_and_public_raw_value(monkeypatch):
    provider = TikTokBrowserProvider()

    @contextmanager
    def fake_context():
        yield object()

    monkeypatch.setattr(provider, "_open_context", fake_context)
    monkeypatch.setattr(
        provider,
        "_query_profile",
        lambda _context, profile: TikTokPageQueryResult(
            ParsedFollowerValue(3200000, "3.2M", True),
            profile.profile_url,
        ),
    )

    result = provider.fetch("https://www.tiktok.com/@sample")

    assert result.success is True
    assert result.follower_count == 3200000
    assert result.raw_display_value == "3.2M"
    assert result.source is FollowerSource.TIKTOK_BROWSER
    assert result.settlement_eligible is False


def test_public_profile_query_succeeds_without_login_state(monkeypatch):
    provider = TikTokBrowserProvider(timeout_seconds=1)

    class FakePage:
        url = "https://www.tiktok.com/@sample"

        def set_default_timeout(self, _value):
            return None

        def goto(self, *_args, **_kwargs):
            return type("Response", (), {"status": 200})()

        def wait_for_timeout(self, _milliseconds):
            return None

    page = FakePage()
    monkeypatch.setattr(provider, "_first_page", lambda _context: page)
    monkeypatch.setattr(provider, "_detect_blocker", lambda _page: None)
    monkeypatch.setattr(provider, "_detect_access_restriction", lambda _page: None)
    monkeypatch.setattr(provider, "_body_text", lambda _page: "")
    monkeypatch.setattr(
        provider,
        "_read_follower_value",
        lambda _page: ParsedFollowerValue(21800, "21.8K", True),
    )

    profile = build_tiktok_profile("@sample")
    assert profile is not None
    result = provider._query_profile(object(), profile)
    assert result.error_code is None
    assert result.parsed_value is not None
    assert result.parsed_value.follower_count == 21800


def test_public_profile_login_button_is_not_treated_as_login_requirement(monkeypatch):
    provider = TikTokBrowserProvider()
    page = type("Page", (), {"url": "https://www.tiktok.com/@sample"})()
    monkeypatch.setattr(provider, "_body_text", lambda _page: "登录")
    assert provider._detect_access_restriction(page) is None


def test_redirect_to_login_is_reported_as_access_restricted(monkeypatch):
    provider = TikTokBrowserProvider()
    page = type("Page", (), {"url": "https://www.tiktok.com/login"})()
    monkeypatch.setattr(provider, "_body_text", lambda _page: "")
    restriction = provider._detect_access_restriction(page)
    assert restriction is not None
    assert restriction[0] == "ACCESS_RESTRICTED"
