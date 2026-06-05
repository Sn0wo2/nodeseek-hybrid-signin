from __future__ import annotations

import unittest

from nodeseek_signin.config import ConfigLoader


class ConfigLoaderTest(unittest.TestCase):
    def test_load_app_config_accepts_common_env_values(self) -> None:
        config = ConfigLoader(
            {
                "COOKIE_WRITEBACK": "yes",
                "ENABLE_STATISTICS": " no ",
                "NS_RANDOM": "1",
                "PROXY_URL": " http://127.0.0.1:8080 ",
                "TIMEOUT": " 60 ",
            }
        ).load_app_config()

        self.assertTrue(config.cookie_writeback)
        self.assertFalse(config.enable_statistics)
        self.assertTrue(config.random_mode)
        self.assertEqual("http://127.0.0.1:8080", config.proxy_url)
        self.assertEqual(60, config.timeout)

    def test_cookie_writeback_defaults_to_github_actions_only(self) -> None:
        self.assertFalse(ConfigLoader({}).load_app_config().cookie_writeback)
        self.assertTrue(
            ConfigLoader({"GITHUB_ACTIONS": "true"}).load_app_config().cookie_writeback
        )

    def test_load_app_config_rejects_invalid_timeout(self) -> None:
        with self.assertRaisesRegex(ValueError, "TIMEOUT"):
            ConfigLoader({"TIMEOUT": "soon"}).load_app_config()

        with self.assertRaisesRegex(ValueError, "TIMEOUT"):
            ConfigLoader({"TIMEOUT": "0"}).load_app_config()

    def test_load_app_config_rejects_invalid_bool(self) -> None:
        with self.assertRaisesRegex(ValueError, "NS_RANDOM"):
            ConfigLoader({"NS_RANDOM": "maybe"}).load_app_config()

    def test_load_accounts_trims_empty_cookie_segments(self) -> None:
        accounts = ConfigLoader({"NS_COOKIE": " first & & second "}).load_accounts()

        self.assertEqual(["Account1", "Account2"], [account.display_name for account in accounts])
        self.assertEqual(["first", "second"], [account.cookie for account in accounts])


if __name__ == "__main__":
    unittest.main()
