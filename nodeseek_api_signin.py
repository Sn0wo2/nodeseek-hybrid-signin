#!/usr/bin/env python3
# NodeSeek HTTP signin with optional statistics fetch.

import json
import logging
import os
import random
import sys
import time
import traceback
from dataclasses import dataclass
from typing import List, Optional, Tuple

from curl_cffi import requests as cf_requests
from curl_cffi.requests import Session as CfSession

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)

# Pinned TLS fingerprint for curl_cffi.
# When CF blocks it, bump to the newest Firefox entry curl_cffi ships.
FIREFOX_IMPERSONATE = "firefox147"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) "
    "Gecko/20100101 Firefox/147.0"
)


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
    proxy_url: str
    random_mode: bool
    timeout: int


def get_env_config() -> AppConfig:
    env_type = "github" if os.environ.get("GITHUB_ACTIONS") == "true" else "local"
    timeout = int(os.environ.get("TIMEOUT", "30"))

    if env_type == "github":
        timeout = min(timeout, 120)

    return AppConfig(
        environment=env_type,
        enable_statistics=os.environ.get("ENABLE_STATISTICS", "true").lower() == "true",
        proxy_url=os.environ.get("PROXY_URL", ""),
        random_mode=os.environ.get("NS_RANDOM", "true").lower() == "true",
        timeout=timeout,
    )




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
            response = self.session.request(
                "POST", url, headers=self.get_headers(cookie),
                timeout=self.config.timeout, json={},
                impersonate=FIREFOX_IMPERSONATE,
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


class NodeSeekAPISigner:
    def __init__(self):
        self.config = get_env_config()
        self.http_signer = HTTPSigner(self.config)

        logging.info("Environment: %s", self.config.environment)
        logging.info("Statistics: %s", "enabled" if self.config.enable_statistics else "disabled")

    @staticmethod
    def _parse_cookies() -> List[str]:
        raw = os.environ.get("NS_COOKIE", "")
        if not raw:
            return []
        return [c.strip() for c in raw.split("&") if c.strip()]

    def load_accounts(self) -> List[AccountConfig]:
        cookies = self._parse_cookies()
        return [
            AccountConfig(index=i, display_name=f"Account{i}", cookie=c)
            for i, c in enumerate(cookies, start=1)
        ]

    def _fetch_stats(self, cookie: str, days: int = 30) -> Optional[SigninStats]:
        if not cookie or not self.config.enable_statistics:
            return None
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Cookie": cookie,
        }

        session = self.http_signer._build_session()
        all_records: list = []
        page = 1
        while page <= 10:
            url = f"https://www.nodeseek.com/api/account/credit/page-{page}"
            response = session.request(
                "GET", url, headers=headers, timeout=10,
                impersonate=FIREFOX_IMPERSONATE,
            )

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

    def progressive_signin(self, account: AccountConfig) -> SigninResult:
        logging.info("Starting signin: %s", account.display_name)
        if not account.cookie:
            return SigninResult(False, "No cookie", "none")
        result = self.http_signer.signin(account.cookie)
        if result.success:
            logging.info("HTTP success: %s", result.message)
        else:
            logging.warning("HTTP failed: %s", result.message)
        return result

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
        logging.info("=" * 30 + " %s " + "=" * 30, account.display_name)
        result = self.progressive_signin(account)
        result = self._annotate_with_stats(result, account.cookie)
        return account, result

    def run(self) -> int:
        logging.info("NodeSeek HTTP signer starting")
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
            if not result.success:
                logging.error("%s: %s", acc.display_name, result.message)
                if result.cookie_expired:
                    expired.append(acc.display_name)
                    logging.warning("Cookie expired detected: %s", acc.display_name)

        if expired:
            logging.warning("%d expired cookie(s): %s", len(expired), ", ".join(expired))

        logging.info("Cookie check complete")
        success_count = sum(1 for _, r in results if r.success)
        logging.info("=" * 50)
        logging.info("Done: %d/%d succeeded", success_count, len(results))
        logging.info("HTTP signer finished")
        return success_count


def main() -> int:
    try:
        success = NodeSeekAPISigner().run()
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
