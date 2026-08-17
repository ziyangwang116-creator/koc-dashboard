from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from followers.base import FollowerFetchResult
from followers.tiktok_provider import TikTokProfile, build_tiktok_profile
from models.enums import FollowerSource


TIKTOK_BATCH_STOP_ERROR_CODES = {
    "ACCESS_RESTRICTED",
    "CAPTCHA_REQUIRED",
    "SECURITY_VERIFICATION_REQUIRED",
}

_JSON_SCRIPT_PATTERN = re.compile(
    r"<script[^>]*id=[\"'](?:__UNIVERSAL_DATA_FOR_REHYDRATION__|SIGI_STATE)"
    r"[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_FOLLOWER_COUNT_PATTERN = re.compile(
    r'[\"\']followerCount[\"\']\s*:\s*(\d+)',
    re.IGNORECASE,
)
_BLOCKED_MARKERS = (
    "access denied",
    "captcha",
    "security verification",
    "verify to continue",
    "verify you are human",
)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _username(value: Any) -> str:
    return str(value or "").strip().lstrip("@").casefold()


def _count_from_user_info(value: Any, target_username: str) -> int | None:
    if not isinstance(value, Mapping):
        return None
    user = value.get("user")
    stats = value.get("stats") or value.get("statsV2")
    if not isinstance(user, Mapping) or not isinstance(stats, Mapping):
        return None
    unique_id = user.get("uniqueId") or user.get("unique_id") or user.get("username")
    if _username(unique_id) != target_username:
        return None
    return _non_negative_int(stats.get("followerCount"))


def _count_from_user_module(value: Any, target_username: str) -> int | None:
    if not isinstance(value, Mapping):
        return None
    users = value.get("users")
    stats = value.get("stats")
    if not isinstance(users, Mapping) or not isinstance(stats, Mapping):
        return None
    for key, user in users.items():
        if not isinstance(user, Mapping):
            continue
        unique_id = user.get("uniqueId") or user.get("unique_id") or user.get("username")
        if _username(unique_id) != target_username:
            continue
        stats_key = str(user.get("id") or key)
        candidate = stats.get(stats_key) or stats.get(key)
        if isinstance(candidate, Mapping):
            return _non_negative_int(candidate.get("followerCount"))
    return None


def _find_follower_count(value: Any, target_username: str) -> int | None:
    if isinstance(value, Mapping):
        direct = _count_from_user_info(value, target_username)
        if direct is not None:
            return direct
        user_info = _count_from_user_info(value.get("userInfo"), target_username)
        if user_info is not None:
            return user_info
        user_module = _count_from_user_module(value.get("UserModule"), target_username)
        if user_module is not None:
            return user_module
        for child in value.values():
            found = _find_follower_count(child, target_username)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_follower_count(child, target_username)
            if found is not None:
                return found
    return None


def extract_public_tiktok_follower_count(body: str, username: str) -> int:
    """Read the requested profile's follower count from TikTok JSON payloads."""
    target_username = _username(username)
    for raw_payload in _JSON_SCRIPT_PATTERN.findall(body):
        try:
            payload = json.loads(html.unescape(raw_payload).strip())
        except (json.JSONDecodeError, TypeError):
            continue
        count = _find_follower_count(payload, target_username)
        if count is not None:
            return count

    counts = {
        int(match.group(1))
        for match in _FOLLOWER_COUNT_PATTERN.finditer(body)
    }
    folded_body = body.casefold()
    username_markers = (
        f'"uniqueId":"{username}"'.casefold(),
        f'"uniqueId": "{username}"'.casefold(),
    )
    if len(counts) == 1 and any(marker in folded_body for marker in username_markers):
        return counts.pop()
    raise ValueError("TikTok profile follower count is unavailable.")


class TikTokPublicProfileProvider:
    """Read public TikTok profile data without a local browser or login."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 20,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("TikTok request timeout must be positive.")
        self.timeout_seconds = float(timeout_seconds)
        self._opener = opener or urlopen

    @staticmethod
    def _result(
        profile: TikTokProfile | None,
        *,
        success: bool,
        follower_count: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> FollowerFetchResult:
        return FollowerFetchResult(
            success=success,
            follower_count=follower_count,
            platform="TikTok",
            fetched_at=_now(),
            error_code=error_code,
            error_message=error_message,
            raw_display_value=(
                str(follower_count) if follower_count is not None else None
            ),
            is_estimated=False,
            source=FollowerSource.TIKTOK_API,
            source_url=profile.profile_url if profile else None,
            profile_url=profile.profile_url if profile else None,
            settlement_eligible=False,
            profile_id=profile.username if profile else None,
        )

    def fetch(self, homepage_url: str) -> FollowerFetchResult:
        profile = build_tiktok_profile(homepage_url)
        if profile is None:
            return self._result(
                None,
                success=False,
                error_code="INVALID_TIKTOK_URL",
                error_message="无法从 TikTok 主页链接解析用户名。",
            )

        request = Request(
            profile.profile_url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="ignore")
        except HTTPError as exc:
            if exc.code == 404:
                code, message = "PROFILE_NOT_FOUND", "TikTok 主页不存在。"
            elif exc.code in {401, 403, 429}:
                code, message = (
                    "ACCESS_RESTRICTED",
                    "TikTok 暂时限制云端公开主页访问，已保留原粉丝数。",
                )
            else:
                code, message = "NETWORK_ERROR", "TikTok 主页暂时不可用。"
            return self._result(
                profile,
                success=False,
                error_code=code,
                error_message=message,
            )
        except (TimeoutError, URLError, OSError):
            return self._result(
                profile,
                success=False,
                error_code="NETWORK_ERROR",
                error_message="访问 TikTok 公开主页失败，已保留原粉丝数。",
            )

        try:
            follower_count = extract_public_tiktok_follower_count(
                body, profile.username
            )
        except ValueError:
            folded_body = body.casefold()
            if any(marker in folded_body for marker in _BLOCKED_MARKERS):
                return self._result(
                    profile,
                    success=False,
                    error_code="ACCESS_RESTRICTED",
                    error_message="TikTok 要求验证或限制访问，已保留原粉丝数。",
                )
            return self._result(
                profile,
                success=False,
                error_code="PAGE_STRUCTURE_CHANGED",
                error_message="TikTok 主页未返回可核对的粉丝数，已保留原数据。",
            )
        return self._result(
            profile,
            success=True,
            follower_count=follower_count,
        )
