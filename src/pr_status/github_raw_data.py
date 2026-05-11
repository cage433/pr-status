import threading
from dataclasses import dataclass

from .config import Config
from . import gh_api
from .loc import LOC
from .node import Node
from .pr_number import PRNumber


def node_login(node: Node) -> str:
    return (node.get("author") or {}).get("login", "")


@dataclass
class GithubRawData:
    pr_nodes: list[Node]
    loc_results: dict[PRNumber, LOC]
    comment_data: dict[PRNumber, Node]

    def comment_nodes(self, pr_num: PRNumber) -> list[Node]:
        return self.comment_data.get(pr_num, {}).get("comments", {}).get("nodes", [])

    def review_nodes(self, pr_num: PRNumber) -> list[Node]:
        return self.comment_data.get(pr_num, {}).get("reviews", {}).get("nodes", [])

    def review_thread_nodes(self, pr_num: PRNumber) -> list[list[Node]]:
        threads = self.comment_data.get(pr_num, {}).get("reviewThreads", {}).get("nodes", [])
        return [t.get("comments", {}).get("nodes", []) for t in threads]

    @staticmethod
    def fetch(config: Config, all_cols: set[str]) -> "GithubRawData":
        pr_nodes = gh_api.fetch_pr_nodes(config.repo)
        pr_nodes = [n for n in pr_nodes
                    if node_login(n) not in config.ignored_authors
                    and n["number"] not in config.ignored_prs
                    and not n.get("isDraft", False)]
        pr_nums = [PRNumber(n["number"]) for n in pr_nodes]

        loc_results: dict[PRNumber, LOC] = {}
        if "loc" in all_cols:
            def fetch_scala_loc(pr_num: PRNumber) -> None:
                loc_results[pr_num] = gh_api.fetch_scala_loc(config.repo, pr_num)
            threads = [threading.Thread(target=fetch_scala_loc, args=(n,)) for n in pr_nums]
            for t in threads: t.start()
            for t in threads: t.join()

        COMMENT_COLS = {"num-comments", "last-comment-time", "my-last-comment-time", "comment"}
        comment_data: dict[PRNumber, Node] = {}
        if COMMENT_COLS & all_cols:
            def fetch_comment_data(pr_num: PRNumber) -> None:
                comment_data[pr_num] = gh_api.fetch_pr_comment_data(config.repo, pr_num)
            threads = [threading.Thread(target=fetch_comment_data, args=(n,)) for n in pr_nums]
            for t in threads: t.start()
            for t in threads: t.join()

        return GithubRawData(pr_nodes=pr_nodes, loc_results=loc_results, comment_data=comment_data)
