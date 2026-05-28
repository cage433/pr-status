import dataclasses
import re
from dataclasses import dataclass

from .column import (
    Column, ColumnDisplay, FilterSpec,
    ColumnFilterSpec, ComparisonFilterSpec, _ListError,
    ALL_COLUMNS, TIMESTAMP_COLS,
    PULL_REQUEST_COL, TITLE_COL, AUTHOR_COL,
)
from .report_args import ReportArgs


@dataclass
class ReportSpec:
    cols:      list[ColumnDisplay]
    sort_cols: list[tuple[Column, bool]]
    filters:   list[FilterSpec]
    all_cols:  set[Column]

    @staticmethod
    def resolve(args: ReportArgs) -> "ReportSpec":
        def parse_sort_item(s: str) -> tuple[Column, bool]:
            s = s.strip()
            if s.lower().endswith(":r"):
                return (Column.resolve(s[:-2].rstrip()), True)
            return (Column.resolve(s), False)

        cols      = [ColumnDisplay.resolve(c) for c in args.columns.split(",") if c.strip()] if args.columns else [ColumnDisplay(PULL_REQUEST_COL), ColumnDisplay(TITLE_COL), ColumnDisplay(AUTHOR_COL)]
        sort_cols = [parse_sort_item(c) for c in args.sort.split(",") if c.strip()] if args.sort else []

        filters: list[FilterSpec] = []
        for fspec in args.filters:
            fspec = fspec.strip()
            if not fspec:
                continue
            ne_parts = fspec.split("!=", 1)
            if len(ne_parts) == 2:
                fs = FilterSpec.parse(ne_parts[0].strip())
                if not isinstance(fs, ColumnFilterSpec):
                    raise _ListError("Invalid --filter: != not valid for comparison filters")
                fs = dataclasses.replace(fs, values={v.strip() for v in ne_parts[1].split(",")}, negate=True)
                filters.append(fs)
                continue
            fparts = re.split(r'(?<![><=!])=(?!=)', fspec, maxsplit=1)
            if len(fparts) == 1:
                fs = FilterSpec.parse(fparts[0].strip())
                if not isinstance(fs, ComparisonFilterSpec):
                    raise _ListError("Invalid --filter (expected col=val,...): %r" % fspec)
                filters.append(fs)
            else:
                fs = FilterSpec.parse(fparts[0].strip())
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
