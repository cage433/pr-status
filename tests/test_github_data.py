import unittest

from pr_status.config import Config, GithubInfo
from pr_status.github_data import GithubComment, GithubData, GithubPR
from pr_status.github_raw_data import GithubRawData
from pr_status.loc import LOC
from pr_status.marks import Marks
from pr_status.node import Node
from pr_status.pr_number import PRNumber
from pr_status.report_args import ReportArgs


def make_config(**kwargs) -> Config:
    defaults = dict(
        repo=GithubInfo(owner="owner", repo_name="repo"),
        ignored_authors=set(),
        ignored_prs=set(),
        ai_authors=set(),
        author_names={},
        ignored_comments=set(),
        aliases={},
    )
    defaults.update(kwargs)
    return Config(**defaults)


def make_args(include_ai: bool = True) -> ReportArgs:
    return ReportArgs(include_ai=include_ai, include_pre_mark_commits=False, sort="", filters=[], columns="")


def make_marks(data: dict[PRNumber, str] | None = None) -> Marks:
    marks = Marks("/nonexistent/path/marks.csv")
    if data:
        marks._data = data
    return marks


def make_raw(
    pr_nodes: list[Node] | None = None,
    loc_results: dict[PRNumber, LOC] | None = None,
    comment_data: dict[PRNumber, Node] | None = None,
) -> GithubRawData:
    return GithubRawData(
        pr_nodes=pr_nodes or [],
        loc_results=loc_results or {},
        comment_data=comment_data or {},
    )


def pr_node(number: int, title: str = "Test PR", author: str = "alice") -> Node:
    return Node({"number": number, "title": title, "isDraft": False,
                 "createdAt": "2024-01-01T00:00:00Z", "author": {"login": author}})


def comment_node(body: str, author: str = "alice", created_at: str = "2024-01-15T10:00:00Z") -> Node:
    return Node({"body": body, "createdAt": created_at, "author": {"login": author}})


def review_node(body: str, author: str = "alice", submitted_at: str = "2024-01-15T10:00:00Z") -> Node:
    return Node({"body": body, "submittedAt": submitted_at, "author": {"login": author}})


def thread_node(*nodes: Node) -> Node:
    return Node({"comments": {"nodes": list(nodes)}})


def pr_comment_data(
    comments: list[Node] | None = None,
    reviews: list[Node] | None = None,
    threads: list[Node] | None = None,
) -> Node:
    return Node({
        "comments":      {"nodes": comments or []},
        "reviews":       {"nodes": reviews  or []},
        "reviewThreads": {"nodes": threads  or []},
    })


class TestGithubDataFromRaw(unittest.TestCase):

    def test_prs_sorted_by_number(self):
        raw = make_raw(pr_nodes=[pr_node(20), pr_node(5), pr_node(13)])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual([pr.number for pr in data.all_prs], [5, 13, 20])

    def test_loc_results_passed_through(self):
        loc = {PRNumber(1): LOC((100, 50))}
        raw = make_raw(pr_nodes=[pr_node(1)], loc_results=loc)
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.loc_results, loc)

    def test_regular_comment(self):
        pr = PRNumber(1)
        raw = make_raw(
            pr_nodes=[pr_node(1)],
            comment_data={pr: pr_comment_data(comments=[comment_node("hello")])},
        )
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        rows = data.rows_all[pr]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].kind, "comment")
        self.assertEqual(rows[0].body, "hello")
        self.assertEqual(rows[0].author, "alice")

    def test_review_uses_submitted_at(self):
        pr = PRNumber(1)
        raw = make_raw(
            pr_nodes=[pr_node(1)],
            comment_data={pr: pr_comment_data(reviews=[review_node("lgtm", submitted_at="2024-01-15T11:00:00Z")])},
        )
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        rows = data.rows_all[pr]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].kind, "review")
        self.assertEqual(rows[0].timestamp, "2024-01-15T11:00:00Z")

    def test_inline_comment(self):
        pr = PRNumber(1)
        raw = make_raw(
            pr_nodes=[pr_node(1)],
            comment_data={pr: pr_comment_data(threads=[thread_node(comment_node("nit: fix this"))])},
        )
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        rows = data.rows_all[pr]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].kind, "inline")

    def test_blank_body_filtered(self):
        pr = PRNumber(1)
        raw = make_raw(
            pr_nodes=[pr_node(1)],
            comment_data={pr: pr_comment_data(comments=[comment_node("   ")])},
        )
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.rows_all[pr], [])

    def test_ignored_comment_filtered(self):
        pr = PRNumber(1)
        config = make_config(ignored_comments={"auto-generated"})
        raw = make_raw(
            pr_nodes=[pr_node(1)],
            comment_data={pr: pr_comment_data(comments=[comment_node("auto-generated")])},
        )
        data = GithubData.from_raw(config, make_marks(), make_args(), raw)
        self.assertEqual(data.rows_all[pr], [])

    def test_ai_author_filtered_by_default(self):
        pr = PRNumber(1)
        config = make_config(ai_authors={"copilot"})
        raw = make_raw(
            pr_nodes=[pr_node(1)],
            comment_data={pr: pr_comment_data(comments=[comment_node("suggestion", author="copilot")])},
        )
        data = GithubData.from_raw(config, make_marks(), make_args(include_ai=False), raw)
        self.assertEqual(data.rows_all[pr], [])

    def test_ai_author_included_with_include_ai(self):
        pr = PRNumber(1)
        config = make_config(ai_authors={"copilot"})
        raw = make_raw(
            pr_nodes=[pr_node(1)],
            comment_data={pr: pr_comment_data(comments=[comment_node("suggestion", author="copilot")])},
        )
        data = GithubData.from_raw(config, make_marks(), make_args(include_ai=True), raw)
        self.assertEqual(len(data.rows_all[pr]), 1)

    def test_events_sorted_by_timestamp(self):
        pr = PRNumber(1)
        raw = make_raw(
            pr_nodes=[pr_node(1)],
            comment_data={pr: pr_comment_data(comments=[
                comment_node("later",   created_at="2024-01-15T12:00:00Z"),
                comment_node("earlier", created_at="2024-01-15T08:00:00Z"),
            ])},
        )
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        rows = data.rows_all[pr]
        self.assertEqual(rows[0].body, "earlier")
        self.assertEqual(rows[1].body, "later")

    def test_mark_filters_rows_marked(self):
        pr = PRNumber(1)
        marks = make_marks({pr: "2024-01-15T10:00:00Z"})
        raw = make_raw(
            pr_nodes=[pr_node(1)],
            comment_data={pr: pr_comment_data(comments=[
                comment_node("before mark", created_at="2024-01-15T09:00:00Z"),
                comment_node("after mark",  created_at="2024-01-15T11:00:00Z"),
            ])},
        )
        data = GithubData.from_raw(make_config(), marks, make_args(), raw)
        self.assertEqual(len(data.rows_marked[pr]), 1)
        self.assertEqual(data.rows_marked[pr][0].body, "after mark")

    def test_rows_all_unaffected_by_mark(self):
        pr = PRNumber(1)
        marks = make_marks({pr: "2024-01-15T10:00:00Z"})
        raw = make_raw(
            pr_nodes=[pr_node(1)],
            comment_data={pr: pr_comment_data(comments=[
                comment_node("before mark", created_at="2024-01-15T09:00:00Z"),
                comment_node("after mark",  created_at="2024-01-15T11:00:00Z"),
            ])},
        )
        data = GithubData.from_raw(make_config(), marks, make_args(), raw)
        self.assertEqual(len(data.rows_all[pr]), 2)

    def test_thread_sorted_by_first_comment_timestamp(self):
        pr = PRNumber(1)
        raw = make_raw(
            pr_nodes=[pr_node(1)],
            comment_data={pr: pr_comment_data(
                comments=[comment_node("standalone", created_at="2024-01-15T10:30:00Z")],
                threads=[thread_node(
                    comment_node("thread c1", created_at="2024-01-15T10:00:00Z"),
                    comment_node("thread c2", created_at="2024-01-15T10:45:00Z"),
                )],
            )},
        )
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        rows = data.rows_all[pr]
        # thread starts at 10:00 so sorts before standalone at 10:30
        self.assertEqual([r.body for r in rows], ["thread c1", "thread c2", "standalone"])

    def test_thread_filtered_when_all_comments_ignored(self):
        pr = PRNumber(1)
        config = make_config(ignored_comments={"ignore me"})
        raw = make_raw(
            pr_nodes=[pr_node(1)],
            comment_data={pr: pr_comment_data(threads=[thread_node(comment_node("ignore me"))])},
        )
        data = GithubData.from_raw(config, make_marks(), make_args(), raw)
        self.assertEqual(data.rows_all[pr], [])

    def test_mark_uses_max_timestamp_for_threads(self):
        pr = PRNumber(1)
        # thread starts before mark but has a later comment after mark — whole thread included
        marks = make_marks({pr: "2024-01-15T10:00:00Z"})
        raw = make_raw(
            pr_nodes=[pr_node(1)],
            comment_data={pr: pr_comment_data(threads=[thread_node(
                comment_node("c1 before", created_at="2024-01-15T09:00:00Z"),
                comment_node("c2 after",  created_at="2024-01-15T11:00:00Z"),
            )])},
        )
        data = GithubData.from_raw(make_config(), marks, make_args(), raw)
        self.assertEqual(len(data.rows_marked[pr]), 2)


if __name__ == "__main__":
    unittest.main()
