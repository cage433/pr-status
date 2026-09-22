import unittest
from unittest.mock import patch

from pr_status import gh_api
from pr_status.config import GithubInfo
from pr_status.node import Node

REPO = GithubInfo(owner="owner", repo_name="repo")


def core_node(number: int, title: str = "Test PR") -> Node:
    return Node({"number": number, "title": title, "author": {"login": "alice"}})


def reviews_node(number: int, reviewers: list[str]) -> Node:
    return Node({"number": number,
                 "reviews": {"nodes": [{"author": {"login": r}, "state": "APPROVED", "body": ""}
                                       for r in reviewers]}})


class TestFetchPrNodes(unittest.TestCase):
    """The two field groups are fetched concurrently, so each PR's node has to be
    reassembled from the two responses."""

    def fetch(self, core: list[Node], reviews: list[Node]) -> list[Node]:
        def fake(repo, fields, label):
            return core if label == "core" else reviews
        with patch.object(gh_api, "_fetch_pr_pages", side_effect=fake):
            return gh_api.fetch_pr_nodes(REPO)

    def test_merges_both_groups_into_one_node(self):
        nodes = self.fetch([core_node(1)], [reviews_node(1, ["bob"])])
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["title"], "Test PR")
        self.assertEqual([r["author"]["login"] for r in nodes[0]["reviews"]["nodes"]], ["bob"])

    def test_keeps_core_order(self):
        nodes = self.fetch([core_node(3), core_node(1), core_node(2)],
                           [reviews_node(n, []) for n in (1, 2, 3)])
        self.assertEqual([n["number"] for n in nodes], [3, 1, 2])

    def test_pr_missing_from_the_reviews_group_is_kept_without_reviews(self):
        # A PR opened between the two fetches: reportable, just with no reviews yet.
        nodes = self.fetch([core_node(1), core_node(2)], [reviews_node(1, ["bob"])])
        self.assertEqual([n["number"] for n in nodes], [1, 2])
        self.assertNotIn("reviews", nodes[1])

    def test_pr_missing_from_the_core_group_is_dropped(self):
        # Without the core fields there is nothing to report about it.
        nodes = self.fetch([core_node(1)], [reviews_node(1, []), reviews_node(2, ["bob"])])
        self.assertEqual([n["number"] for n in nodes], [1])


if __name__ == "__main__":
    unittest.main()
