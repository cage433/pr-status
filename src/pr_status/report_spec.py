from dataclasses import dataclass

from .column import (
    Column,
    PULL_REQUEST_COL, TITLE_COL, AUTHOR_COL,
)
from .column_display import ColumnDisplay
from .filter_spec import FilterSpec
from .sort_item import SortItem
from .report_args import ReportArgs


@dataclass
class ReportSpec:
    cols:      list[ColumnDisplay]
    sort_cols: list[SortItem]
    filters:   list[FilterSpec]

    @property
    def all_cols(self) -> set[Column]:
        return (
            {cd.column for cd in self.cols}
            | {col for fs in self.filters for col in fs.all_cols}
            | {si.column for si in self.sort_cols}
        )

    @staticmethod
    def resolve(args: ReportArgs) -> "ReportSpec":
        cols      = [ColumnDisplay.resolve(c) for c in args.columns.split(",") if c.strip()] if args.columns else [ColumnDisplay(PULL_REQUEST_COL), ColumnDisplay(TITLE_COL), ColumnDisplay(AUTHOR_COL)]
        sort_cols = [SortItem.resolve(c) for c in args.sort.split(",") if c.strip()] if args.sort else []
        filters   = [FilterSpec.resolve(f) for f in args.filters if f.strip()]
        return ReportSpec(cols=cols, sort_cols=sort_cols, filters=filters)
