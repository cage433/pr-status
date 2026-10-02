import unittest

from pr_status.columns import TITLE_COL, UNRESOLVED_ALL_COL
from pr_status.completions import completion_words
from pr_status.repl_command import COMMANDS, HELP, REPORT, command_listing


class TestReplCommand(unittest.TestCase):

    def test_a_command_answers_to_its_name_and_its_short_forms(self) -> None:
        self.assertTrue(REPORT.matches("report"))
        self.assertTrue(REPORT.matches("r"))
        self.assertFalse(REPORT.matches("rep"))

    def test_no_two_commands_share_a_name(self) -> None:
        names = [n for c in COMMANDS for n in c.names]
        self.assertEqual(len(names), len(set(names)))

    def test_every_command_is_listed_with_its_short_forms(self) -> None:
        lines = command_listing()
        self.assertEqual(len(lines), len(COMMANDS))
        for cmd, line in zip(COMMANDS, lines):
            self.assertTrue(line.startswith(cmd.name), line)
            self.assertIn(cmd.description, line)
            for alias in cmd.aliases:
                self.assertIn(alias, line)


class TestCompletionWords(unittest.TestCase):

    def test_commands_aliases_and_columns_are_all_completed(self) -> None:
        words = completion_words(["mine", "to-review"])
        for name in HELP.names:
            self.assertIn(name, words)
        self.assertIn("to-review", words)
        self.assertIn(TITLE_COL.name, words)
        self.assertIn(TITLE_COL.aliases[0], words)

    def test_a_column_name_carrying_a_space_is_left_out(self) -> None:
        # rlwrap breaks its word list on whitespace, so such a name cannot be completed.
        words = completion_words([])
        self.assertNotIn(UNRESOLVED_ALL_COL.name, words)
        self.assertIn(UNRESOLVED_ALL_COL.aliases[0], words)

    def test_the_list_is_sorted_and_free_of_duplicates(self) -> None:
        words = completion_words(["report", "mine"])   # an alias shadowing a command
        self.assertEqual(words, sorted(set(words)))


if __name__ == "__main__":
    unittest.main()
