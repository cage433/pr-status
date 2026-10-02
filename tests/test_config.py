import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr

from pr_status.config import Config, credential_key


def write(path: str, text: str) -> None:
    with open(path, "w") as f:
        f.write(text)


class TestCredentialKey(unittest.TestCase):

    def test_a_credential_line_is_named(self) -> None:
        self.assertEqual(credential_key("youtrack-token:abc"), "youtrack-token")

    def test_a_credential_this_parser_never_reads_still_counts(self) -> None:
        self.assertEqual(credential_key("teamcity-token:abc"), "teamcity-token")
        self.assertEqual(credential_key("timely-refresh-token:abc"), "timely-refresh-token")

    def test_a_commented_out_credential_still_counts(self) -> None:
        self.assertEqual(credential_key("#timely-secret:abc"), "timely-secret")

    def test_an_ordinary_setting_is_not_one(self) -> None:
        self.assertEqual(credential_key("owner:topaztechnology"), "")
        self.assertEqual(credential_key("youtrack-url:https://example.com"), "")


class TestKeysFile(unittest.TestCase):

    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.config = os.path.join(self.dir.name, "config")
        self.keys   = os.path.join(self.dir.name, "keys")

    def load(self) -> tuple[Config, str]:
        err = io.StringIO()
        with redirect_stderr(err):
            config = Config.load(self.config)
        return config, err.getvalue()

    def test_the_keys_file_sits_beside_the_config(self) -> None:
        self.assertEqual(Config.keys_file_for(self.config), self.keys)

    def test_a_token_is_read_from_the_keys_file(self) -> None:
        write(self.config, "owner:acme\nrepo-name:widgets\n")
        write(self.keys, "youtrack-token:secret-token\ntimely-account-id:12345\n")
        config, err = self.load()
        self.assertEqual(config.youtrack_token, "secret-token")
        self.assertEqual(config.timely_account_id, "12345")
        self.assertEqual(config.repo.owner, "acme")
        self.assertEqual(err, "")

    def test_the_keys_file_wins_over_the_config(self) -> None:
        write(self.config, "youtrack-token:stale\n")
        write(self.keys, "youtrack-token:current\n")
        config, _ = self.load()
        self.assertEqual(config.youtrack_token, "current")

    def test_no_keys_file_is_not_an_error(self) -> None:
        write(self.config, "owner:acme\n")
        config, err = self.load()
        self.assertEqual(config.repo.owner, "acme")
        self.assertEqual(config.youtrack_token, "")
        self.assertEqual(err, "")

    def test_a_credential_left_in_the_config_is_warned_about(self) -> None:
        write(self.config, "owner:acme\nteamcity-token:abc\n#timely-secret:def\n")
        _, err = self.load()
        self.assertIn("holds credentials", err)
        self.assertIn("teamcity-token", err)
        self.assertIn("timely-secret", err)
        self.assertIn(self.keys, err)

    def test_a_keys_symlink_whose_target_is_gone_warns_rather_than_failing(self) -> None:
        write(self.config, "owner:acme\n")
        os.symlink(os.path.join(self.dir.name, "not-mounted", "keys"), self.keys)
        config, err = self.load()
        self.assertIn("broken symlink", err)
        self.assertEqual(config.repo.owner, "acme")
        self.assertEqual(config.youtrack_token, "")


if __name__ == "__main__":
    unittest.main()
