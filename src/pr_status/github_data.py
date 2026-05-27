from dataclasses import dataclass, field
from typing import Any

from .config import Config
from .github_raw_data import GithubRawData, node_login
from .loc import LOC
from .marks import Marks
from .node import Node
from .pr_number import PRNumber
from .report_args import ReportArgs


@dataclass
class GithubComment:
    timestamp: str
    author: str
    kind: str   # "comment", "review", or "inline"
    body: str

    @staticmethod
    def _from_node(
        node: Node,
        kind: str,
        config: Config,
        args: ReportArgs,
        timestamp_key: str = "createdAt",
    ) -> "GithubComment | None":
        stripped = node.get("body", "").strip()
        if not stripped or any(p.search(stripped) for p in config.ignored_comment_patterns):
            return None
        if not args.include_ai and config.is_ai_author(node_login(node)):
            return None
        return GithubComment(node.get(timestamp_key, ""), node_login(node), kind, stripped)


@dataclass
class GithubPR:
    number: PRNumber
    title: str
    isDraft: bool
    createdAt: str
    author: str  # login name; empty string if the account has been deleted
    reviewers: list[str]
    reviewer_states: dict[str, str]  # login → latest review state (APPROVED, CHANGES_REQUESTED, …)
    labels: set[str] = field(default_factory=set)

    @staticmethod
    def from_graph_ql(nodes: list[Node], config: "Config", args: "ReportArgs") -> list["GithubPR"]:
        result = []
        for node in nodes:
            author_dict = node.get("author") or {}
            pr_author = author_dict.get("login", "")
            reviewer_nodes = (node.get("reviewRequests") or {}).get("nodes", [])
            review_nodes = (node.get("reviews") or {}).get("nodes", [])

            # Latest state per reviewer (reviews are in chronological order)
            reviewer_states: dict[str, str] = {}
            for rn in review_nodes:
                login = (rn.get("author") or {}).get("login", "")
                state = rn.get("state", "")
                if login and login != pr_author and (args.include_ai or not config.is_ai_author(login)):
                    reviewer_states[login] = state

            seen: set[str] = set()
            reviewers: list[str] = []
            for rn in reviewer_nodes:
                rv = rn.get("requestedReviewer") or {}
                login = rv.get("login") or rv.get("name", "")
                if login and login not in seen and (args.include_ai or not config.is_ai_author(login)):
                    seen.add(login)
                    reviewers.append(login)
            for login in reviewer_states:
                if login not in seen:
                    seen.add(login)
                    reviewers.append(login)

            title = node["title"]
            if any(p.search(title) for p in config.ignored_title_patterns):
                continue
            labels = {lbl["name"] for lbl in (node.get("labels") or {}).get("nodes", [])}
            result.append(GithubPR(
                number=PRNumber(node["number"]),
                title=title,
                isDraft=node.get("isDraft", False),
                createdAt=node.get("createdAt", ""),
                author=pr_author,
                reviewers=reviewers,
                reviewer_states=reviewer_states,
                labels=labels,
            ))
        return result


@dataclass
class GithubData:
    all_prs: list[GithubPR]
    loc_results: dict[PRNumber, LOC]
    rows_marked: dict[PRNumber, list[GithubComment]]
    rows_all: dict[PRNumber, list[GithubComment]]
    unresolved_counts: dict[PRNumber, tuple[int, int, int]]  # (all, human, ai)
    last_activity: dict[PRNumber, str]  # ISO timestamp of most recent comment or thread resolution
    youtrack_states: dict[str, str] = field(default_factory=dict)  # ticket_id -> state

    @staticmethod
    def _collect_comments(
        config: Config, 
        marks: Marks, 
        args: ReportArgs,
        raw: GithubRawData,
        pr_num: PRNumber,
        apply_mark: bool = True,
    ) -> list[GithubComment]:
        mark_ts = marks.get(pr_num) if apply_mark else ""
        events: list[tuple[str, list[GithubComment]]] = []
        for c in raw.comment_nodes(pr_num):
            if (row := GithubComment._from_node(c, "comment", config, args)) is not None:
                events.append((row.timestamp, [row]))
        for rev in raw.review_nodes(pr_num):
            if (row := GithubComment._from_node(rev, "review", config, args, "submittedAt")) is not None:
                events.append((row.timestamp, [row]))
        for thread_nodes in raw.review_thread_nodes(pr_num):
            thread_rows: list[GithubComment] = []
            for c in thread_nodes:
                if (row := GithubComment._from_node(c, "inline", config, args)) is not None:
                    thread_rows.append(row)
            if thread_rows:
                events.append((thread_rows[0].timestamp, thread_rows))
        events.sort(key=lambda x: x[0])
        if mark_ts:
            events = [(d, rs) for d, rs in events
                      if max((r.timestamp for r in rs), default="") >= mark_ts]
        return [r for _, rs in events for r in rs]

    @staticmethod
    def from_raw(
        config: Config,
        marks: Marks,
        args: ReportArgs,
        raw: GithubRawData,
    ) -> "GithubData":
        all_prs = GithubPR.from_graph_ql(raw.pr_nodes, config, args)
        if not args.include_drafts:
            all_prs = [pr for pr in all_prs if not pr.isDraft]
        all_prs.sort(key=lambda pr: pr.number)
        rows_marked, rows_all = [
            {
                pr.number: GithubData._collect_comments(
                    config, marks, args, raw, pr.number, apply_mark=apply_mark)  
                for pr in all_prs
            }
                for apply_mark in [True, False]
        ]
        unresolved_counts = {
            pr.number: raw.unresolved_thread_counts(pr.number, config)
            for pr in all_prs
        }
        last_activity = {
            pr.number: raw.last_activity_timestamp(pr.number)
            for pr in all_prs
        }
        return GithubData(all_prs=all_prs, loc_results=raw.loc_results,
                          rows_marked=rows_marked, rows_all=rows_all,
                          unresolved_counts=unresolved_counts, last_activity=last_activity)
