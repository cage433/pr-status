import dataclasses
import re
from dataclasses import dataclass

from .column import (
    Column, ColumnDisplay, FilterSpec,
    ALL_COLUMNS, TIMESTAMP_COLS,
    PULL_REQUEST_COL, TITLE_COL, AUTHOR_COL,
)
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


@dataclass
class ReportSpec:
    cols:      list[ColumnDisplay]
    sort_cols: list[tuple[Column, bool]]
    filters:   list[FilterSpec]
    all_cols:  set[Column]

    @staticmethod
    def resolve(args: ReportArgs) -> "ReportSpec":
        def resolve_col(name: str) -> Column:
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

        def parse_col(spec: str) -> ColumnDisplay:
            spec = spec.strip()
            if re.match(r'^.+\s*(>=|<=|==|>|<)\s*.+$', spec):
                raise _ListError("Comparison expressions cannot be used as columns: %r" % spec)
            long_name = spec.endswith("_")
            if long_name:
                spec = spec[:-1].rstrip()
            col = resolve_col(spec)
            return ColumnDisplay(col, use_long_name=True) if long_name else ColumnDisplay(col)

        def parse_filter_spec(spec: str) -> FilterSpec:
            spec = spec.strip()
            m = re.match(r'^(.+?)\s*(>=|<=|==|>|<)\s*(.+)$', spec)
            if m:
                op = m.group(2)
                def _parse_side(s: str) -> str:
                    lit = parse_date_literal(s.strip())
                    return lit if lit is not None else resolve_col(s.strip()).name
                left  = _parse_side(m.group(1))
                right = _parse_side(m.group(3))
                for val in (left, right):
                    col = Column.col_from_name(val)
                    if col and not col.is_timestamp:
                        raise _ListError("Column %r is not a timestamp column" % val)
                return ComparisonFilterSpec(left=left, op=op, right=right)
            return ColumnFilterSpec(column=resolve_col(spec), values=set(), negate=False)

        def parse_sort_item(s: str) -> tuple[Column, bool]:
            s = s.strip()
            if s.lower().endswith(":r"):
                return (resolve_col(s[:-2].rstrip()), True)
            return (resolve_col(s), False)

        cols      = [parse_col(c) for c in args.columns.split(",") if c.strip()] if args.columns else [ColumnDisplay(PULL_REQUEST_COL), ColumnDisplay(TITLE_COL), ColumnDisplay(AUTHOR_COL)]
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

        def _referenced_cols() -> set[Column]:
            result: set[Column] = {cd.column for cd in cols}
            for fs in filters:
                if isinstance(fs, ComparisonFilterSpec):
                    for side in (fs.left, fs.right):
                        col = Column.col_from_name(side)
                        if col and col.is_timestamp:
                            result.add(col)
                elif isinstance(fs, ColumnFilterSpec):
                    result.add(fs.column)
            return result | {col for col, _ in sort_cols}

        return ReportSpec(cols=cols, sort_cols=sort_cols, filters=filters, all_cols=_referenced_cols())
