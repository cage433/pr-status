from dataclasses import dataclass

from .column import (
    Column,
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
        filters   = [FilterSpec.resolve(f) for f in args.filters if f.strip()]
        return ReportSpec(cols=cols, sort_cols=sort_cols, filters=filters)
