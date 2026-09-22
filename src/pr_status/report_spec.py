from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._util import timing_log
from .column import Column
from .column_display import ColumnDisplay
from .config import Config
from .filter_spec import FilterSpec
from .github_data import GithubData
from .github_raw_data import GithubRawData
from .marks import Marks
from .node import Node
from .sort_item import SortItem
from .report_args import ReportArgs

if TYPE_CHECKING:
    from .pr_context import PRContext


@dataclass
class ReportSpec:
    cols:      list[ColumnDisplay]
    sort_cols: list[SortItem]
    filters:   list[FilterSpec]

    @property
    def all_cols(self) -> set[Column]:
        return (
            {cd.column for cd in self.cols}
            | {col for fs in self.filters for col in fs.all_cols}
            | {si.column for si in self.sort_cols}
        )

    @property
    def needs_youtrack(self) -> bool:
        """Whether any column the report uses is read from a YouTrack ticket."""
        return any(col.needs_youtrack for col in self.all_cols)

    @property
    def youtrack_cols(self) -> list[Column]:
        """The columns the report reads from YouTrack, named so an error can say which."""
        return sorted((col for col in self.all_cols if col.needs_youtrack), key=lambda c: c.name)

    @property
    def pre_fetch_filters(self) -> list[FilterSpec]:
        """The filters decidable from the light PR query alone, so they can be applied
        before the per-PR comment/LOC fetch rather than after it. A filter naming no
        column at all — a comparison of two date literals — is left out: `all` over an
        empty set would wave it through, which is the wrong default here."""
        return [fs for fs in self.filters
                if fs.all_cols and all(col.from_light_query for col in fs.all_cols)]

    def search_qualifiers(self, config: Config) -> list[str]:
        """What the report's filters contribute to the GitHub search for the PR list."""
        return [q for fs in self.filters for q in fs.search_qualifiers(config)]

    def narrow_pr_nodes(
        self, config: Config, marks: Marks, args: ReportArgs, pr_nodes: list[Node],
    ) -> list[Node]:
        """Drop the PR nodes a light-query-only filter already excludes, so nothing is
        fetched for a PR that cannot appear in the report. Purely an optimisation: the
        authoritative filtering still runs in _report_data_lines over whatever survives,
        so a column wrongly marked from_light_query would cost a wasted fetch at worst.
        """
        filters = self.pre_fetch_filters
        if not filters:
            return pr_nodes
        raw  = GithubRawData(pr_nodes=pr_nodes, loc_results={}, comment_data={})
        data = GithubData.from_raw(config, marks, args, raw)
        kept = {pr.number for pr in data.all_prs
                if all(fs.matches(data.make_ctx(pr, config, marks, {})) for fs in filters)}
        narrowed = [n for n in pr_nodes if n["number"] in kept]
        if len(narrowed) < len(pr_nodes):
            timing_log("pre-fetch filter: %d of %d PRs kept" % (len(narrowed), len(pr_nodes)))
        return narrowed

    def show_time_cols(self, ctx: "PRContext") -> set[str]:
        from .columns import _timestamp_val
        date_to_cols: dict[str, list[str]] = {}
        for col in self.cols:
            if not col.is_timestamp: continue
            val = _timestamp_val(col.name, ctx)
            if not val: continue
            date_to_cols.setdefault(val[:10], []).append(col.name)
        return {c for date_cols in date_to_cols.values() if len(date_cols) > 1 for c in date_cols}

    @staticmethod
    def resolve(args: ReportArgs, me: str = "") -> "ReportSpec":
        cols      = [ColumnDisplay.resolve(c) for c in args.columns.split(",") if c.strip()]
        sort_cols = [SortItem.resolve(c) for c in args.sort.split(",") if c.strip()] if args.sort else []
        filters   = [FilterSpec.resolve(f, me) for f in args.filters if f.strip()]
        return ReportSpec(cols=cols, sort_cols=sort_cols, filters=filters)
