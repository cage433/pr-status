import unittest

from pr_status.report_args import ReportArgs
from pr_status.report_spec import (
    ColSpec, Comparison, PlainColumn, ReportSpec, _ListError,
    col_header, col_width,
)


def make_args(columns: str = "", sort: str = "", filters: list[str] | None = None) -> ReportArgs:
    return ReportArgs(include_ai=False, include_pre_mark_commits=False, include_drafts=False, sort=sort, filters=filters or [], columns=columns)


def resolve(columns: str = "", sort: str = "", filters: list[str] | None = None) -> ReportSpec:
    return ReportSpec.resolve(make_args(columns=columns, sort=sort, filters=filters))


class TestResolveColumns(unittest.TestCase):

    def test_default_columns_when_empty(self):
        spec = resolve()
        self.assertEqual(spec.cols, [PlainColumn("pull-request"), PlainColumn("title"), PlainColumn("author")])

    def test_explicit_columns(self):
        spec = resolve("title,author")
        self.assertEqual(spec.cols, [PlainColumn("title"), PlainColumn("author")])

    def test_column_alias(self):
        spec = resolve("pr,nc,lct,mct,cd,mk,c")
        self.assertEqual(spec.cols, [
            PlainColumn("pull-request"), PlainColumn("num-comments"),
            PlainColumn("last-comment-time"), PlainColumn("my-last-comment-time"),
            PlainColumn("creation-date"), PlainColumn("mark"), PlainColumn("comment"),
        ])

    def test_column_prefix_match(self):
        spec = resolve("tit,auth,loc")
        self.assertEqual(spec.cols, [PlainColumn("title"), PlainColumn("author"), PlainColumn("loc")])

    def test_column_name_case_insensitive(self):
        spec = resolve("TITLE,Author")
        self.assertEqual(spec.cols, [PlainColumn("title"), PlainColumn("author")])

    def test_trailing_underscore_sets_long_name(self):
        spec = resolve("nc_")
        self.assertEqual(spec.cols, [PlainColumn("num-comments", long_name=True)])

    def test_trailing_underscore_works_with_alias(self):
        spec = resolve("cd_,author")
        self.assertEqual(spec.cols, [PlainColumn("creation-date", long_name=True), PlainColumn("author")])

    def test_unknown_column_raises(self):
        with self.assertRaises(_ListError):
            resolve("nonexistent")

    def test_ambiguous_column_raises(self):
        # "m" matches both "mark" and "my-last-comment-time"
        with self.assertRaises(_ListError):
            resolve("m")

    def test_comparison_column(self):
        spec = resolve("lct>cd")
        self.assertEqual(spec.cols, [Comparison("last-comment-time", ">", "creation-date")])

    def test_all_comparison_operators(self):
        for op in (">", "<", ">=", "<=", "=="):
            spec = resolve("lct%scd" % op)
            self.assertEqual(spec.cols, [Comparison("last-comment-time", op, "creation-date")])

    def test_comparison_with_date_literal(self):
        spec = resolve("lct>2024-01-15")
        self.assertEqual(spec.cols, [Comparison("last-comment-time", ">", "2024-01-15T00:00:00Z")])

    def test_comparison_with_non_timestamp_col_raises(self):
        with self.assertRaises(_ListError):
            resolve("title>lct")

    def test_whitespace_around_columns_ignored(self):
        spec = resolve(" title , author ")
        self.assertEqual(spec.cols, [PlainColumn("title"), PlainColumn("author")])


class TestResolveSort(unittest.TestCase):

    def test_no_sort(self):
        spec = resolve()
        self.assertEqual(spec.sort_cols, [])

    def test_single_sort_col(self):
        spec = resolve(sort="author")
        self.assertEqual(spec.sort_cols, [("author", False)])

    def test_multiple_sort_cols(self):
        spec = resolve(sort="author,creation-date")
        self.assertEqual(spec.sort_cols, [("author", False), ("creation-date", False)])

    def test_sort_col_alias(self):
        spec = resolve(sort="pr")
        self.assertEqual(spec.sort_cols, [("pull-request", False)])

    def test_sort_col_prefix(self):
        spec = resolve(sort="auth")
        self.assertEqual(spec.sort_cols, [("author", False)])

    def test_sort_col_reversed(self):
        spec = resolve(sort="author:R")
        self.assertEqual(spec.sort_cols, [("author", True)])

    def test_sort_col_reversed_lowercase(self):
        spec = resolve(sort="author:r")
        self.assertEqual(spec.sort_cols, [("author", True)])

    def test_sort_mixed_reversed(self):
        spec = resolve(sort="author,nc:R")
        self.assertEqual(spec.sort_cols, [("author", False), ("num-comments", True)])


class TestResolveFilters(unittest.TestCase):

    def test_filter_col_equals_val(self):
        spec = resolve(filters=["author=alice"])
        self.assertEqual(len(spec.filters), 1)
        col, vals, neg = spec.filters[0]
        self.assertEqual(col, PlainColumn("author"))
        self.assertEqual(vals, {"alice"})
        self.assertFalse(neg)

    def test_filter_multiple_values(self):
        spec = resolve(filters=["author=alice,bob"])
        _, vals, _ = spec.filters[0]
        self.assertEqual(vals, {"alice", "bob"})

    def test_filter_multiple_filters(self):
        spec = resolve(filters=["author=alice", "title=foo"])
        self.assertEqual(len(spec.filters), 2)

    def test_filter_comparison_shorthand(self):
        # a bare comparison in --filter implicitly filters for "true"
        spec = resolve(filters=["lct>cd"])
        self.assertEqual(len(spec.filters), 1)
        col, vals, neg = spec.filters[0]
        self.assertEqual(col, Comparison("last-comment-time", ">", "creation-date"))
        self.assertEqual(vals, {"true"})
        self.assertFalse(neg)

    def test_filter_plain_col_without_equals_raises(self):
        with self.assertRaises(_ListError):
            resolve(filters=["author"])

    def test_filter_col_alias(self):
        spec = resolve(filters=["pr=42"])
        col, _, _ = spec.filters[0]
        self.assertEqual(col, PlainColumn("pull-request"))

    def test_empty_filter_string_ignored(self):
        spec = resolve(filters=[""])
        self.assertEqual(spec.filters, [])

    def test_filter_not_equal(self):
        spec = resolve(filters=["author!=alice"])
        col, vals, neg = spec.filters[0]
        self.assertEqual(col, PlainColumn("author"))
        self.assertEqual(vals, {"alice"})
        self.assertTrue(neg)

    def test_filter_not_equal_multiple_values(self):
        spec = resolve(filters=["author!=alice,bob"])
        _, vals, neg = spec.filters[0]
        self.assertEqual(vals, {"alice", "bob"})
        self.assertTrue(neg)


class TestResolveAllCols(unittest.TestCase):

    def test_plain_cols_included(self):
        spec = resolve("title,author")
        self.assertIn("title", spec.all_cols)
        self.assertIn("author", spec.all_cols)

    def test_sort_cols_included(self):
        spec = resolve("title", sort="author")
        self.assertIn("author", spec.all_cols)

    def test_timestamp_cols_from_comparison_included(self):
        spec = resolve("lct>cd")
        self.assertIn("last-comment-time", spec.all_cols)
        self.assertIn("creation-date", spec.all_cols)

    def test_non_timestamp_sides_of_comparison_not_in_all_cols(self):
        # date literals are not column names so should not appear in all_cols
        spec = resolve("lct>2024-01-01")
        self.assertIn("last-comment-time", spec.all_cols)
        self.assertNotIn("2024-01-01T00:00:00Z", spec.all_cols)

    def test_filter_cols_included(self):
        spec = resolve(filters=["author=alice"])
        self.assertIn("author", spec.all_cols)


class TestColHeader(unittest.TestCase):

    def test_plain_column_headers(self):
        cases = {
            "pull-request": "PR", "title": "TITLE", "author": "AUTHOR",
            "loc": "LOC", "num-comments": "NC", "creation-date": "CREATED",
            "last-comment-time": "LAST COMMENT", "my-last-comment-time": "MY LAST COMMENT",
            "mark": "MARK", "comment": "COMMENT",
        }
        for col, expected in cases.items():
            self.assertEqual(col_header(PlainColumn(col)), expected)

    def test_long_name_header_is_column_name_uppercased(self):
        self.assertEqual(col_header(PlainColumn("num-comments", long_name=True)), "NUM-COMMENTS")
        self.assertEqual(col_header(PlainColumn("creation-date", long_name=True)), "CREATION-DATE")
        self.assertEqual(col_header(PlainColumn("unresolved (all)", long_name=True)), "UNRESOLVED (ALL)")

    def test_comparison_header_uses_abbrevs(self):
        c = Comparison("last-comment-time", ">", "creation-date")
        self.assertEqual(col_header(c), "LCT>CD")

    def test_comparison_header_with_date_literal(self):
        c = Comparison("last-comment-time", ">", "2024-01-15T00:00:00Z")
        self.assertEqual(col_header(c), "LCT>2024-01-15")

    def test_comparison_header_unknown_side_truncated(self):
        # a date literal longer than 10 chars uses first 10 chars as abbreviation
        c = Comparison("mark", ">=", "2024-06-01T00:00:00Z")
        self.assertEqual(col_header(c), "MK>=2024-06-01")


class TestColWidth(unittest.TestCase):

    def test_plain_column_widths(self):
        self.assertEqual(col_width(PlainColumn("title")), 60)
        self.assertEqual(col_width(PlainColumn("author")), 15)
        self.assertEqual(col_width(PlainColumn("num-comments")), 4)

    def test_long_name_width_at_least_header_length(self):
        col = PlainColumn("num-comments", long_name=True)
        self.assertGreaterEqual(col_width(col), len("NUM-COMMENTS"))

    def test_long_name_width_not_less_than_data_width(self):
        col = PlainColumn("creation-date", long_name=True)
        self.assertGreaterEqual(col_width(col), col_width(PlainColumn("creation-date")))

    def test_comparison_width_at_least_5(self):
        # "false" is 5 chars — width must accommodate it
        c = Comparison("mark", ">", "creation-date")
        self.assertGreaterEqual(col_width(c), 5)

    def test_comparison_width_matches_header_length(self):
        c = Comparison("last-comment-time", ">", "creation-date")
        self.assertEqual(col_width(c), len(col_header(c)))


if __name__ == "__main__":
    unittest.main()
