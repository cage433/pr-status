import re
import sys
from dataclasses import dataclass

from ._util import truncate
from .column import Column
from .date_utils import fmt_ts, days_since
from .pr_context import PRContext
from .youtrack_issue import YoutrackIssue

_YT_RE = re.compile(r'^([A-Z][A-Za-z0-9]*)-(\d+)\b')


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

_REVIEW_STATE_COLOURS = {
    "APPROVED":          "\033[32m",        # green
    "CHANGES_REQUESTED": "\033[31m",        # red
    "COMMENTED":         "\033[38;5;208m",  # orange
}
_RESET = "\033[0m"

def _cell_reviewers(ctx: PRContext, _: bool) -> str:
    use_color = sys.stdout.isatty()
    parts = []
    for r in ctx.pr.reviewers:
        rname = ctx.config.author_name(r)
        asks = ctx.pr.review_request_counts.get(r, 0)
        # An open request against someone who has been asked before means they have been
        # asked to look again — whether or not they ever submitted a review the first
        # time. The colour of any last review says nothing about the one now owed, so
        # the number of that pending ask replaces it.
        if asks > 1 and r in ctx.pr.requested_reviewers:
            parts.append("%s (%d)" % (rname, asks))
            continue
        colour = _REVIEW_STATE_COLOURS.get(ctx.pr.reviewer_states.get(r, ""), "") if use_color else ""
        parts.append((colour + rname + _RESET) if colour else rname)
    return ", ".join(parts)

def _yt_ticket(ctx: PRContext) -> str:
    m = _yt_match(ctx)
    return m.group(1) + "-" + m.group(2) if m else ""


def _yt_issue(ctx: PRContext) -> YoutrackIssue:
    """The ticket a PR's title names, or an empty issue when it names none — every
    column then reads a blank rather than each having to test for the ticket."""
    return ctx.youtrack_issues.get(_yt_ticket(ctx), YoutrackIssue())


def _cell_valid(ctx: PRContext, _: bool) -> str:
    _, _, ua = ctx.unresolved
    # A PR with no YT ticket in its title is not invalid on that account. A PR that
    # does reference a ticket is only valid if that ticket is in the "Review" state
    # (a ticket that can't be found in YT has state "NOT FOUND", so is invalid).
    yt_ok = True if not _yt_ticket(ctx) else _yt_issue(ctx).state == "Review"
    is_valid = bool(ctx.pr.reviewers) and ua == 0 and yt_ok
    return "true" if is_valid else "false"

def _cell_workdays(ctx: PRContext, _: bool) -> str:
    m = _yt_match(ctx)
    if not m: return ""
    tid = (m.group(1) + "-" + m.group(2)).upper()
    tid = ctx.config.timely_yt_map.get(tid, tid)
    wd = ctx.yt_workdays.get(tid)
    return "" if wd is None else "%.1f" % wd

def _cell_yt_state(ctx: PRContext, _: bool) -> str:
    if not _yt_ticket(ctx): return "none"
    return _yt_issue(ctx).state or "—"


@dataclass(frozen=True)
class _EnumVocabulary:
    """The values a YouTrack enum field takes, least first, each with the letter the
    report shows in its place. Keeping the scale's own order is what lets a sort on such
    a column mean anything — alphabetically, High comes before Low."""
    values: tuple[tuple[str, str], ...]

    def letter(self, value: str) -> str:
        for name, letter in self.values:
            if name == value:
                return letter
        # A value added in YouTrack since keeps its initial rather than showing as blank.
        return value[:1].upper()

    def rank(self, value: str) -> int:
        for i, (name, _) in enumerate(self.values):
            if name == value:
                return i
        return len(self.values)   # unset, or unrecognised, sorts after the scale


COMMITTED_VALUES   = _EnumVocabulary((("Not Committed", "N"), ("Requested commit", "R"),
                                      ("Committed", "C")))
UNCERTAINTY_VALUES = _EnumVocabulary((("Low", "L"), ("Medium", "M"), ("High", "H")))
RISK_VALUES        = _EnumVocabulary((("Small", "S"), ("Medium", "M"), ("Large", "L")))


def _cell_estimate(ctx: PRContext, _: bool) -> str:
    days = _yt_issue(ctx).estimate_days
    return "" if days is None else "%.1f" % days

def _sort_key_workdays(ctx: PRContext) -> float:
    m = _yt_match(ctx)
    if not m: return float("inf")
    tid = (m.group(1) + "-" + m.group(2)).upper()
    tid = ctx.config.timely_yt_map.get(tid, tid)
    wd = ctx.yt_workdays.get(tid)
    return wd if wd is not None else float("inf")

def _sort_key_build(ctx: PRContext) -> int:
    # Failures first, then running, then passing, then no/partial build.
    return {"✗": 0, "…": 1, "✓": 2, "_": 3}.get(ctx.pr.build_symbol, 3)

def _sort_key_yt_id(ctx: PRContext) -> int:
    m = _yt_match(ctx)
    return int(m.group(2)) if m else 10**18

def _sort_key_yt_state(ctx: PRContext) -> str:
    if not _yt_ticket(ctx): return "none"
    return _yt_issue(ctx).state or "—"


PULL_REQUEST_COL = Column(
    "pull-request", "PR", 6, ("pr",), from_light_query=True,
    cell=lambda ctx, _: "#%-5s" % ctx.pr.number,
    sort_key=lambda ctx: ctx.pr.number,
)
TITLE_COL = Column(
    "title", "TITLE", 60, ("t",), from_light_query=True,
    cell=lambda ctx, _: truncate(ctx.pr.title, 58),
    sort_key=lambda ctx: ctx.pr.title.lower(),
)
AUTHOR_COL = Column(
    "author", "AUTHOR", 15, ("a",), from_light_query=True,
    cell=lambda ctx, _: ctx.config.author_name(ctx.pr.author),
    sort_key=lambda ctx: ctx.config.author_name(ctx.pr.author).lower(),
)
LOC_COL = Column(
    "loc", "LOC", 15, ("loc",),
    cell=_cell_loc,
    sort_key=lambda ctx: sum(ctx.loc),
)
NUM_COMMENTS_COL = Column(
    "num-comments", "NC", 4, ("nc",), is_numeric=True,
    cell=lambda ctx, _: str(len(ctx.marked_comments)),
    sort_key=lambda ctx: len(ctx.marked_comments),
)
CREATION_DATE_COL = Column(
    "creation-date", "CREATED", 17, ("cd",), is_timestamp=True, from_light_query=True,
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
    "mark", "MARK", 17, ("mk",), is_timestamp=True, from_light_query=True,
    cell=lambda ctx, st: fmt_ts(ctx.marks.get(ctx.pr.number), st, blank_if_empty=True),
    sort_key=lambda ctx: ctx.marks.get(ctx.pr.number) or "",
)
COMMENT_COL         = Column("comment",        "COMMENT",         70, ("c",))
COMMENT_TIME_COL    = Column("comment-time",   "CT",              17, ("ct",),  is_timestamp=True)
COMMENT_AUTHOR_COL  = Column("comment-author", "CA",              20, ("ca",))
REVIEWERS_COL = Column(
    "reviewers", "REVIEWERS", 20, ("r",), from_light_query=True,
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
    "age", "AG", 4, ("ag",), is_numeric=True, from_light_query=True, multi_line_header=("AGE", "(days)"),
    cell=lambda ctx, _: "" if (d := days_since(ctx.pr.createdAt)) is None else str(d),
    sort_key=lambda ctx: days_since(ctx.pr.createdAt) or 0,
)
DRAFT_COL = Column(
    "draft", "D", 5, ("d",), from_light_query=True,
    cell=lambda ctx, _: "true" if ctx.pr.isDraft else "false",
    sort_key=lambda ctx: ctx.pr.isDraft,
)
YOUTRACK_TICKET_COL = Column(
    "youtrack-ticket", "YT", 12, ("yt",), from_light_query=True,
    cell=lambda ctx, _: (m := _yt_match(ctx)) and m.group(1) + "-" + m.group(2) or "none",
    sort_key=lambda ctx: (m := _yt_match(ctx)) and m.group(1) + "-" + m.group(2) or "none",
)
YOUTRACK_PROJECT_COL = Column(
    "youtrack-project", "YP", 12, ("yp",), from_light_query=True,
    cell=lambda ctx, _: (m := _yt_match(ctx)) and m.group(1) or "none",
    sort_key=lambda ctx: (m := _yt_match(ctx)) and m.group(1) or "none",
)
YOUTRACK_ID_COL = Column(
    "youtrack-id", "YI", 7, ("yi",), from_light_query=True,
    cell=lambda ctx, _: (m := _yt_match(ctx)) and m.group(2) or "none",
    sort_key=_sort_key_yt_id,
)
YOUTRACK_STATE_COL = Column(
    "youtrack-state", "YS", 15, ("ys",), needs_youtrack=True,
    cell=_cell_yt_state,
    sort_key=_sort_key_yt_state,
)
VALID_COL = Column(
    "valid", "V", 5, ("v",), needs_youtrack=True,
    cell=_cell_valid,
    sort_key=lambda ctx: _cell_valid(ctx, False) == "true",
)
REVIEW_OUTSTANDING_COL = Column(
    "review-outstanding", "RO", 20, ("ro",), from_light_query=True,
    cell=lambda ctx, _: ", ".join(ctx.config.author_name(r) for r in ctx.pr.outstanding_reviewers),
    sort_key=lambda ctx: ", ".join(ctx.config.author_name(r) for r in ctx.pr.outstanding_reviewers).lower(),
)
BRANCH_COL = Column(
    "branch", "BRANCH", 40, ("b",), from_light_query=True,
    cell=lambda ctx, _: truncate(ctx.pr.head_ref, 38),
    sort_key=lambda ctx: ctx.pr.head_ref.lower(),
)
BUILD_COL = Column(
    "build", "CI", 4, ("ci",), from_light_query=True,
    cell=lambda ctx, _: ctx.pr.build_symbol,
    sort_key=_sort_key_build,
)
WORKDAYS_COL = Column(
    "workdays", "WD", 6, ("wd",), is_numeric=True, is_fractional=True,
    cell=_cell_workdays,
    sort_key=_sort_key_workdays,
)

DEV_DEADLINE_COL = Column(
    "dev-deadline", "DD", 12, ("dd",), needs_youtrack=True,
    cell=lambda ctx, _: _yt_issue(ctx).dev_deadline,
    sort_key=lambda ctx: _yt_issue(ctx).dev_deadline or "9999",
)
RELEASE_CYCLE_COL = Column(
    "release-cycle", "RC", 30, ("rc",), needs_youtrack=True,
    cell=lambda ctx, _: _yt_issue(ctx).release_cycle,
    sort_key=lambda ctx: _yt_issue(ctx).release_cycle.lower(),
)
RELEASE_NUMBER_COL = Column(
    "release-number", "RN", 8, ("rn",), needs_youtrack=True,
    cell=lambda ctx, _: _yt_issue(ctx).release_number,
    sort_key=lambda ctx: _yt_issue(ctx).release_number,
)
RELEASE_DATE_COL = Column(
    "release-date", "RD", 12, ("rd",), needs_youtrack=True,
    cell=lambda ctx, _: _yt_issue(ctx).release_date,
    # Unscheduled sorts last rather than first: a blank date is not an early one.
    sort_key=lambda ctx: _yt_issue(ctx).release_date or "9999",
)
COMMITTED_COL = Column(
    "committed", "CM", 3, ("cm",), needs_youtrack=True,
    cell=lambda ctx, _: COMMITTED_VALUES.letter(_yt_issue(ctx).committed),
    sort_key=lambda ctx: COMMITTED_VALUES.rank(_yt_issue(ctx).committed),
)
ESTIMATE_COL = Column(
    "estimate", "EST", 6, ("es", "est"), is_numeric=True, is_fractional=True, needs_youtrack=True,
    multi_line_header=("ESTIMATE", "(days)"),
    cell=_cell_estimate,
    sort_key=lambda ctx: _yt_issue(ctx).estimate_days if _yt_issue(ctx).estimate_days is not None else -1.0,
)
ESTIMATE_UNCERTAINTY_COL = Column(
    "estimate-uncertainty", "EU", 3, ("eu",), needs_youtrack=True,
    cell=lambda ctx, _: UNCERTAINTY_VALUES.letter(_yt_issue(ctx).estimate_uncertainty),
    sort_key=lambda ctx: UNCERTAINTY_VALUES.rank(_yt_issue(ctx).estimate_uncertainty),
)
TYPE_COL = Column(
    "type", "TY", 10, ("ty",), needs_youtrack=True,
    cell=lambda ctx, _: _yt_issue(ctx).issue_type,
    sort_key=lambda ctx: _yt_issue(ctx).issue_type.lower(),
)
RISK_COMPLEXITY_COL = Column(
    "risk-complexity", "RK", 3, ("rk",), needs_youtrack=True,
    cell=lambda ctx, _: RISK_VALUES.letter(_yt_issue(ctx).risk_complexity),
    sort_key=lambda ctx: RISK_VALUES.rank(_yt_issue(ctx).risk_complexity),
)

ALL_COLUMNS: list[Column] = [
    PULL_REQUEST_COL, TITLE_COL, AUTHOR_COL, LOC_COL, NUM_COMMENTS_COL,
    CREATION_DATE_COL, LAST_COMMENT_TIME_COL, MY_LAST_COMMENT_COL,
    MARK_COL, COMMENT_COL, COMMENT_TIME_COL, COMMENT_AUTHOR_COL,
    REVIEWERS_COL, UNRESOLVED_ALL_COL, UNRESOLVED_HUMAN_COL, UNRESOLVED_AI_COL,
    LAST_ACTIVITY_COL, AGE_COL, DRAFT_COL,
    YOUTRACK_TICKET_COL, YOUTRACK_PROJECT_COL, YOUTRACK_ID_COL, YOUTRACK_STATE_COL,
    VALID_COL, REVIEW_OUTSTANDING_COL, BRANCH_COL, BUILD_COL, WORKDAYS_COL,
    DEV_DEADLINE_COL, RELEASE_CYCLE_COL, RELEASE_NUMBER_COL, RELEASE_DATE_COL,
    COMMITTED_COL, ESTIMATE_COL, ESTIMATE_UNCERTAINTY_COL, TYPE_COL, RISK_COMPLEXITY_COL,
]

TIMESTAMP_COLS = frozenset(c.name for c in ALL_COLUMNS if c.is_timestamp)
