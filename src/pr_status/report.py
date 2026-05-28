import re
import sys
from typing import Any


class _Rev:
    """Wraps a value so it sorts in reverse order."""
    __slots__ = ("val",)
    def __init__(self, val: Any) -> None: self.val = val
    def __lt__(self, o: "_Rev") -> bool: return self.val > o.val
    def __le__(self, o: "_Rev") -> bool: return self.val >= o.val
    def __gt__(self, o: "_Rev") -> bool: return self.val < o.val
    def __ge__(self, o: "_Rev") -> bool: return self.val <= o.val
    def __eq__(self, o: object) -> bool: return isinstance(o, _Rev) and self.val == o.val

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

def _ljust_ansi(s: str, width: int) -> str:
    visible = len(_ANSI_RE.sub('', s))
    return s + ' ' * max(0, width - visible)

def _rjust_ansi(s: str, width: int) -> str:
    visible = len(_ANSI_RE.sub('', s))
    return ' ' * max(0, width - visible) + s

def _visible_len(s: str) -> int:
    return len(_ANSI_RE.sub('', s))

from .column import _ListError
from .column_display import ColumnDisplay
from .columns import (
    _YT_RE,
    YOUTRACK_STATE_COL, VALID_COL, WORKDAYS_COL,
)
from .filter_spec import FilterSpec
from .sort_item import SortItem
from .config import Config
from .github_data import GithubData, GithubPR
from .github_raw_data import GithubRawData
from .marks import Marks
from .pr_context import PRContext
from .report_args import ReportArgs
from . import youtrack
from .timely_cache import load_yt_workdays
from .report_spec import ReportSpec


def run_report(
    config: Config,
    marks: Marks,
    args: ReportArgs,
) -> None:
    try:
        spec = ReportSpec.resolve(args)
        raw  = GithubRawData.fetch(config, {col.name for col in spec.all_cols})
        data = GithubData.from_raw(config, marks, args, raw)
        _render_report(config, marks, args, spec, data)
    except _ListError as e:
        print(str(e), file=sys.stderr)


def _report_data_lines(
    config: Config,
    marks: Marks,
    args: ReportArgs,
    spec: ReportSpec,
    data: GithubData,
) -> list[list[str]]:
    cols              = spec.cols
    sort_cols         = spec.sort_cols
    filters           = spec.filters
    all_prs           = data.all_prs
    loc_results       = data.loc_results
    rows_marked       = data.rows_marked
    rows_all          = data.rows_all
    unresolved_counts = data.unresolved_counts
    last_activity     = data.last_activity
    youtrack_states   = data.youtrack_states
    yt_workdays: dict[str, float] = load_yt_workdays() if WORKDAYS_COL in spec.all_cols else {}

    def make_ctx(pr: GithubPR) -> PRContext:
        return PRContext(
            config=config, marks=marks, pr=pr,
            comments=rows_all.get(pr.number, []),
            marked_comments=rows_marked.get(pr.number, []),
            loc=loc_results.get(pr.number, (0, 0)),
            unresolved=unresolved_counts.get(pr.number, (0, 0, 0)),
            last_activity_ts=last_activity.get(pr.number, ""),
            youtrack_states=youtrack_states,
            yt_workdays=yt_workdays,
        )

    if sort_cols:
        def sort_key(pr: GithubPR) -> list[Any]:
            ctx = make_ctx(pr)
            key: list[Any] = []
            for si in sort_cols:
                v = si.column.sort_key(ctx)
                key.append(_Rev(v) if si.reverse else v)
            return key
        all_prs.sort(key=sort_key)

    pr_filters      = [fs for fs in filters if not fs.uses_comment_time]
    comment_filters = [fs for fs in filters if     fs.uses_comment_time]

    if {YOUTRACK_STATE_COL, VALID_COL} & spec.all_cols and config.youtrack_url and config.youtrack_token:
        ticket_ids = [m.group(1) + "-" + m.group(2) for pr in all_prs if (m := _YT_RE.match(pr.title))]
        if ticket_ids:
            youtrack_states = youtrack.fetch_states(config.youtrack_url, config.youtrack_token, ticket_ids)

    if pr_filters:
        all_prs = [pr for pr in all_prs if all(fs.matches(make_ctx(pr)) for fs in pr_filters)]

    from .columns import COMMENT_COL, COMMENT_TIME_COL, COMMENT_AUTHOR_COL
    _COMMENT_COLS    = frozenset({COMMENT_COL, COMMENT_TIME_COL, COMMENT_AUTHOR_COL})
    _comment_in_cols = any(col.column in _COMMENT_COLS for col in cols)
    comment_source   = rows_all if args.include_pre_mark_commits else rows_marked

    rows = []
    for pr in all_prs:
        ctx = make_ctx(pr)
        stc = spec.show_time_cols(ctx)
        if _comment_in_cols:
            for cr in comment_source.get(pr.number, []):
                if not comment_filters or all(fs.matches_comment(ctx, cr) for fs in comment_filters):
                    rows.append([col.comment_cell(cr, ctx, stc) for col in cols])
        else:
            rows.append([col.cell(ctx, col.name in stc) for col in cols])
    return rows


def _render_report(
    config: Config,
    marks: Marks,
    args: ReportArgs,
    spec: ReportSpec,
    data: GithubData,
) -> None:
    cols = spec.cols
    rows = _report_data_lines(config, marks, args, spec, data)

    # Aggregate: group by non-numeric columns, sum numeric columns.
    # None means no non-blank value seen yet (displays as blank).
    numeric_idx = [i for i, c in enumerate(cols) if c.is_numeric]
    if numeric_idx:
        group_idx = [i for i in range(len(cols)) if i not in set(numeric_idx)]
        grouped: dict[tuple, list[float | None]] = {}
        order: list[tuple] = []
        display: dict[tuple, list[str]] = {}
        for row in rows:
            key = tuple(_ANSI_RE.sub('', row[i]) for i in group_idx)
            if key not in grouped:
                grouped[key] = [None] * len(numeric_idx)
                order.append(key)
                display[key] = [row[i] for i in group_idx]
            for j, ni in enumerate(numeric_idx):
                v = _ANSI_RE.sub('', row[ni]).strip()
                try:
                    fv = float(v)
                    grouped[key][j] = (grouped[key][j] or 0.0) + fv
                except ValueError:
                    pass
        rows = []
        for key in order:
            new_row = [""] * len(cols)
            for k, gi in enumerate(group_idx):
                new_row[gi] = display[key][k]
            for j, ni in enumerate(numeric_idx):
                t = grouped[key][j]
                if t is not None:
                    c = cols[ni]
                    new_row[ni] = ("%.1f" % t) if c.column == WORKDAYS_COL else str(int(t))
            rows.append(new_row)

    hdr_lines = [c.header_lines for c in cols]
    widths = [max(c.display_width, max(_visible_len(l) for l in hdr_lines[i])) for i, c in enumerate(cols)]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], _visible_len(val))

    def fmt_row(vals: list[str]) -> str:
        parts = []
        for i, (c, val) in enumerate(zip(cols, vals)):
            if c.is_numeric:
                parts.append(_rjust_ansi(val, widths[i]))
            elif i == len(cols) - 1:
                parts.append(val)
            else:
                parts.append(_ljust_ansi(val, widths[i]))
        return " ".join(parts)

    max_hdr = max(len(lines) for lines in hdr_lines)
    for line_idx in range(max_hdr):
        parts = []
        for col_idx, lines in enumerate(hdr_lines):
            text = lines[line_idx] if line_idx < len(lines) else ""
            w = widths[col_idx]
            cell_str = text.center(w) if col_idx < len(cols) - 1 else text.center(w).rstrip()
            parts.append(cell_str)
        print(" ".join(parts))

    _ROW_RESET = "\033[0m" if sys.stdout.isatty() else ""
    print(fmt_row(["-" * widths[i] for i in range(len(cols))]))
    for row in rows:
        print(fmt_row(row) + _ROW_RESET)

    if numeric_idx and rows:
        totals: list[str] = [""] * len(cols)
        for i in numeric_idx:
            total: float | None = None
            for row in rows:
                v = _ANSI_RE.sub('', row[i]).strip()
                if v and v.replace('.', '', 1).lstrip('-').isdigit():
                    total = (total or 0.0) + float(v)
            if total is not None:
                c = cols[i]
                totals[i] = ("%.1f" % total) if c.column == WORKDAYS_COL else str(int(total))
        print(fmt_row(["-" * widths[i] for i in range(len(cols))]))
        print(fmt_row(totals))
