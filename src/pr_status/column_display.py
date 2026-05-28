import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .column import Column, _ListError

if TYPE_CHECKING:
    from .pr_context import PRContext
    from .github_data import GithubComment


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

    def cell(self, ctx: "PRContext", show_time: bool = False) -> str:
        return self.column.cell(ctx, show_time)

    def comment_cell(self, cr: "GithubComment", ctx: "PRContext", stc: set[str]) -> str:
        from .columns import COMMENT_COL, COMMENT_TIME_COL, COMMENT_AUTHOR_COL
        from .date_utils import fmt_ts
        if self.column == COMMENT_COL:        return cr.body.split("\n")[0][:70]
        if self.column == COMMENT_TIME_COL:   return fmt_ts(cr.timestamp, show_time=True)
        if self.column == COMMENT_AUTHOR_COL: return ctx.config.author_name(cr.author)
        return self.cell(ctx, self.name in stc)

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
