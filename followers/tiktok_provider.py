from __future__ import annotations

import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from followers.base import FollowerFetchResult
from followers.url_parser import parse_tiktok_username
from followers.value_parser import (
    FollowerValueError,
    ParsedFollowerValue,
    parse_follower_display_value,
)
from models.enums import FollowerSource


TIKTOK_PROFILE_URL = "https://www.tiktok.com/@{username}"
TIKTOK_BATCH_STOP_ERROR_CODES = {
    "CAPTCHA_REQUIRED",
    "SECURITY_VERIFICATION_REQUIRED",
    "ACCESS_RESTRICTED",
}

# All selectors used to read TikTok are centralized here. Only elements whose
# own semantics identify Followers are accepted; numeric position is never used.
CAPTCHA_SELECTORS = (
    "iframe[src*='captcha']",
    "iframe[src*='recaptcha']",
    "[id*='captcha' i]",
    "[class*='captcha' i]",
)
FOLLOWER_COUNT_SELECTORS = (
    "[data-e2e='followers-count']",
    "[data-testid='followers-count']",
    "[aria-label*='followers' i]",
    "[aria-label*='粉丝']",
)
FOLLOWER_LABEL_SELECTORS = (
    "text=/^\\s*Followers\\s*$/i",
    "text=/^\\s*粉丝(?:数)?\\s*$/",
)

_FOLLOWER_LABEL = re.compile(r"^\s*(?:Followers|粉丝(?:数)?)\s*$", re.IGNORECASE)
_FOLLOWER_WORD = re.compile(r"(?:\bFollowers\b|粉丝(?:数)?)", re.IGNORECASE)
_NON_FOLLOWER_WORD = re.compile(
    r"(?:\bFollowing\b|\bLikes?\b|获赞|点赞|关注)", re.IGNORECASE
)
_NUMBER_TOKEN = re.compile(
    r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
    r"\s*(?:百万|万|[KM])?(?![\w.])",
    re.IGNORECASE,
)
_CAPTCHA_TEXT = re.compile(
    r"captcha|verify you are human|complete the puzzle|验证码|验证您是真人",
    re.IGNORECASE,
)
_SECURITY_TEXT = re.compile(
    r"security verification|unusual activity|suspicious activity|"
    r"verify (?:your )?(?:phone|email|identity)|"
    r"安全验证|异常登录|登录确认|手机验证|邮箱验证|身份验证",
    re.IGNORECASE,
)
_ACCESS_RESTRICTED_TEXT = re.compile(
    r"log in to continue|login required|sign in to continue|"
    r"请先登录|登录后继续|需要登录才能继续",
    re.IGNORECASE,
)
_PROFILE_NOT_FOUND_TEXT = re.compile(
    r"couldn't find this account|account not found|user not found|"
    r"this account doesn't exist|账号不存在|找不到此账号|用户不存在",
    re.IGNORECASE,
)
_SYSTEM_BROWSER_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class TikTokProfile:
    username: str
    profile_url: str


@dataclass(frozen=True)
class TikTokPageQueryResult:
    parsed_value: ParsedFollowerValue | None
    profile_url: str
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class FollowerSemanticCandidate:
    label: str
    raw_value: str
    selector: str


class TikTokSemanticError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def build_tiktok_profile(value: str | None) -> TikTokProfile | None:
    username = parse_tiktok_username(value)
    if username is None:
        return None
    return TikTokProfile(
        username=username,
        profile_url=TIKTOK_PROFILE_URL.format(username=username),
    )


def extract_tiktok_follower_value(
    candidates: list[FollowerSemanticCandidate],
) -> ParsedFollowerValue:
    """Return one value only when an explicit Followers semantic confirms it."""
    follower_candidates = [
        candidate
        for candidate in candidates
        if _FOLLOWER_LABEL.fullmatch(candidate.label.strip()) is not None
        and _NON_FOLLOWER_WORD.search(candidate.label) is None
    ]
    if not follower_candidates:
        raise TikTokSemanticError(
            "PAGE_STRUCTURE_CHANGED",
            "页面中没有可确认语义的 Followers 字段。",
        )

    parsed_values: list[ParsedFollowerValue] = []
    for candidate in follower_candidates:
        try:
            parsed_values.append(parse_follower_display_value(candidate.raw_value))
        except FollowerValueError:
            continue
    if not parsed_values:
        raise TikTokSemanticError(
            "INVALID_FOLLOWER_VALUE",
            "Followers 字段的公开展示值无法可靠解析。",
        )

    counts = {value.follower_count for value in parsed_values}
    if len(counts) != 1:
        raise TikTokSemanticError(
            "PAGE_STRUCTURE_CHANGED",
            "页面中出现多个不一致的 Followers 数值，已停止写入。",
        )
    return parsed_values[0]


class TikTokBrowserProvider:
    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_seconds: float = 45,
        browser_executable: str | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("TIKTOK_PAGE_TIMEOUT_SECONDS 必须大于 0。")
        self.headless = bool(headless)
        self.timeout_seconds = float(timeout_seconds)
        self.browser_executable = browser_executable
        self._query_lock = threading.Lock()

    def browser_launch_options(self) -> dict[str, Any]:
        """Return options for a fresh, non-persistent browser process."""
        return {"headless": self.headless}

    def _browser_candidates(self) -> list[Path | None]:
        candidates: list[Path | None] = []
        if self.browser_executable:
            candidates.append(Path(self.browser_executable))
        candidates.extend(path for path in _SYSTEM_BROWSER_CANDIDATES if path.exists())
        candidates.append(None)
        return list(dict.fromkeys(candidates))

    @contextmanager
    def _open_context(self) -> Iterator[Any]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("PLAYWRIGHT_NOT_INSTALLED") from exc

        with sync_playwright() as playwright:
            browser = None
            context = None
            last_error: Exception | None = None
            options = self.browser_launch_options()
            for executable in self._browser_candidates():
                try:
                    launch_options = dict(options)
                    if executable is not None:
                        launch_options["executable_path"] = str(executable)
                    browser = playwright.chromium.launch(**launch_options)
                    context = browser.new_context(locale="zh-CN")
                    break
                except Exception as exc:  # Playwright browser availability varies locally.
                    last_error = exc
                    if browser is not None:
                        try:
                            browser.close()
                        except Exception:
                            pass
                        browser = None
            if context is None or browser is None:
                raise RuntimeError("BROWSER_LAUNCH_FAILED") from last_error
            try:
                yield context
            finally:
                try:
                    context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass

    @staticmethod
    def _first_page(context: Any) -> Any:
        return context.pages[0] if context.pages else context.new_page()

    @staticmethod
    def _visible(locator: Any, *, limit: int = 20) -> bool:
        try:
            return any(
                locator.nth(index).is_visible()
                for index in range(min(locator.count(), limit))
            )
        except Exception:
            return False

    @staticmethod
    def _body_text(page: Any) -> str:
        try:
            return (page.locator("body").inner_text(timeout=2000) or "")[:200_000]
        except Exception:
            return ""

    def _detect_blocker(self, page: Any) -> tuple[str, str] | None:
        for selector in CAPTCHA_SELECTORS:
            if self._visible(page.locator(selector)):
                return "CAPTCHA_REQUIRED", "TikTok 显示验证码，已停止本批次。"
        text = " ".join((self._body_text(page), str(page.url), page.title()))
        if _CAPTCHA_TEXT.search(text):
            return "CAPTCHA_REQUIRED", "TikTok 要求人机验证，已停止本批次。"
        if _SECURITY_TEXT.search(text):
            return (
                "SECURITY_VERIFICATION_REQUIRED",
                "TikTok 要求安全或身份验证，已停止本批次。",
            )
        return None

    def _detect_access_restriction(self, page: Any) -> tuple[str, str] | None:
        url = str(page.url).casefold()
        if "/login" in url or "/signup" in url:
            return (
                "ACCESS_RESTRICTED",
                "TikTok 公开主页要求登录，工具不会登录账号或绕过访问限制。",
            )
        if _ACCESS_RESTRICTED_TEXT.search(self._body_text(page)):
            return (
                "ACCESS_RESTRICTED",
                "TikTok 公开主页当前不可匿名访问，工具不会尝试登录。",
            )
        return None

    @staticmethod
    def _safe_text(locator: Any) -> str:
        try:
            return (locator.inner_text(timeout=1000) or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _number_from_text(text: str) -> str | None:
        match = _NUMBER_TOKEN.search(text)
        return match.group(0).strip() if match else None

    def _collect_follower_candidates(
        self, page: Any
    ) -> list[FollowerSemanticCandidate]:
        candidates: list[FollowerSemanticCandidate] = []

        for selector in FOLLOWER_COUNT_SELECTORS:
            locator = page.locator(selector)
            try:
                count = min(locator.count(), 20)
            except Exception:
                continue
            for index in range(count):
                item = locator.nth(index)
                if not self._visible(item, limit=1):
                    continue
                data_e2e = (item.get_attribute("data-e2e") or "").casefold()
                aria_label = item.get_attribute("aria-label") or ""
                own_text = self._safe_text(item)
                if data_e2e == "followers-count":
                    raw = self._number_from_text(own_text)
                    if raw:
                        candidates.append(
                            FollowerSemanticCandidate("Followers", raw, selector)
                        )
                elif _FOLLOWER_WORD.search(aria_label):
                    raw = self._number_from_text(aria_label) or self._number_from_text(
                        own_text
                    )
                    if raw:
                        label = "粉丝" if "粉丝" in aria_label else "Followers"
                        candidates.append(FollowerSemanticCandidate(label, raw, selector))

        for selector in FOLLOWER_LABEL_SELECTORS:
            labels = page.locator(selector)
            try:
                count = min(labels.count(), 20)
            except Exception:
                continue
            for index in range(count):
                label_item = labels.nth(index)
                if not self._visible(label_item, limit=1):
                    continue
                label = self._safe_text(label_item)
                if _FOLLOWER_LABEL.fullmatch(label) is None:
                    continue
                siblings = label_item.locator(
                    "xpath=preceding-sibling::*[1] | following-sibling::*[1]"
                )
                try:
                    sibling_count = min(siblings.count(), 4)
                except Exception:
                    continue
                for sibling_index in range(sibling_count):
                    sibling_text = self._safe_text(siblings.nth(sibling_index))
                    if _NON_FOLLOWER_WORD.search(sibling_text):
                        continue
                    raw = self._number_from_text(sibling_text)
                    if raw:
                        candidates.append(
                            FollowerSemanticCandidate(label, raw, selector)
                        )
        return candidates

    def _read_follower_value(self, page: Any) -> ParsedFollowerValue:
        return extract_tiktok_follower_value(
            self._collect_follower_candidates(page)
        )

    def _failure(
        self,
        profile: TikTokProfile | None,
        error_code: str,
        error_message: str,
        *,
        raw_display_value: str | None = None,
    ) -> FollowerFetchResult:
        return FollowerFetchResult(
            success=False,
            follower_count=None,
            platform="TikTok",
            fetched_at=_now(),
            error_code=error_code,
            error_message=error_message,
            raw_display_value=raw_display_value,
            source=FollowerSource.TIKTOK_BROWSER,
            source_url=profile.profile_url if profile else None,
            profile_url=profile.profile_url if profile else None,
            settlement_eligible=False,
            profile_id=profile.username if profile else None,
        )

    def _success(
        self, profile: TikTokProfile, parsed: ParsedFollowerValue
    ) -> FollowerFetchResult:
        return FollowerFetchResult(
            success=True,
            follower_count=parsed.follower_count,
            platform="TikTok",
            fetched_at=_now(),
            raw_display_value=parsed.raw_display_value,
            is_estimated=parsed.is_estimated,
            source=FollowerSource.TIKTOK_BROWSER,
            source_url=profile.profile_url,
            profile_url=profile.profile_url,
            settlement_eligible=False,
            profile_id=profile.username,
        )

    def _query_profile(self, context: Any, profile: TikTokProfile) -> TikTokPageQueryResult:
        page = self._first_page(context)
        timeout_ms = int(self.timeout_seconds * 1000)
        page.set_default_timeout(timeout_ms)
        response = page.goto(
            profile.profile_url,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
        blocker = self._detect_blocker(page)
        if blocker:
            return TikTokPageQueryResult(None, profile.profile_url, *blocker)
        access_restriction = self._detect_access_restriction(page)
        if access_restriction:
            return TikTokPageQueryResult(
                None, profile.profile_url, *access_restriction
            )
        if response is not None and response.status == 404:
            return TikTokPageQueryResult(
                None, profile.profile_url, "PROFILE_NOT_FOUND", "TikTok 主页不存在。"
            )
        if response is not None and response.status >= 500:
            return TikTokPageQueryResult(
                None, profile.profile_url, "NETWORK_ERROR", "TikTok 主页暂时不可用。"
            )
        if response is not None and response.status in {401, 403, 429}:
            return TikTokPageQueryResult(
                None,
                profile.profile_url,
                "ACCESS_RESTRICTED",
                "TikTok 暂时限制公开主页访问，工具不会尝试绕过。",
            )
        if _PROFILE_NOT_FOUND_TEXT.search(self._body_text(page)):
            return TikTokPageQueryResult(
                None, profile.profile_url, "PROFILE_NOT_FOUND", "TikTok 主页不存在。"
            )

        deadline = time.monotonic() + self.timeout_seconds
        last_semantic_error: TikTokSemanticError | None = None
        while time.monotonic() < deadline:
            blocker = self._detect_blocker(page)
            if blocker:
                return TikTokPageQueryResult(None, profile.profile_url, *blocker)
            access_restriction = self._detect_access_restriction(page)
            if access_restriction:
                return TikTokPageQueryResult(
                    None, profile.profile_url, *access_restriction
                )
            try:
                parsed = self._read_follower_value(page)
            except TikTokSemanticError as exc:
                last_semantic_error = exc
            else:
                return TikTokPageQueryResult(parsed, profile.profile_url)
            page.wait_for_timeout(500)

        if last_semantic_error is not None:
            return TikTokPageQueryResult(
                None,
                profile.profile_url,
                last_semantic_error.error_code,
                str(last_semantic_error),
            )
        return TikTokPageQueryResult(
            None, profile.profile_url, "TIMEOUT", "等待 TikTok 主页加载超时。"
        )

    def _playwright_failure(
        self, profile: TikTokProfile | None, exc: Exception
    ) -> FollowerFetchResult:
        message = str(exc).casefold()
        if "timeout" in message:
            code, text = "TIMEOUT", "访问 TikTok 主页超时。"
        elif "playwright_not_installed" in message or "browser_launch_failed" in message:
            code, text = "NETWORK_ERROR", "无法启动 TikTok 公开主页浏览器。"
        else:
            code, text = "NETWORK_ERROR", "无法访问 TikTok 公开主页。"
        return self._failure(profile, code, text)

    def fetch(self, homepage_url: str) -> FollowerFetchResult:
        profile = build_tiktok_profile(homepage_url)
        if profile is None:
            return self._failure(
                None,
                "INVALID_TIKTOK_URL",
                "无法从 TikTok 主页链接解析 username。",
            )
        with self._query_lock:
            try:
                with self._open_context() as context:
                    query = self._query_profile(context, profile)
            except Exception as exc:
                return self._playwright_failure(profile, exc)
        if query.error_code:
            return self._failure(
                profile,
                query.error_code,
                query.error_message or "TikTok 粉丝数读取失败。",
            )
        if query.parsed_value is None:
            return self._failure(
                profile,
                "PAGE_STRUCTURE_CHANGED",
                "无法确认 TikTok Followers 字段。",
            )
        return self._success(profile, query.parsed_value)

TikTokProvider = TikTokBrowserProvider
