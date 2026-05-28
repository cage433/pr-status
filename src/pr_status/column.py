import re
from abc import ABC
from dataclasses import dataclass

from .date_utils import parse_date_literal


class _ListError(Exception):
    pass


class FilterSpec(ABC):
    @staticmethod
    def parse(spec: str) -> "FilterSpec":
        spec = spec.strip()
        m = re.match(r'^(.+?)\s*(>=|<=|==|>|<)\s*(.+)$', spec)
        if m:
            op = m.group(2)
            def _parse_side(s: str) -> str:
                lit = parse_date_literal(s.strip())
                return lit if lit is not None else Column.resolve(s.strip()).name
            left  = _parse_side(m.group(1))
            right = _parse_side(m.group(3))
            for val in (left, right):
                col = Column.col_from_name(val)
                if col and not col.is_timestamp:
                    raise _ListError("Column %r is not a timestamp column" % val)
            return ComparisonFilterSpec(left=left, op=op, right=right)
        return ColumnFilterSpec(column=Column.resolve(spec), values=set(), negate=False)


@dataclass
class ColumnFilterSpec(FilterSpec):
    column: "Column"
    values: set[str]
    negate: bool


@dataclass
class ComparisonFilterSpec(FilterSpec):
    left:  str
    op:    str
    right: str


@dataclass(frozen=True)
class Column:
    name:              str
    label:             str
    width:             int
    aliases:           tuple[str, ...]        = ()
    is_timestamp:      bool                   = False
    is_numeric:        bool                   = False
    multi_line_header: tuple[str, ...] | None = None

    @staticmethod
    def col_from_name(name: str) -> "Column | None":
        return _COL_BY_NAME.get(name)

    @staticmethod
    def col_from_alias(alias: str) -> "Column | None":
        return _ALIAS_TO_COL.get(alias)

    @staticmethod
    def resolve(name: str) -> "Column":
        name = name.lower().strip()
        col = Column.col_from_alias(name)
        if col:
            return col
        matches = [c for c in ALL_COLUMNS if c.name.startswith(name)]
        if len(matches) == 1:
            return matches[0]
        col = Column.col_from_name(name)
        if col:
            return col
        if not matches:
            raise _ListError("Unknown column: %r" % name)
        raise _ListError("Ambiguous column %r (matches: %s)" % (name, ", ".join(c.name for c in matches)))


@dataclass(frozen=True)
class ColumnDisplay:
    column:        Column
    use_long_name: bool = False

    @property
    def name(self) -> str:          return self.column.name
    @property
    def is_numeric(self) -> bool:   return self.column.is_numeric
    @property
    def is_timestamp(self) -> bool: return self.column.is_timestamp

    @property
    def header(self) -> str:
        return self.column.name.upper() if self.use_long_name else self.column.label

    @property
    def header_lines(self) -> list[str]:
        if self.use_long_name and self.column.multi_line_header:
            return list(self.column.multi_line_header)
        return [self.header]

    @property
    def display_width(self) -> int:
        if self.use_long_name:
            return max(self.column.width, max(len(l) for l in self.header_lines))
        return self.column.width

    @staticmethod
    def resolve(spec: str) -> "ColumnDisplay":
        spec = spec.strip()
        if re.match(r'^.+\s*(>=|<=|==|>|<)\s*.+$', spec):
            raise _ListError("Comparison expressions cannot be used as columns: %r" % spec)
        long_name = spec.endswith("_")
        if long_name:
            spec = spec[:-1].rstrip()
        col = Column.resolve(spec)
        return ColumnDisplay(col, use_long_name=True) if long_name else ColumnDisplay(col)


@dataclass(frozen=True)
class SortItem:
    column:  Column
    reverse: bool = False

    @staticmethod
    def resolve(s: str) -> "SortItem":
        s = s.strip()
        if s.lower().endswith(":r"):
            return SortItem(column=Column.resolve(s[:-2].rstrip()), reverse=True)
        return SortItem(column=Column.resolve(s))


PULL_REQUEST_COL       = Column("pull-request",         "PR",              6,  ("pr",))
TITLE_COL              = Column("title",                "TITLE",           60, ())
AUTHOR_COL             = Column("author",               "AUTHOR",          15, ("a",))
LOC_COL                = Column("loc",                  "LOC",             15, ())
NUM_COMMENTS_COL       = Column("num-comments",         "NC",              4,  ("nc",),         is_numeric=True)
CREATION_DATE_COL      = Column("creation-date",        "CREATED",         17, ("cd",),         is_timestamp=True)
LAST_COMMENT_TIME_COL  = Column("last-comment-time",    "LAST COMMENT",    17, ("lct",),        is_timestamp=True)
MY_LAST_COMMENT_COL    = Column("my-last-comment-time", "MY LAST COMMENT", 17, ("mct",),        is_timestamp=True)
MARK_COL               = Column("mark",                 "MARK",            17, ("mk",),         is_timestamp=True)
COMMENT_COL            = Column("comment",              "COMMENT",         70, ("c",))
COMMENT_TIME_COL       = Column("comment-time",         "CT",              17, ("ct",),         is_timestamp=True)
COMMENT_AUTHOR_COL     = Column("comment-author",       "CA",              20, ("ca",))
REVIEWERS_COL          = Column("reviewers",            "REVIEWERS",       20, ("r",))
UNRESOLVED_ALL_COL     = Column("unresolved (all)",     "UC",              4,  ("uc",),         is_numeric=True, multi_line_header=("UNRESOLVED", "(ALL)"))
UNRESOLVED_HUMAN_COL   = Column("unresolved (human)",   "UH",              4,  ("uh",),         is_numeric=True, multi_line_header=("UNRESOLVED", "(HUMAN)"))
UNRESOLVED_AI_COL      = Column("unresolved (ai)",      "UA",              4,  ("ua",),         is_numeric=True, multi_line_header=("UNRESOLVED", "(AI)"))
LAST_ACTIVITY_COL      = Column("last-activity",        "LA",              4,  ("la",),         is_numeric=True, multi_line_header=("LAST ACTIVITY", "(days)"))
AGE_COL                = Column("age",                  "AG",              4,  ("ag",),         is_numeric=True, multi_line_header=("AGE", "(days)"))
DRAFT_COL              = Column("draft",                "D",               5,  ("d",))
YOUTRACK_TICKET_COL    = Column("youtrack-ticket",      "YT",              12, ("yt",))
YOUTRACK_PROJECT_COL   = Column("youtrack-project",     "YP",              12, ("yp",))
YOUTRACK_ID_COL        = Column("youtrack-id",          "YI",              7,  ("yi",))
YOUTRACK_STATE_COL     = Column("youtrack-state",       "YS",              15, ("ys",))
VALID_COL              = Column("valid",                "V",               5,  ("v",))
REVIEW_OUTSTANDING_COL = Column("review-outstanding",   "RO",              20, ("ro",))
WORKDAYS_COL           = Column("workdays",             "WD",              6,  ("wd",),         is_numeric=True)

ALL_COLUMNS: list[Column] = [
    PULL_REQUEST_COL, TITLE_COL, AUTHOR_COL, LOC_COL, NUM_COMMENTS_COL,
    CREATION_DATE_COL, LAST_COMMENT_TIME_COL, MY_LAST_COMMENT_COL,
    MARK_COL, COMMENT_COL, COMMENT_TIME_COL, COMMENT_AUTHOR_COL,
    REVIEWERS_COL, UNRESOLVED_ALL_COL, UNRESOLVED_HUMAN_COL, UNRESOLVED_AI_COL,
    LAST_ACTIVITY_COL, AGE_COL, DRAFT_COL,
    YOUTRACK_TICKET_COL, YOUTRACK_PROJECT_COL, YOUTRACK_ID_COL, YOUTRACK_STATE_COL,
    VALID_COL, REVIEW_OUTSTANDING_COL, WORKDAYS_COL,
]

_COL_BY_NAME:  dict[str, Column] = {c.name: c for c in ALL_COLUMNS}
_ALIAS_TO_COL: dict[str, Column] = {a: c for c in ALL_COLUMNS for a in c.aliases}

TIMESTAMP_COLS = frozenset(c.name for c in ALL_COLUMNS if c.is_timestamp)
