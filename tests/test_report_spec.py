import unittest

from pr_status.column import (
    Column, ColumnDisplay,
    PULL_REQUEST_COL, TITLE_COL, AUTHOR_COL, NUM_COMMENTS_COL,
    CREATION_DATE_COL, LAST_COMMENT_TIME_COL, UNRESOLVED_ALL_COL, WORKDAYS_COL,
)
from pr_status.report_args import ReportArgs
from pr_status.report_spec import (
    ColumnFilterSpec, ComparisonFilterSpec, ReportSpec, _ListError,
)


def make_args(columns: str = "", sort: str = "", filters: list[str] | None = None) -> ReportArgs:
    return ReportArgs(include_ai=False, include_pre_mark_commits=False, include_drafts=False, sort=sort, filters=filters or [], columns=columns)


def resolve(columns: str = "", sort: str = "", filters: list[str] | None = None) -> ReportSpec:
    return ReportSpec.resolve(make_args(columns=columns, sort=sort, filters=filters))


class TestResolveColumns(unittest.TestCase):

    def test_default_columns_when_empty(self):
        spec = resolve()
        self.assertEqual([c.name for c in spec.cols], ["pull-request", "title", "author"])

    def test_explicit_columns(self):
        spec = resolve("title,author")
        self.assertEqual([c.name for c in spec.cols], ["title", "author"])

    def test_column_alias(self):
        spec = resolve("pr,nc,lct,mct,cd,mk,c")
        self.assertEqual([c.name for c in spec.cols], [
            "pull-request", "num-comments",
            "last-comment-time", "my-last-comment-time",
            "creation-date", "mark", "comment",
        ])

    def test_alias_takes_priority_over_prefix(self):
        # 'a' is a prefix of both 'author' and 'age', but resolves unambiguously via alias
        spec = resolve("a")
        self.assertEqual([c.name for c in spec.cols], ["author"])

    def test_column_prefix_match(self):
        spec = resolve("tit,auth,loc")
        self.assertEqual([c.name for c in spec.cols], ["title", "author", "loc"])

    def test_column_name_case_insensitive(self):
        spec = resolve("TITLE,Author")
        self.assertEqual([c.name for c in spec.cols], ["title", "author"])

    def test_trailing_underscore_sets_use_long_name(self):
        spec = resolve("nc_")
        self.assertEqual(spec.cols[0].column, NUM_COMMENTS_COL)
        self.assertTrue(spec.cols[0].use_long_name)

    def test_trailing_underscore_works_with_alias(self):
        spec = resolve("cd_,author")
        self.assertEqual(spec.cols[0].column, CREATION_DATE_COL)
        self.assertTrue(spec.cols[0].use_long_name)
        self.assertFalse(spec.cols[1].use_long_name)

    def test_cols_are_column_display(self):
        spec = resolve("title,author")
        for cd in spec.cols:
            self.assertIsInstance(cd, ColumnDisplay)

    def test_unknown_column_raises(self):
        with self.assertRaises(_ListError):
            resolve("nonexistent")

    def test_ambiguous_column_raises(self):
        # "m" matches both "mark" and "my-last-comment-time"
        with self.assertRaises(_ListError):
            resolve("m")

    def test_comparison_in_column_position_raises(self):
        with self.assertRaises(_ListError):
            resolve("lct>cd")

    def test_comparison_with_non_timestamp_col_raises(self):
        with self.assertRaises(_ListError):
            resolve(filters=["title>lct"])

    def test_whitespace_around_columns_ignored(self):
        spec = resolve(" title , author ")
        self.assertEqual([c.name for c in spec.cols], ["title", "author"])


class TestResolveSort(unittest.TestCase):

    def test_no_sort(self):
        spec = resolve()
        self.assertEqual(spec.sort_cols, [])

    def test_single_sort_col(self):
        col, rev = resolve(sort="author").sort_cols[0]
        self.assertEqual(col, AUTHOR_COL)
        self.assertFalse(rev)

    def test_multiple_sort_cols(self):
        spec = resolve(sort="author,creation-date")
        self.assertEqual(len(spec.sort_cols), 2)
        self.assertEqual(spec.sort_cols[0][0], AUTHOR_COL)
        self.assertEqual(spec.sort_cols[1][0], CREATION_DATE_COL)

    def test_sort_col_alias(self):
        self.assertEqual(resolve(sort="pr").sort_cols[0][0], PULL_REQUEST_COL)

    def test_sort_col_prefix(self):
        self.assertEqual(resolve(sort="auth").sort_cols[0][0], AUTHOR_COL)

    def test_sort_col_reversed(self):
        col, rev = resolve(sort="author:R").sort_cols[0]
        self.assertEqual(col, AUTHOR_COL)
        self.assertTrue(rev)

    def test_sort_col_reversed_lowercase(self):
        _, rev = resolve(sort="author:r").sort_cols[0]
        self.assertTrue(rev)

    def test_sort_mixed_reversed(self):
        spec = resolve(sort="author,nc:R")
        self.assertEqual(spec.sort_cols[0], (AUTHOR_COL, False))
        self.assertEqual(spec.sort_cols[1], (NUM_COMMENTS_COL, True))


class TestResolveFilters(unittest.TestCase):

    def test_filter_col_equals_val(self):
        spec = resolve(filters=["author=alice"])
        self.assertEqual(len(spec.filters), 1)
        fs = spec.filters[0]
        self.assertIsInstance(fs, ColumnFilterSpec)
        assert isinstance(fs, ColumnFilterSpec)
        self.assertEqual(fs.column, AUTHOR_COL)
        self.assertEqual(fs.values, {"alice"})
        self.assertFalse(fs.negate)

    def test_filter_multiple_values(self):
        spec = resolve(filters=["author=alice,bob"])
        fs = spec.filters[0]
        assert isinstance(fs, ColumnFilterSpec)
        self.assertEqual(fs.values, {"alice", "bob"})

    def test_filter_multiple_filters(self):
        spec = resolve(filters=["author=alice", "title=foo"])
        self.assertEqual(len(spec.filters), 2)

    def test_filter_comparison_shorthand(self):
        spec = resolve(filters=["lct>cd"])
        self.assertEqual(len(spec.filters), 1)
        fs = spec.filters[0]
        self.assertIsInstance(fs, ComparisonFilterSpec)
        assert isinstance(fs, ComparisonFilterSpec)
        self.assertEqual(fs.left, "last-comment-time")
        self.assertEqual(fs.op, ">")
        self.assertEqual(fs.right, "creation-date")

    def test_filter_plain_col_without_equals_raises(self):
        with self.assertRaises(_ListError):
            resolve(filters=["author"])

    def test_filter_col_alias(self):
        spec = resolve(filters=["pr=42"])
        fs = spec.filters[0]
        assert isinstance(fs, ColumnFilterSpec)
        self.assertEqual(fs.column, PULL_REQUEST_COL)

    def test_empty_filter_string_ignored(self):
        spec = resolve(filters=[""])
        self.assertEqual(spec.filters, [])

    def test_filter_not_equal(self):
        spec = resolve(filters=["author!=alice"])
        fs = spec.filters[0]
        assert isinstance(fs, ColumnFilterSpec)
        self.assertEqual(fs.column, AUTHOR_COL)
        self.assertEqual(fs.values, {"alice"})
        self.assertTrue(fs.negate)

    def test_filter_not_equal_multiple_values(self):
        spec = resolve(filters=["author!=alice,bob"])
        fs = spec.filters[0]
        assert isinstance(fs, ColumnFilterSpec)
        self.assertEqual(fs.values, {"alice", "bob"})
        self.assertTrue(fs.negate)


class TestResolveAllCols(unittest.TestCase):

    def test_plain_cols_included(self):
        spec = resolve("title,author")
        self.assertIn(TITLE_COL, spec.all_cols)
        self.assertIn(AUTHOR_COL, spec.all_cols)

    def test_sort_cols_included(self):
        spec = resolve("title", sort="author")
        self.assertIn(AUTHOR_COL, spec.all_cols)

    def test_timestamp_cols_from_comparison_filter_included(self):
        spec = resolve(filters=["lct>cd"])
        self.assertIn(LAST_COMMENT_TIME_COL, spec.all_cols)
        self.assertIn(CREATION_DATE_COL, spec.all_cols)

    def test_non_timestamp_sides_of_comparison_not_in_all_cols(self):
        spec = resolve(filters=["lct>2024-01-01"])
        self.assertIn(LAST_COMMENT_TIME_COL, spec.all_cols)
        self.assertEqual(len([c for c in spec.all_cols if not isinstance(c, Column)]), 0)

    def test_filter_cols_included(self):
        spec = resolve(filters=["author=alice"])
        self.assertIn(AUTHOR_COL, spec.all_cols)


class TestColFromName(unittest.TestCase):

    def test_known_name_returns_column(self):
        self.assertEqual(Column.col_from_name("workdays"), WORKDAYS_COL)
        self.assertEqual(Column.col_from_name("author"), AUTHOR_COL)

    def test_unknown_name_returns_none(self):
        self.assertIsNone(Column.col_from_name("nonexistent"))


class TestColFromAlias(unittest.TestCase):

    def test_known_alias_returns_column(self):
        self.assertEqual(Column.col_from_alias("pr"), PULL_REQUEST_COL)
        self.assertEqual(Column.col_from_alias("nc"), NUM_COMMENTS_COL)

    def test_unknown_alias_returns_none(self):
        self.assertIsNone(Column.col_from_alias("xyz"))


class TestColHeader(unittest.TestCase):

    def test_plain_column_headers(self):
        cases = {
            "pull-request": "PR", "title": "TITLE", "author": "AUTHOR",
            "loc": "LOC", "num-comments": "NC", "creation-date": "CREATED",
            "last-comment-time": "LAST COMMENT", "my-last-comment-time": "MY LAST COMMENT",
            "mark": "MARK", "comment": "COMMENT",
        }
        for col_name, expected in cases.items():
            self.assertEqual(ColumnDisplay(Column.col_from_name(col_name)).header, expected)

    def test_long_name_header_is_column_name_uppercased(self):
        self.assertEqual(ColumnDisplay(NUM_COMMENTS_COL,   use_long_name=True).header, "NUM-COMMENTS")
        self.assertEqual(ColumnDisplay(CREATION_DATE_COL,  use_long_name=True).header, "CREATION-DATE")
        self.assertEqual(ColumnDisplay(UNRESOLVED_ALL_COL, use_long_name=True).header, "UNRESOLVED (ALL)")


class TestColWidth(unittest.TestCase):

    def test_plain_column_widths(self):
        self.assertEqual(ColumnDisplay(TITLE_COL).display_width,        60)
        self.assertEqual(ColumnDisplay(AUTHOR_COL).display_width,       15)
        self.assertEqual(ColumnDisplay(NUM_COMMENTS_COL).display_width,  4)

    def test_long_name_width_at_least_header_length(self):
        cd = ColumnDisplay(NUM_COMMENTS_COL, use_long_name=True)
        self.assertGreaterEqual(cd.display_width, len("NUM-COMMENTS"))

    def test_long_name_width_not_less_than_data_width(self):
        self.assertGreaterEqual(
            ColumnDisplay(CREATION_DATE_COL, use_long_name=True).display_width,
            ColumnDisplay(CREATION_DATE_COL).display_width,
        )


if __name__ == "__main__":
    unittest.main()
