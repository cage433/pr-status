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

from .config import Config
from .date_utils import fmt_ts, days_since
from .github_data import GithubComment, GithubData, GithubPR
from .github_raw_data import GithubRawData
from .marks import Marks
from .pr_number import PRNumber
from .report_args import ReportArgs
from . import youtrack
from .report_spec import (
    ColSpec, PlainColumn, Comparison, _ListError,
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
        for spec in cols:
            if not isinstance(spec, PlainColumn) or spec.name not in TIMESTAMP_COLS: continue
            val = timestamp_val(spec.name, pr)
            if not val: continue
            date_to_cols.setdefault(val[:10], []).append(spec.name)
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
                    is_valid = bool(pr.reviewers) and ua == 0 and m is not None and yt_state == "Review"
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
            return key
        all_prs.sort(key=sort_key)

    def cell(
        spec: ColSpec,
        pr: GithubPR,
        show_time_cols: frozenset[str] = frozenset(),
    ) -> str:
        if isinstance(spec, Comparison):
            lv = timestamp_val(spec.left,  pr) or "1970-01-01T00:00:00Z"
            rv = timestamp_val(spec.right, pr) or "1970-01-01T00:00:00Z"
            result = (lv > rv if spec.op == ">" else lv < rv if spec.op == "<" else
                      lv >= rv if spec.op == ">=" else lv <= rv if spec.op == "<=" else lv == rv)
            return "true" if result else "false"
        col = spec.name
        if col == "pull-request":         return "#%-5s" % pr.number
        if col == "title":                return pr.title[:58]
        if col == "author":               return get_author(pr)
        if col == "creation-date":        return fmt_ts(pr.createdAt, col in show_time_cols)
        if col == "last-comment-time":    return fmt_ts(get_last_comment(pr.number), col in show_time_cols)
        if col == "my-last-comment-time": return fmt_ts(get_last_comment(pr.number, user_only=True), col in show_time_cols, blank_if_empty=True)
        if col == "mark":                 return fmt_ts(marks.get(pr.number), col in show_time_cols, blank_if_empty=True)
        if col == "loc":
            adds, dels = loc_results.get(pr.number, (0, 0))
            return "+%d/-%d" % (adds, dels) if (adds or dels) else "-"
        if col == "num-comments":
            return str(count_since(pr.number))
        if col == "reviewers":
            GREEN, RED, ORANGE, RESET = "\033[32m", "\033[31m", "\033[38;5;208m", "\033[0m"
            use_color = sys.stdout.isatty()
            parts = []
            for r in pr.reviewers:
                name = config.author_name(r)
                state = pr.reviewer_states.get(r, "")
                if use_color and state == "APPROVED":
                    parts.append(GREEN + name + RESET)
                elif use_color and state == "CHANGES_REQUESTED":
                    parts.append(RED + name + RESET)
                elif use_color and state == "COMMENTED":
                    parts.append(ORANGE + name + RESET)
                else:
                    parts.append(name)
            return ", ".join(parts)
        if col == "age":
            d = days_since(pr.createdAt)
            return "" if d is None else str(d)
        if col == "last-activity":
            d = days_since(last_activity.get(pr.number, ""))
            return "" if d is None else str(d)
        if col in ("unresolved (all)", "unresolved (human)", "unresolved (ai)"):
            uc, uh, ua = unresolved_counts.get(pr.number, (0, 0, 0))
            val = uc if col == "unresolved (all)" else uh if col == "unresolved (human)" else ua
            return str(val) if val else ""
        if col == "draft":
            return "true" if pr.isDraft else "false"
        if col == "review-outstanding":
            outstanding = [config.author_name(r) for r in pr.reviewers
                           if pr.reviewer_states.get(r, "") not in ("APPROVED", "CHANGES_REQUESTED")]
            return ", ".join(outstanding)
        if col == "valid":
            _, _, ua = unresolved_counts.get(pr.number, (0, 0, 0))
            m = _YT_RE.match(pr.title)
            yt_state = youtrack_states.get(m.group(1) + "-" + m.group(2), "") if m else ""
            is_valid = bool(pr.reviewers) and ua == 0 and m is not None and yt_state == "Review"
            return "true" if is_valid else "false"
        if col == "youtrack-ticket":
            m = _YT_RE.match(pr.title)
            return m.group(1) + '-' + m.group(2) if m else "MISSING"
        if col == "youtrack-project":
            m = _YT_RE.match(pr.title)
            return m.group(1) if m else "MISSING"
        if col == "youtrack-id":
            m = _YT_RE.match(pr.title)
            return m.group(2) if m else "MISSING"
        if col == "youtrack-state":
            m = _YT_RE.match(pr.title)
            if not m:
                return "MISSING"
            tid = m.group(1) + "-" + m.group(2)
            return youtrack_states.get(tid, "—")
        if col in ("comment", "comment-time", "comment-author"): return ""
        return ""

    def _filter_val(fc: ColSpec, pr: GithubPR) -> str:
        if isinstance(fc, PlainColumn) and fc.name == "pull-request": return str(pr.number)
        return cell(fc, pr, compute_show_time(pr))

    def _pr_passes_filter(pr: GithubPR, fc: ColSpec, fv: set[str], neg: bool) -> bool:
        if isinstance(fc, PlainColumn) and fc.name == "reviewers":
            reviewer_names = {config.author_name(r) for r in pr.reviewers}
            matched = (not pr.reviewers and "none" in fv) or bool(reviewer_names & fv)
            return not matched if neg else matched
        if isinstance(fc, PlainColumn) and fc.name == "review-outstanding":
            outstanding = {config.author_name(r) for r in pr.reviewers
                           if pr.reviewer_states.get(r, "") not in ("APPROVED", "CHANGES_REQUESTED")}
            matched = (not outstanding and "none" in fv) or bool(outstanding & fv)
            return not matched if neg else matched
        val = _filter_val(fc, pr)
        return (val not in fv) if neg else (val in fv)

    def _uses_comment_time(fc: ColSpec) -> bool:
        if isinstance(fc, PlainColumn):   return fc.name == "comment-time"
        if isinstance(fc, Comparison):    return "comment-time" in (fc.left, fc.right)
        return False

    pr_filters      = [(fc, fv, neg) for fc, fv, neg in filters if not _uses_comment_time(fc)]
    comment_filters = [(fc, fv, neg) for fc, fv, neg in filters if     _uses_comment_time(fc)]

    if spec.all_cols & {"youtrack-state", "valid"} and config.youtrack_url and config.youtrack_token:
        ticket_ids = [m.group(1) + "-" + m.group(2) for pr in all_prs if (m := _YT_RE.match(pr.title))]
        if ticket_ids:
            youtrack_states = youtrack.fetch_states(config.youtrack_url, config.youtrack_token, ticket_ids)

    if pr_filters:
        all_prs = [pr for pr in all_prs
                   if all(_pr_passes_filter(pr, fc, fv, neg) for fc, fv, neg in pr_filters)]

    _COMMENT_NAMES = frozenset({"comment", "comment-time", "comment-author"})
    _comment_in_cols = any(isinstance(c, PlainColumn) and c.name in _COMMENT_NAMES for c in cols)

    def comment_cell(c: ColSpec, cr: GithubComment) -> str:
        if isinstance(c, PlainColumn):
            if c.name == "comment":        return cr.body.split("\n")[0][:70]
            if c.name == "comment-time":   return fmt_ts(cr.timestamp, show_time=True)
            if c.name == "comment-author": return config.author_name(cr.author)
        return cell(c, pr, stc)

    def _comment_ts_val(col: str, cr: GithubComment) -> str:
        if col == "comment-time": return cr.timestamp
        return timestamp_val(col, pr)

    def _comment_filter_val(fc: ColSpec, cr: GithubComment) -> str:
        if isinstance(fc, Comparison):
            lv = _comment_ts_val(fc.left,  cr) or "1970-01-01T00:00:00Z"
            rv = _comment_ts_val(fc.right, cr) or "1970-01-01T00:00:00Z"
            result = (lv > rv if fc.op == ">" else lv < rv if fc.op == "<" else
                      lv >= rv if fc.op == ">=" else lv <= rv if fc.op == "<=" else lv == rv)
            return "true" if result else "false"
        if isinstance(fc, PlainColumn) and fc.name == "comment-time":
            return fmt_ts(cr.timestamp, show_time=True)
        return _filter_val(fc, pr)

    def _comment_passes_filters(cr: GithubComment) -> bool:
        return all(
            _comment_filter_val(fc, cr) not in fv if neg else _comment_filter_val(fc, cr) in fv
            for fc, fv, neg in comment_filters
        )

    comment_source = rows_all if args.include_pre_mark_commits else rows_marked

    rows = []
    for pr in all_prs:
        stc = compute_show_time(pr)
        if _comment_in_cols:
            for cr in comment_source.get(pr.number, []):
                if not comment_filters or _comment_passes_filters(cr):
                    rows.append([comment_cell(c, cr) for c in cols])
        else:
            rows.append([cell(c, pr, stc) for c in cols])
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
            cell = text.center(w) if col_idx < len(cols) - 1 else text.center(w).rstrip()
            parts.append(cell)
        print(" ".join(parts))

    _ROW_RESET = "\033[0m" if sys.stdout.isatty() else ""
    print(fmt_row(["-" * widths[i] for i in range(len(cols))]))
    for row in rows:
        print(fmt_row(row) + _ROW_RESET)
