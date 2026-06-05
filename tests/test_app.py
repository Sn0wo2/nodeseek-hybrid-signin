from __future__ import annotations

import unittest

from nodeseek_signin.app import NodeSeekSignInApp
from nodeseek_signin.models import AccountConfig, SignInResult


class FakeCookieStore:
    def __init__(self, result: bool = True) -> None:
        self._result = result
        self.saved_values: list[str] = []

    def save(self, value: str) -> bool:
        self.saved_values.append(value)
        return self._result


class NodeSeekSignInAppTest(unittest.TestCase):
    def test_write_back_cookies_preserves_account_order(self) -> None:
        app = object.__new__(NodeSeekSignInApp)
        store = FakeCookieStore()
        app._cookie_store = store

        app._write_back_cookies(
            [
                (
                    AccountConfig(index=1, display_name="Account1", cookie="a=old"),
                    SignInResult(True, "ok", "http"),
                ),
                (
                    AccountConfig(index=2, display_name="Account2", cookie="b=old"),
                    SignInResult(True, "ok", "http", updated_cookie="b=new"),
                ),
            ]
        )

        self.assertEqual(["a=old&b=new"], store.saved_values)

    def test_write_back_cookies_skips_when_no_cookie_changed(self) -> None:
        app = object.__new__(NodeSeekSignInApp)
        store = FakeCookieStore()
        app._cookie_store = store

        app._write_back_cookies(
            [
                (
                    AccountConfig(index=1, display_name="Account1", cookie="a=old"),
                    SignInResult(True, "ok", "http"),
                ),
            ]
        )

        self.assertEqual([], store.saved_values)


if __name__ == "__main__":
    unittest.main()
