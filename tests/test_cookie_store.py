from __future__ import annotations

import subprocess
import unittest

from nodeseek_signin.cookie_store import GitHubSecretCookieStore


class FakeRunner:
    def __init__(self, result: subprocess.CompletedProcess[str] | Exception) -> None:
        self._result = result
        self.calls: list[dict[str, object]] = []

    def __call__(self, args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append({"args": args, **kwargs})
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class GitHubSecretCookieStoreTest(unittest.TestCase):
    def test_save_sets_actions_secret_with_pat(self) -> None:
        runner = FakeRunner(subprocess.CompletedProcess(["gh"], 0, "", ""))
        store = GitHubSecretCookieStore(
            enabled=True,
            environ={
                "NS_COOKIE_WRITE_TOKEN": "pat-token",
                "GITHUB_REPOSITORY": "owner/repo",
            },
            runner=runner,
        )

        self.assertTrue(store.save("session=new"))

        call = runner.calls[0]
        self.assertEqual(
            ["gh", "secret", "set", "NS_COOKIE", "--repo", "owner/repo", "--app", "actions"],
            call["args"],
        )
        self.assertEqual("session=new", call["input"])
        self.assertEqual("pat-token", call["env"]["GH_TOKEN"])
        self.assertNotIn("NS_COOKIE", call["env"])
        self.assertNotIn("NS_COOKIE_WRITE_TOKEN", call["env"])

    def test_save_accepts_gh_token_env_fallback(self) -> None:
        runner = FakeRunner(subprocess.CompletedProcess(["gh"], 0, "", ""))
        store = GitHubSecretCookieStore(
            enabled=True,
            environ={"GH_TOKEN": "pat-token", "GITHUB_REPOSITORY": "owner/repo"},
            runner=runner,
        )

        self.assertTrue(store.save("session=new"))
        self.assertEqual("pat-token", runner.calls[0]["env"]["GH_TOKEN"])

    def test_save_skips_without_pat_or_repository(self) -> None:
        runner = FakeRunner(subprocess.CompletedProcess(["gh"], 0, "", ""))
        store = GitHubSecretCookieStore(enabled=True, environ={}, runner=runner)

        with self.assertLogs(level="WARNING"):
            self.assertFalse(store.save("session=new"))
        self.assertEqual([], runner.calls)

    def test_save_returns_false_on_gh_failure(self) -> None:
        runner = FakeRunner(subprocess.CompletedProcess(["gh"], 1, "", "denied"))
        store = GitHubSecretCookieStore(
            enabled=True,
            environ={"GH_TOKEN": "pat-token", "GITHUB_REPOSITORY": "owner/repo"},
            runner=runner,
        )

        with self.assertLogs(level="WARNING"):
            self.assertFalse(store.save("session=new"))

    def test_save_returns_false_when_gh_is_missing(self) -> None:
        runner = FakeRunner(FileNotFoundError("gh"))
        store = GitHubSecretCookieStore(
            enabled=True,
            environ={"GH_TOKEN": "pat-token", "GITHUB_REPOSITORY": "owner/repo"},
            runner=runner,
        )

        with self.assertLogs(level="WARNING"):
            self.assertFalse(store.save("session=new"))


if __name__ == "__main__":
    unittest.main()
