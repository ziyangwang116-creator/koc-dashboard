from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

from followers.base import FollowerFetchResult
from followers.url_parser import identify_platform
from models.enums import FollowerSource


JsonFetcher = Callable[[str, float], dict[str, Any]]


class YouTubeRequestError(RuntimeError):
    def __init__(self, status_code: int, reason: str | None = None) -> None:
        super().__init__("YouTube API request failed")
        self.status_code = status_code
        self.reason = reason or ""


class YouTubeInvalidResponseError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _error_reason(payload: dict[str, Any]) -> str:
    error = payload.get("error") or {}
    errors = error.get("errors") or []
    if errors and isinstance(errors[0], dict):
        return str(errors[0].get("reason") or "")
    return str(error.get("status") or "")


def _default_json_fetcher(url: str, timeout: float) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=timeout) as response:  # noqa: S310 - official HTTPS API
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            reason = _error_reason(payload)
        except Exception:
            reason = ""
        raise YouTubeRequestError(exc.code, reason) from None
    except (URLError, TimeoutError, OSError) as exc:
        raise ConnectionError("YouTube API network error") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise YouTubeInvalidResponseError("Invalid YouTube API response") from exc
    if not isinstance(payload, dict):
        raise YouTubeInvalidResponseError("Invalid YouTube API response")
    return payload


class YouTubeOfficialProvider:
    API_URL = "https://www.googleapis.com/youtube/v3/channels"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = 10.0,
        json_fetcher: JsonFetcher | None = None,
    ) -> None:
        configured = api_key if api_key is not None else os.getenv("YOUTUBE_API_KEY")
        self.api_key = configured.strip() if configured else None
        self.timeout = timeout
        self.json_fetcher = json_fetcher or _default_json_fetcher

    @staticmethod
    def _lookup(homepage_url: str) -> tuple[str, str] | None:
        if identify_platform(homepage_url) != "YouTube":
            return None
        parts = [part for part in urlparse(homepage_url).path.split("/") if part]
        if not parts:
            return None
        first = parts[0]
        if first.startswith("@") and len(first) > 1:
            return "forHandle", first[1:]
        if len(parts) >= 2 and first.casefold() == "channel" and parts[1]:
            return "id", parts[1]
        if len(parts) >= 2 and first.casefold() == "user" and parts[1]:
            return "forUsername", parts[1]
        return None

    @staticmethod
    def _api_error_code(error: YouTubeRequestError) -> str:
        reason = error.reason.casefold()
        if reason in {"quotaexceeded", "dailylimitexceeded", "ratelimitexceeded"}:
            return "QUOTA_EXCEEDED"
        if reason in {"keyinvalid", "apikeyinvalid", "badrequest"}:
            return "API_KEY_INVALID"
        if error.status_code == 403:
            return "API_FORBIDDEN"
        if error.status_code in {400, 401}:
            return "API_KEY_INVALID"
        return "INVALID_RESPONSE"

    def _failure(
        self,
        homepage_url: str,
        error_code: str,
        error_message: str,
    ) -> FollowerFetchResult:
        return FollowerFetchResult(
            success=False,
            follower_count=None,
            platform="YouTube",
            fetched_at=_now(),
            error_code=error_code,
            error_message=error_message,
            source=FollowerSource.YOUTUBE_API,
            source_url=self.API_URL,
            profile_url=homepage_url.strip(),
            settlement_eligible=False,
        )

    def fetch(self, homepage_url: str) -> FollowerFetchResult:
        if not self.api_key:
            return self._failure(
                homepage_url,
                "MISSING_API_KEY",
                "未配置 YOUTUBE_API_KEY，可继续人工填写粉丝数。",
            )
        lookup = self._lookup(homepage_url)
        if lookup is None:
            return self._failure(
                homepage_url,
                "INVALID_YOUTUBE_URL",
                "该链接不是支持的 YouTube 频道主页格式。",
            )
        lookup_key, lookup_value = lookup
        query = urlencode(
            {
                "part": "snippet,statistics",
                lookup_key: lookup_value,
                "key": self.api_key,
            }
        )
        try:
            payload = self.json_fetcher(f"{self.API_URL}?{query}", self.timeout)
            if payload.get("error"):
                status = int((payload.get("error") or {}).get("code") or 0)
                raise YouTubeRequestError(status, _error_reason(payload))
            items = payload.get("items")
            if not isinstance(items, list):
                return self._failure(
                    homepage_url, "INVALID_RESPONSE", "YouTube API 返回格式无效。"
                )
            if not items:
                return self._failure(
                    homepage_url, "CHANNEL_NOT_FOUND", "YouTube API 未找到该频道。"
                )
            item = items[0]
            if not isinstance(item, dict):
                return self._failure(
                    homepage_url, "INVALID_RESPONSE", "YouTube API 返回格式无效。"
                )
            statistics = item.get("statistics") or {}
            snippet = item.get("snippet") or {}
            if statistics.get("hiddenSubscriberCount") is True:
                return self._failure(
                    homepage_url,
                    "HIDDEN_SUBSCRIBER_COUNT",
                    "该频道隐藏了公开订阅者数量。",
                )
            raw_count = statistics.get("subscriberCount")
            if raw_count is None:
                return self._failure(
                    homepage_url,
                    "HIDDEN_SUBSCRIBER_COUNT",
                    "YouTube API 未返回公开订阅者数量。",
                )
            try:
                count = int(str(raw_count))
            except (TypeError, ValueError):
                return self._failure(
                    homepage_url, "INVALID_RESPONSE", "YouTube 订阅者数量格式无效。"
                )
            if count < 0:
                return self._failure(
                    homepage_url, "INVALID_RESPONSE", "YouTube 订阅者数量格式无效。"
                )
            return FollowerFetchResult(
                success=True,
                follower_count=count,
                platform="YouTube",
                fetched_at=_now(),
                raw_display_value=str(raw_count),
                is_estimated=True,
                source=FollowerSource.YOUTUBE_API,
                source_url=self.API_URL,
                profile_url=homepage_url.strip(),
                settlement_eligible=True,
                profile_id=str(item.get("id") or "") or None,
                profile_title=str(snippet.get("title") or "") or None,
            )
        except YouTubeRequestError as exc:
            code = self._api_error_code(exc)
            messages = {
                "QUOTA_EXCEEDED": "YouTube API 配额已用尽。",
                "API_KEY_INVALID": "YouTube API Key 无效。",
                "API_FORBIDDEN": "YouTube API 请求被拒绝，请检查 API 权限。",
                "INVALID_RESPONSE": "YouTube API 返回了无法识别的错误。",
            }
            return self._failure(homepage_url, code, messages[code])
        except (ConnectionError, URLError, TimeoutError, OSError):
            return self._failure(
                homepage_url, "NETWORK_ERROR", "YouTube API 网络请求失败。"
            )
        except (YouTubeInvalidResponseError, ValueError, TypeError, KeyError):
            return self._failure(
                homepage_url, "INVALID_RESPONSE", "YouTube API 返回格式无效。"
            )
        except Exception:
            return self._failure(
                homepage_url, "INVALID_RESPONSE", "YouTube API 请求处理失败。"
            )


YouTubeDataAPIProvider = YouTubeOfficialProvider
