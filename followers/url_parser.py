from __future__ import annotations

import re
from urllib.parse import urlparse


YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
TIKTOK_HOSTS = {"tiktok.com", "www.tiktok.com", "m.tiktok.com"}
_TIKTOK_USERNAME = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def identify_platform(homepage_url: str | None) -> str | None:
    if homepage_url is None or not homepage_url.strip():
        return None
    try:
        parsed = urlparse(homepage_url.strip())
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").casefold()
    if host in YOUTUBE_HOSTS:
        return "YouTube"
    if host in TIKTOK_HOSTS:
        return "TikTok"
    return None


def parse_tiktok_username(homepage_url: str | None) -> str | None:
    if homepage_url is None:
        return None
    text = homepage_url.strip()
    if not text:
        return None

    if text.casefold().startswith(("http://", "https://")):
        if identify_platform(text) != "TikTok":
            return None
        parsed = urlparse(text)
        parts = [part for part in parsed.path.split("/") if part]
        if not parts or not parts[0].startswith("@"):
            return None
        username = parts[0][1:].strip()
    else:
        username = text[1:].strip() if text.startswith("@") else text

    if _TIKTOK_USERNAME.fullmatch(username) is None:
        return None
    return username
