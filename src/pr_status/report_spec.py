import dataclasses
import re
from dataclasses import dataclass

from .column import Column, FilterSpec
from .date_utils import parse_date_literal
from .report_args import ReportArgs


@dataclass
class ColumnFilterSpec(FilterSpec):
    column: Column
    values: set[str]
    negate: bool

@dataclass
class ComparisonFilterSpec(FilterSpec):
    left:  str
    op:    str
    right: str


class _ListError(Exception):
    pass


ALL_COLUMNS: list[Column] = [
    Column("pull-request",         "PR",              6,  ("pr",)),
    Column("title",                "TITLE",           60, ()),
    Column("author",               "AUTHOR",          15, ("a",)),
    Column("loc",                  "LOC",             15, ()),
    Column("num-comments",         "NC",              4,  ("nc",),         is_numeric=True),
    Column("creation-date",        "CREATED",         17, ("cd",),         is_timestamp=True),
    Column("last-comment-time",    "LAST COMMENT",    17, ("lct",),        is_timestamp=True),
    Column("my-last-comment-time", "MY LAST COMMENT", 17, ("mct",),        is_timestamp=True),
    Column("mark",                 "MARK",            17, ("mk",),         is_timestamp=True),
    Column("comment",              "COMMENT",         70, ("c",)),
    Column("comment-time",         "CT",              17, ("ct",),         is_timestamp=True),
    Column("comment-author",       "CA",              20, ("ca",)),
    Column("reviewers",            "REVIEWERS",       20, ("r",)),
    Column("unresolved (all)",     "UC",              4,  ("uc",),         is_numeric=True,
           multi_line_header=("UNRESOLVED", "(ALL)")),
    Column("unresolved (human)",   "UH",              4,  ("uh",),         is_numeric=True,
           multi_line_header=("UNRESOLVED", "(HUMAN)")),
    Column("unresolved (ai)",      "UA",              4,  ("ua",),         is_numeric=True,
           multi_line_header=("UNRESOLVED", "(AI)")),
    Column("last-activity",        "LA",              4,  ("la",),         is_numeric=True,
           multi_line_header=("LAST ACTIVITY", "(days)")),
    Column("age",                  "AG",              4,  ("ag",),         is_numeric=True,
           multi_line_header=("AGE", "(days)")),
    Column("draft",                "D",               5,  ("d",)),
    Column("youtrack-ticket",      "YT",              12, ("yt",)),
    Column("youtrack-project",     "YP",              12, ("yp",)),
    Column("youtrack-id",          "YI",              7,  ("yi",)),
    Column("youtrack-state",       "YS",              15, ("ys",)),
    Column("valid",                "V",               5,  ("v",)),
    Column("review-outstanding",   "RO",              20, ("ro",)),
    Column("workdays",             "WD",              6,  ("wd",),         is_numeric=True),
]

_COL_BY_NAME:   dict[str, Column] = {c.name: c      for c in ALL_COLUMNS}
_ALIAS_TO_NAME: dict[str, str]    = {a: c.name for c in ALL_COLUMNS for a in c.aliases}

TIMESTAMP_COLS = frozenset(c.name for c in ALL_COLUMNS if c.is_timestamp)



@dataclass
class ReportSpec:
    cols:      list[Column]
    sort_cols: list[tuple[str, bool]]  # (col_name, reversed)
    filters:   list[FilterSpec]
    all_cols:  set[str]

    @staticmethod
    def resolve(args: ReportArgs) -> "ReportSpec":
        def resolve_col(name: str) -> str:
            name = name.lower().strip()
            if name in _ALIAS_TO_NAME:
                return _ALIAS_TO_NAME[name]
            matches = [c.name for c in ALL_COLUMNS if c.name.startswith(name)]
            if len(matches) == 1:
                return matches[0]
            if name in _COL_BY_NAME:
                return name
            if not matches:
                raise _ListError("Unknown column: %r" % name)
            raise _ListError("Ambiguous column %r (matches: %s)" % (name, ", ".join(matches)))

        def parse_col(spec: str) -> Column:
            spec = spec.strip()
            if re.match(r'^.+\s*(>=|<=|==|>|<)\s*.+$', spec):
                raise _ListError("Comparison expressions cannot be used as columns: %r" % spec)
            long_name = spec.endswith("_")
            if long_name:
                spec = spec[:-1].rstrip()
            col = _COL_BY_NAME[resolve_col(spec)]
            return dataclasses.replace(col, long_name=True) if long_name else col

        def parse_filter_spec(spec: str) -> FilterSpec:
            spec = spec.strip()
            m = re.match(r'^(.+?)\s*(>=|<=|==|>|<)\s*(.+)$', spec)
            if m:
                op = m.group(2)
                def _parse_side(s: str) -> str:
                    lit = parse_date_literal(s.strip())
                    return lit if lit is not None else resolve_col(s.strip())
                left  = _parse_side(m.group(1))
                right = _parse_side(m.group(3))
                for val in (left, right):
                    col = _COL_BY_NAME.get(val)
                    if col and not col.is_timestamp:
                        raise _ListError("Column %r is not a timestamp column" % val)
                return ComparisonFilterSpec(left=left, op=op, right=right)
            return ColumnFilterSpec(column=_COL_BY_NAME[resolve_col(spec)], values=set(), negate=False)

        def parse_sort_item(s: str) -> tuple[str, bool]:
            s = s.strip()
            if s.lower().endswith(":r"):
                return (resolve_col(s[:-2].rstrip()), True)
            return (resolve_col(s), False)

        cols      = [parse_col(c) for c in args.columns.split(",") if c.strip()] if args.columns else [_COL_BY_NAME["pull-request"], _COL_BY_NAME["title"], _COL_BY_NAME["author"]]
        sort_cols = [parse_sort_item(c) for c in args.sort.split(",") if c.strip()] if args.sort else []

        filters: list[FilterSpec] = []
        for fspec in args.filters:
            fspec = fspec.strip()
            if not fspec:
                continue
            ne_parts = fspec.split("!=", 1)
            if len(ne_parts) == 2:
                fs = parse_filter_spec(ne_parts[0].strip())
                if not isinstance(fs, ColumnFilterSpec):
                    raise _ListError("Invalid --filter: != not valid for comparison filters")
                fs = dataclasses.replace(fs, values={v.strip() for v in ne_parts[1].split(",")}, negate=True)
                filters.append(fs)
                continue
            fparts = re.split(r'(?<![><=!])=(?!=)', fspec, maxsplit=1)
            if len(fparts) == 1:
                fs = parse_filter_spec(fparts[0].strip())
                if not isinstance(fs, ComparisonFilterSpec):
                    raise _ListError("Invalid --filter (expected col=val,...): %r" % fspec)
                filters.append(fs)
            else:
                fs = parse_filter_spec(fparts[0].strip())
                if not isinstance(fs, ColumnFilterSpec):
                    raise _ListError("Invalid --filter: = not valid for comparison filters")
                fs = dataclasses.replace(fs, values={v.strip() for v in fparts[1].split(",")})
                filters.append(fs)

        def _referenced_cols() -> set[str]:
            names: set[str] = {col.name for col in cols}
            for fs in filters:
                if isinstance(fs, ComparisonFilterSpec):
                    for side in (fs.left, fs.right):
                        col = _COL_BY_NAME.get(side)
                        if col and col.is_timestamp:
                            names.add(side)
                elif isinstance(fs, ColumnFilterSpec):
                    names.add(fs.column.name)
            return names | {col for col, _ in sort_cols}

        return ReportSpec(cols=cols, sort_cols=sort_cols, filters=filters, all_cols=_referenced_cols())
