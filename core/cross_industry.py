from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import pandas as pd


_YOUTUBE_HOSTS = {
    "youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "www.youtube.com",
    "youtu.be",
}
_TIKTOK_HOSTS = {
    "m.tiktok.com",
    "tiktok.com",
    "vm.tiktok.com",
    "vt.tiktok.com",
    "www.tiktok.com",
}
_YOUTUBE_PATH_PREFIXES = {"embed", "live", "shorts", "v"}
_TRACKING_QUERY_KEYS = {
    "feature",
    "si",
    "source",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}
_URL_PATTERN = re.compile(r"https?://[^\s，,；;]+", re.IGNORECASE)
_TIKTOK_VIDEO_PATTERN = re.compile(r"/(?:video|photo)/(\d+)(?:/|$)", re.IGNORECASE)


@dataclass(frozen=True)
class VideoUrlIdentity:
    platform: str
    url_key: str
    normalized_url: str
    original_url: str


def _clean_url_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip().strip("\"'<>[](){}，。；;、")


def parse_pasted_urls(value: object) -> list[str]:
    """Extract ordered, unique HTTP URLs from pasted text."""
    text = _clean_url_text(value)
    if not text:
        return []
    matches = _URL_PATTERN.findall(text)
    candidates = matches or [line.strip() for line in text.splitlines()]
    urls: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = _clean_url_text(candidate)
        if not cleaned:
            continue
        if cleaned.casefold().startswith("www."):
            cleaned = f"https://{cleaned}"
        if not cleaned.casefold().startswith(("http://", "https://")):
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        urls.append(cleaned)
    return urls


def normalize_video_url(value: object) -> VideoUrlIdentity | None:
    """Create a stable cross-import key for YouTube, TikTok, and generic URLs."""
    original = _clean_url_text(value)
    if not original:
        return None
    if original.casefold().startswith("www."):
        original = f"https://{original}"
    try:
        parsed = urlsplit(original)
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return None

    host = parsed.hostname.casefold().rstrip(".")
    path_parts = [part for part in parsed.path.split("/") if part]
    query = parse_qs(parsed.query, keep_blank_values=False)

    if host in _YOUTUBE_HOSTS:
        video_id = ""
        if host == "youtu.be" and path_parts:
            video_id = path_parts[0]
        elif query.get("v"):
            video_id = str(query["v"][0]).strip()
        elif len(path_parts) >= 2 and path_parts[0].casefold() in _YOUTUBE_PATH_PREFIXES:
            video_id = path_parts[1]
        if video_id:
            return VideoUrlIdentity(
                platform="YouTube",
                url_key=f"youtube:{video_id}",
                normalized_url=f"https://www.youtube.com/watch?v={video_id}",
                original_url=original,
            )

    if host in _TIKTOK_HOSTS:
        match = _TIKTOK_VIDEO_PATTERN.search(parsed.path)
        if match:
            video_id = match.group(1)
            return VideoUrlIdentity(
                platform="TikTok",
                url_key=f"tiktok:{video_id}",
                normalized_url=f"https://www.tiktok.com/video/{video_id}",
                original_url=original,
            )

    kept_query = {
        key: values
        for key, values in query.items()
        if key.casefold() not in _TRACKING_QUERY_KEYS
    }
    normalized_query = urlencode(
        sorted(
            (key, value)
            for key, values in kept_query.items()
            for value in values
        )
    )
    normalized_path = parsed.path.rstrip("/") or "/"
    normalized_url = urlunsplit(
        ("https", host, normalized_path, normalized_query, "")
    )
    platform = (
        "YouTube"
        if host in _YOUTUBE_HOSTS
        else "TikTok"
        if host in _TIKTOK_HOSTS
        else "Other"
    )
    return VideoUrlIdentity(
        platform=platform,
        url_key=f"url:{normalized_url}",
        normalized_url=normalized_url,
        original_url=original,
    )


def annotate_cross_industry_posts(
    data: pd.DataFrame,
    exclusions: pd.DataFrame | Iterable[dict[str, object]],
) -> pd.DataFrame:
    annotated = data.copy()
    if "url" not in annotated:
        annotated["url"] = pd.Series(pd.NA, index=annotated.index, dtype="object")

    if isinstance(exclusions, pd.DataFrame):
        exclusion_data = exclusions.copy()
    else:
        exclusion_data = pd.DataFrame(list(exclusions))
    if "active" in exclusion_data:
        active = pd.to_numeric(exclusion_data["active"], errors="coerce").fillna(0)
        exclusion_data = exclusion_data.loc[active.astype(int).eq(1)]

    reason_by_key: dict[str, str] = {}
    exclusion_id_by_key: dict[str, int] = {}
    for row in exclusion_data.to_dict("records"):
        url_key = str(row.get("url_key") or "").strip()
        if not url_key:
            continue
        reason_by_key[url_key] = str(row.get("reason") or "").strip()
        try:
            exclusion_id_by_key[url_key] = int(row.get("id"))
        except (TypeError, ValueError):
            continue

    identities = annotated["url"].map(normalize_video_url)
    keys = identities.map(lambda item: item.url_key if item is not None else "")
    annotated["cross_industry_url_key"] = keys
    annotated["is_cross_industry"] = keys.isin(reason_by_key).astype(bool)
    annotated["compensation_eligible"] = ~annotated["is_cross_industry"]
    annotated["cross_industry_reason"] = keys.map(reason_by_key).fillna("")
    annotated["cross_industry_exclusion_id"] = keys.map(exclusion_id_by_key).astype(
        "Int64"
    )
    return annotated


def exclude_cross_industry_posts(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty or "is_cross_industry" not in data:
        return data.copy().reset_index(drop=True)
    excluded = data["is_cross_industry"].fillna(False).astype(bool)
    return data.loc[~excluded].copy().reset_index(drop=True)


def cross_industry_totals(data: pd.DataFrame) -> tuple[int, int]:
    if data.empty or "is_cross_industry" not in data:
        return 0, 0
    mask = data["is_cross_industry"].fillna(False).astype(bool)
    views = pd.to_numeric(data.loc[mask, "views"], errors="coerce").fillna(0)
    return int(mask.sum()), int(views.sum())
