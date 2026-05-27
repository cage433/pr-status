import threading
from dataclasses import dataclass

from .config import Config
from . import gh_api
from .loc import LOC
from .node import Node
from .pr_number import PRNumber


def node_login(node: Node) -> str:
    return (node.get("author") or {}).get("login", "")


def node_label_names(node: Node) -> set[str]:
    return {lbl["name"] for lbl in (node.get("labels") or {}).get("nodes", [])}


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
        return [t.get("comments", {}).get("nodes", []) for t in threads if not t.get("isOutdated")]

    def last_activity_timestamp(self, pr_num: PRNumber) -> str:
        timestamps: list[str] = []
        for c in self.comment_nodes(pr_num):
            if ts := c.get("createdAt", ""):
                timestamps.append(ts)
        for r in self.review_nodes(pr_num):
            if ts := r.get("submittedAt", ""):
                timestamps.append(ts)
        for thread_comments in self.review_thread_nodes(pr_num):
            for c in thread_comments:
                if ts := c.get("createdAt", ""):
                    timestamps.append(ts)
        return max(timestamps, default="")

    def unresolved_thread_counts(self, pr_num: PRNumber, config: Config) -> tuple[int, int, int]:
        threads = (self.comment_data.get(pr_num) or {}).get("reviewThreads", {}).get("nodes", [])
        total = human = ai = 0
        for thread in threads:
            if thread.get("isResolved") or thread.get("isOutdated"):
                continue
            comments = (thread.get("comments") or {}).get("nodes", [])
            author = (comments[0].get("author") or {}).get("login", "") if comments else ""
            total += 1
            if config.is_ai_author(author):
                ai += 1
            else:
                human += 1
        return (total, human, ai)

    @staticmethod
    def fetch(config: Config, all_cols: set[str]) -> "GithubRawData":
        pr_nodes = gh_api.fetch_pr_nodes(config.repo)
        pr_nodes = [n for n in pr_nodes
                    if node_login(n) not in config.ignored_authors
                    and n["number"] not in config.ignored_prs
                    and not (node_label_names(n) & config.ignored_labels)]
        pr_nums = [PRNumber(n["number"]) for n in pr_nodes]

        loc_results: dict[PRNumber, LOC] = {}
        if "loc" in all_cols:
            def fetch_scala_loc(pr_num: PRNumber) -> None:
                loc_results[pr_num] = gh_api.fetch_scala_loc(config.repo, pr_num)
            threads = [threading.Thread(target=fetch_scala_loc, args=(n,)) for n in pr_nums]
            for t in threads: t.start()
            for t in threads: t.join()

        COMMENT_COLS = {"num-comments", "last-comment-time", "my-last-comment-time", "comment",
                        "unresolved (all)", "unresolved (human)", "unresolved (ai)", "last-activity"}
        comment_data: dict[PRNumber, Node] = {}
        if COMMENT_COLS & all_cols:
            def fetch_comment_data(pr_num: PRNumber) -> None:
                comment_data[pr_num] = gh_api.fetch_pr_comment_data(config.repo, pr_num)
            threads = [threading.Thread(target=fetch_comment_data, args=(n,)) for n in pr_nums]
            for t in threads: t.start()
            for t in threads: t.join()

        return GithubRawData(pr_nodes=pr_nodes, loc_results=loc_results, comment_data=comment_data)
