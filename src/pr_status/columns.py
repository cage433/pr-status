import re
import sys

from .column import Column
from .date_utils import fmt_ts, days_since
from .pr_context import PRContext

_YT_RE = re.compile(r'^([A-Za-z0-9][A-Za-z0-9-]*)-(\d+)')


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


PULL_REQUEST_COL = Column(
    "pull-request", "PR", 6, ("pr",),
    cell=lambda ctx, _: "#%-5s" % ctx.pr.number,
    sort_key=lambda ctx: ctx.pr.number,
)
TITLE_COL = Column(
    "title", "TITLE", 60, (),
    cell=lambda ctx, _: ctx.pr.title[:58],
    sort_key=lambda ctx: ctx.pr.title.lower(),
)
AUTHOR_COL = Column(
    "author", "AUTHOR", 15, ("a",),
    cell=lambda ctx, _: ctx.config.author_name(ctx.pr.author),
    sort_key=lambda ctx: ctx.config.author_name(ctx.pr.author).lower(),
)
LOC_COL = Column(
    "loc", "LOC", 15, (),
    cell=_cell_loc,
    sort_key=lambda ctx: sum(ctx.loc),
)
NUM_COMMENTS_COL = Column(
    "num-comments", "NC", 4, ("nc",), is_numeric=True,
    cell=lambda ctx, _: str(len(ctx.marked_comments)),
    sort_key=lambda ctx: len(ctx.marked_comments),
)
CREATION_DATE_COL = Column(
    "creation-date", "CREATED", 17, ("cd",), is_timestamp=True,
    cell=lambda ctx, st: fmt_ts(ctx.pr.createdAt, st),
    sort_key=lambda ctx: ctx.pr.createdAt or "",
)
LAST_COMMENT_TIME_COL = Column(
    "last-comment-time", "LAST COMMENT", 17, ("lct",), is_timestamp=True,
    cell=lambda ctx, st: fmt_ts(_last_comment(ctx), st),
    sort_key=lambda ctx: _last_comment(ctx) or "",
)
MY_LAST_COMMENT_COL = Column(
    "my-last-comment-time", "MY LAST COMMENT", 17, ("mct",), is_timestamp=True,
    cell=lambda ctx, st: fmt_ts(_last_comment(ctx, user_only=True), st, blank_if_empty=True),
    sort_key=lambda ctx: _last_comment(ctx, user_only=True) or "",
)
MARK_COL = Column(
    "mark", "MARK", 17, ("mk",), is_timestamp=True,
    cell=lambda ctx, st: fmt_ts(ctx.marks.get(ctx.pr.number), st, blank_if_empty=True),
    sort_key=lambda ctx: ctx.marks.get(ctx.pr.number) or "",
)
COMMENT_COL         = Column("comment",        "COMMENT",         70, ("c",))
COMMENT_TIME_COL    = Column("comment-time",   "CT",              17, ("ct",),  is_timestamp=True)
COMMENT_AUTHOR_COL  = Column("comment-author", "CA",              20, ("ca",))
REVIEWERS_COL = Column(
    "reviewers", "REVIEWERS", 20, ("r",),
    cell=_cell_reviewers,
    sort_key=lambda ctx: ", ".join(ctx.config.author_name(r) for r in ctx.pr.reviewers).lower(),
)
UNRESOLVED_ALL_COL = Column(
    "unresolved (all)", "UC", 4, ("uc",), is_numeric=True, multi_line_header=("UNRESOLVED", "(ALL)"),
    cell=lambda ctx, _: str(ctx.unresolved[0]) if ctx.unresolved[0] else "",
    sort_key=lambda ctx: ctx.unresolved[0],
)
UNRESOLVED_HUMAN_COL = Column(
    "unresolved (human)", "UH", 4, ("uh",), is_numeric=True, multi_line_header=("UNRESOLVED", "(HUMAN)"),
    cell=lambda ctx, _: str(ctx.unresolved[1]) if ctx.unresolved[1] else "",
    sort_key=lambda ctx: ctx.unresolved[1],
)
UNRESOLVED_AI_COL = Column(
    "unresolved (ai)", "UA", 4, ("ua",), is_numeric=True, multi_line_header=("UNRESOLVED", "(AI)"),
    cell=lambda ctx, _: str(ctx.unresolved[2]) if ctx.unresolved[2] else "",
    sort_key=lambda ctx: ctx.unresolved[2],
)
LAST_ACTIVITY_COL = Column(
    "last-activity", "LA", 4, ("la",), is_numeric=True, multi_line_header=("LAST ACTIVITY", "(days)"),
    cell=lambda ctx, _: "" if (d := days_since(ctx.last_activity_ts)) is None else str(d),
    sort_key=lambda ctx: -1 if (d := days_since(ctx.last_activity_ts)) is None else d,
)
AGE_COL = Column(
    "age", "AG", 4, ("ag",), is_numeric=True, multi_line_header=("AGE", "(days)"),
    cell=lambda ctx, _: "" if (d := days_since(ctx.pr.createdAt)) is None else str(d),
    sort_key=lambda ctx: days_since(ctx.pr.createdAt) or 0,
)
DRAFT_COL = Column(
    "draft", "D", 5, ("d",),
    cell=lambda ctx, _: "true" if ctx.pr.isDraft else "false",
    sort_key=lambda ctx: ctx.pr.isDraft,
)
YOUTRACK_TICKET_COL = Column(
    "youtrack-ticket", "YT", 12, ("yt",),
    cell=lambda ctx, _: (m := _yt_match(ctx)) and m.group(1) + "-" + m.group(2) or "MISSING",
    sort_key=lambda ctx: (m := _yt_match(ctx)) and m.group(1) + "-" + m.group(2) or "MISSING",
)
YOUTRACK_PROJECT_COL = Column(
    "youtrack-project", "YP", 12, ("yp",),
    cell=lambda ctx, _: (m := _yt_match(ctx)) and m.group(1) or "MISSING",
    sort_key=lambda ctx: (m := _yt_match(ctx)) and m.group(1) or "MISSING",
)
YOUTRACK_ID_COL = Column(
    "youtrack-id", "YI", 7, ("yi",),
    cell=lambda ctx, _: (m := _yt_match(ctx)) and m.group(2) or "MISSING",
    sort_key=_sort_key_yt_id,
)
YOUTRACK_STATE_COL = Column(
    "youtrack-state", "YS", 15, ("ys",),
    cell=_cell_yt_state,
    sort_key=_sort_key_yt_state,
)
VALID_COL = Column(
    "valid", "V", 5, ("v",),
    cell=_cell_valid,
    sort_key=lambda ctx: _cell_valid(ctx, False) == "true",
)
REVIEW_OUTSTANDING_COL = Column(
    "review-outstanding", "RO", 20, ("ro",),
    cell=lambda ctx, _: ", ".join(
        ctx.config.author_name(r) for r in ctx.pr.reviewers
        if ctx.pr.reviewer_states.get(r, "") not in ("APPROVED", "CHANGES_REQUESTED")),
    sort_key=lambda ctx: ", ".join(
        ctx.config.author_name(r) for r in ctx.pr.reviewers
        if ctx.pr.reviewer_states.get(r, "") not in ("APPROVED", "CHANGES_REQUESTED")).lower(),
)
WORKDAYS_COL = Column(
    "workdays", "WD", 6, ("wd",), is_numeric=True,
    cell=_cell_workdays,
    sort_key=_sort_key_workdays,
)

ALL_COLUMNS: list[Column] = [
    PULL_REQUEST_COL, TITLE_COL, AUTHOR_COL, LOC_COL, NUM_COMMENTS_COL,
    CREATION_DATE_COL, LAST_COMMENT_TIME_COL, MY_LAST_COMMENT_COL,
    MARK_COL, COMMENT_COL, COMMENT_TIME_COL, COMMENT_AUTHOR_COL,
    REVIEWERS_COL, UNRESOLVED_ALL_COL, UNRESOLVED_HUMAN_COL, UNRESOLVED_AI_COL,
    LAST_ACTIVITY_COL, AGE_COL, DRAFT_COL,
    YOUTRACK_TICKET_COL, YOUTRACK_PROJECT_COL, YOUTRACK_ID_COL, YOUTRACK_STATE_COL,
    VALID_COL, REVIEW_OUTSTANDING_COL, WORKDAYS_COL,
]

TIMESTAMP_COLS = frozenset(c.name for c in ALL_COLUMNS if c.is_timestamp)
