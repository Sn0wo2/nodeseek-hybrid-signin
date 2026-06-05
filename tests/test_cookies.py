from __future__ import annotations

import unittest
from dataclasses import dataclass

from nodeseek_signin.cookies import (
    extract_response_cookies,
    join_account_cookies,
    merge_cookie_values,
)


@dataclass(slots=True)
class FakeCookieResponse:
    cookies: object | None = None


class FakeCookieJar:
    def __init__(self, cookies: dict[str, str]) -> None:
        self._cookies = cookies

    def get_dict(self) -> dict[str, str]:
        return self._cookies


class CookieHelpersTest(unittest.TestCase):
    def test_merge_cookie_values_preserves_order_and_appends_new_names(self) -> None:
        merged = merge_cookie_values(
            "session=old; theme=dark",
            {"session": "new", "uid": "42"},
        )

        self.assertEqual("session=new; theme=dark; uid=42", merged)

    def test_extract_response_cookies_reads_response_cookie_jar(self) -> None:
        cookies = extract_response_cookies(
            FakeCookieResponse(cookies=FakeCookieJar({"session": "new", "uid": "42"}))
        )

        self.assertEqual({"session": "new", "uid": "42"}, cookies)

    def test_join_account_cookies_removes_empty_entries(self) -> None:
        self.assertEqual("a=1&b=2", join_account_cookies([" a=1 ", "", " b=2 "]))


if __name__ == "__main__":
    unittest.main()
