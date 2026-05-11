from dataclasses import dataclass
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
        if not stripped or stripped in config.ignored_comments:
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

    @staticmethod
    def from_graph_ql(nodes: list[Node]) -> list["GithubPR"]:
        result = []
        for node in nodes:
            author_dict = node.get("author") or {}
            result.append(GithubPR(
                number=PRNumber(node["number"]),
                title=node["title"],
                isDraft=node.get("isDraft", False),
                createdAt=node.get("createdAt", ""),
                author=author_dict.get("login", ""),
            ))
        return result


@dataclass
class GithubData:
    all_prs: list[GithubPR]
    loc_results: dict[PRNumber, LOC]
    rows_marked: dict[PRNumber, list[GithubComment]]
    rows_all: dict[PRNumber, list[GithubComment]]

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
        all_prs = GithubPR.from_graph_ql(raw.pr_nodes)
        all_prs.sort(key=lambda pr: pr.number)
        rows_marked, rows_all = [
            {
                pr.number: GithubData._collect_comments(
                    config, marks, args, raw, pr.number, apply_mark=apply_mark)  
                for pr in all_prs
            }
                for apply_mark in [True, False]
        ]
        return GithubData(all_prs=all_prs, loc_results=raw.loc_results, rows_marked=rows_marked, rows_all=rows_all)
