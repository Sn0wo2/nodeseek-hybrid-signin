from __future__ import annotations

import logging
import os


from nodeseek_signin.cookie_store import CookieStore, create_cookie_store
from nodeseek_signin.signer import SignInResult, sign_in


_BASE_URL = "https://www.nodeseek.com"


def _load_cookies() -> list[str]:
    raw = os.environ.get("NS_COOKIE", "")
    return [c.strip() for c in raw.split("&") if c.strip()]


def _bool(name: str, default: bool) -> bool:
    val = (os.environ.get(name) or "").strip().lower()
    if not val:
        return default
    if val in ("1", "true", "yes", "y", "on"):
        return True
    if val in ("0", "false", "no", "n", "off"):
        return False
    raise ValueError(f"{name} must be a boolean value")


def _int(name: str, default: int, *, minimum: int = 1) -> int:
    val = (os.environ.get(name) or "").strip()
    if not val:
        return default
    n = int(val)
    if n < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return n


def _cookie_store_name() -> str:
    val = (os.environ.get("COOKIE_STORE") or "").strip().lower()
    if val in ("github", "qinglong", "none"):
        return val
    return "auto"


def _default_writeback(store: str) -> bool:
    if store in ("github", "qinglong"):
        return True
    return os.environ.get("GITHUB_ACTIONS") == "true"


class App:
    def __init__(self) -> None:
        store_name = _cookie_store_name()
        self._base_url = (os.environ.get("BASE_URL") or _BASE_URL).strip().rstrip("/")
        self._random = _bool("NS_RANDOM", True)
        self._timeout = _int("TIMEOUT", 30)
        self._proxy = os.environ.get("PROXY_URL", "").strip()
        self._cookie_store: CookieStore | None = create_cookie_store(
            store=store_name,
            enabled=False if store_name == "none" else _bool("COOKIE_WRITEBACK", _default_writeback(store_name)),
        )

    def run(self) -> int:
        cookies = _load_cookies()
        if not cookies:
            logging.error("No cookies found (set NS_COOKIE)")
            return 0

        logging.info("Found %d account(s)", len(cookies))
        results = [self._sign_one(i, c) for i, c in enumerate(cookies, 1)]
        self._write_back(cookies, results)

        expired = [i for i, r in enumerate(results, 1) if r.cookie_expired]
        if expired:
            logging.warning("Expired cookies: Account %s", ", ".join(str(i) for i in expired))

        ok = sum(1 for r in results if r.success)
        logging.info("Done: %d/%d succeeded", ok, len(results))
        return ok

    def _sign_one(self, index: int, cookie: str) -> SignInResult:
        name = f"Account{index}"
        logging.info("Signing in: %s", name)

        result = sign_in(
            cookie,
            base_url=self._base_url,
            random_mode=self._random,
            proxy_url=self._proxy,
            timeout=self._timeout,
        )

        log = logging.info if result.success else logging.error
        log("%s: %s", name, result.message)
        return result

    def _write_back(self, cookies: list[str], results: list[SignInResult]) -> None:
        if self._cookie_store is None:
            return
        if not any(r.updated_cookie for r in results):
            return

        updated = [r.updated_cookie or orig for orig, r in zip(cookies, results)]
        merged = "&".join(c for c in updated if c)

        if self._cookie_store.save(merged):
            logging.info("NS_COOKIE write-back complete")
        else:
            logging.warning("NS_COOKIE changed but write-back failed")
