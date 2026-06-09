from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


DEFAULT_BASE_URL = "https://www.nodeseek.com"


def normalize_base_url(value: str, *, name: str = "base_url") -> str:
    raw_value = value.strip()
    if not raw_value:
        raise ValueError(f"{name} must not be empty")

    parsed = urlsplit(raw_value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute HTTP(S) URL")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{name} must not include query string or fragment")

    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def origin_from_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def join_base_url(base_url: str, path: str) -> str:
    if path.startswith("/"):
        return f"{base_url}{path}"
    return f"{base_url}/{path}"
