import unittest

from pr_status.config import Config, GithubInfo
from pr_status.github_data import GithubComment, GithubData, GithubPR
from pr_status.loc import LOC
from pr_status.marks import Marks
from pr_status.pr_number import PRNumber
from pr_status.report import _report_data_lines
from pr_status.report_args import ReportArgs
from pr_status.report_spec import ReportSpec


def make_config(**kwargs) -> Config:
    defaults = dict(
        repo=GithubInfo(owner="owner", repo_name="repo"),
        ignored_authors=set(),
        ignored_prs=set(),
        ai_authors=set(),
        author_names={},
        ignored_comment_patterns=[],
        ignored_title_patterns=[],
        aliases={},
    )
    defaults.update(kwargs)
    return Config(**defaults)


def make_args(columns: str = "", sort: str = "", filters: list[str] | None = None, include_pre_mark_commits: bool = False) -> ReportArgs:
    return ReportArgs(include_ai=False, include_pre_mark_commits=include_pre_mark_commits, include_drafts=False, sort=sort, filters=filters or [], columns=columns)


def make_marks(data: dict[PRNumber, str] | None = None) -> Marks:
    marks = Marks("/nonexistent/path/marks.csv")
    if data:
        marks._data = data
    return marks


def make_spec(columns: str = "", sort: str = "", filters: list[str] | None = None) -> ReportSpec:
    return ReportSpec.resolve(make_args(columns=columns, sort=sort, filters=filters))


def make_pr(
    number: int,
    title: str = "Test PR",
    author: str = "alice",
    created_at: str = "2024-01-01T00:00:00Z",
    is_draft: bool = False,
    reviewers: list[str] | None = None,
    reviewer_states: dict[str, str] | None = None,
) -> GithubPR:
    return GithubPR(
        number=PRNumber(number), title=title, isDraft=is_draft,
        createdAt=created_at, author=author, reviewers=reviewers or [],
        reviewer_states=reviewer_states or {},
    )


def make_comment(
    body: str,
    author: str = "alice",
    timestamp: str = "2024-01-15T10:00:00Z",
    kind: str = "comment",
) -> GithubComment:
    return GithubComment(timestamp=timestamp, author=author, kind=kind, body=body)


def make_data(
    prs: list[GithubPR] | None = None,
    loc_results: dict[PRNumber, LOC] | None = None,
    rows_marked: dict[PRNumber, list[GithubComment]] | None = None,
    rows_all: dict[PRNumber, list[GithubComment]] | None = None,
    unresolved_counts: dict[PRNumber, tuple[int, int, int]] | None = None,
    last_activity: dict[PRNumber, str] | None = None,
) -> GithubData:
    prs = prs or []
    pr_nums = [pr.number for pr in prs]
    return GithubData(
        all_prs=prs,
        loc_results=loc_results or {},
        rows_marked=rows_marked if rows_marked is not None else {n: [] for n in pr_nums},
        rows_all=rows_all if rows_all is not None else {n: [] for n in pr_nums},
        unresolved_counts=unresolved_counts or {},
        last_activity=last_activity or {},
    )


def run(
    columns: str = "",
    sort: str = "",
    filters: list[str] | None = None,
    config: Config | None = None,
    marks: Marks | None = None,
    data: GithubData | None = None,
    include_pre_mark_commits: bool = False,
) -> list[list[str]]:
    args = make_args(columns=columns, sort=sort, filters=filters, include_pre_mark_commits=include_pre_mark_commits)
    spec = ReportSpec.resolve(args)
    return _report_data_lines(
        config or make_config(),
        marks or make_marks(),
        args,
        spec,
        data or make_data(),
    )


class TestBasicColumns(unittest.TestCase):

    def test_pull_request_format(self):
        data = make_data(prs=[make_pr(42)])
        rows = run("pr", data=data)
        self.assertEqual(rows[0][0], "#42   ")

    def test_title_truncated_to_58(self):
        long_title = "x" * 80
        data = make_data(prs=[make_pr(1, title=long_title)])
        rows = run("title", data=data)
        self.assertEqual(rows[0][0], "x" * 58)

    def test_author_column(self):
        data = make_data(prs=[make_pr(1, author="bob")])
        rows = run("author", data=data)
        self.assertEqual(rows[0][0], "bob")

    def test_author_name_mapping(self):
        config = make_config(author_names={"alice": "Alice Smith"})
        data = make_data(prs=[make_pr(1, author="alice")])
        rows = run("author", config=config, data=data)
        self.assertEqual(rows[0][0], "Alice Smith")

    def test_loc_with_values(self):
        pr = make_pr(1)
        data = make_data(prs=[pr], loc_results={PRNumber(1): LOC((100, 50))})
        rows = run("loc", data=data)
        self.assertEqual(rows[0][0], "+100/-50")

    def test_loc_without_values(self):
        data = make_data(prs=[make_pr(1)])
        rows = run("loc", data=data)
        self.assertEqual(rows[0][0], "-")

    def test_num_comments(self):
        pr = make_pr(1)
        rows_marked = {PRNumber(1): [make_comment("c1"), make_comment("c2")]}
        data = make_data(prs=[pr], rows_marked=rows_marked, rows_all={PRNumber(1): []})
        rows = run("nc", data=data)
        self.assertEqual(rows[0][0], "2")

    def test_num_comments_zero(self):
        data = make_data(prs=[make_pr(1)])
        rows = run("nc", data=data)
        self.assertEqual(rows[0][0], "0")

    def test_creation_date(self):
        pr = make_pr(1, created_at="2024-03-15T08:30:00Z")
        data = make_data(prs=[pr])
        rows = run("cd", data=data)
        self.assertEqual(rows[0][0], "2024-03-15")

    def test_last_comment_time(self):
        pr = make_pr(1)
        rows_all = {PRNumber(1): [make_comment("hi", timestamp="2024-06-01T12:00:00Z")]}
        data = make_data(prs=[pr], rows_all=rows_all)
        rows = run("lct", data=data)
        self.assertEqual(rows[0][0], "2024-06-01")

    def test_last_comment_time_empty_when_no_comments(self):
        data = make_data(prs=[make_pr(1)])
        rows = run("lct", data=data)
        self.assertEqual(rows[0][0], "n/a")

    def test_last_comment_time_uses_max_timestamp(self):
        pr = make_pr(1)
        rows_all = {PRNumber(1): [
            make_comment("earlier", timestamp="2024-06-01T08:00:00Z"),
            make_comment("later",   timestamp="2024-06-15T12:00:00Z"),
        ]}
        data = make_data(prs=[pr], rows_all=rows_all)
        rows = run("lct", data=data)
        self.assertEqual(rows[0][0], "2024-06-15")

    def test_my_last_comment_time_filters_to_gh_user(self):
        config = make_config(repo=GithubInfo(owner="o", repo_name="r", gh_user="myuser"))
        pr = make_pr(1)
        rows_all = {PRNumber(1): [
            make_comment("other",  author="alice",  timestamp="2024-06-10T12:00:00Z"),
            make_comment("mine",   author="myuser", timestamp="2024-06-01T08:00:00Z"),
        ]}
        data = make_data(prs=[pr], rows_all=rows_all)
        rows = run("mct", config=config, data=data)
        self.assertEqual(rows[0][0], "2024-06-01")

    def test_my_last_comment_time_blank_when_no_user_comments(self):
        config = make_config(repo=GithubInfo(owner="o", repo_name="r", gh_user="myuser"))
        pr = make_pr(1)
        rows_all = {PRNumber(1): [make_comment("other", author="alice", timestamp="2024-06-10T12:00:00Z")]}
        data = make_data(prs=[pr], rows_all=rows_all)
        rows = run("mct", config=config, data=data)
        self.assertEqual(rows[0][0], "")

    def test_mark_column(self):
        pr = make_pr(1)
        marks = make_marks({PRNumber(1): "2024-05-10T09:00:00Z"})
        data = make_data(prs=[pr])
        rows = run("mk", marks=marks, data=data)
        self.assertEqual(rows[0][0], "2024-05-10")

    def test_mark_column_blank_when_no_mark(self):
        data = make_data(prs=[make_pr(1)])
        rows = run("mk", data=data)
        self.assertEqual(rows[0][0], "")

    def test_reviewers_column_with_reviewers(self):
        pr = make_pr(1, reviewers=["bob", "carol"])
        data = make_data(prs=[pr])
        rows = run("reviewers", data=data)
        self.assertEqual(rows[0][0], "bob, carol")

    def test_reviewers_column_empty_when_no_reviewers(self):
        data = make_data(prs=[make_pr(1)])
        rows = run("reviewers", data=data)
        self.assertEqual(rows[0][0], "")

    def test_reviewers_column_applies_author_name_mapping(self):
        config = make_config(author_names={"bob": "Bob Smith"})
        pr = make_pr(1, reviewers=["bob"])
        data = make_data(prs=[pr])
        rows = run("reviewers", config=config, data=data)
        self.assertEqual(rows[0][0], "Bob Smith")

    def test_unresolved_all_column(self):
        data = make_data(prs=[make_pr(1)], unresolved_counts={PRNumber(1): (3, 2, 1)})
        rows = run("uc", data=data)
        self.assertEqual(rows[0][0], "3")

    def test_unresolved_human_column(self):
        data = make_data(prs=[make_pr(1)], unresolved_counts={PRNumber(1): (3, 2, 1)})
        rows = run("uh", data=data)
        self.assertEqual(rows[0][0], "2")

    def test_unresolved_ai_column(self):
        data = make_data(prs=[make_pr(1)], unresolved_counts={PRNumber(1): (3, 2, 1)})
        rows = run("ua", data=data)
        self.assertEqual(rows[0][0], "1")

    def test_unresolved_column_blank_when_zero(self):
        data = make_data(prs=[make_pr(1)], unresolved_counts={PRNumber(1): (0, 0, 0)})
        rows = run("uc", data=data)
        self.assertEqual(rows[0][0], "")

    def test_unresolved_column_blank_when_no_data(self):
        data = make_data(prs=[make_pr(1)])
        rows = run("uc", data=data)
        self.assertEqual(rows[0][0], "")

    def test_age_column(self):
        import datetime
        created = (datetime.date.today() - datetime.timedelta(days=10)).isoformat() + "T00:00:00Z"
        data = make_data(prs=[make_pr(1, created_at=created)])
        rows = run("ag", data=data)
        self.assertEqual(rows[0][0], "10")

    def test_last_activity_shows_days_since_timestamp(self):
        import datetime
        ts = (datetime.date.today() - datetime.timedelta(days=5)).isoformat() + "T12:00:00Z"
        data = make_data(prs=[make_pr(1)], last_activity={PRNumber(1): ts})
        rows = run("la", data=data)
        self.assertEqual(rows[0][0], "5")

    def test_last_activity_blank_when_no_activity(self):
        data = make_data(prs=[make_pr(1)])
        rows = run("la", data=data)
        self.assertEqual(rows[0][0], "")

    def test_last_activity_zero_when_today(self):
        import datetime
        ts = datetime.date.today().isoformat() + "T08:00:00Z"
        data = make_data(prs=[make_pr(1)], last_activity={PRNumber(1): ts})
        rows = run("la", data=data)
        self.assertEqual(rows[0][0], "0")


class TestComparisonColumn(unittest.TestCase):

    def test_comparison_true_when_lct_after_cd(self):
        pr = make_pr(1, created_at="2024-01-01T00:00:00Z")
        rows_all = {PRNumber(1): [make_comment("hi", timestamp="2024-06-01T12:00:00Z")]}
        data = make_data(prs=[pr], rows_all=rows_all)
        rows = run("lct>cd", data=data)
        self.assertEqual(rows[0][0], "true")

    def test_comparison_false_when_lct_before_cd(self):
        pr = make_pr(1, created_at="2024-06-01T00:00:00Z")
        rows_all = {PRNumber(1): [make_comment("hi", timestamp="2024-01-01T12:00:00Z")]}
        data = make_data(prs=[pr], rows_all=rows_all)
        rows = run("lct>cd", data=data)
        self.assertEqual(rows[0][0], "false")

    def test_comparison_with_date_literal(self):
        pr = make_pr(1, created_at="2024-06-01T00:00:00Z")
        data = make_data(prs=[pr])
        rows = run("cd>2024-01-01", data=data)
        self.assertEqual(rows[0][0], "true")

    def test_comparison_all_operators(self):
        pr = make_pr(1, created_at="2024-06-01T00:00:00Z")
        data = make_data(prs=[pr])
        cases = [
            ("cd>2024-01-01",  "true"),
            ("cd<2024-01-01",  "false"),
            ("cd>=2024-06-01", "true"),
            ("cd<=2024-06-01", "true"),
            ("cd==2024-06-01", "true"),
        ]
        for columns, expected in cases:
            with self.subTest(columns=columns):
                rows = run(columns, data=data)
                self.assertEqual(rows[0][0], expected)


class TestFiltering(unittest.TestCase):

    def test_filter_by_author(self):
        data = make_data(prs=[make_pr(1, author="alice"), make_pr(2, author="bob")])
        rows = run("pr", filters=["author=alice"], data=data)
        self.assertEqual(len(rows), 1)
        self.assertIn("1", rows[0][0])

    def test_filter_yields_empty_when_no_match(self):
        data = make_data(prs=[make_pr(1, author="alice")])
        rows = run("pr", filters=["author=bob"], data=data)
        self.assertEqual(rows, [])

    def test_filter_by_comparison_column(self):
        pr1 = make_pr(1, created_at="2024-06-01T00:00:00Z")
        pr2 = make_pr(2, created_at="2024-01-01T00:00:00Z")
        data = make_data(prs=[pr1, pr2])
        rows = run("pr", filters=["cd>2024-03-01"], data=data)
        self.assertEqual(len(rows), 1)
        self.assertIn("1", rows[0][0])

    def test_filter_by_pr_number(self):
        data = make_data(prs=[make_pr(10), make_pr(20)])
        rows = run("pr", filters=["pr=10"], data=data)
        self.assertEqual(len(rows), 1)
        self.assertIn("10", rows[0][0])

    def test_filter_not_equal_excludes_matching_rows(self):
        data = make_data(prs=[make_pr(1, author="alice"), make_pr(2, author="bob")])
        rows = run("pr,author", filters=["author!=alice"], data=data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "bob")

    def test_filter_not_equal_multiple_values(self):
        data = make_data(prs=[make_pr(1, author="alice"), make_pr(2, author="bob"), make_pr(3, author="carol")])
        rows = run("author", filters=["author!=alice,bob"], data=data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "carol")

    def test_filter_reviewers_matches_when_user_is_one_of_several(self):
        pr = make_pr(1, reviewers=["bob", "carol"])
        data = make_data(prs=[pr])
        rows = run("pr", filters=["reviewers=bob"], data=data)
        self.assertEqual(len(rows), 1)

    def test_filter_reviewers_no_match_when_user_absent(self):
        pr = make_pr(1, reviewers=["bob", "carol"])
        data = make_data(prs=[pr])
        rows = run("pr", filters=["reviewers=alice"], data=data)
        self.assertEqual(rows, [])

    def test_filter_reviewers_not_equal_excludes_when_user_present(self):
        pr1 = make_pr(1, reviewers=["bob"])
        pr2 = make_pr(2, reviewers=["carol"])
        data = make_data(prs=[pr1, pr2])
        rows = run("pr", filters=["reviewers!=bob"], data=data)
        self.assertEqual(len(rows), 1)
        self.assertIn("2", rows[0][0])

    def test_filter_reviewers_respects_author_name_mapping(self):
        config = make_config(author_names={"boblogin": "Bob"})
        pr = make_pr(1, reviewers=["boblogin", "carol"])
        data = make_data(prs=[pr])
        rows = run("pr", filters=["reviewers=Bob"], config=config, data=data)
        self.assertEqual(len(rows), 1)

    def test_filter_reviewers_none_matches_pr_with_no_reviewers(self):
        pr1 = make_pr(1, reviewers=[])
        pr2 = make_pr(2, reviewers=["bob"])
        data = make_data(prs=[pr1, pr2])
        rows = run("pr", filters=["reviewers=none"], data=data)
        self.assertEqual(len(rows), 1)
        self.assertIn("1", rows[0][0])

    def test_filter_reviewers_not_none_excludes_pr_with_no_reviewers(self):
        pr1 = make_pr(1, reviewers=[])
        pr2 = make_pr(2, reviewers=["bob"])
        data = make_data(prs=[pr1, pr2])
        rows = run("pr", filters=["reviewers!=none"], data=data)
        self.assertEqual(len(rows), 1)
        self.assertIn("2", rows[0][0])

    def test_comment_time_filter_applied_per_comment(self):
        config = make_config(repo=GithubInfo(owner="o", repo_name="r", gh_user="myuser"))
        pr = make_pr(1)
        comments = [
            make_comment("old",   author="alice",  timestamp="2024-06-01T08:00:00Z"),
            make_comment("new",   author="bob",    timestamp="2024-06-15T10:00:00Z"),
        ]
        rows_all = {PRNumber(1): [
            make_comment("my comment", author="myuser", timestamp="2024-06-10T00:00:00Z"),
        ]}
        rows_marked = {PRNumber(1): comments}
        data = make_data(prs=[pr], rows_marked=rows_marked, rows_all=rows_all)
        # CT>MCT: keep only comments newer than myuser's last comment (2024-06-10)
        rows = run("ct,ca,c,mct", filters=["CT>MCT"], config=config, data=data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "new")


class TestSorting(unittest.TestCase):

    def test_sort_by_author(self):
        data = make_data(prs=[make_pr(1, author="zara"), make_pr(2, author="alice")])
        rows = run("pr,author", sort="author", data=data)
        self.assertEqual(rows[0][1], "alice")
        self.assertEqual(rows[1][1], "zara")

    def test_sort_by_creation_date(self):
        pr1 = make_pr(1, created_at="2024-06-01T00:00:00Z")
        pr2 = make_pr(2, created_at="2024-01-01T00:00:00Z")
        data = make_data(prs=[pr1, pr2])
        rows = run("pr,cd", sort="cd", data=data)
        self.assertIn("2", rows[0][0])  # PR 2 has earlier date
        self.assertIn("1", rows[1][0])

    def test_sort_by_num_comments_ascending(self):
        pr1 = make_pr(1)
        pr2 = make_pr(2)
        rows_marked = {
            PRNumber(1): [make_comment("c1")],
            PRNumber(2): [make_comment("c1"), make_comment("c2"), make_comment("c3")],
        }
        data = make_data(prs=[pr1, pr2], rows_marked=rows_marked, rows_all={PRNumber(1): [], PRNumber(2): []})
        rows = run("pr,nc", sort="nc", data=data)
        self.assertEqual(rows[0][1], "1")
        self.assertEqual(rows[1][1], "3")

    def test_sort_by_num_comments_descending_with_r(self):
        pr1 = make_pr(1)
        pr2 = make_pr(2)
        rows_marked = {
            PRNumber(1): [make_comment("c1")],
            PRNumber(2): [make_comment("c1"), make_comment("c2"), make_comment("c3")],
        }
        data = make_data(prs=[pr1, pr2], rows_marked=rows_marked, rows_all={PRNumber(1): [], PRNumber(2): []})
        rows = run("pr,nc", sort="nc:R", data=data)
        self.assertEqual(rows[0][1], "3")
        self.assertEqual(rows[1][1], "1")

    def test_sort_by_loc_ascending(self):
        pr1 = make_pr(1)
        pr2 = make_pr(2)
        data = make_data(
            prs=[pr1, pr2],
            loc_results={PRNumber(1): LOC((10, 5)), PRNumber(2): LOC((1000, 500))},
        )
        rows = run("pr,loc", sort="loc", data=data)
        self.assertIn("1", rows[0][0])
        self.assertIn("2", rows[1][0])

    def test_sort_by_loc_descending_with_r(self):
        pr1 = make_pr(1)
        pr2 = make_pr(2)
        data = make_data(
            prs=[pr1, pr2],
            loc_results={PRNumber(1): LOC((10, 5)), PRNumber(2): LOC((1000, 500))},
        )
        rows = run("pr,loc", sort="loc:R", data=data)
        self.assertIn("2", rows[0][0])
        self.assertIn("1", rows[1][0])

    def test_sort_reversal_case_insensitive(self):
        data = make_data(prs=[make_pr(1, author="zara"), make_pr(2, author="alice")])
        rows = run("pr,author", sort="author:r", data=data)
        self.assertEqual(rows[0][1], "zara")
        self.assertEqual(rows[1][1], "alice")

    def test_sort_blanks_first_for_timestamps(self):
        pr1 = make_pr(1, created_at="2024-06-01T00:00:00Z")
        pr2 = make_pr(2, created_at="")
        data = make_data(prs=[pr1, pr2])
        rows = run("pr,cd", sort="cd", data=data)
        self.assertIn("2", rows[0][0])  # blank sorts first
        self.assertIn("1", rows[1][0])

    def test_sort_blanks_last_when_reversed(self):
        pr1 = make_pr(1, created_at="2024-06-01T00:00:00Z")
        pr2 = make_pr(2, created_at="")
        data = make_data(prs=[pr1, pr2])
        rows = run("pr,cd", sort="cd:R", data=data)
        self.assertIn("1", rows[0][0])  # real date sorts first when reversed
        self.assertIn("2", rows[1][0])

    def test_sort_last_activity_blank_first(self):
        import datetime
        ts = (datetime.date.today() - datetime.timedelta(days=5)).isoformat() + "T12:00:00Z"
        data = make_data(
            prs=[make_pr(1), make_pr(2)],
            last_activity={PRNumber(2): ts},
        )
        rows = run("pr,la", sort="la", data=data)
        self.assertIn("1", rows[0][0])  # blank sorts first
        self.assertIn("2", rows[1][0])

    def test_sort_by_draft_non_drafts_first(self):
        data = make_data(prs=[make_pr(1, is_draft=True), make_pr(2, is_draft=False)])
        rows = run("pr,d", sort="d", data=data)
        self.assertIn("2", rows[0][0])  # non-draft sorts first
        self.assertIn("1", rows[1][0])

    def test_sort_by_draft_reversed_drafts_first(self):
        data = make_data(prs=[make_pr(1, is_draft=False), make_pr(2, is_draft=True)])
        rows = run("pr,d", sort="d:R", data=data)
        self.assertIn("2", rows[0][0])  # draft sorts first when reversed
        self.assertIn("1", rows[1][0])


class TestCommentColumn(unittest.TestCase):

    def test_comment_column_expands_one_row_per_marked_comment(self):
        pr = make_pr(1)
        comments = [make_comment("first"), make_comment("second")]
        rows_marked = {PRNumber(1): comments}
        data = make_data(prs=[pr], rows_marked=rows_marked, rows_all={PRNumber(1): []})
        rows = run("pr,c", data=data)
        self.assertEqual(len(rows), 2)

    def test_comment_column_empty_when_no_marked_comments(self):
        data = make_data(prs=[make_pr(1)])
        rows = run("pr,c", data=data)
        self.assertEqual(rows, [])

    def test_comment_cell_shows_body_only(self):
        pr = make_pr(1)
        comments = [make_comment("this is the body", author="bob")]
        rows_marked = {PRNumber(1): comments}
        data = make_data(prs=[pr], rows_marked=rows_marked, rows_all={PRNumber(1): []})
        rows = run("pr,c", data=data)
        self.assertEqual(rows[0][1], "this is the body")

    def test_comment_author_cell(self):
        pr = make_pr(1)
        comments = [make_comment("body", author="bob")]
        rows_marked = {PRNumber(1): comments}
        data = make_data(prs=[pr], rows_marked=rows_marked, rows_all={PRNumber(1): []})
        rows = run("pr,ca", data=data)
        self.assertEqual(rows[0][1], "bob")

    def test_comment_author_uses_author_name_mapping(self):
        config = make_config(author_names={"bob": "Robert"})
        pr = make_pr(1)
        comments = [make_comment("body", author="bob")]
        rows_marked = {PRNumber(1): comments}
        data = make_data(prs=[pr], rows_marked=rows_marked, rows_all={PRNumber(1): []})
        rows = run("pr,ca", config=config, data=data)
        self.assertEqual(rows[0][1], "Robert")

    def test_comment_time_cell(self):
        pr = make_pr(1)
        comments = [make_comment("body", timestamp="2024-06-15T10:30:00Z")]
        rows_marked = {PRNumber(1): comments}
        data = make_data(prs=[pr], rows_marked=rows_marked, rows_all={PRNumber(1): []})
        rows = run("pr,ct", data=data)
        self.assertEqual(rows[0][1], "2024-06-15 10:30")

    def test_comment_columns_trigger_expansion_without_c(self):
        pr = make_pr(1)
        comments = [make_comment("c1"), make_comment("c2")]
        rows_marked = {PRNumber(1): comments}
        data = make_data(prs=[pr], rows_marked=rows_marked, rows_all={PRNumber(1): []})
        rows = run("pr,ct,ca", data=data)
        self.assertEqual(len(rows), 2)

    def test_non_comment_cols_repeated_per_comment_row(self):
        pr = make_pr(1, title="My PR")
        comments = [make_comment("c1"), make_comment("c2")]
        rows_marked = {PRNumber(1): comments}
        data = make_data(prs=[pr], rows_marked=rows_marked, rows_all={PRNumber(1): []})
        rows = run("title,c", data=data)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "My PR")
        self.assertEqual(rows[1][0], "My PR")


class TestIncludePreMarkCommits(unittest.TestCase):

    def test_marked_pr_always_included_in_report(self):
        pr = make_pr(1)
        marks = make_marks({PRNumber(1): "2024-06-01T00:00:00Z"})
        data = make_data(prs=[pr], rows_marked={PRNumber(1): []}, rows_all={PRNumber(1): []})
        rows = run("pr", marks=marks, data=data)
        self.assertEqual(len(rows), 1)

    def test_default_comment_column_uses_only_post_mark_comments(self):
        pr = make_pr(1)
        marks = make_marks({PRNumber(1): "2024-06-10T00:00:00Z"})
        old_comment = make_comment("old", timestamp="2024-06-01T00:00:00Z")
        new_comment = make_comment("new", timestamp="2024-06-15T00:00:00Z")
        rows_marked = {PRNumber(1): [new_comment]}
        rows_all = {PRNumber(1): [old_comment, new_comment]}
        data = make_data(prs=[pr], rows_marked=rows_marked, rows_all=rows_all)
        rows = run("pr,c", marks=marks, data=data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "new")

    def test_include_pre_mark_commits_uses_rows_all_for_comment_columns(self):
        pr = make_pr(1)
        marks = make_marks({PRNumber(1): "2024-06-10T00:00:00Z"})
        old_comment = make_comment("old", timestamp="2024-06-01T00:00:00Z")
        new_comment = make_comment("new", timestamp="2024-06-15T00:00:00Z")
        rows_marked = {PRNumber(1): [new_comment]}
        rows_all = {PRNumber(1): [old_comment, new_comment]}
        data = make_data(prs=[pr], rows_marked=rows_marked, rows_all=rows_all)
        rows = run("pr,c", marks=marks, data=data, include_pre_mark_commits=True)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][1], "old")
        self.assertEqual(rows[1][1], "new")


class TestShowTime(unittest.TestCase):

    def test_show_time_when_two_timestamp_cols_share_date(self):
        pr = make_pr(1, created_at="2024-06-01T00:00:00Z")
        rows_all = {PRNumber(1): [make_comment("hi", timestamp="2024-06-01T12:30:00Z")]}
        data = make_data(prs=[pr], rows_all=rows_all)
        rows = run("cd,lct", data=data)
        # both cols share date 2024-06-01 so time portion shown for both
        self.assertIn("00:00", rows[0][0])
        self.assertIn("12:30", rows[0][1])

    def test_no_show_time_when_dates_differ(self):
        pr = make_pr(1, created_at="2024-06-01T00:00:00Z")
        rows_all = {PRNumber(1): [make_comment("hi", timestamp="2024-07-15T12:30:00Z")]}
        data = make_data(prs=[pr], rows_all=rows_all)
        rows = run("cd,lct", data=data)
        self.assertNotIn("00:00", rows[0][0])
        self.assertNotIn("12:30", rows[0][1])


class TestMultiplePRs(unittest.TestCase):

    def test_one_row_per_pr(self):
        data = make_data(prs=[make_pr(1), make_pr(2), make_pr(3)])
        rows = run("pr", data=data)
        self.assertEqual(len(rows), 3)

    def test_empty_prs_yields_no_rows(self):
        rows = run("pr")
        self.assertEqual(rows, [])

    def test_multiple_columns_per_row(self):
        data = make_data(prs=[make_pr(1, title="Hello", author="alice")])
        rows = run("pr,title,author", data=data)
        self.assertEqual(len(rows[0]), 3)


class TestYTColumn(unittest.TestCase):

    def test_yt_extracts_uppercase_ticket_id(self):
        data = make_data(prs=[make_pr(1, title="PROJ-123 fix something")])
        rows = run("yt", data=data)
        self.assertEqual(rows[0][0], "PROJ-123")

    def test_yt_extracts_lowercase_ticket_id(self):
        data = make_data(prs=[make_pr(1, title="proj-42 fix something")])
        rows = run("yt", data=data)
        self.assertEqual(rows[0][0], "proj-42")

    def test_yt_extracts_mixed_case_ticket_id(self):
        data = make_data(prs=[make_pr(1, title="MyProj-7 do a thing")])
        rows = run("yt", data=data)
        self.assertEqual(rows[0][0], "MyProj-7")

    def test_yt_extracts_alphanumeric_project_name(self):
        data = make_data(prs=[make_pr(1, title="proj2b-99 stuff")])
        rows = run("yt", data=data)
        self.assertEqual(rows[0][0], "proj2b-99")

    def test_yt_extracts_project_name_with_internal_dashes(self):
        data = make_data(prs=[make_pr(1, title="MY-PROJECT-456 description")])
        rows = run("yt", data=data)
        self.assertEqual(rows[0][0], "MY-PROJECT-456")

    def test_yt_missing_when_no_ticket_id(self):
        data = make_data(prs=[make_pr(1, title="fix something without ticket")])
        rows = run("yt", data=data)
        self.assertEqual(rows[0][0], "MISSING")

    def test_yt_missing_when_ticket_not_at_start(self):
        data = make_data(prs=[make_pr(1, title="[WIP] PROJ-123 description")])
        rows = run("yt", data=data)
        self.assertEqual(rows[0][0], "MISSING")

    def test_yt_missing_when_no_digits_after_dash(self):
        data = make_data(prs=[make_pr(1, title="PROJ- something")])
        rows = run("yt", data=data)
        self.assertEqual(rows[0][0], "MISSING")

    def test_yt_sort_alphabetical(self):
        data = make_data(prs=[
            make_pr(1, title="ZZZ-10 last"),
            make_pr(2, title="AAA-1 first"),
        ])
        rows = run("pr,yt", sort="yt", data=data)
        self.assertIn("2", rows[0][0])
        self.assertIn("1", rows[1][0])

    def test_yt_sort_missing_last(self):
        data = make_data(prs=[
            make_pr(1, title="no ticket here"),
            make_pr(2, title="AAA-1 has ticket"),
        ])
        rows = run("pr,yt", sort="yt", data=data)
        self.assertIn("2", rows[0][0])
        self.assertIn("1", rows[1][0])

    def test_yt_filter_by_missing(self):
        data = make_data(prs=[
            make_pr(1, title="PROJ-1 has ticket"),
            make_pr(2, title="no ticket"),
        ])
        rows = run("pr,yt", filters=["yt=MISSING"], data=data)
        self.assertEqual(len(rows), 1)
        self.assertIn("2", rows[0][0])

    def test_yt_filter_by_ticket_id(self):
        data = make_data(prs=[
            make_pr(1, title="PROJ-1 a"),
            make_pr(2, title="OTHER-2 b"),
        ])
        rows = run("pr,yt", filters=["yt=PROJ-1"], data=data)
        self.assertEqual(len(rows), 1)
        self.assertIn("1", rows[0][0])

    def test_yt_full_ticket_from_dashed_project(self):
        data = make_data(prs=[make_pr(1, title="MY-PROJECT-456 description")])
        rows = run("yt", data=data)
        self.assertEqual(rows[0][0], "MY-PROJECT-456")


class TestYPColumn(unittest.TestCase):

    def test_yp_extracts_simple_project_name(self):
        data = make_data(prs=[make_pr(1, title="PROJ-123 fix something")])
        rows = run("yp", data=data)
        self.assertEqual(rows[0][0], "PROJ")

    def test_yp_extracts_dashed_project_name(self):
        data = make_data(prs=[make_pr(1, title="MY-PROJECT-456 description")])
        rows = run("yp", data=data)
        self.assertEqual(rows[0][0], "MY-PROJECT")

    def test_yp_missing_when_no_ticket_id(self):
        data = make_data(prs=[make_pr(1, title="no ticket here")])
        rows = run("yp", data=data)
        self.assertEqual(rows[0][0], "MISSING")

    def test_yp_missing_when_ticket_not_at_start(self):
        data = make_data(prs=[make_pr(1, title="[WIP] PROJ-123")])
        rows = run("yp", data=data)
        self.assertEqual(rows[0][0], "MISSING")

    def test_yp_sort_alphabetical(self):
        data = make_data(prs=[
            make_pr(1, title="ZZZ-1 last"),
            make_pr(2, title="AAA-2 first"),
        ])
        rows = run("pr,yp", sort="yp", data=data)
        self.assertIn("2", rows[0][0])
        self.assertIn("1", rows[1][0])

    def test_yp_filter_by_project(self):
        data = make_data(prs=[
            make_pr(1, title="PROJ-1 a"),
            make_pr(2, title="OTHER-2 b"),
        ])
        rows = run("pr,yp", filters=["yp=PROJ"], data=data)
        self.assertEqual(len(rows), 1)
        self.assertIn("1", rows[0][0])

    def test_yp_filter_missing(self):
        data = make_data(prs=[
            make_pr(1, title="PROJ-1 a"),
            make_pr(2, title="no ticket"),
        ])
        rows = run("pr,yp", filters=["yp=MISSING"], data=data)
        self.assertEqual(len(rows), 1)
        self.assertIn("2", rows[0][0])


class TestYIColumn(unittest.TestCase):

    def test_yi_extracts_numeric_id(self):
        data = make_data(prs=[make_pr(1, title="PROJ-123 fix something")])
        rows = run("yi", data=data)
        self.assertEqual(rows[0][0], "123")

    def test_yi_extracts_id_from_dashed_project(self):
        data = make_data(prs=[make_pr(1, title="MY-PROJECT-456 description")])
        rows = run("yi", data=data)
        self.assertEqual(rows[0][0], "456")

    def test_yi_missing_when_no_ticket_id(self):
        data = make_data(prs=[make_pr(1, title="no ticket here")])
        rows = run("yi", data=data)
        self.assertEqual(rows[0][0], "MISSING")

    def test_yi_sort_numeric(self):
        data = make_data(prs=[
            make_pr(1, title="PROJ-9 low"),
            make_pr(2, title="PROJ-10 high"),
        ])
        rows = run("pr,yi", sort="yi", data=data)
        self.assertIn("1", rows[0][0])   # 9 < 10 numerically
        self.assertIn("2", rows[1][0])

    def test_yi_sort_missing_last(self):
        data = make_data(prs=[
            make_pr(1, title="no ticket"),
            make_pr(2, title="PROJ-1 has ticket"),
        ])
        rows = run("pr,yi", sort="yi", data=data)
        self.assertIn("2", rows[0][0])
        self.assertIn("1", rows[1][0])

    def test_yi_filter_by_id(self):
        data = make_data(prs=[
            make_pr(1, title="PROJ-42 a"),
            make_pr(2, title="PROJ-99 b"),
        ])
        rows = run("pr,yi", filters=["yi=42"], data=data)
        self.assertEqual(len(rows), 1)
        self.assertIn("1", rows[0][0])

    def test_yi_filter_missing(self):
        data = make_data(prs=[
            make_pr(1, title="PROJ-1 a"),
            make_pr(2, title="no ticket"),
        ])
        rows = run("pr,yi", filters=["yi=MISSING"], data=data)
        self.assertEqual(len(rows), 1)
        self.assertIn("2", rows[0][0])


if __name__ == "__main__":
    unittest.main()
