import unittest

from pr_status.columns import (
    ALL_COLUMNS, ESTIMATE_COL, TITLE_COL, YOUTRACK_STATE_COL, column_listing,
)


def line_for(name: str) -> str:
    return next(l for l in column_listing() if l.split()[0] == name)


class TestColumnListing(unittest.TestCase):

    def test_every_column_is_listed_with_its_name_label_and_aliases(self) -> None:
        lines = column_listing()
        self.assertEqual(len(lines), len(ALL_COLUMNS))
        for col, line in zip(ALL_COLUMNS, lines):
            self.assertTrue(line.startswith(col.name), line)
            self.assertIn(col.label, line)
            for alias in col.aliases:
                self.assertIn(alias, line)

    def test_a_column_with_two_aliases_shows_both(self) -> None:
        self.assertIn("es, est", line_for(ESTIMATE_COL.name))

    def test_a_youtrack_column_says_so(self) -> None:
        self.assertIn("youtrack", line_for(YOUTRACK_STATE_COL.name).split("  ")[-1])

    def test_a_plain_column_carries_no_notes(self) -> None:
        self.assertEqual(line_for(TITLE_COL.name).split(), ["title", "t", "TITLE"])


if __name__ == "__main__":
    unittest.main()
