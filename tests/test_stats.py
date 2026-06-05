from __future__ import annotations

import unittest
from dataclasses import dataclass
from unittest.mock import patch

from nodeseek_signin.stats import CreditStatsFetcher


@dataclass(slots=True)
class FakeResponse:
    payload: object
    status_code: int = 200
    text: str = ""

    def json(self) -> object:
        return self.payload


class FakeSession:
    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        page = int(url.rsplit("page-", maxsplit=1)[1])
        return FakeResponse({"success": True, "data": [[page, "", "签到收益"]]})


class FakeHttpClient:
    def open_session(self) -> FakeSession:
        return FakeSession()


class CreditStatsFetcherTest(unittest.TestCase):
    def test_extract_sign_in_amounts_skips_invalid_records(self) -> None:
        fetcher = CreditStatsFetcher(FakeHttpClient(), enabled=True)

        amounts = fetcher._extract_sign_in_amounts(
            [
                [1, "", "签到收益"],
                [True, "", "签到收益"],
                ["2.5", "", "签到收益"],
                [3, "", "other"],
                ["bad", "", "签到收益"],
            ],
            days=2,
        )

        self.assertEqual([1.0, 2.5], amounts)

    def test_fetch_credit_records_does_not_sleep_after_last_page(self) -> None:
        fetcher = CreditStatsFetcher(FakeHttpClient(), enabled=True)
        fetcher.MAX_PAGES = 2

        with patch("nodeseek_signin.stats.time.sleep") as sleep:
            records = fetcher._fetch_credit_records("cookie")

        self.assertEqual([[1, "", "签到收益"], [2, "", "签到收益"]], records)
        sleep.assert_called_once_with(fetcher.REQUEST_DELAY_SECONDS)


if __name__ == "__main__":
    unittest.main()
