from __future__ import annotations

import unittest
from dataclasses import dataclass

from niquests.exceptions import RequestException

from nodeseek_signin.signer import HttpSignInService


@dataclass(slots=True)
class FakeResponse:
    status_code: int
    text: str
    payload: object
    cookies: object | None = None

    def json(self) -> object:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class RespondingHttpClient:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response

    def request(self, *args: object, **kwargs: object) -> FakeResponse:
        return self._response


class FailingHttpClient:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def request(self, *args: object, **kwargs: object) -> FakeResponse:
        raise self._exc


class FakeCookieJar:
    def __init__(self, cookies: dict[str, str]) -> None:
        self._cookies = cookies

    def get_dict(self) -> dict[str, str]:
        return self._cookies


class HttpSignInServiceTest(unittest.TestCase):
    def test_classifies_success_response(self) -> None:
        result = HttpSignInService._classify_attendance_response(
            FakeResponse(200, "{}", {"success": True, "gain": 5, "current": 20})
        )

        self.assertTrue(result.success)
        self.assertEqual("http", result.method)
        self.assertIn("Today +5", result.message)

    def test_failure_message_is_always_string(self) -> None:
        result = HttpSignInService._classify_attendance_response(
            FakeResponse(200, "{}", {"success": False, "message": ["blocked"]})
        )

        self.assertFalse(result.success)
        self.assertEqual("['blocked']", result.message)

    def test_classifies_already_signed_in_500_as_success(self) -> None:
        result = HttpSignInService._classify_attendance_response(
            FakeResponse(500, "{}", {"message": "已完成签到"})
        )

        self.assertTrue(result.success)
        self.assertIn("Already signed in", result.message)

    def test_classifies_invalid_json_as_parse_failure(self) -> None:
        result = HttpSignInService._classify_attendance_response(
            FakeResponse(200, "not json", ValueError("bad json"))
        )

        self.assertFalse(result.success)
        self.assertIn("Response parse failed", result.message)

    def test_unknown_status_detects_expired_cookie_body(self) -> None:
        result = HttpSignInService._classify_attendance_response(
            FakeResponse(418, "please signin", {})
        )

        self.assertFalse(result.success)
        self.assertTrue(result.cookie_expired)

    def test_sign_in_converts_request_exception(self) -> None:
        service = HttpSignInService(
            FailingHttpClient(RequestException("offline")),
            random_mode=False,
        )

        result = service.sign_in("cookie")

        self.assertFalse(result.success)
        self.assertIn("offline", result.message)

    def test_sign_in_exposes_refreshed_cookie(self) -> None:
        response = FakeResponse(
            200,
            "{}",
            {"success": True},
            cookies=FakeCookieJar({"session": "new", "uid": "42"}),
        )
        service = HttpSignInService(RespondingHttpClient(response), random_mode=False)

        result = service.sign_in("session=old; theme=dark")

        self.assertTrue(result.success)
        self.assertEqual("session=new; theme=dark; uid=42", result.updated_cookie)

    def test_sign_in_does_not_hide_programming_errors(self) -> None:
        service = HttpSignInService(FailingHttpClient(RuntimeError("bug")), random_mode=False)

        with self.assertRaisesRegex(RuntimeError, "bug"):
            service.sign_in("cookie")


if __name__ == "__main__":
    unittest.main()
