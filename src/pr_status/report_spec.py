import dataclasses
import re
from dataclasses import dataclass

from .column import (
    Column, _ListError,
    PULL_REQUEST_COL, TITLE_COL, AUTHOR_COL,
)
from .column_display import ColumnDisplay
from .filter_spec import FilterSpec, ColumnFilterSpec, ComparisonFilterSpec
from .sort_item import SortItem
from .report_args import ReportArgs


@dataclass
class ReportSpec:
    cols:      list[ColumnDisplay]
    sort_cols: list[SortItem]
    filters:   list[FilterSpec]

    @property
    def all_cols(self) -> set[Column]:
        result: set[Column] = {cd.column for cd in self.cols}
        for fs in self.filters:
            if isinstance(fs, ComparisonFilterSpec):
                for side in (fs.left, fs.right):
                    col = Column.col_from_name(side)
                    if col and col.is_timestamp:
                        result.add(col)
            elif isinstance(fs, ColumnFilterSpec):
                result.add(fs.column)
        return result | {si.column for si in self.sort_cols}

    @staticmethod
    def resolve(args: ReportArgs) -> "ReportSpec":
        cols      = [ColumnDisplay.resolve(c) for c in args.columns.split(",") if c.strip()] if args.columns else [ColumnDisplay(PULL_REQUEST_COL), ColumnDisplay(TITLE_COL), ColumnDisplay(AUTHOR_COL)]
        sort_cols = [SortItem.resolve(c) for c in args.sort.split(",") if c.strip()] if args.sort else []

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

        return ReportSpec(cols=cols, sort_cols=sort_cols, filters=filters)
