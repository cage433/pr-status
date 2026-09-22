import unittest
from unittest.mock import patch

from pr_status import gh_api
from pr_status.config import Config, GithubInfo
from pr_status.github_raw_data import GithubRawData
from pr_status.node import Node
from pr_status.report_args import ReportArgs

REPO = GithubInfo(owner="owner", repo_name="repo")


def make_config(**kwargs) -> Config:
    defaults = dict(
        repo=REPO, ignored_authors=set(), ignored_prs=set(), ai_authors=set(), author_names={},
        ignored_comment_patterns=[], ignored_title_patterns=[], ignored_labels=set(), aliases={},
    )
    defaults.update(kwargs)
    return Config(**defaults)


def make_args(include_drafts: bool = False) -> ReportArgs:
    return ReportArgs(include_ai=False, include_pre_mark_commits=False,
                      include_drafts=include_drafts, sort="", filters=[], columns="pr")


def core_node(number: int, title: str = "Test PR") -> Node:
    return Node({"number": number, "title": title, "author": {"login": "alice"}})


def reviews_node(number: int, reviewers: list[str]) -> Node:
    return Node({"number": number,
                 "reviews": {"nodes": [{"author": {"login": r}, "state": "APPROVED", "body": ""}
                                       for r in reviewers]}})


class TestSearchQuery(unittest.TestCase):

    def test_open_prs_of_the_repo_without_drafts(self):
        self.assertEqual(GithubRawData.search_query(make_config(), make_args(), []),
                         "repo:owner/repo is:pr is:open draft:false")

    def test_drafts_are_asked_for_when_the_report_wants_them(self):
        self.assertEqual(GithubRawData.search_query(make_config(), make_args(include_drafts=True), []),
                         "repo:owner/repo is:pr is:open")

    def test_qualifiers_are_appended(self):
        self.assertEqual(
            GithubRawData.search_query(make_config(), make_args(), ["author:bob", "author:carol"]),
            "repo:owner/repo is:pr is:open draft:false author:bob author:carol")


class TestFetchPrNodes(unittest.TestCase):
    """The two field groups are fetched concurrently, so each PR's node has to be
    reassembled from the two responses."""

    def fetch(self, core: list[Node], reviews: list[Node], issue_count: int | None = None,
              connection: tuple[list[Node], list[Node]] | None = None) -> list[Node]:
        def fake_search(query, fields, label):
            nodes = core if label == "core" else reviews
            return nodes, (len(core) if issue_count is None else issue_count)
        def fake_connection(repo, fields, label):
            assert connection is not None
            return connection[0] if label == "core" else connection[1]
        with patch.object(gh_api, "_fetch_search_pages",     side_effect=fake_search), \
             patch.object(gh_api, "_fetch_connection_pages", side_effect=fake_connection):
            return gh_api.fetch_pr_nodes(REPO, "repo:owner/repo is:pr is:open")

    def test_merges_both_groups_into_one_node(self):
        nodes = self.fetch([core_node(1)], [reviews_node(1, ["bob"])])
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["title"], "Test PR")
        self.assertEqual([r["author"]["login"] for r in nodes[0]["reviews"]["nodes"]], ["bob"])

    def test_orders_by_pr_number(self):
        nodes = self.fetch([core_node(3), core_node(1), core_node(2)],
                           [reviews_node(n, []) for n in (1, 2, 3)])
        self.assertEqual([n["number"] for n in nodes], [1, 2, 3])

    def test_pr_missing_from_the_reviews_group_is_kept_without_reviews(self):
        # A PR opened between the two fetches: reportable, just with no reviews yet.
        nodes = self.fetch([core_node(1), core_node(2)], [reviews_node(1, ["bob"])])
        self.assertEqual([n["number"] for n in nodes], [1, 2])
        self.assertNotIn("reviews", nodes[1])

    def test_pr_missing_from_the_core_group_is_dropped(self):
        # Without the core fields there is nothing to report about it.
        nodes = self.fetch([core_node(1)], [reviews_node(1, []), reviews_node(2, ["bob"])])
        self.assertEqual([n["number"] for n in nodes], [1])

    def test_falls_back_to_the_connection_when_search_caps_out(self):
        # Search stops handing results over past SEARCH_RESULT_LIMIT, so what it
        # returned is an arbitrary subset and the connection has to answer instead.
        nodes = self.fetch([core_node(1)], [reviews_node(1, [])],
                           issue_count=gh_api.SEARCH_RESULT_LIMIT + 1,
                           connection=([core_node(1), core_node(2)],
                                       [reviews_node(1, []), reviews_node(2, [])]))
        self.assertEqual([n["number"] for n in nodes], [1, 2])


if __name__ == "__main__":
    unittest.main()
