import re
from abc import ABC
from dataclasses import dataclass
from typing import Any

from .date_utils import parse_date_literal
from .report_args import ReportArgs


class ColSpec(ABC):
    pass

@dataclass
class PlainColumn(ColSpec):
    name: str

@dataclass
class Comparison(ColSpec):
    left: str
    op: str
    right: str


class _ListError(Exception):
    pass


KNOWN_COLS   = ["pull-request", "title", "author", "loc", "num-comments",
                "creation-date", "last-comment-time", "my-last-comment-time", "mark",
                "comment", "comment-time", "comment-author", "requested"]
COL_ALIASES  = {"nc": "num-comments", "pr": "pull-request",
                "cd": "creation-date", "lct": "last-comment-time",
                "mct": "my-last-comment-time", "mk": "mark", "c": "comment",
                "ct": "comment-time", "ca": "comment-author", "r": "requested"}
COL_HEADERS  = {"pull-request": "PR", "title": "TITLE", "author": "AUTHOR", "loc": "LOC",
                "num-comments": "NC", "creation-date": "CREATED",
                "last-comment-time": "LAST COMMENT", "my-last-comment-time": "MY LAST COMMENT",
                "mark": "MARK", "comment": "COMMENT", "comment-time": "CT", "comment-author": "CA",
                "requested": "REQUESTED"}
COL_WIDTHS   = {"pull-request": 6, "title": 60,       "author": 20,       "loc": 15,
                "num-comments": 4, "creation-date": 17,
                "last-comment-time": 17, "my-last-comment-time": 17, "mark": 17,
                "comment": 70, "comment-time": 17, "comment-author": 20, "requested": 40}
TIMESTAMP_COLS = {"creation-date", "last-comment-time", "my-last-comment-time", "mark", "comment-time"}
COL_ABBREVS  = {
    "pull-request": "P", "title": "T", "author": "A", "loc": "LOC",
    "num-comments": "NC", "creation-date": "CD",
    "last-comment-time": "LCT", "my-last-comment-time": "MCT", "mark": "MK",
}


def col_header(spec: ColSpec) -> str:
    if isinstance(spec, Comparison):
        def _abbrev(s: str) -> str:
            return COL_ABBREVS.get(s, s[:10])
        return "%s%s%s" % (_abbrev(spec.left), spec.op, _abbrev(spec.right))
    return COL_HEADERS[spec.name]


def col_width(spec: ColSpec) -> int:
    if isinstance(spec, Comparison):
        return max(len(col_header(spec)), 5)  # 5 for "false"
    return COL_WIDTHS[spec.name]


@dataclass
class ReportSpec:
    cols: list[ColSpec]
    sort_cols: list[str]
    filters: list[tuple[ColSpec, set[str], bool]]  # bool: True = negate (!=)
    all_cols: set[str]

    @staticmethod
    def resolve(args: ReportArgs) -> "ReportSpec":
        def resolve_col(name: str) -> str:
            name = name.lower().strip()
            if name in COL_ALIASES:
                return COL_ALIASES[name]
            matches = [c for c in KNOWN_COLS if c.startswith(name)]
            if len(matches) == 1:
                return matches[0]
            if name in KNOWN_COLS:
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
                    if val in KNOWN_COLS and val not in TIMESTAMP_COLS:
                        raise _ListError("Column %r is not a timestamp column" % val)
                return Comparison(left=left, op=op, right=right)
            return PlainColumn(resolve_col(spec))

        cols      = [parse_col_spec(c) for c in args.columns.split(",") if c.strip()] if args.columns else [PlainColumn("pull-request"), PlainColumn("title"), PlainColumn("author")]
        sort_cols = [resolve_col(c) for c in args.sort.split(",") if c.strip()] if args.sort else []

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
                if not isinstance(col, Comparison):
                    raise _ListError("Invalid --filter (expected col=val,...): %r" % fspec)
                filters.append((col, {"true"}, False))
            else:
                filters.append((parse_col_spec(fparts[0].strip()), {v.strip() for v in fparts[1].split(",")}, False))

        def _referenced_cols() -> set[str]:
            names: set[str] = set()
            for s in cols + [fc for fc, _, _ in filters]:
                if isinstance(s, Comparison):
                    if s.left  in TIMESTAMP_COLS: names.add(s.left)
                    if s.right in TIMESTAMP_COLS: names.add(s.right)
                else:
                    names.add(s.name)
            return names | set(sort_cols)

        return ReportSpec(cols=cols, sort_cols=sort_cols, filters=filters, all_cols=_referenced_cols())
