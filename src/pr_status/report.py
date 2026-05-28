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
_YT_RE   = re.compile(r'^([A-Za-z0-9][A-Za-z0-9-]*)-(\d+)')

def _ljust_ansi(s: str, width: int) -> str:
    visible = len(_ANSI_RE.sub('', s))
    return s + ' ' * max(0, width - visible)

def _rjust_ansi(s: str, width: int) -> str:
    visible = len(_ANSI_RE.sub('', s))
    return ' ' * max(0, width - visible) + s

def _visible_len(s: str) -> int:
    return len(_ANSI_RE.sub('', s))

from .column import Column, FilterSpec
from .config import Config
from .date_utils import fmt_ts, days_since
from .github_data import GithubComment, GithubData, GithubPR
from .github_raw_data import GithubRawData
from .marks import Marks
from .pr_number import PRNumber
from .report_args import ReportArgs
from . import youtrack
from .timely_cache import load_yt_workdays
from .report_spec import (
    ColumnFilterSpec, ComparisonFilterSpec, _ListError,
    TIMESTAMP_COLS, col_header, col_header_lines, col_is_numeric, col_width,
    ReportSpec,
)


def run_report(
    config: Config,
    marks: Marks,
    args: ReportArgs,
) -> None:
    try:
        spec = ReportSpec.resolve(args)
        raw  = GithubRawData.fetch(config, spec.all_cols)
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
    yt_workdays: dict[str, float] = load_yt_workdays() if "workdays" in spec.all_cols else {}

    def get_author(pr: GithubPR) -> str:
        return config.author_name(pr.author)

    def count_since(pr_num: PRNumber) -> int:
        return len(rows_marked.get(pr_num, []))

    def get_last_comment(pr_num: PRNumber, user_only: bool = False) -> str:
        rows = rows_all.get(pr_num, [])
        if user_only:
            rows = [r for r in rows if r.author == config.repo.gh_user]
        return max((r.timestamp for r in rows), default="")

    def timestamp_val(col: str, pr: GithubPR) -> str:
        if col not in TIMESTAMP_COLS:     return col  # date literal
        if col == "creation-date":        return pr.createdAt
        if col == "last-comment-time":    return get_last_comment(pr.number)
        if col == "my-last-comment-time": return get_last_comment(pr.number, user_only=True)
        if col == "mark":                 return marks.get(pr.number)
        return ""

    def compute_show_time(pr: GithubPR) -> set[str]:
        date_to_cols: dict[str, list[str]] = {}
        for col in cols:
            if not col.is_timestamp: continue
            val = timestamp_val(col.name, pr)
            if not val: continue
            date_to_cols.setdefault(val[:10], []).append(col.name)
        return {c for date_cols in date_to_cols.values() if len(date_cols) > 1 for c in date_cols}

    if sort_cols:
        def sort_key(pr: GithubPR) -> list[Any]:
            key: list[Any] = []
            for col, rev in sort_cols:
                def k(v: Any) -> Any:
                    return _Rev(v) if rev else v
                if col == "pull-request":
                    key.append(k(pr.number))
                elif col == "title":
                    key.append(k(pr.title.lower()))
                elif col == "author":
                    key.append(k(get_author(pr).lower()))
                elif col == "creation-date":
                    key.append(k(pr.createdAt or ""))
                elif col == "last-comment-time":
                    key.append(k(get_last_comment(pr.number) or ""))
                elif col == "my-last-comment-time":
                    key.append(k(get_last_comment(pr.number, user_only=True) or ""))
                elif col == "mark":
                    key.append(k(marks.get(pr.number) or ""))
                elif col == "loc":
                    adds, dels = loc_results.get(pr.number, (0, 0))
                    key.append(k(adds + dels))
                elif col == "num-comments":
                    key.append(k(count_since(pr.number)))
                elif col == "age":
                    key.append(k(days_since(pr.createdAt) or 0))
                elif col == "last-activity":
                    d = days_since(last_activity.get(pr.number, ""))
                    key.append(k(-1 if d is None else d))
                elif col in ("unresolved (all)", "unresolved (human)", "unresolved (ai)"):
                    uc, uh, ua = unresolved_counts.get(pr.number, (0, 0, 0))
                    val = uc if col == "unresolved (all)" else uh if col == "unresolved (human)" else ua
                    key.append(k(val))
                elif col == "reviewers":
                    key.append(k(", ".join(config.author_name(r) for r in pr.reviewers).lower()))
                elif col == "draft":
                    key.append(k(pr.isDraft))
                elif col == "review-outstanding":
                    outstanding = [config.author_name(r) for r in pr.reviewers
                                   if pr.reviewer_states.get(r, "") not in ("APPROVED", "CHANGES_REQUESTED")]
                    key.append(k(", ".join(outstanding).lower()))
                elif col == "valid":
                    _, _, ua = unresolved_counts.get(pr.number, (0, 0, 0))
                    m = _YT_RE.match(pr.title)
                    yt_state = youtrack_states.get(m.group(1) + "-" + m.group(2), "") if m else ""
                    all_approved = bool(pr.reviewers) and all(pr.reviewer_states.get(r, "") == "APPROVED" for r in pr.reviewers)
                    yt_ok = (m is not None and yt_state == "Review") or ("documentation" in pr.labels and m is None)
                    is_valid = bool(pr.reviewers) and (ua == 0 or all_approved) and yt_ok
                    key.append(k(is_valid))
                elif col == "youtrack-ticket":
                    m = _YT_RE.match(pr.title)
                    key.append(k(m.group(1) + '-' + m.group(2) if m else "MISSING"))
                elif col == "youtrack-project":
                    m = _YT_RE.match(pr.title)
                    key.append(k(m.group(1) if m else "MISSING"))
                elif col == "youtrack-id":
                    m = _YT_RE.match(pr.title)
                    key.append(k(int(m.group(2)) if m else 10**18))
                elif col == "youtrack-state":
                    m = _YT_RE.match(pr.title)
                    tid = m.group(1) + "-" + m.group(2) if m else None
                    key.append(k(youtrack_states.get(tid, "MISSING") if tid else "MISSING"))
                elif col == "workdays":
                    m = _YT_RE.match(pr.title)
                    if m:
                        tid = (m.group(1) + "-" + m.group(2)).upper()
                        tid = config.timely_yt_map.get(tid, tid)
                        wd = yt_workdays.get(tid)
                    else:
                        wd = None
                    key.append(k(wd if wd is not None else float("inf")))
            return key
        all_prs.sort(key=sort_key)

    def cell(
        col: Column,
        pr: GithubPR,
        show_time_cols: frozenset[str] = frozenset(),
    ) -> str:
        name = col.name
        if name == "pull-request":         return "#%-5s" % pr.number
        if name == "title":                return pr.title[:58]
        if name == "author":               return get_author(pr)
        if name == "creation-date":        return fmt_ts(pr.createdAt, name in show_time_cols)
        if name == "last-comment-time":    return fmt_ts(get_last_comment(pr.number), name in show_time_cols)
        if name == "my-last-comment-time": return fmt_ts(get_last_comment(pr.number, user_only=True), name in show_time_cols, blank_if_empty=True)
        if name == "mark":                 return fmt_ts(marks.get(pr.number), name in show_time_cols, blank_if_empty=True)
        if name == "loc":
            adds, dels = loc_results.get(pr.number, (0, 0))
            return "+%d/-%d" % (adds, dels) if (adds or dels) else "-"
        if name == "num-comments":
            return str(count_since(pr.number))
        if name == "reviewers":
            GREEN, RED, ORANGE, RESET = "\033[32m", "\033[31m", "\033[38;5;208m", "\033[0m"
            use_color = sys.stdout.isatty()
            parts = []
            for r in pr.reviewers:
                rname = config.author_name(r)
                state = pr.reviewer_states.get(r, "")
                if use_color and state == "APPROVED":
                    parts.append(GREEN + rname + RESET)
                elif use_color and state == "CHANGES_REQUESTED":
                    parts.append(RED + rname + RESET)
                elif use_color and state == "COMMENTED":
                    parts.append(ORANGE + rname + RESET)
                else:
                    parts.append(rname)
            return ", ".join(parts)
        if name == "age":
            d = days_since(pr.createdAt)
            return "" if d is None else str(d)
        if name == "last-activity":
            d = days_since(last_activity.get(pr.number, ""))
            return "" if d is None else str(d)
        if name in ("unresolved (all)", "unresolved (human)", "unresolved (ai)"):
            uc, uh, ua = unresolved_counts.get(pr.number, (0, 0, 0))
            val = uc if name == "unresolved (all)" else uh if name == "unresolved (human)" else ua
            return str(val) if val else ""
        if name == "draft":
            return "true" if pr.isDraft else "false"
        if name == "review-outstanding":
            outstanding = [config.author_name(r) for r in pr.reviewers
                           if pr.reviewer_states.get(r, "") not in ("APPROVED", "CHANGES_REQUESTED")]
            return ", ".join(outstanding)
        if name == "valid":
            _, _, ua = unresolved_counts.get(pr.number, (0, 0, 0))
            m = _YT_RE.match(pr.title)
            yt_state = youtrack_states.get(m.group(1) + "-" + m.group(2), "") if m else ""
            all_approved = bool(pr.reviewers) and all(pr.reviewer_states.get(r, "") == "APPROVED" for r in pr.reviewers)
            yt_ok = (m is not None and yt_state == "Review") or ("documentation" in pr.labels and m is None)
            is_valid = bool(pr.reviewers) and (ua == 0 or all_approved) and yt_ok
            return "true" if is_valid else "false"
        if name == "youtrack-ticket":
            m = _YT_RE.match(pr.title)
            return m.group(1) + '-' + m.group(2) if m else "MISSING"
        if name == "youtrack-project":
            m = _YT_RE.match(pr.title)
            return m.group(1) if m else "MISSING"
        if name == "youtrack-id":
            m = _YT_RE.match(pr.title)
            return m.group(2) if m else "MISSING"
        if name == "youtrack-state":
            m = _YT_RE.match(pr.title)
            if not m:
                return "MISSING"
            tid = m.group(1) + "-" + m.group(2)
            return youtrack_states.get(tid, "—")
        if name == "workdays":
            m = _YT_RE.match(pr.title)
            if not m:
                return ""
            tid = (m.group(1) + "-" + m.group(2)).upper()
            tid = config.timely_yt_map.get(tid, tid)
            wd = yt_workdays.get(tid)
            return "" if wd is None else "%.1f" % wd
        if name in ("comment", "comment-time", "comment-author"): return ""
        return ""

    def _col_filter_val(fs: ColumnFilterSpec, pr: GithubPR) -> str:
        if fs.column.name == "pull-request": return str(pr.number)
        return cell(fs.column, pr, compute_show_time(pr))

    def _comparison_result(fs: ComparisonFilterSpec, pr: GithubPR) -> bool:
        lv = timestamp_val(fs.left,  pr) or "1970-01-01T00:00:00Z"
        rv = timestamp_val(fs.right, pr) or "1970-01-01T00:00:00Z"
        return (lv > rv if fs.op == ">" else lv < rv if fs.op == "<" else
                lv >= rv if fs.op == ">=" else lv <= rv if fs.op == "<=" else lv == rv)

    def _pr_passes_filter(pr: GithubPR, fs: FilterSpec) -> bool:
        if isinstance(fs, ComparisonFilterSpec):
            return _comparison_result(fs, pr)
        assert isinstance(fs, ColumnFilterSpec)
        if fs.column.name == "reviewers":
            reviewer_names = {config.author_name(r) for r in pr.reviewers}
            matched = (not pr.reviewers and "none" in fs.values) or bool(reviewer_names & fs.values)
            return not matched if fs.negate else matched
        if fs.column.name == "review-outstanding":
            outstanding = {config.author_name(r) for r in pr.reviewers
                           if pr.reviewer_states.get(r, "") not in ("APPROVED", "CHANGES_REQUESTED")}
            matched = (not outstanding and "none" in fs.values) or bool(outstanding & fs.values)
            return not matched if fs.negate else matched
        val = _col_filter_val(fs, pr)
        return (val not in fs.values) if fs.negate else (val in fs.values)

    def _uses_comment_time(fs: FilterSpec) -> bool:
        if isinstance(fs, ColumnFilterSpec):    return fs.column.name == "comment-time"
        if isinstance(fs, ComparisonFilterSpec): return "comment-time" in (fs.left, fs.right)
        return False

    pr_filters      = [fs for fs in filters if not _uses_comment_time(fs)]
    comment_filters = [fs for fs in filters if     _uses_comment_time(fs)]

    if spec.all_cols & {"youtrack-state", "valid"} and config.youtrack_url and config.youtrack_token:
        ticket_ids = [m.group(1) + "-" + m.group(2) for pr in all_prs if (m := _YT_RE.match(pr.title))]
        if ticket_ids:
            youtrack_states = youtrack.fetch_states(config.youtrack_url, config.youtrack_token, ticket_ids)

    if pr_filters:
        all_prs = [pr for pr in all_prs if all(_pr_passes_filter(pr, fs) for fs in pr_filters)]

    _COMMENT_NAMES = frozenset({"comment", "comment-time", "comment-author"})
    _comment_in_cols = any(col.name in _COMMENT_NAMES for col in cols)

    def comment_cell(col: Column, cr: GithubComment) -> str:
        if col.name == "comment":        return cr.body.split("\n")[0][:70]
        if col.name == "comment-time":   return fmt_ts(cr.timestamp, show_time=True)
        if col.name == "comment-author": return config.author_name(cr.author)
        return cell(col, pr, stc)

    def _comment_ts_val(col: str, cr: GithubComment) -> str:
        if col == "comment-time": return cr.timestamp
        return timestamp_val(col, pr)

    def _comment_filter_val(fs: FilterSpec, cr: GithubComment) -> bool:
        if isinstance(fs, ComparisonFilterSpec):
            lv = _comment_ts_val(fs.left,  cr) or "1970-01-01T00:00:00Z"
            rv = _comment_ts_val(fs.right, cr) or "1970-01-01T00:00:00Z"
            return (lv > rv if fs.op == ">" else lv < rv if fs.op == "<" else
                    lv >= rv if fs.op == ">=" else lv <= rv if fs.op == "<=" else lv == rv)
        assert isinstance(fs, ColumnFilterSpec)
        if fs.column.name == "comment-time":
            val = fmt_ts(cr.timestamp, show_time=True)
            return (val not in fs.values) if fs.negate else (val in fs.values)
        return _pr_passes_filter(pr, fs)

    def _comment_passes_filters(cr: GithubComment) -> bool:
        return all(_comment_filter_val(fs, cr) for fs in comment_filters)

    comment_source = rows_all if args.include_pre_mark_commits else rows_marked

    rows = []
    for pr in all_prs:
        stc = compute_show_time(pr)
        if _comment_in_cols:
            for cr in comment_source.get(pr.number, []):
                if not comment_filters or _comment_passes_filters(cr):
                    rows.append([comment_cell(col, cr) for col in cols])
        else:
            rows.append([cell(col, pr, stc) for col in cols])
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
    numeric_idx = [i for i, c in enumerate(cols) if col_is_numeric(c)]
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
                    new_row[ni] = ("%.1f" % t) if c.name == "workdays" else str(int(t))
            rows.append(new_row)

    hdr_lines = [col_header_lines(c) for c in cols]
    widths = [max(col_width(c), max(_visible_len(l) for l in hdr_lines[i])) for i, c in enumerate(cols)]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], _visible_len(val))

    def fmt_row(vals: list[str]) -> str:
        parts = []
        for i, (c, val) in enumerate(zip(cols, vals)):
            if col_is_numeric(c):
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
                totals[i] = ("%.1f" % total) if c.name == "workdays" else str(int(total))
        print(fmt_row(["-" * widths[i] for i in range(len(cols))]))
        print(fmt_row(totals))
