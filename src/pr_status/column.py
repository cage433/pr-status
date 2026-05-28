from dataclasses import dataclass


class _ListError(Exception):
    pass


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
