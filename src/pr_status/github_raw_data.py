import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from ._util import timing_log
from .config import Config
from . import gh_api
from .loc import LOC
from .node import Node
from .pr_number import PRNumber
from .report_args import ReportArgs


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
    def fetch_pr_nodes_filtered(config: Config, args: ReportArgs) -> list[Node]:
        """The light PR query plus the filters that decide whether a PR is reported at
        all. Split out so callers can get PR titles (hence YouTrack ticket ids) early,
        before the slow per-PR comment/LOC fetch."""
        t0 = time.monotonic()
        pr_nodes = gh_api.fetch_pr_nodes(config.repo)
        timing_log("fetch_pr_nodes: %d PRs in %.3fs" % (len(pr_nodes), time.monotonic() - t0))
        # Exclude PRs that won't be reported *before* fetching their per-PR data, so we
        # don't pay for comment/LOC fetches on drafts (dropped unless --include-drafts).
        return [n for n in pr_nodes
                if node_login(n) not in config.ignored_authors
                and n["number"] not in config.ignored_prs
                and not (node_label_names(n) & config.ignored_labels)
                and (args.include_drafts or not n.get("isDraft", False))]

    @staticmethod
    def fetch(config: Config, args: ReportArgs, all_cols: set[str],
              pr_nodes: "list[Node] | None" = None) -> "GithubRawData":
        t_start = time.monotonic()
        workers = max(1, config.max_threads)
        if pr_nodes is None:
            pr_nodes = GithubRawData.fetch_pr_nodes_filtered(config, args)
        pr_nums = [PRNumber(n["number"]) for n in pr_nodes]

        loc_results: dict[PRNumber, LOC] = {}
        if "loc" in all_cols:
            t0 = time.monotonic()
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(gh_api.fetch_scala_loc, config.repo, n): n for n in pr_nums}
                for f in as_completed(futs):
                    loc_results[futs[f]] = f.result()
            timing_log("loc: %d PRs in %.3fs (max_threads=%d)" % (len(pr_nums), time.monotonic() - t0, workers))

        # Columns needing the full comment payload (bodies / timestamps / top-level
        # comments+reviews) vs those needing only unresolved-thread counts. When only the
        # latter are requested (e.g. the 'all' report), fetch the minimal query.
        FULL_COMMENT_COLS = {"num-comments", "last-comment-time", "my-last-comment-time",
                             "comment", "last-activity"}
        UNRESOLVED_COLS   = {"unresolved (all)", "unresolved (human)", "unresolved (ai)"}
        comment_data: dict[PRNumber, Node] = {}
        if (FULL_COMMENT_COLS | UNRESOLVED_COLS) & all_cols:
            minimal = not (FULL_COMMENT_COLS & all_cols)
            t0 = time.monotonic()
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(gh_api.fetch_pr_comment_data, config.repo, n, minimal): n for n in pr_nums}
                for f in as_completed(futs):
                    comment_data[futs[f]] = f.result()
            timing_log("comments: %d PRs in %.3fs (max_threads=%d%s)"
                       % (len(pr_nums), time.monotonic() - t0, workers, ", minimal" if minimal else ""))

        timing_log("github data fetch: %.3fs" % (time.monotonic() - t_start))
        return GithubRawData(pr_nodes=pr_nodes, loc_results=loc_results, comment_data=comment_data)
