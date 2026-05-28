import re
import sys
from typing import Any, Callable


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
_YT_RE   = re.compile(r'^([A-Za-z0-9][A-Za-z0-9-]*)-(\d+)')

def _ljust_ansi(s: str, width: int) -> str:
    visible = len(_ANSI_RE.sub('', s))
    return s + ' ' * max(0, width - visible)

def _rjust_ansi(s: str, width: int) -> str:
    visible = len(_ANSI_RE.sub('', s))
    return ' ' * max(0, width - visible) + s

def _visible_len(s: str) -> int:
    return len(_ANSI_RE.sub('', s))

from .column import (
    Column, _ListError,
    TIMESTAMP_COLS,
    PULL_REQUEST_COL, TITLE_COL, AUTHOR_COL, CREATION_DATE_COL,
    LAST_COMMENT_TIME_COL, MY_LAST_COMMENT_COL, MARK_COL, LOC_COL,
    NUM_COMMENTS_COL, REVIEWERS_COL, AGE_COL, LAST_ACTIVITY_COL,
    UNRESOLVED_ALL_COL, UNRESOLVED_HUMAN_COL, UNRESOLVED_AI_COL,
    DRAFT_COL, REVIEW_OUTSTANDING_COL, VALID_COL,
    YOUTRACK_TICKET_COL, YOUTRACK_PROJECT_COL, YOUTRACK_ID_COL, YOUTRACK_STATE_COL,
    WORKDAYS_COL, COMMENT_COL, COMMENT_TIME_COL, COMMENT_AUTHOR_COL,
)
from .column_display import ColumnDisplay
from .filter_spec import FilterSpec, ColumnFilterSpec, ComparisonFilterSpec
from .sort_item import SortItem
from .config import Config
from .date_utils import fmt_ts, days_since
from .github_data import GithubComment, GithubData, GithubPR
from .github_raw_data import GithubRawData
from .marks import Marks
from .pr_context import PRContext
from .pr_number import PRNumber
from .report_args import ReportArgs
from . import youtrack
from .timely_cache import load_yt_workdays
from .report_spec import ReportSpec


# --- Module-level helpers ---

def _last_comment(ctx: PRContext, user_only: bool = False) -> str:
    rows = ctx.comments
    if user_only:
        rows = [r for r in rows if r.author == ctx.config.repo.gh_user]
    return max((r.timestamp for r in rows), default="")

def _yt_match(ctx: PRContext):
    return _YT_RE.match(ctx.pr.title)

def _timestamp_val(col: str, ctx: PRContext) -> str:
    if col not in TIMESTAMP_COLS:          return col
    if col == "creation-date":             return ctx.pr.createdAt
    if col == "last-comment-time":         return _last_comment(ctx)
    if col == "my-last-comment-time":      return _last_comment(ctx, user_only=True)
    if col == "mark":                      return ctx.marks.get(ctx.pr.number)
    return ""


# --- Named cell functions (complex columns) ---

def _cell_loc(ctx: PRContext, _: bool) -> str:
    adds, dels = ctx.loc
    return "+%d/-%d" % (adds, dels) if (adds or dels) else "-"

def _cell_reviewers(ctx: PRContext, _: bool) -> str:
    GREEN, RED, ORANGE, RESET = "\033[32m", "\033[31m", "\033[38;5;208m", "\033[0m"
    use_color = sys.stdout.isatty()
    parts = []
    for r in ctx.pr.reviewers:
        rname = ctx.config.author_name(r)
        state = ctx.pr.reviewer_states.get(r, "")
        if use_color and state == "APPROVED":            parts.append(GREEN + rname + RESET)
        elif use_color and state == "CHANGES_REQUESTED": parts.append(RED + rname + RESET)
        elif use_color and state == "COMMENTED":         parts.append(ORANGE + rname + RESET)
        else:                                            parts.append(rname)
    return ", ".join(parts)

def _cell_valid(ctx: PRContext, _: bool) -> str:
    _, _, ua = ctx.unresolved
    m = _yt_match(ctx)
    yt_state     = ctx.youtrack_states.get(m.group(1) + "-" + m.group(2), "") if m else ""
    all_approved = bool(ctx.pr.reviewers) and all(
        ctx.pr.reviewer_states.get(r, "") == "APPROVED" for r in ctx.pr.reviewers)
    yt_ok    = (m is not None and yt_state == "Review") or ("documentation" in ctx.pr.labels and m is None)
    is_valid = bool(ctx.pr.reviewers) and (ua == 0 or all_approved) and yt_ok
    return "true" if is_valid else "false"

def _cell_workdays(ctx: PRContext, _: bool) -> str:
    m = _yt_match(ctx)
    if not m: return ""
    tid = (m.group(1) + "-" + m.group(2)).upper()
    tid = ctx.config.timely_yt_map.get(tid, tid)
    wd = ctx.yt_workdays.get(tid)
    return "" if wd is None else "%.1f" % wd

def _cell_yt_state(ctx: PRContext, _: bool) -> str:
    m = _yt_match(ctx)
    if not m: return "MISSING"
    return ctx.youtrack_states.get(m.group(1) + "-" + m.group(2), "—")


# --- Named sort-key functions (complex columns) ---

def _sort_key_workdays(ctx: PRContext) -> float:
    m = _yt_match(ctx)
    if not m: return float("inf")
    tid = (m.group(1) + "-" + m.group(2)).upper()
    tid = ctx.config.timely_yt_map.get(tid, tid)
    wd = ctx.yt_workdays.get(tid)
    return wd if wd is not None else float("inf")

def _sort_key_yt_id(ctx: PRContext) -> int:
    m = _yt_match(ctx)
    return int(m.group(2)) if m else 10**18

def _sort_key_yt_state(ctx: PRContext) -> str:
    m = _yt_match(ctx)
    if not m: return "MISSING"
    return ctx.youtrack_states.get(m.group(1) + "-" + m.group(2), "MISSING")


# --- Dispatch tables ---

_CELL_FNS: dict[Column, Callable[[PRContext, bool], str]] = {
    PULL_REQUEST_COL:       lambda ctx, _:  "#%-5s" % ctx.pr.number,
    TITLE_COL:              lambda ctx, _:  ctx.pr.title[:58],
    AUTHOR_COL:             lambda ctx, _:  ctx.config.author_name(ctx.pr.author),
    CREATION_DATE_COL:      lambda ctx, st: fmt_ts(ctx.pr.createdAt, st),
    LAST_COMMENT_TIME_COL:  lambda ctx, st: fmt_ts(_last_comment(ctx), st),
    MY_LAST_COMMENT_COL:    lambda ctx, st: fmt_ts(_last_comment(ctx, user_only=True), st, blank_if_empty=True),
    MARK_COL:               lambda ctx, st: fmt_ts(ctx.marks.get(ctx.pr.number), st, blank_if_empty=True),
    LOC_COL:                _cell_loc,
    NUM_COMMENTS_COL:       lambda ctx, _:  str(len(ctx.marked_comments)),
    REVIEWERS_COL:          _cell_reviewers,
    AGE_COL:                lambda ctx, _:  "" if (d := days_since(ctx.pr.createdAt)) is None else str(d),
    LAST_ACTIVITY_COL:      lambda ctx, _:  "" if (d := days_since(ctx.last_activity_ts)) is None else str(d),
    UNRESOLVED_ALL_COL:     lambda ctx, _:  str(ctx.unresolved[0]) if ctx.unresolved[0] else "",
    UNRESOLVED_HUMAN_COL:   lambda ctx, _:  str(ctx.unresolved[1]) if ctx.unresolved[1] else "",
    UNRESOLVED_AI_COL:      lambda ctx, _:  str(ctx.unresolved[2]) if ctx.unresolved[2] else "",
    DRAFT_COL:              lambda ctx, _:  "true" if ctx.pr.isDraft else "false",
    REVIEW_OUTSTANDING_COL: lambda ctx, _:  ", ".join(
        ctx.config.author_name(r) for r in ctx.pr.reviewers
        if ctx.pr.reviewer_states.get(r, "") not in ("APPROVED", "CHANGES_REQUESTED")),
    VALID_COL:              _cell_valid,
    YOUTRACK_TICKET_COL:    lambda ctx, _:  (m := _yt_match(ctx)) and m.group(1) + "-" + m.group(2) or "MISSING",
    YOUTRACK_PROJECT_COL:   lambda ctx, _:  (m := _yt_match(ctx)) and m.group(1) or "MISSING",
    YOUTRACK_ID_COL:        lambda ctx, _:  (m := _yt_match(ctx)) and m.group(2) or "MISSING",
    YOUTRACK_STATE_COL:     _cell_yt_state,
    WORKDAYS_COL:           _cell_workdays,
    COMMENT_COL:            lambda ctx, _:  "",
    COMMENT_TIME_COL:       lambda ctx, _:  "",
    COMMENT_AUTHOR_COL:     lambda ctx, _:  "",
}

_SORT_KEY_FNS: dict[Column, Callable[[PRContext], Any]] = {
    PULL_REQUEST_COL:       lambda ctx: ctx.pr.number,
    TITLE_COL:              lambda ctx: ctx.pr.title.lower(),
    AUTHOR_COL:             lambda ctx: ctx.config.author_name(ctx.pr.author).lower(),
    CREATION_DATE_COL:      lambda ctx: ctx.pr.createdAt or "",
    LAST_COMMENT_TIME_COL:  lambda ctx: _last_comment(ctx) or "",
    MY_LAST_COMMENT_COL:    lambda ctx: _last_comment(ctx, user_only=True) or "",
    MARK_COL:               lambda ctx: ctx.marks.get(ctx.pr.number) or "",
    LOC_COL:                lambda ctx: sum(ctx.loc),
    NUM_COMMENTS_COL:       lambda ctx: len(ctx.marked_comments),
    AGE_COL:                lambda ctx: days_since(ctx.pr.createdAt) or 0,
    LAST_ACTIVITY_COL:      lambda ctx: -1 if (d := days_since(ctx.last_activity_ts)) is None else d,
    UNRESOLVED_ALL_COL:     lambda ctx: ctx.unresolved[0],
    UNRESOLVED_HUMAN_COL:   lambda ctx: ctx.unresolved[1],
    UNRESOLVED_AI_COL:      lambda ctx: ctx.unresolved[2],
    REVIEWERS_COL:          lambda ctx: ", ".join(ctx.config.author_name(r) for r in ctx.pr.reviewers).lower(),
    DRAFT_COL:              lambda ctx: ctx.pr.isDraft,
    REVIEW_OUTSTANDING_COL: lambda ctx: ", ".join(
        ctx.config.author_name(r) for r in ctx.pr.reviewers
        if ctx.pr.reviewer_states.get(r, "") not in ("APPROVED", "CHANGES_REQUESTED")).lower(),
    VALID_COL:              lambda ctx: _cell_valid(ctx, False) == "true",
    YOUTRACK_TICKET_COL:    lambda ctx: (m := _yt_match(ctx)) and m.group(1) + "-" + m.group(2) or "MISSING",
    YOUTRACK_PROJECT_COL:   lambda ctx: (m := _yt_match(ctx)) and m.group(1) or "MISSING",
    YOUTRACK_ID_COL:        _sort_key_yt_id,
    YOUTRACK_STATE_COL:     _sort_key_yt_state,
    WORKDAYS_COL:           _sort_key_workdays,
}


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

    def compute_show_time(ctx: PRContext) -> set[str]:
        date_to_cols: dict[str, list[str]] = {}
        for col in cols:
            if not col.is_timestamp: continue
            val = _timestamp_val(col.name, ctx)
            if not val: continue
            date_to_cols.setdefault(val[:10], []).append(col.name)
        return {c for date_cols in date_to_cols.values() if len(date_cols) > 1 for c in date_cols}

    def cell(col: ColumnDisplay, ctx: PRContext, show_time: bool = False) -> str:
        return _CELL_FNS.get(col.column, lambda _ctx, _st: "")(ctx, show_time)

    if sort_cols:
        def sort_key(pr: GithubPR) -> list[Any]:
            ctx = make_ctx(pr)
            key: list[Any] = []
            for si in sort_cols:
                v = _SORT_KEY_FNS.get(si.column, lambda _: "")(ctx)
                key.append(_Rev(v) if si.reverse else v)
            return key
        all_prs.sort(key=sort_key)

    def _col_filter_val(fs: ColumnFilterSpec, ctx: PRContext) -> str:
        if fs.column == PULL_REQUEST_COL: return str(ctx.pr.number)
        return cell(ColumnDisplay(fs.column), ctx)

    def _comparison_result(fs: ComparisonFilterSpec, ctx: PRContext) -> bool:
        lv = _timestamp_val(fs.left,  ctx) or "1970-01-01T00:00:00Z"
        rv = _timestamp_val(fs.right, ctx) or "1970-01-01T00:00:00Z"
        return (lv > rv if fs.op == ">" else lv < rv if fs.op == "<" else
                lv >= rv if fs.op == ">=" else lv <= rv if fs.op == "<=" else lv == rv)

    def _pr_passes_filter(ctx: PRContext, fs: FilterSpec) -> bool:
        if isinstance(fs, ComparisonFilterSpec):
            return _comparison_result(fs, ctx)
        assert isinstance(fs, ColumnFilterSpec)
        if fs.column == REVIEWERS_COL:
            reviewer_names = {ctx.config.author_name(r) for r in ctx.pr.reviewers}
            matched = (not ctx.pr.reviewers and "none" in fs.values) or bool(reviewer_names & fs.values)
            return not matched if fs.negate else matched
        if fs.column == REVIEW_OUTSTANDING_COL:
            outstanding = {ctx.config.author_name(r) for r in ctx.pr.reviewers
                           if ctx.pr.reviewer_states.get(r, "") not in ("APPROVED", "CHANGES_REQUESTED")}
            matched = (not outstanding and "none" in fs.values) or bool(outstanding & fs.values)
            return not matched if fs.negate else matched
        val = _col_filter_val(fs, ctx)
        return (val not in fs.values) if fs.negate else (val in fs.values)

    def _uses_comment_time(fs: FilterSpec) -> bool:
        if isinstance(fs, ColumnFilterSpec):     return fs.column == COMMENT_TIME_COL
        if isinstance(fs, ComparisonFilterSpec): return "comment-time" in (fs.left, fs.right)
        return False

    pr_filters      = [fs for fs in filters if not _uses_comment_time(fs)]
    comment_filters = [fs for fs in filters if     _uses_comment_time(fs)]

    if {YOUTRACK_STATE_COL, VALID_COL} & spec.all_cols and config.youtrack_url and config.youtrack_token:
        ticket_ids = [m.group(1) + "-" + m.group(2) for pr in all_prs if (m := _YT_RE.match(pr.title))]
        if ticket_ids:
            youtrack_states = youtrack.fetch_states(config.youtrack_url, config.youtrack_token, ticket_ids)

    if pr_filters:
        all_prs = [pr for pr in all_prs if all(_pr_passes_filter(make_ctx(pr), fs) for fs in pr_filters)]

    _COMMENT_COLS    = frozenset({COMMENT_COL, COMMENT_TIME_COL, COMMENT_AUTHOR_COL})
    _comment_in_cols = any(col.column in _COMMENT_COLS for col in cols)
    comment_source   = rows_all if args.include_pre_mark_commits else rows_marked

    rows = []
    for pr in all_prs:
        ctx = make_ctx(pr)
        stc = compute_show_time(ctx)
        if _comment_in_cols:
            def comment_cell(col: ColumnDisplay, cr: GithubComment) -> str:
                if col.column == COMMENT_COL:        return cr.body.split("\n")[0][:70]
                if col.column == COMMENT_TIME_COL:   return fmt_ts(cr.timestamp, show_time=True)
                if col.column == COMMENT_AUTHOR_COL: return ctx.config.author_name(cr.author)
                return cell(col, ctx, col.name in stc)

            def _comment_ts_val(col: str, cr: GithubComment) -> str:
                if col == "comment-time": return cr.timestamp
                return _timestamp_val(col, ctx)

            def _comment_filter_val(fs: FilterSpec, cr: GithubComment) -> bool:
                if isinstance(fs, ComparisonFilterSpec):
                    lv = _comment_ts_val(fs.left,  cr) or "1970-01-01T00:00:00Z"
                    rv = _comment_ts_val(fs.right, cr) or "1970-01-01T00:00:00Z"
                    return (lv > rv if fs.op == ">" else lv < rv if fs.op == "<" else
                            lv >= rv if fs.op == ">=" else lv <= rv if fs.op == "<=" else lv == rv)
                assert isinstance(fs, ColumnFilterSpec)
                if fs.column == COMMENT_TIME_COL:
                    val = fmt_ts(cr.timestamp, show_time=True)
                    return (val not in fs.values) if fs.negate else (val in fs.values)
                return _pr_passes_filter(ctx, fs)

            for cr in comment_source.get(pr.number, []):
                if not comment_filters or all(_comment_filter_val(fs, cr) for fs in comment_filters):
                    rows.append([comment_cell(col, cr) for col in cols])
        else:
            rows.append([cell(col, ctx, col.name in stc) for col in cols])
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
