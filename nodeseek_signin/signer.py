from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from niquests import Response, Session
from niquests.exceptions import RequestException


@dataclass
class SignInResult:
    success: bool
    message: str
    cookie_expired: bool = False
    updated_cookie: str | None = None


ALREADY_SIGNED = ("已完成签到", "已签到", "重复操作")


def sign_in(
    cookie: str,
    *,
    base_url: str,
    random_mode: bool,
    proxy_url: str,
    timeout: int,
) -> SignInResult:
    """Sign in for one account.  Returns result with optional updated cookie."""
    base = _normalize_base(base_url)
    url = f"{base}/api/attendance?random={'true' if random_mode else 'false'}"

    if random_mode:
        time.sleep(random.uniform(1, 3))

    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

    try:
        with Session() as s:
            resp = s.post(
                url,
                headers=_headers(base, cookie),
                json={},
                timeout=timeout,
                proxies=proxies,
            )
    except RequestException as exc:
        return SignInResult(False, f"HTTP exception: {exc}")

    result = _classify(resp)
    if result.success:
        merged = _merge_cookies(cookie, resp)
        if merged != cookie:
            result.updated_cookie = merged
    return result


def _classify(resp: Response) -> SignInResult:
    status = resp.status_code or 0

    if status == 200:
        body = _json(resp)
        if body is None:
            return SignInResult(False, f"JSON parse failed: {(resp.text or '')[:100]}")
        if body.get("success"):
            gain = str(body.get("gain", "0"))
            current = str(body.get("current", "0"))
            return SignInResult(True, f"Sign-in success! +{gain} drumsticks, total {current}")
        return SignInResult(False, str(body.get("message") or "Sign-in failed"))

    if status == 500:
        body = _json(resp)
        msg = str(body.get("message", "")) if body else ""
        if any(k in msg for k in ALREADY_SIGNED):
            return SignInResult(True, f"Already signed in: {msg}")
        return SignInResult(False, f"Server 500: {msg}" if msg else "Server 500 error")

    if status == 401:
        return SignInResult(False, "Cookie expired", cookie_expired=True)
    if status == 403:
        return SignInResult(False, "403 Forbidden (Cloudflare?)")
    if status == 302:
        return SignInResult(False, "302 redirect (cookie expired?)", cookie_expired=True)

    text = (resp.text or "").lower()
    if any(k in text for k in ("login", "signin", "sign in", "登录")):
        return SignInResult(False, f"HTTP {status} (cookie expired?)", cookie_expired=True)
    return SignInResult(False, f"HTTP {status} error")


def _merge_cookies(original: str, resp: Response) -> str:
    updates = _cookie_dict(resp)
    if not updates:
        return original

    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()

    for part in original.split(";"):
        name, sep, value = part.strip().partition("=")
        name = name.strip()
        if name and sep:
            seen.add(name)
            pairs.append((name, updates.get(name, value.strip())))

    for name, value in updates.items():
        if name not in seen:
            pairs.append((name, value))

    return "; ".join(f"{n}={v}" for n, v in pairs)


def _cookie_dict(resp: Response) -> dict[str, str]:
    """Extract response cookies into a plain dict."""
    return {str(k): str(v) for k, v in resp.cookies.get_dict().items() if k and v}


def _normalize_base(value: str) -> str:
    raw = value.strip()
    if not raw:
        return "https://www.nodeseek.com"
    p = urlsplit(raw)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError(f"Invalid base URL: {value}")
    return urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), "", ""))


def _headers(base: str, cookie: str) -> dict[str, str]:
    p = urlsplit(base)
    origin = f"{p.scheme}://{p.netloc}"
    return {
        "Cache-Control": "no-cache",
        "Cookie": cookie,
        "Origin": origin,
        "Referer": f"{base}/board",
        "X-Requested-With": "XMLHttpRequest",
    }


def _json(resp: Response) -> dict[str, Any] | None:
    try:
        payload = resp.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return {k: v for k, v in payload.items() if isinstance(k, str)}
