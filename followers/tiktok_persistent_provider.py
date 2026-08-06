from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from followers.base import FollowerFetchResult
from followers.tiktok_provider import TikTokProfile, build_tiktok_profile
from followers.value_parser import (
    FollowerValueError,
    ParsedFollowerValue,
    parse_follower_display_value,
)
from models.enums import FollowerSource


TIKTOK_BATCH_STOP_ERROR_CODES = {
    "ACCESS_RESTRICTED",
    "CAPTCHA_REQUIRED",
    "SECURITY_VERIFICATION_REQUIRED",
    "TIKTOK_BROWSER_TIMEOUT",
    "TIKTOK_LOGIN_REQUIRED",
}
_FOLLOWER_SELECTOR = "strong[data-e2e='followers-count']"
_T = TypeVar("_T")


class TikTokBrowserQueryError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TikTokPersistentBrowserProvider:
    """Read public follower counts through a user-managed local browser profile."""

    def __init__(
        self,
        *,
        user_data_dir: Path,
        headless: bool = False,
        timeout_seconds: float = 180,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("TikTok browser timeout must be positive.")
        self.user_data_dir = Path(user_data_dir)
        self.headless = bool(headless)
        self.timeout_seconds = float(timeout_seconds)
        self._query_lock = threading.Lock()

    @staticmethod
    async def _body_text(page: Any) -> str:
        try:
            return (
                await page.locator("body").inner_text(timeout=2_000) or ""
            )[:50_000]
        except Exception:
            return ""

    async def _timeout_error(self, page: Any) -> TikTokBrowserQueryError:
        url = str(page.url).casefold()
        body = (await self._body_text(page)).casefold()
        if "captcha" in body or "verify you are human" in body:
            return TikTokBrowserQueryError(
                "CAPTCHA_REQUIRED",
                "TikTok 要求人机验证。请在弹出的本地浏览器中手动完成验证后重试。",
            )
        if "security verification" in body or "unusual activity" in body:
            return TikTokBrowserQueryError(
                "SECURITY_VERIFICATION_REQUIRED",
                "TikTok 要求安全验证。请在弹出的本地浏览器中手动完成验证后重试。",
            )
        if "/login" in url or "log in" in body or "sign in" in body:
            return TikTokBrowserQueryError(
                "TIKTOK_LOGIN_REQUIRED",
                "请在弹出的本地浏览器中登录 TikTok，然后重试读取粉丝数。",
            )
        return TikTokBrowserQueryError(
            "TIKTOK_BROWSER_TIMEOUT",
            "未在限定时间内找到 TikTok 的 Followers 字段。请检查浏览器页面后重试。",
        )

    async def _read_profile(self, profile: TikTokProfile) -> ParsedFollowerValue:
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise TikTokBrowserQueryError(
                "PLAYWRIGHT_NOT_INSTALLED",
                "本机未安装 Playwright，无法启动 TikTok 本地浏览器。",
            ) from exc

        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                headless=self.headless,
                locale="en-US",
                viewport={"width": 1280, "height": 900},
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                timeout_ms = int(self.timeout_seconds * 1_000)
                await page.goto(
                    profile.profile_url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
                locator = page.locator(_FOLLOWER_SELECTOR).first
                try:
                    await locator.wait_for(state="visible", timeout=timeout_ms)
                    raw_value = (await locator.inner_text()).strip()
                except PlaywrightTimeoutError as exc:
                    raise await self._timeout_error(page) from exc
                try:
                    return parse_follower_display_value(raw_value)
                except FollowerValueError as exc:
                    raise TikTokBrowserQueryError(
                        "INVALID_FOLLOWER_VALUE",
                        "TikTok Followers 字段的展示值无法可靠解析。",
                    ) from exc
            finally:
                await context.close()

    @staticmethod
    def _run_awaitable(awaitable: Awaitable[_T]) -> _T:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)

        results: list[_T] = []
        errors: list[BaseException] = []

        def run_in_worker() -> None:
            try:
                results.append(asyncio.run(awaitable))
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=run_in_worker, daemon=True)
        worker.start()
        worker.join()
        if errors:
            raise errors[0]
        return results[0]

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
            source=FollowerSource.TIKTOK_BROWSER,
            source_url=profile.profile_url if profile else None,
            profile_url=profile.profile_url if profile else None,
            settlement_eligible=False,
            profile_id=profile.username if profile else None,
        )

    @staticmethod
    def _success(
        profile: TikTokProfile,
        parsed_value: ParsedFollowerValue,
    ) -> FollowerFetchResult:
        return FollowerFetchResult(
            success=True,
            follower_count=parsed_value.follower_count,
            platform="TikTok",
            fetched_at=_now(),
            raw_display_value=parsed_value.raw_display_value,
            is_estimated=parsed_value.is_estimated,
            source=FollowerSource.TIKTOK_BROWSER,
            source_url=profile.profile_url,
            profile_url=profile.profile_url,
            settlement_eligible=False,
            profile_id=profile.username,
        )

    def fetch(self, homepage_url: str) -> FollowerFetchResult:
        profile = build_tiktok_profile(homepage_url)
        if profile is None:
            return self._failure(
                None,
                "INVALID_TIKTOK_URL",
                "无法从 TikTok 主页链接解析用户名。",
            )
        with self._query_lock:
            try:
                parsed_value = self._run_awaitable(self._read_profile(profile))
            except TikTokBrowserQueryError as exc:
                return self._failure(profile, exc.error_code, str(exc))
            except Exception:
                return self._failure(
                    profile,
                    "TIKTOK_BROWSER_ERROR",
                    "TikTok 本地浏览器读取失败，已保留原有粉丝数。",
                )
        return self._success(profile, parsed_value)
