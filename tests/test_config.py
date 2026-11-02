import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr

from pr_status.config import Config, GithubInfo, broken_symlink, credential_key


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


class TestBrokenSymlink(unittest.TestCase):

    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def path(self, name: str) -> str:
        return os.path.join(self.dir.name, name)

    def test_a_link_to_an_absent_file_is_broken(self) -> None:
        os.symlink(self.path("not-mounted"), self.path("link"))
        self.assertTrue(broken_symlink(self.path("link")))

    def test_a_link_to_a_file_that_is_there_is_not(self) -> None:
        write(self.path("target"), "owner:acme\n")
        os.symlink(self.path("target"), self.path("link"))
        self.assertFalse(broken_symlink(self.path("link")))

    def test_a_path_that_was_never_created_is_not(self) -> None:
        # Absent and unmounted call for opposite remedies, so they must not look alike.
        self.assertFalse(broken_symlink(self.path("nothing-here")))


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


class TestExpandAlias(unittest.TestCase):

    def setUp(self) -> None:
        self.config = Config(
            repo=GithubInfo(owner="owner", repo_name="repo"), ignored_authors=set(),
            ignored_prs=set(), ai_authors=set(), author_names={}, ignored_comment_patterns=[],
            ignored_title_patterns=[], ignored_labels=set(),
            aliases={"to-review": "report P,T,A --filter RO=@me", "bare": "report"},
        )

    def test_an_alias_is_replaced_by_its_command(self) -> None:
        self.assertEqual(self.config.expand_alias("to-review", ""),
                         ("report", "P,T,A --filter RO=@me"))

    def test_the_rest_of_the_line_is_appended(self) -> None:
        self.assertEqual(self.config.expand_alias("to-review", "--filter A=bob"),
                         ("report", "P,T,A --filter RO=@me --filter A=bob"))

    def test_columns_after_a_comma_are_added_to_the_aliases_own(self) -> None:
        self.assertEqual(self.config.expand_alias("to-review,V,LOC_", "--sort A"),
                         ("report", "P,T,A --filter RO=@me V,LOC_ --sort A"))

    def test_an_alias_with_no_argument_takes_the_added_columns_alone(self) -> None:
        self.assertEqual(self.config.expand_alias("bare,V", ""), ("report", "V"))

    def test_a_trailing_comma_adds_nothing(self) -> None:
        self.assertEqual(self.config.expand_alias("to-review,", ""),
                         ("report", "P,T,A --filter RO=@me"))

    def test_the_alias_name_is_matched_whatever_its_case(self) -> None:
        self.assertEqual(self.config.expand_alias("To-Review,V", "")[0], "report")

    def test_a_word_that_is_no_alias_is_left_as_it_is(self) -> None:
        self.assertEqual(self.config.expand_alias("Report", "P,T"), ("report", "P,T"))
        self.assertEqual(self.config.expand_alias("nonesuch,V", ""), ("nonesuch,v", ""))


if __name__ == "__main__":
    unittest.main()
