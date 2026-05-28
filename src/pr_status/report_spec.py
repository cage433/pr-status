import re
from abc import ABC
from dataclasses import dataclass
from typing import Any

from .column import Column
from .date_utils import parse_date_literal
from .report_args import ReportArgs


class ColSpec(ABC):
    pass

@dataclass
class PlainColSpec(ColSpec):
    name: str
    long_name: bool = False

@dataclass
class ComparisonColSpec(ColSpec):
    left: str
    op: str
    right: str


class _ListError(Exception):
    pass


ALL_COLUMNS: list[Column] = [
    Column("pull-request",         "PR",              6,  ("pr",),        abbrev="P"),
    Column("title",                "TITLE",           60, ()),
    Column("author",               "AUTHOR",          15, ("a",),         abbrev="A"),
    Column("loc",                  "LOC",             15, (),              abbrev="LOC"),
    Column("num-comments",         "NC",              4,  ("nc",),         is_numeric=True,   abbrev="NC"),
    Column("creation-date",        "CREATED",         17, ("cd",),         is_timestamp=True, abbrev="CD"),
    Column("last-comment-time",    "LAST COMMENT",    17, ("lct",),        is_timestamp=True, abbrev="LCT"),
    Column("my-last-comment-time", "MY LAST COMMENT", 17, ("mct",),        is_timestamp=True, abbrev="MCT"),
    Column("mark",                 "MARK",            17, ("mk",),         is_timestamp=True, abbrev="MK"),
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

_COL_BY_NAME:   dict[str, Column] = {c.name:  c      for c in ALL_COLUMNS}
_ALIAS_TO_NAME: dict[str, str]    = {a: c.name for c in ALL_COLUMNS for a in c.aliases}

# Derived sets kept for callers that need fast membership tests
TIMESTAMP_COLS = frozenset(c.name for c in ALL_COLUMNS if c.is_timestamp)


def col_header(spec: ColSpec) -> str:
    if isinstance(spec, ComparisonColSpec):
        def _abbrev(s: str) -> str:
            col = _COL_BY_NAME.get(s)
            return col.abbrev if col and col.abbrev else s[:10]
        return "%s%s%s" % (_abbrev(spec.left), spec.op, _abbrev(spec.right))
    if isinstance(spec, PlainColSpec) and spec.long_name:
        return spec.name.upper()
    return _COL_BY_NAME[spec.name].header


def col_is_numeric(spec: ColSpec) -> bool:
    return isinstance(spec, PlainColSpec) and _COL_BY_NAME[spec.name].is_numeric


def col_header_lines(spec: ColSpec) -> list[str]:
    if isinstance(spec, PlainColSpec) and spec.long_name:
        col = _COL_BY_NAME[spec.name]
        if col.multi_line_header:
            return list(col.multi_line_header)
    return [col_header(spec)]


def col_width(spec: ColSpec) -> int:
    if isinstance(spec, ComparisonColSpec):
        return max(len(col_header(spec)), 5)  # 5 for "false"
    col = _COL_BY_NAME[spec.name]
    if isinstance(spec, PlainColSpec) and spec.long_name:
        lines = col_header_lines(spec)
        return max(col.width, max(len(line) for line in lines))
    return col.width


@dataclass
class ReportSpec:
    cols: list[ColSpec]
    sort_cols: list[tuple[str, bool]]  # (col_name, reversed)
    filters: list[tuple[ColSpec, set[str], bool]]  # bool: True = negate (!=)
    all_cols: set[str]

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

        def parse_col_spec(spec: str) -> ColSpec:
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
                return ComparisonColSpec(left=left, op=op, right=right)
            long_name = spec.endswith("_")
            if long_name:
                spec = spec[:-1].rstrip()
            return PlainColSpec(resolve_col(spec), long_name=long_name)

        def parse_sort_item(s: str) -> tuple[str, bool]:
            s = s.strip()
            if s.lower().endswith(":r"):
                return (resolve_col(s[:-2].rstrip()), True)
            return (resolve_col(s), False)

        cols      = [parse_col_spec(c) for c in args.columns.split(",") if c.strip()] if args.columns else [PlainColSpec("pull-request"), PlainColSpec("title"), PlainColSpec("author")]
        sort_cols = [parse_sort_item(c) for c in args.sort.split(",") if c.strip()] if args.sort else []

        filters: list[tuple[ColSpec, set[str], bool]] = []
        for fspec in args.filters:
            fspec = fspec.strip()
            if not fspec: continue
            ne_parts = fspec.split("!=", 1)
            if len(ne_parts) == 2:
                filters.append((parse_col_spec(ne_parts[0].strip()), {v.strip() for v in ne_parts[1].split(",")}, True))
                continue
            fparts = re.split(r'(?<![><=!])=(?!=)', fspec, maxsplit=1)
            if len(fparts) == 1:
                col = parse_col_spec(fparts[0].strip())
                if not isinstance(col, ComparisonColSpec):
                    raise _ListError("Invalid --filter (expected col=val,...): %r" % fspec)
                filters.append((col, {"true"}, False))
            else:
                filters.append((parse_col_spec(fparts[0].strip()), {v.strip() for v in fparts[1].split(",")}, False))

        def _referenced_cols() -> set[str]:
            names: set[str] = set()
            for s in cols + [fc for fc, _, _ in filters]:
                if isinstance(s, ComparisonColSpec):
                    for side in (s.left, s.right):
                        col = _COL_BY_NAME.get(side)
                        if col and col.is_timestamp:
                            names.add(side)
                else:
                    names.add(s.name)
            return names | {col for col, _ in sort_cols}

        return ReportSpec(cols=cols, sort_cols=sort_cols, filters=filters, all_cols=_referenced_cols())
