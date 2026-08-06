from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from followers.base import FollowerFetchResult
from followers.tiktok_provider import TikTokProfile, build_tiktok_profile
from models.enums import FollowerSource


TIKTOK_BATCH_STOP_ERROR_CODES = {
    "ACCESS_RESTRICTED",
    "CAPTCHA_REQUIRED",
    "MISSING_TIKTOK_MS_TOKEN",
    "SECURITY_VERIFICATION_REQUIRED",
    "TIKTOK_EMPTY_RESPONSE",
    "TIKTOK_API_NOT_INSTALLED",
    "TIKTOK_API_SESSION_FAILED",
}


class TikTokApiResponseError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TikTokApiProvider:
    """Read TikTok follower counts through the official TikTok-Api session flow."""

    def __init__(
        self,
        *,
        ms_token: str | None = None,
        browser: str = "chromium",
        headless: bool = True,
        api_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.ms_token = (ms_token or "").strip()
        self.browser = (browser or "chromium").strip()
        self.headless = bool(headless)
        self._api_factory = api_factory
        self._query_lock = threading.Lock()

    @staticmethod
    def _default_api_factory() -> Any:
        try:
            from TikTokApi import TikTokApi
        except ImportError as exc:
            raise RuntimeError("TIKTOK_API_NOT_INSTALLED") from exc
        return TikTokApi

    async def _read_user_data(self, profile: TikTokProfile) -> Mapping[str, Any]:
        factory = self._api_factory or self._default_api_factory()
        async with factory() as api:
            await api.create_sessions(
                ms_tokens=[self.ms_token],
                num_sessions=1,
                sleep_after=3,
                browser=self.browser,
                headless=self.headless,
            )
            payload = await api.user(profile.username).info()
        if not isinstance(payload, Mapping):
            raise TikTokApiResponseError("TikTok-Api returned invalid user data.")
        return payload

    @staticmethod
    def _follower_count(payload: Mapping[str, Any]) -> int:
        user_info = payload.get("userInfo")
        stats = user_info.get("stats") if isinstance(user_info, Mapping) else None
        if not isinstance(stats, Mapping):
            stats = payload.get("stats")
        raw_count = stats.get("followerCount") if isinstance(stats, Mapping) else None
        if isinstance(raw_count, bool):
            raise TikTokApiResponseError("TikTok follower count is invalid.")
        try:
            count = int(raw_count)
        except (TypeError, ValueError) as exc:
            raise TikTokApiResponseError("TikTok follower count is unavailable.") from exc
        if count < 0:
            raise TikTokApiResponseError("TikTok follower count is invalid.")
        return count

    @staticmethod
    def _error_code(error: Exception) -> str:
        if isinstance(error, TikTokApiResponseError):
            return "TIKTOK_API_RESPONSE_INVALID"
        error_type = type(error).__name__.casefold()
        if error_type == "emptyresponseexception":
            return "TIKTOK_EMPTY_RESPONSE"
        if error_type == "notfoundexception":
            return "PROFILE_NOT_FOUND"
        if error_type in {"invalidjsonexception", "invalidresponseexception"}:
            return "TIKTOK_API_RESPONSE_INVALID"
        message = f"{type(error).__name__} {error}".casefold()
        if "captcha" in message:
            return "CAPTCHA_REQUIRED"
        if "security" in message or "verification" in message:
            return "SECURITY_VERIFICATION_REQUIRED"
        if any(value in message for value in ("forbidden", "unauthorized", "login")):
            return "ACCESS_RESTRICTED"
        return "TIKTOK_API_SESSION_FAILED"

    @staticmethod
    def _error_message(error_code: str) -> str:
        messages = {
            "TIKTOK_EMPTY_RESPONSE": (
                "TikTok-Api 已重试用户详情请求，但 TikTok 未返回数据。"
                "当前会话或网络可能被识别为自动化，请勿批量重试或覆盖已有粉丝数。"
            ),
            "TIKTOK_API_RESPONSE_INVALID": (
                "TikTok 返回的数据结构无效，已保留原有粉丝数。"
            ),
            "PROFILE_NOT_FOUND": "TikTok 未找到该达人主页，已保留原有粉丝数。",
            "CAPTCHA_REQUIRED": "TikTok 要求人机验证，已停止更新且保留原有粉丝数。",
            "SECURITY_VERIFICATION_REQUIRED": (
                "TikTok 要求安全验证，已停止更新且保留原有粉丝数。"
            ),
            "ACCESS_RESTRICTED": "TikTok 限制当前会话访问，已保留原有粉丝数。",
        }
        return messages.get(
            error_code,
            "TikTok-Api 无法读取该达人粉丝数，已保留原有粉丝数。",
        )

    @staticmethod
    def _failure(
        profile: TikTokProfile | None,
        error_code: str,
        error_message: str,
    ) -> FollowerFetchResult:
        return FollowerFetchResult(
            success=False,
            follower_count=None,
            platform="TikTok",
            fetched_at=_now(),
            error_code=error_code,
            error_message=error_message,
            source=FollowerSource.TIKTOK_API,
            source_url=profile.profile_url if profile else None,
            profile_url=profile.profile_url if profile else None,
            settlement_eligible=False,
            profile_id=profile.username if profile else None,
        )

    @staticmethod
    def _success(profile: TikTokProfile, follower_count: int) -> FollowerFetchResult:
        return FollowerFetchResult(
            success=True,
            follower_count=follower_count,
            platform="TikTok",
            fetched_at=_now(),
            raw_display_value=str(follower_count),
            is_estimated=False,
            source=FollowerSource.TIKTOK_API,
            source_url=profile.profile_url,
            profile_url=profile.profile_url,
            settlement_eligible=False,
            profile_id=profile.username,
        )

    @staticmethod
    def _run_awaitable(awaitable: Awaitable[Mapping[str, Any]]) -> Mapping[str, Any]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)

        result: list[Mapping[str, Any]] = []
        errors: list[BaseException] = []

        def run_in_worker() -> None:
            try:
                result.append(asyncio.run(awaitable))
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=run_in_worker, daemon=True)
        worker.start()
        worker.join()
        if errors:
            raise errors[0]
        return result[0]

    def fetch(self, homepage_url: str) -> FollowerFetchResult:
        profile = build_tiktok_profile(homepage_url)
        if profile is None:
            return self._failure(
                None,
                "INVALID_TIKTOK_URL",
                "Unable to parse a TikTok username from the profile URL.",
            )
        if not self.ms_token:
            return self._failure(
                profile,
                "MISSING_TIKTOK_MS_TOKEN",
                "Set TIKTOK_MS_TOKEN in the local .env file before updating TikTok followers.",
            )
        with self._query_lock:
            try:
                payload = self._run_awaitable(self._read_user_data(profile))
                follower_count = self._follower_count(payload)
            except RuntimeError as exc:
                if str(exc) == "TIKTOK_API_NOT_INSTALLED":
                    return self._failure(
                        profile,
                        "TIKTOK_API_NOT_INSTALLED",
                        "TikTokApi is not installed in this local environment.",
                    )
                error_code = self._error_code(exc)
                return self._failure(
                    profile,
                    error_code,
                    self._error_message(error_code),
                )
            except Exception as exc:
                error_code = self._error_code(exc)
                return self._failure(
                    profile,
                    error_code,
                    self._error_message(error_code),
                )
        return self._success(profile, follower_count)


TikTokProvider = TikTokApiProvider
