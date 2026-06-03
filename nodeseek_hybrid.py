import json
import logging
import os
import random
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from curl_cffi import requests as cf_requests
from curl_cffi.requests import Session as CfSession
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)

# Pinned TLS fingerprint. When CF starts blocking this version, bump it
# (curl_cffi ships a newer firefox entry on each release).
IMPERSONATE_VERSIONS: List[str] = ["firefox147"]

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SigninResult:
    success: bool
    message: str
    method: str
    cookie_expired: bool = False
    statistics: Optional[dict] = None


@dataclass
class AccountConfig:
    index: int
    display_name: str
    cookie: str = ""
    username: str = ""
    password: str = ""


@dataclass
class SigninStats:
    total_amount: float
    average: float
    days_count: int
    period: str


@dataclass
class AppConfig:
    environment: str
    enable_statistics: bool
    enable_browser: bool
    proxy_url: str
    random_mode: bool
    headless: bool
    timeout: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_env_config() -> AppConfig:
    env_type = "github" if os.environ.get("GITHUB_ACTIONS") == "true" else "local"
    enable_browser_raw = os.environ.get("ENABLE_BROWSER", os.environ.get("ENABLE_SELENIUM", "auto"))
    timeout = int(os.environ.get("TIMEOUT", "30"))

    if env_type == "github":
        # GitHub Actions hard-caps job time; force-enable browser fallback and clamp timeout.
        if enable_browser_raw == "auto":
            enable_browser_raw = "true"
        timeout = min(timeout, 120)

    return AppConfig(
        environment=env_type,
        enable_statistics=os.environ.get("ENABLE_STATISTICS", "true").lower() == "true",
        enable_browser=enable_browser_raw.lower() in ("true", "auto"),
        proxy_url=os.environ.get("PROXY_URL", ""),
        random_mode=os.environ.get("NS_RANDOM", "true").lower() == "true",
        headless=os.environ.get("HEADLESS", "true").lower() == "true",
        timeout=timeout,
    )


def _request_with_impersonate(
    session: CfSession,
    method: str,
    url: str,
    *,
    headers: dict,
    timeout: int,
    **kwargs,
) -> cf_requests.Response:
    """Try each TLS fingerprint in order; fall back to no spoofing if all fail."""
    for version in IMPERSONATE_VERSIONS:
        try:
            return session.request(method, url, headers=headers, timeout=timeout, impersonate=version, **kwargs)
        except Exception as e:
            logging.debug("impersonate=%s failed: %s", version, e)
    logging.warning("All curl_cffi impersonate versions failed, falling back to no TLS spoofing")
    return session.request(method, url, headers=headers, timeout=timeout, **kwargs)


# Mask account identifiers in logs: keeps first 2 + last 1 chars when long enough
# to stay recognisable, falls back to a fixed string for very short names.
_NAME_MASK_KEEP_HEAD = 2
_NAME_MASK_KEEP_TAIL = 1


def _mask_name(name: str) -> str:
    if not name:
        return "N/A"
    n = name.strip()
    if len(n) <= 2:
        return "*" * len(n) if n else "N/A"
    if len(n) <= 4:
        return f"{n[0]}{'*' * (len(n) - 1)}"
    return f"{n[:_NAME_MASK_KEEP_HEAD]}***{n[-_NAME_MASK_KEEP_TAIL:]}"


# Pull the first integer (with optional sign) out of arbitrary text — reserved
# for the Playwright head-info DOM fallback when the JSON response is not
# directly available.
_DRUMSTICK_NUM_RE = re.compile(r"-?\d+")


def _extract_int(text: str) -> Optional[int]:
    if not text:
        return None
    m = _DRUMSTICK_NUM_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(0))
    except (TypeError, ValueError):
        return None




# ---------------------------------------------------------------------------
# HTTP signer
# ---------------------------------------------------------------------------


class HTTPSigner:
    def __init__(self, config: AppConfig):
        self.config = config
        self.session: Optional[CfSession] = None

    def _build_session(self) -> CfSession:
        session = cf_requests.Session()
        if self.config.proxy_url:
            session.proxies.update({"http": self.config.proxy_url, "https": self.config.proxy_url})
        return session

    def get_headers(self, cookie: str) -> dict:
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "application/json",
            "Cookie": cookie,
            "Host": "www.nodeseek.com",
            "Origin": "https://www.nodeseek.com",
            "Referer": "https://www.nodeseek.com/board",
            "User-Agent": DEFAULT_USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
        }

    def signin(self, cookie: str) -> SigninResult:
        try:
            self.session = self._build_session()
            if self.config.random_mode:
                time.sleep(random.uniform(1, 3))
            url = f"https://www.nodeseek.com/api/attendance?random={'true' if self.config.random_mode else 'false'}"
            response = _request_with_impersonate(
                self.session, "POST", url, headers=self.get_headers(cookie), timeout=self.config.timeout, json={},
            )
            return self._classify_attendance_response(response)
        except Exception as e:
            return SigninResult(False, f"HTTP signin exception: {e}", "http")

    @staticmethod
    def _classify_attendance_response(response: cf_requests.Response) -> SigninResult:
        status = response.status_code

        match status:
            case 200:
                try:
                    result = response.json()
                except json.JSONDecodeError:
                    return SigninResult(False, f"Response parse failed: {response.text[:100]}", "http")
                if result.get("success"):
                    return SigninResult(
                        True,
                        f"Signin success! Today +{result.get('gain', 0)} drumsticks, total {result.get('current', 0)}",
                        "http",
                    )
                return SigninResult(False, result.get("message", "Signin failed"), "http")

            case 500:
                try:
                    message = response.json().get("message", "")
                except (json.JSONDecodeError, ValueError):
                    return SigninResult(False, "Server 500 error", "http")
                if any(k in message for k in ("已完成签到", "已签到", "重复操作")):
                    return SigninResult(True, f"Already signed in: {message}", "http")
                return SigninResult(False, f"Server error: {message}", "http")

            case 401:
                return SigninResult(False, "Cookie expired, please update manually", "http", cookie_expired=True)
            case 403:
                return SigninResult(False, "403 Forbidden — possibly blocked by Cloudflare", "http")
            case 302:
                return SigninResult(False, "302 redirect — cookie likely expired", "http", cookie_expired=True)

            case _:
                body = response.text.lower()
                if any(k in body for k in ("login", "signin", "sign in", "登录", "请登录")):
                    return SigninResult(False, f"HTTP {status} — cookie likely expired", "http", cookie_expired=True)
                return SigninResult(False, f"HTTP {status} error", "http")


# ---------------------------------------------------------------------------
# Playwright signer
# ---------------------------------------------------------------------------


class PlaywrightSigner:
    def __init__(self, config: AppConfig):
        self.config = config
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    def _start(self) -> None:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.config.headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        self._context = self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=DEFAULT_USER_AGENT,
        )
        # Runs before any page script: hides navigator.webdriver.
        self._context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        self._page = self._context.new_page()

    def _stop(self) -> None:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def signin(self, cookie: str) -> SigninResult:
        try:
            self._start()
            assert self._page is not None and self._context is not None

            self._page.goto("https://www.nodeseek.com")
            self._page.wait_for_selector("body", timeout=30_000)

            for item in cookie.split(";"):
                try:
                    name, value = item.strip().split("=", 1)
                except ValueError:
                    continue
                self._context.add_cookies([{
                    "name": name, "value": value,
                    "domain": ".nodeseek.com", "path": "/",
                }])

            self._page.reload()
            self._page.wait_for_load_state("domcontentloaded")

            try:
                username = self._page.locator("a.Username").first
                username.wait_for(timeout=15_000)
                logging.info("Playwright login verified: %s", (username.text_content() or "").strip())
            except Exception:
                if "signin" in self._page.url.lower() or "login" in self._page.url.lower():
                    return SigninResult(False, "Playwright — cookie expired, re-login required",
                                        "playwright", cookie_expired=True)
                return SigninResult(False, "Playwright login verification failed", "playwright")

            self._page.goto("https://www.nodeseek.com/board")
            head_info = self._page.locator(".head-info > div").first
            head_info.wait_for(timeout=30_000)

            if not head_info.locator("button").count():
                return SigninResult(True, f"Already signed in: {(head_info.text_content() or '').strip()}",
                                    "playwright")

            button_text = "试试手气" if self.config.random_mode else "鸡腿 x 5"
            button = self._page.locator(
                f"//div[button[text()='鸡腿 x 5'] and button[text()='试试手气']]"
                f"//button[text()='{button_text}']"
            )
            button.scroll_into_view_if_needed()
            self._page.wait_for_timeout(500)
            button.click()
            return SigninResult(True, f"Playwright signin success ({button_text})", "playwright")

        except Exception as e:
            error_msg = str(e)
            if any(k in error_msg.lower() for k in ("login", "signin", "authentication", "登录")):
                return SigninResult(False, f"Playwright — cookie may be expired: {error_msg}",
                                    "playwright", cookie_expired=True)
            return SigninResult(False, f"Playwright signin exception: {error_msg}", "playwright")
        finally:
            self._stop()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class NodeSeekHybridSigner:
    def __init__(self):
        self.config = get_env_config()
        self.http_signer = HTTPSigner(self.config)
        self.playwright_signer = PlaywrightSigner(self.config)

        logging.info("Environment: %s", self.config.environment)
        logging.info("Statistics: %s", "enabled" if self.config.enable_statistics else "disabled")
        logging.info("Playwright signer initialized")

    @staticmethod
    def _parse_cookies() -> List[str]:
        raw = os.environ.get("NS_COOKIE", "")
        if not raw:
            return []
        return [c.strip() for c in raw.split("&") if c.strip()]

    @staticmethod
    def _parse_credentials() -> List[Tuple[str, str]]:
        creds: List[Tuple[str, str]] = []
        user, password = os.environ.get("USER", ""), os.environ.get("PASS", "")
        if user and password:
            creds.append((user, password))
        index = 1
        while True:
            user = os.environ.get(f"USER{index}", "")
            password = os.environ.get(f"PASS{index}", "")
            if not (user and password):
                break
            creds.append((user, password))
            index += 1
        return creds

    def load_accounts(self) -> List[AccountConfig]:
        cookies = self._parse_cookies()
        creds = self._parse_credentials()
        # Pad shorter list so each account index has a credential + cookie pair.
        max_count = max(len(cookies), len(creds))
        while len(cookies) < max_count:
            cookies.append("")
        while len(creds) < max_count:
            creds.append(("", ""))

        accounts: List[AccountConfig] = []
        for i, ((username, password), cookie) in enumerate(zip(creds, cookies), start=1):
            display_name = username or f"Account{i}"
            accounts.append(
                AccountConfig(
                    index=i,
                    display_name=display_name,
                    cookie=cookie,
                    username=username,
                    password=password,
                )
            )
        return accounts

    def _fetch_stats(self, cookie: str, days: int = 30) -> Optional[SigninStats]:
        if not cookie or not self.config.enable_statistics:
            return None
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Cookie": cookie,
        }

        all_records: list = []
        page = 1
        while page <= 10:
            url = f"https://www.nodeseek.com/api/account/credit/page-{page}"
            session = cf_requests.Session()
            response = _request_with_impersonate(session, "GET", url, headers=headers, timeout=10)

            try:
                data = response.json()
            except (json.JSONDecodeError, ValueError):
                break
            if not data.get("success") or not data.get("data"):
                break
            records = data["data"]
            if not records:
                break
            all_records.extend(records)
            page += 1
            time.sleep(0.3)

        signin_records = [
            {"amount": r[0], "description": r[2]}
            for r in all_records
            if len(r) >= 4 and "签到收益" in str(r[2])
        ]
        if not signin_records:
            return None

        sliced = signin_records[:days]
        count = len(sliced)
        total = sum(item["amount"] for item in sliced)
        average = round(total / count, 2) if count else 0
        return SigninStats(total_amount=total, average=average, days_count=count, period=f"Last {days} days")

    def _try_method(self, name: str, fn: Callable[[], SigninResult]) -> Optional[SigninResult]:
        try:
            result = fn()
        except Exception as e:
            logging.error("%s exception: %s", name, e)
            return None
        if result.success:
            logging.info("%s success", name)
            return result
        logging.warning("%s failed: %s", name, result.message)
        return None

    def progressive_signin(self, account: AccountConfig) -> SigninResult:
        logging.info("Starting signin: %s", _mask_name(account.display_name))
        if not account.cookie:
            return SigninResult(False, "No cookie", "none")

        for method_name, runner in self._signin_pipeline(account.cookie):
            result = self._try_method(method_name, runner)
            if result is not None:
                return result
        return SigninResult(False, "All signin methods failed, please update cookie manually", "failed")

    def _signin_pipeline(self, cookie: str) -> List[Tuple[str, Callable[[], SigninResult]]]:
        pipeline: List[Tuple[str, Callable[[], SigninResult]]] = [
            ("HTTP", lambda: self.http_signer.signin(cookie)),
        ]
        if self.config.proxy_url:
            pipeline.append(("Proxy HTTP", lambda: self._proxy_signin(cookie)))
        if self.config.enable_browser:
            pipeline.append(("Playwright", lambda: self.playwright_signer.signin(cookie)))
        return pipeline

    def _proxy_signin(self, cookie: str) -> SigninResult:
        proxy = self.config.proxy_url
        session = cf_requests.Session()
        session.proxies.update({"http": proxy, "https": proxy})
        original_session = self.http_signer.session
        self.http_signer.session = session
        try:
            result = self.http_signer.signin(cookie)
            result.method = "proxy"
            return result
        finally:
            self.http_signer.session = original_session

    def _annotate_with_stats(self, result: SigninResult, cookie: str) -> SigninResult:
        if not result.success or not self.config.enable_statistics:
            return result
        try:
            stats = self._fetch_stats(cookie)
        except Exception as e:
            logging.warning("Statistics query failed: %s", e)
            return result
        if stats is None:
            return result
        result.statistics = {
            "total_amount": stats.total_amount,
            "average": stats.average,
            "days_count": stats.days_count,
            "period": stats.period,
        }
        result.message += f" | {stats.days_count}-day stats: avg {stats.average} drumsticks/day"
        return result

    def _process_account(self, account: AccountConfig) -> Tuple[AccountConfig, SigninResult]:
        masked = _mask_name(account.display_name)
        logging.info("=" * 30 + " %s " + "=" * 30, masked)
        result = self.progressive_signin(account)
        result = self._annotate_with_stats(result, account.cookie)
        return account, result

    def run(self) -> int:
        logging.info("NodeSeek hybrid signer starting")
        logging.info("=" * 50)

        accounts = self.load_accounts()
        if not accounts:
            logging.error("No account configuration found")
            return 0
        logging.info("Found %d account(s)", len(accounts))

        results: List[Tuple[AccountConfig, SigninResult]] = []
        expired: List[str] = []
        for account in accounts:
            acc, result = self._process_account(account)
            results.append((acc, result))
            masked = _mask_name(acc.display_name)
            if not result.success:
                logging.error("%s: %s", masked, result.message)
                if result.cookie_expired:
                    expired.append(masked)
                    logging.warning("Cookie expired detected: %s", masked)

        if expired:
            logging.warning("%d expired cookie(s): %s", len(expired), ", ".join(expired))

        logging.info("Cookie check complete")
        success_count = sum(1 for _, r in results if r.success)
        logging.info("=" * 50)
        logging.info("Done: %d/%d succeeded", success_count, len(results))
        logging.info("Hybrid signer finished")
        return success_count


def main() -> int:
    try:
        success = NodeSeekHybridSigner().run()
    except KeyboardInterrupt:
        logging.info("User interrupted")
        return 1
    except Exception as e:
        logging.error("Execution exception: %s", e)
        logging.debug(traceback.format_exc())
        return 1
    return 0 if success > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
