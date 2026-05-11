import sys
from typing import Any

from .config import Config
from .date_utils import fmt_ts
from .github_data import GithubComment, GithubData, GithubPR
from .github_raw_data import GithubRawData
from .marks import Marks
from .pr_number import PRNumber
from .report_args import ReportArgs
from .report_spec import (
    ColSpec, PlainColumn, Comparison, _ListError,
    TIMESTAMP_COLS, col_header, col_width,
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
    cols        = spec.cols
    sort_cols   = spec.sort_cols
    filters     = spec.filters
    all_prs     = data.all_prs
    loc_results = data.loc_results
    rows_marked = data.rows_marked
    rows_all    = data.rows_all

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
            for col in sort_cols:
                if col == "pull-request":           key.append(pr.number)
                elif col == "title":                key.append(pr.title.lower())
                elif col == "author":               key.append(get_author(pr).lower())
                elif col == "creation-date":        key.append(pr.createdAt or "Z")
                elif col == "last-comment-time":    key.append(get_last_comment(pr.number) or "Z")
                elif col == "my-last-comment-time": key.append(get_last_comment(pr.number, user_only=True) or "Z")
                elif col == "loc":
                    adds, dels = loc_results.get(pr.number, (0, 0))
                    key.append(-(adds + dels))
                elif col == "num-comments":
                    key.append(-count_since(pr.number))
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
        if col == "requested":
            return ", ".join(config.author_name(r) for r in pr.reviewers)
        if col in ("comment", "comment-time", "comment-author"): return ""
        return ""

    def _filter_val(fc: ColSpec, pr: GithubPR) -> str:
        if isinstance(fc, PlainColumn) and fc.name == "pull-request": return str(pr.number)
        return cell(fc, pr, compute_show_time(pr))

    def _pr_passes_filter(pr: GithubPR, fc: ColSpec, fv: set[str], neg: bool) -> bool:
        if isinstance(fc, PlainColumn) and fc.name == "requested":
            reviewer_names = {config.author_name(r) for r in pr.reviewers}
            matched = (not pr.reviewers and "unassigned" in fv) or bool(reviewer_names & fv)
            return not matched if neg else matched
        val = _filter_val(fc, pr)
        return (val not in fv) if neg else (val in fv)

    def _uses_comment_time(fc: ColSpec) -> bool:
        if isinstance(fc, PlainColumn):   return fc.name == "comment-time"
        if isinstance(fc, Comparison):    return "comment-time" in (fc.left, fc.right)
        return False

    pr_filters      = [(fc, fv, neg) for fc, fv, neg in filters if not _uses_comment_time(fc)]
    comment_filters = [(fc, fv, neg) for fc, fv, neg in filters if     _uses_comment_time(fc)]

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

    def fmt_row(vals: list[str]) -> str:
        parts = ["%-*s" % (col_width(c), val) if i < len(cols) - 1 else val
                 for i, (c, val) in enumerate(zip(cols, vals))]
        return " ".join(parts)

    print(fmt_row([col_header(c) for c in cols]))
    print(fmt_row(["-" * col_width(c) for c in cols]))
    for row in _report_data_lines(config, marks, args, spec, data):
        print(fmt_row(row))
