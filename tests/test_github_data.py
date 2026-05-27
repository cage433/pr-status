import re
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
        ignored_comment_patterns=[],
        ignored_title_patterns=[],
        ignored_labels=set(),
        aliases={},
    )
    defaults.update(kwargs)
    return Config(**defaults)


def make_args(include_ai: bool = True, include_drafts: bool = False) -> ReportArgs:
    return ReportArgs(include_ai=include_ai, include_pre_mark_commits=False, include_drafts=include_drafts, sort="", filters=[], columns="")


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


def pr_node(
    number: int,
    title: str = "Test PR",
    author: str = "alice",
    is_draft: bool = False,
    reviewers: list[str] | None = None,
    submitted_reviewers: list[str] | None = None,
    submitted_reviewer_states: dict[str, str] | None = None,
) -> Node:
    review_request_nodes = [{"requestedReviewer": {"login": r}} for r in (reviewers or [])]
    states = submitted_reviewer_states or {}
    review_nodes = [{"author": {"login": r}, "state": states.get(r, "COMMENTED")}
                    for r in (submitted_reviewers or [])]
    return Node({"number": number, "title": title, "isDraft": is_draft,
                 "createdAt": "2024-01-01T00:00:00Z", "author": {"login": author},
                 "reviewRequests": {"nodes": review_request_nodes},
                 "reviews": {"nodes": review_nodes}})


def comment_node(body: str, author: str = "alice", created_at: str = "2024-01-15T10:00:00Z") -> Node:
    return Node({"body": body, "createdAt": created_at, "author": {"login": author}})


def review_node(body: str, author: str = "alice", submitted_at: str = "2024-01-15T10:00:00Z") -> Node:
    return Node({"body": body, "submittedAt": submitted_at, "author": {"login": author}})


def thread_node(*nodes: Node, is_outdated: bool = False, is_resolved: bool = False) -> Node:
    return Node({"isOutdated": is_outdated, "isResolved": is_resolved, "comments": {"nodes": list(nodes)}})


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
        config = make_config(ignored_comment_patterns=[re.compile("auto-generated")])
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

    def test_outdated_thread_ignored(self):
        pr = PRNumber(1)
        raw = make_raw(
            pr_nodes=[pr_node(1)],
            comment_data={pr: pr_comment_data(threads=[thread_node(comment_node("nit"), is_outdated=True)])},
        )
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.rows_all[pr], [])

    def test_thread_filtered_when_all_comments_ignored(self):
        pr = PRNumber(1)
        config = make_config(ignored_comment_patterns=[re.compile("ignore me")])
        raw = make_raw(
            pr_nodes=[pr_node(1)],
            comment_data={pr: pr_comment_data(threads=[thread_node(comment_node("ignore me"))])},
        )
        data = GithubData.from_raw(config, make_marks(), make_args(), raw)
        self.assertEqual(data.rows_all[pr], [])

    def test_ignored_comment_regex_partial_match(self):
        pr = PRNumber(1)
        config = make_config(ignored_comment_patterns=[re.compile(r"auto-gen")])
        raw = make_raw(
            pr_nodes=[pr_node(1)],
            comment_data={pr: pr_comment_data(comments=[comment_node("auto-generated comment")])},
        )
        data = GithubData.from_raw(config, make_marks(), make_args(), raw)
        self.assertEqual(data.rows_all[pr], [])

    def test_ignored_comment_regex_no_match_kept(self):
        pr = PRNumber(1)
        config = make_config(ignored_comment_patterns=[re.compile(r"auto-gen")])
        raw = make_raw(
            pr_nodes=[pr_node(1)],
            comment_data={pr: pr_comment_data(comments=[comment_node("manual comment")])},
        )
        data = GithubData.from_raw(config, make_marks(), make_args(), raw)
        self.assertEqual(len(data.rows_all[pr]), 1)


class TestIgnoredTitles(unittest.TestCase):

    def test_pr_excluded_when_title_matches(self):
        raw = make_raw(pr_nodes=[pr_node(1, title="[WIP] my feature"), pr_node(2, title="ready feature")])
        config = make_config(ignored_title_patterns=[re.compile(r"\[WIP\]")])
        data = GithubData.from_raw(config, make_marks(), make_args(), raw)
        self.assertEqual([pr.number for pr in data.all_prs], [PRNumber(2)])

    def test_pr_kept_when_title_does_not_match(self):
        raw = make_raw(pr_nodes=[pr_node(1, title="ready feature")])
        config = make_config(ignored_title_patterns=[re.compile(r"\[WIP\]")])
        data = GithubData.from_raw(config, make_marks(), make_args(), raw)
        self.assertEqual(len(data.all_prs), 1)

    def test_multiple_patterns_any_match_excludes(self):
        raw = make_raw(pr_nodes=[pr_node(1, title="chore: cleanup"), pr_node(2, title="feat: add thing")])
        config = make_config(ignored_title_patterns=[re.compile(r"^chore:"), re.compile(r"^docs:")])
        data = GithubData.from_raw(config, make_marks(), make_args(), raw)
        self.assertEqual([pr.number for pr in data.all_prs], [PRNumber(2)])

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


class TestGithubPRReviewers(unittest.TestCase):

    def test_reviewers_parsed_from_review_requests(self):
        raw = make_raw(pr_nodes=[pr_node(1, reviewers=["bob", "carol"])])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.all_prs[0].reviewers, ["bob", "carol"])

    def test_no_reviewers_when_none_requested(self):
        raw = make_raw(pr_nodes=[pr_node(1)])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.all_prs[0].reviewers, [])

    def test_missing_review_requests_field_handled(self):
        node = Node({"number": 1, "title": "T", "isDraft": False,
                     "createdAt": "2024-01-01T00:00:00Z", "author": {"login": "alice"}})
        raw = make_raw(pr_nodes=[node])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.all_prs[0].reviewers, [])

    def test_submitted_reviewers_included_when_no_pending_request(self):
        raw = make_raw(pr_nodes=[pr_node(1, submitted_reviewers=["bob", "carol"])])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.all_prs[0].reviewers, ["bob", "carol"])

    def test_submitted_reviewers_deduplicated_with_pending(self):
        raw = make_raw(pr_nodes=[pr_node(1, reviewers=["bob"], submitted_reviewers=["bob", "carol"])])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.all_prs[0].reviewers, ["bob", "carol"])

    def test_pr_author_excluded_from_submitted_reviewers(self):
        raw = make_raw(pr_nodes=[pr_node(1, author="alice", submitted_reviewers=["alice", "bob"])])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.all_prs[0].reviewers, ["bob"])

    def test_ai_reviewer_excluded_from_pending_requests_by_default(self):
        config = make_config(ai_authors={"copilot"})
        raw = make_raw(pr_nodes=[pr_node(1, reviewers=["copilot", "bob"])])
        data = GithubData.from_raw(config, make_marks(), make_args(include_ai=False), raw)
        self.assertEqual(data.all_prs[0].reviewers, ["bob"])

    def test_ai_reviewer_excluded_from_submitted_reviews_by_default(self):
        config = make_config(ai_authors={"copilot"})
        raw = make_raw(pr_nodes=[pr_node(1, submitted_reviewers=["copilot", "bob"])])
        data = GithubData.from_raw(config, make_marks(), make_args(include_ai=False), raw)
        self.assertEqual(data.all_prs[0].reviewers, ["bob"])

    def test_ai_reviewer_included_with_include_ai_flag(self):
        config = make_config(ai_authors={"copilot"})
        raw = make_raw(pr_nodes=[pr_node(1, reviewers=["copilot", "bob"])])
        data = GithubData.from_raw(config, make_marks(), make_args(include_ai=True), raw)
        self.assertEqual(data.all_prs[0].reviewers, ["copilot", "bob"])

    def test_reviewer_states_populated_from_submitted_reviews(self):
        raw = make_raw(pr_nodes=[pr_node(1, submitted_reviewers=["bob", "carol"],
                                         submitted_reviewer_states={"bob": "APPROVED", "carol": "CHANGES_REQUESTED"})])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.all_prs[0].reviewer_states, {"bob": "APPROVED", "carol": "CHANGES_REQUESTED"})

    def test_reviewer_states_empty_for_pending_only(self):
        raw = make_raw(pr_nodes=[pr_node(1, reviewers=["bob"])])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.all_prs[0].reviewer_states, {})

    def test_reviewer_states_latest_wins_for_multiple_reviews(self):
        node = pr_node(1)
        node["reviews"] = {"nodes": [
            {"author": {"login": "bob"}, "state": "CHANGES_REQUESTED"},
            {"author": {"login": "bob"}, "state": "APPROVED"},
        ]}
        raw = make_raw(pr_nodes=[node])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.all_prs[0].reviewer_states.get("bob"), "APPROVED")


class TestDraftFiltering(unittest.TestCase):

    def test_draft_excluded_by_default(self):
        raw = make_raw(pr_nodes=[pr_node(1), pr_node(2, is_draft=True)])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(include_drafts=False), raw)
        self.assertEqual([pr.number for pr in data.all_prs], [1])

    def test_draft_included_with_flag(self):
        raw = make_raw(pr_nodes=[pr_node(1), pr_node(2, is_draft=True)])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(include_drafts=True), raw)
        self.assertEqual([pr.number for pr in data.all_prs], [1, 2])

    def test_is_draft_field_set_correctly(self):
        raw = make_raw(pr_nodes=[pr_node(1), pr_node(2, is_draft=True)])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(include_drafts=True), raw)
        self.assertFalse(data.all_prs[0].isDraft)
        self.assertTrue(data.all_prs[1].isDraft)


class TestUnresolvedThreadCounts(unittest.TestCase):

    def _make_thread(self, is_resolved: bool, author: str) -> Node:
        return Node({"isResolved": is_resolved,
                     "comments": {"nodes": [{"author": {"login": author}, "createdAt": "2024-01-01T00:00:00Z", "body": "x"}]}})

    def _make_raw(self, threads: list[Node]) -> GithubRawData:
        pr = pr_node(1)
        comment_data = Node({
            "comments": {"nodes": []},
            "reviews": {"nodes": []},
            "reviewThreads": {"nodes": list(threads)},
        })
        return make_raw(pr_nodes=[pr], comment_data={PRNumber(1): comment_data})

    def test_counts_unresolved_threads(self):
        raw = self._make_raw([self._make_thread(False, "bob"), self._make_thread(False, "carol")])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.unresolved_counts[PRNumber(1)], (2, 2, 0))

    def test_ignores_resolved_threads(self):
        raw = self._make_raw([self._make_thread(True, "bob"), self._make_thread(False, "carol")])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.unresolved_counts[PRNumber(1)], (1, 1, 0))

    def test_splits_by_ai_author(self):
        config = make_config(ai_authors={"copilot"})
        raw = self._make_raw([self._make_thread(False, "copilot"), self._make_thread(False, "bob")])
        data = GithubData.from_raw(config, make_marks(), make_args(), raw)
        self.assertEqual(data.unresolved_counts[PRNumber(1)], (2, 1, 1))

    def test_zero_when_all_resolved(self):
        raw = self._make_raw([self._make_thread(True, "bob")])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.unresolved_counts[PRNumber(1)], (0, 0, 0))

    def test_zero_when_no_threads(self):
        raw = self._make_raw([])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.unresolved_counts[PRNumber(1)], (0, 0, 0))

    def test_ignores_outdated_threads(self):
        outdated = Node({"isResolved": False, "isOutdated": True,
                         "comments": {"nodes": [{"author": {"login": "bob"}, "createdAt": "2024-01-01T00:00:00Z", "body": "x"}]}})
        raw = self._make_raw([outdated, self._make_thread(False, "carol")])
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.unresolved_counts[PRNumber(1)], (1, 1, 0))


class TestLastActivityTimestamp(unittest.TestCase):

    def _make_raw(self, comment_data: Node) -> GithubRawData:
        return make_raw(pr_nodes=[pr_node(1)], comment_data={PRNumber(1): comment_data})

    def test_uses_general_comment_timestamp(self):
        raw = self._make_raw(Node({
            "comments": {"nodes": [{"author": {"login": "a"}, "createdAt": "2024-06-01T10:00:00Z", "body": "hi"}]},
            "reviews": {"nodes": []}, "reviewThreads": {"nodes": []},
        }))
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.last_activity[PRNumber(1)], "2024-06-01T10:00:00Z")

    def test_uses_review_submitted_at(self):
        raw = self._make_raw(Node({
            "comments": {"nodes": []},
            "reviews": {"nodes": [{"author": {"login": "a"}, "submittedAt": "2024-07-01T10:00:00Z", "body": "lgtm"}]},
            "reviewThreads": {"nodes": []},
        }))
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.last_activity[PRNumber(1)], "2024-07-01T10:00:00Z")

    def test_uses_inline_comment_timestamp(self):
        thread = {"isResolved": False, "comments": {"nodes": [
            {"author": {"login": "a"}, "createdAt": "2024-08-01T10:00:00Z", "body": "inline"}
        ]}}
        raw = self._make_raw(Node({
            "comments": {"nodes": []}, "reviews": {"nodes": []},
            "reviewThreads": {"nodes": [thread]},
        }))
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.last_activity[PRNumber(1)], "2024-08-01T10:00:00Z")

    def test_takes_most_recent_across_all_sources(self):
        thread = {"isResolved": False, "comments": {"nodes": [
            {"author": {"login": "a"}, "createdAt": "2024-08-01T10:00:00Z", "body": "inline"}
        ]}}
        raw = self._make_raw(Node({
            "comments": {"nodes": [{"author": {"login": "a"}, "createdAt": "2024-06-01T10:00:00Z", "body": "x"}]},
            "reviews": {"nodes": [{"author": {"login": "a"}, "submittedAt": "2024-07-01T10:00:00Z", "body": "x"}]},
            "reviewThreads": {"nodes": [thread]},
        }))
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.last_activity[PRNumber(1)], "2024-08-01T10:00:00Z")

    def test_empty_when_no_activity(self):
        raw = self._make_raw(Node({
            "comments": {"nodes": []}, "reviews": {"nodes": []}, "reviewThreads": {"nodes": []},
        }))
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.last_activity[PRNumber(1)], "")

    def test_outdated_thread_excluded_from_last_activity(self):
        thread = {"isResolved": False, "isOutdated": True, "comments": {"nodes": [
            {"author": {"login": "a"}, "createdAt": "2024-08-01T10:00:00Z", "body": "outdated"}
        ]}}
        raw = self._make_raw(Node({
            "comments": {"nodes": [{"author": {"login": "a"}, "createdAt": "2024-06-01T10:00:00Z", "body": "x"}]},
            "reviews": {"nodes": []},
            "reviewThreads": {"nodes": [thread]},
        }))
        data = GithubData.from_raw(make_config(), make_marks(), make_args(), raw)
        self.assertEqual(data.last_activity[PRNumber(1)], "2024-06-01T10:00:00Z")


if __name__ == "__main__":
    unittest.main()
