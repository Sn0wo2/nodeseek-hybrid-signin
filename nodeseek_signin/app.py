from __future__ import annotations

import logging

from niquests.exceptions import RequestException

from nodeseek_signin.config import AppConfig, ConfigLoader
from nodeseek_signin.cookie_store import GitHubSecretCookieStore
from nodeseek_signin.cookies import join_account_cookies
from nodeseek_signin.http_client import NodeSeekHttpClient
from nodeseek_signin.models import AccountConfig, SignInResult
from nodeseek_signin.signer import HttpSignInService
from nodeseek_signin.stats import CreditStatsFetcher


class NodeSeekSignInApp:
    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self._config_loader = config_loader or ConfigLoader()
        self._config = self._config_loader.load_app_config()
        self._http_client = NodeSeekHttpClient(
            proxy_url=self._config.proxy_url,
            timeout=self._config.timeout,
        )
        self._signer = HttpSignInService(
            self._http_client,
            random_mode=self._config.random_mode,
        )
        self._stats_fetcher = CreditStatsFetcher(
            self._http_client,
            enabled=self._config.enable_statistics,
        )
        self._cookie_store = GitHubSecretCookieStore(
            enabled=self._config.cookie_writeback,
        )

        logging.info("Statistics: %s", "enabled" if self._config.enable_statistics else "disabled")
        logging.info(
            "Cookie write-back: %s",
            "enabled" if self._config.cookie_writeback else "disabled",
        )

    @property
    def config(self) -> AppConfig:
        return self._config

    def run(self) -> int:
        logging.info("NodeSeek HTTP signer starting")
        logging.info("=" * 50)

        accounts = self._config_loader.load_accounts()
        if not accounts:
            logging.error("No account configuration found")
            return 0

        logging.info("Found %d account(s)", len(accounts))
        results = self._process_accounts(accounts)
        self._write_back_cookies(results)
        expired = [account.display_name for account, result in results if result.cookie_expired]
        if expired:
            logging.warning("%d expired cookie(s): %s", len(expired), ", ".join(expired))

        success_count = sum(1 for _, result in results if result.success)
        logging.info("Cookie check complete")
        logging.info("=" * 50)
        logging.info("Done: %d/%d succeeded", success_count, len(results))
        logging.info("HTTP signer finished")
        return success_count

    def _process_accounts(
        self,
        accounts: list[AccountConfig],
    ) -> list[tuple[AccountConfig, SignInResult]]:
        results: list[tuple[AccountConfig, SignInResult]] = []
        for account in accounts:
            result = self._process_account(account)
            results.append((account, result))
            if result.success:
                continue

            logging.error("%s: %s", account.display_name, result.message)
            if result.cookie_expired:
                logging.warning("Cookie expired detected: %s", account.display_name)

        return results

    def _process_account(self, account: AccountConfig) -> SignInResult:
        logging.info("=" * 30 + " %s " + "=" * 30, account.display_name)
        result = self._sign_in(account)
        return self._annotate_with_stats(result, result.updated_cookie or account.cookie)

    def _sign_in(self, account: AccountConfig) -> SignInResult:
        logging.info("Starting sign-in: %s", account.display_name)
        if not account.cookie:
            return SignInResult(False, "No cookie", "none")

        result = self._signer.sign_in(account.cookie)
        if result.success:
            logging.info("HTTP success: %s", result.message)
        else:
            logging.warning("HTTP failed: %s", result.message)
        return result

    def _annotate_with_stats(self, result: SignInResult, cookie: str) -> SignInResult:
        if not result.success or not self._config.enable_statistics:
            return result

        try:
            stats = self._stats_fetcher.fetch(cookie)
        except RequestException as exc:
            logging.warning("Statistics query failed: %s", exc)
            return result

        if stats is None:
            return result

        result.statistics = stats.to_payload()
        result.message += f" | {stats.days_count}-day stats: avg {stats.average} drumsticks/day"
        return result

    def _write_back_cookies(self, results: list[tuple[AccountConfig, SignInResult]]) -> None:
        if not any(result.updated_cookie for _, result in results):
            return

        updated_cookies = [
            result.updated_cookie or account.cookie
            for account, result in results
        ]
        if self._cookie_store.save(join_account_cookies(updated_cookies)):
            logging.info("NS_COOKIE secret write-back complete")
        else:
            logging.warning("NS_COOKIE changed but secret write-back did not complete")
