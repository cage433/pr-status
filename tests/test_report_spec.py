import unittest

from pr_status.config import Config, GithubInfo
from pr_status.marks import Marks
from pr_status.column import Column, _ListError
from pr_status.columns import (
    PULL_REQUEST_COL, TITLE_COL, AUTHOR_COL, NUM_COMMENTS_COL,
    CREATION_DATE_COL, LAST_COMMENT_TIME_COL, UNRESOLVED_ALL_COL, WORKDAYS_COL,
    BRANCH_COL, BUILD_COL,
)
from pr_status.column_display import ColumnDisplay
from pr_status.filter_spec import ColumnFilterSpec, ComparisonFilterSpec
from pr_status.sort_item import SortItem
from pr_status.report_args import ReportArgs
from pr_status.report_spec import ReportSpec


def make_args(columns: str = "", sort: str = "", filters: list[str] | None = None) -> ReportArgs:
    return ReportArgs(include_ai=False, include_pre_mark_commits=False, include_drafts=False, sort=sort, filters=filters or [], columns=columns)


def resolve(columns: str = "", sort: str = "", filters: list[str] | None = None) -> ReportSpec:
    return ReportSpec.resolve(make_args(columns=columns, sort=sort, filters=filters))


class TestResolveColumns(unittest.TestCase):

    def test_no_columns_when_empty(self):
        spec = resolve()
        self.assertEqual(spec.cols, [])

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

    def test_branch_alias_beats_build_prefix(self):
        # 'b' is a prefix of both 'branch' and 'build', and is branch's alias, so it
        # resolves to branch; build stays reachable via its own alias or a longer prefix.
        self.assertEqual(Column.resolve("b"), BRANCH_COL)
        self.assertEqual(Column.resolve("bu"), BUILD_COL)
        self.assertEqual(Column.resolve("ci"), BUILD_COL)

    def test_estimate_resolves_from_either_alias(self):
        # The label is EST, so 'est' has to work as well as 'es'; without the alias it
        # would be an ambiguous prefix of estimate and estimate-uncertainty.
        self.assertEqual([c.name for c in resolve("es,est").cols], ["estimate", "estimate"])

    def test_estimate_prefix_still_reaches_the_longer_name(self):
        self.assertEqual([c.name for c in resolve("estimate-u").cols], ["estimate-uncertainty"])

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
        spec = resolve("cd_,a")
        self.assertEqual(spec.cols[0].column, CREATION_DATE_COL)
        self.assertTrue(spec.cols[0].use_long_name)
        self.assertEqual(spec.cols[1].column, AUTHOR_COL)
        self.assertFalse(spec.cols[1].use_long_name)

    def test_full_name_uses_long_header(self):
        spec = resolve("num-comments")
        self.assertEqual(spec.cols[0].column, NUM_COMMENTS_COL)
        self.assertTrue(spec.cols[0].use_long_name)

    def test_full_name_header_matches_alias_underscore(self):
        self.assertEqual(resolve("num-comments").cols[0].header, resolve("nc_").cols[0].header)

    def test_alias_without_underscore_uses_short_header(self):
        spec = resolve("nc")
        self.assertEqual(spec.cols[0].column, NUM_COMMENTS_COL)
        self.assertFalse(spec.cols[0].use_long_name)

    def test_prefix_match_uses_short_header(self):
        spec = resolve("num-comm")
        self.assertEqual(spec.cols[0].column, NUM_COMMENTS_COL)
        self.assertFalse(spec.cols[0].use_long_name)

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
        si = resolve(sort="author").sort_cols[0]
        self.assertEqual(si, SortItem(AUTHOR_COL))

    def test_multiple_sort_cols(self):
        spec = resolve(sort="author,creation-date")
        self.assertEqual(len(spec.sort_cols), 2)
        self.assertEqual(spec.sort_cols[0].column, AUTHOR_COL)
        self.assertEqual(spec.sort_cols[1].column, CREATION_DATE_COL)

    def test_sort_col_alias(self):
        self.assertEqual(resolve(sort="pr").sort_cols[0].column, PULL_REQUEST_COL)

    def test_sort_col_prefix(self):
        self.assertEqual(resolve(sort="auth").sort_cols[0].column, AUTHOR_COL)

    def test_sort_col_reversed(self):
        si = resolve(sort="author:R").sort_cols[0]
        self.assertEqual(si, SortItem(AUTHOR_COL, reverse=True))

    def test_sort_col_reversed_lowercase(self):
        si = resolve(sort="author:r").sort_cols[0]
        self.assertTrue(si.reverse)

    def test_sort_mixed_reversed(self):
        spec = resolve(sort="author,nc:R")
        self.assertEqual(spec.sort_cols[0], SortItem(AUTHOR_COL))
        self.assertEqual(spec.sort_cols[1], SortItem(NUM_COMMENTS_COL, reverse=True))


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

    def test_filter_me_resolves_to_this_author(self):
        spec = ReportSpec.resolve(make_args(filters=["author=@me"]), me="alice")
        fs = spec.filters[0]
        assert isinstance(fs, ColumnFilterSpec)
        self.assertEqual(fs.column, AUTHOR_COL)
        self.assertEqual(fs.values, {"alice"})

    def test_filter_me_without_this_author_raises(self):
        with self.assertRaises(_ListError):
            ReportSpec.resolve(make_args(filters=["author=@me"]), me="")


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


def make_config(**kwargs) -> Config:
    defaults = dict(
        repo=GithubInfo(owner="owner", repo_name="repo"),
        ignored_authors=set(), ignored_prs=set(), ai_authors=set(), author_names={},
        ignored_comment_patterns=[], ignored_title_patterns=[], ignored_labels=set(),
        aliases={},
    )
    defaults.update(kwargs)
    return Config(**defaults)


def pr_node(number: int, title: str = "Test PR", author: str = "alice",
            reviewers: list[str] | None = None) -> dict:
    return {"number": number, "title": title, "isDraft": False,
            "createdAt": "2024-01-01T00:00:00Z", "author": {"login": author},
            "reviewRequests": {"nodes": [{"requestedReviewer": {"login": r}}
                                         for r in (reviewers or [])]},
            "reviews": {"nodes": []},
            "timelineItems": {"nodes": [{"requestedReviewer": {"login": r}}
                                        for r in (reviewers or [])]}}


class TestPreFetchFilters(unittest.TestCase):

    def test_light_query_filter_is_pre_fetchable(self):
        spec = resolve("pr", filters=["RO=bob"])
        self.assertEqual(len(spec.pre_fetch_filters), 1)

    def test_filter_needing_per_pr_fetch_is_not(self):
        # The unresolved-thread count only exists after the per-PR comment fetch.
        spec = resolve("pr", filters=["UA=0"])
        self.assertEqual(spec.pre_fetch_filters, [])

    def test_filter_needing_youtrack_is_not(self):
        spec = resolve("pr", filters=["V=false"])
        self.assertEqual(spec.pre_fetch_filters, [])

    def test_comparison_filter_is_pre_fetchable_only_when_both_sides_are(self):
        self.assertEqual(len(resolve("pr", filters=["cd>mk"]).pre_fetch_filters), 1)
        self.assertEqual(resolve("pr", filters=["lct>mk"]).pre_fetch_filters, [])

    def test_filter_naming_no_column_is_not_pre_fetchable(self):
        # Two date literals name no column at all, so there is nothing to vouch for it.
        spec = resolve("pr", filters=["2024-01-01>2023-01-01"])
        self.assertEqual(spec.pre_fetch_filters, [])

    def test_mixed_filters_keep_only_the_light_ones(self):
        spec = resolve("pr", filters=["RO=bob", "UA=0"])
        self.assertEqual([fs.column.name for fs in spec.pre_fetch_filters], ["review-outstanding"])


class TestSearchQualifiers(unittest.TestCase):

    def qualifiers(self, filters: list[str], **config_kwargs) -> list[str]:
        return resolve("pr", filters=filters).search_qualifiers(make_config(**config_kwargs))

    def test_author_filter_becomes_an_author_qualifier(self):
        # The value could also be the login of an account the config says nothing
        # about, and repeated author: qualifiers are ORed, so both are asked for.
        self.assertEqual(self.qualifiers(["A=alex"], author_names={"cage433": "alex"}),
                         ["author:cage433", "author:alex"])

    def test_author_value_with_no_mapping_is_taken_as_a_login(self):
        self.assertEqual(self.qualifiers(["A=bob"]), ["author:bob"])

    def test_several_authors_are_asked_for_at_once(self):
        # Repeated author: qualifiers are ORed, which is what a multi-valued filter means.
        self.assertEqual(self.qualifiers(["A=alex,bob"], author_names={"cage433": "alex"}),
                         ["author:cage433", "author:alex", "author:bob"])

    def test_review_outstanding_becomes_a_review_requested_qualifier(self):
        self.assertEqual(self.qualifiers(["RO=alex"], author_names={"cage433": "alex"}),
                         ["review-requested:cage433"])

    def test_review_outstanding_value_with_no_mapping_is_taken_as_a_login(self):
        self.assertEqual(self.qualifiers(["RO=bob"]), ["review-requested:bob"])

    def test_review_outstanding_over_several_logins_is_not_pushed_down(self):
        # GitHub does not OR repeated review-requested: qualifiers, so the filter has to
        # stay client-side; the search is just wider.
        self.assertEqual(self.qualifiers(["RO=alex,bob"]), [])
        self.assertEqual(self.qualifiers(["RO=alex"], author_names={"a": "alex", "b": "alex"}), [])

    def test_negated_filter_is_not_pushed_down(self):
        self.assertEqual(self.qualifiers(["A!=alex"], author_names={"cage433": "alex"}), [])

    def test_none_is_not_pushed_down(self):
        self.assertEqual(self.qualifiers(["RO=none"]), [])

    def test_null_is_not_pushed_down(self):
        # 'null' asks for PRs the column has no value for; there is no login to ask
        # GitHub about, and author:null would come back empty.
        self.assertEqual(self.qualifiers(["A=null"]), [])
        self.assertEqual(self.qualifiers(["RO=null"]), [])
        self.assertEqual(self.qualifiers(["A=alex,null"], author_names={"cage433": "alex"}), [])

    def test_other_columns_are_not_pushed_down(self):
        self.assertEqual(self.qualifiers(["R=alex"], author_names={"cage433": "alex"}), [])
        self.assertEqual(self.qualifiers(["V=false"]), [])

    def test_qualifiers_from_several_filters_are_combined(self):
        self.assertEqual(self.qualifiers(["A=bob", "RO=carol"]),
                         ["author:bob", "review-requested:carol"])


class TestNarrowPrNodes(unittest.TestCase):

    def setUp(self):
        self.config = make_config()
        self.marks  = Marks("/nonexistent/path/marks.csv")
        self.nodes  = [pr_node(1, reviewers=["bob"]), pr_node(2, reviewers=["carol"])]

    def narrow(self, filters: list[str]) -> list[int]:
        args = make_args(columns="pr", filters=filters)
        spec = ReportSpec.resolve(args)
        return [n["number"] for n in spec.narrow_pr_nodes(self.config, self.marks, args, self.nodes)]

    def test_keeps_only_the_prs_a_light_filter_matches(self):
        self.assertEqual(self.narrow(["RO=bob"]), [1])

    def test_keeps_nothing_when_no_pr_matches(self):
        self.assertEqual(self.narrow(["RO=dave"]), [])

    def test_keeps_everything_with_no_filters(self):
        self.assertEqual(self.narrow([]), [1, 2])

    def test_keeps_everything_when_no_filter_is_pre_fetchable(self):
        # UA needs the per-PR comment fetch, so nothing can be decided yet.
        self.assertEqual(self.narrow(["UA=1"]), [1, 2])

    def test_a_non_pre_fetchable_filter_does_not_narrow_alongside_a_light_one(self):
        self.assertEqual(self.narrow(["RO=bob,carol", "UA=1"]), [1, 2])


if __name__ == "__main__":
    unittest.main()
