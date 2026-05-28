import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from .column import Column, _ListError
from .date_utils import parse_date_literal

if TYPE_CHECKING:
    from .pr_context import PRContext


class FilterSpec(ABC):
    @property
    @abstractmethod
    def all_cols(self) -> set[Column]: ...

    @property
    def uses_comment_time(self) -> bool:
        return False

    @abstractmethod
    def matches(self, ctx: "PRContext") -> bool: ...
    @staticmethod
    def resolve(spec: str) -> "FilterSpec":
        spec = spec.strip()
        ne_parts = spec.split("!=", 1)
        if len(ne_parts) == 2:
            fs = FilterSpec._parse(ne_parts[0].strip())
            if not isinstance(fs, ColumnFilterSpec):
                raise _ListError("Invalid --filter: != not valid for comparison filters")
            return replace(fs, values={v.strip() for v in ne_parts[1].split(",")}, negate=True)
        fparts = re.split(r'(?<![><=!])=(?!=)', spec, maxsplit=1)
        if len(fparts) == 1:
            fs = FilterSpec._parse(fparts[0].strip())
            if not isinstance(fs, ComparisonFilterSpec):
                raise _ListError("Invalid --filter (expected col=val,...): %r" % spec)
            return fs
        fs = FilterSpec._parse(fparts[0].strip())
        if not isinstance(fs, ColumnFilterSpec):
            raise _ListError("Invalid --filter: = not valid for comparison filters")
        return replace(fs, values={v.strip() for v in fparts[1].split(",")})

    @staticmethod
    def _parse(spec: str) -> "FilterSpec":
        spec = spec.strip()
        m = re.match(r'^(.+?)\s*(>=|<=|==|>|<)\s*(.+)$', spec)
        if m:
            op = m.group(2)
            def _parse_side(s: str) -> str:
                lit = parse_date_literal(s.strip())
                return lit if lit is not None else Column.resolve(s.strip()).name
            left  = _parse_side(m.group(1))
            right = _parse_side(m.group(3))
            for val in (left, right):
                col = Column.col_from_name(val)
                if col and not col.is_timestamp:
                    raise _ListError("Column %r is not a timestamp column" % val)
            return ComparisonFilterSpec(left=left, op=op, right=right)
        return ColumnFilterSpec(column=Column.resolve(spec), values=set(), negate=False)


@dataclass
class ColumnFilterSpec(FilterSpec):
    column: Column
    values: set[str]
    negate: bool

    @property
    def all_cols(self) -> set[Column]:
        return {self.column}

    @property
    def uses_comment_time(self) -> bool:
        from .columns import COMMENT_TIME_COL
        return self.column == COMMENT_TIME_COL

    def matches(self, ctx: "PRContext") -> bool:
        from .columns import PULL_REQUEST_COL, REVIEWERS_COL, REVIEW_OUTSTANDING_COL
        if self.column == REVIEWERS_COL:
            reviewer_names = {ctx.config.author_name(r) for r in ctx.pr.reviewers}
            matched = (not ctx.pr.reviewers and "none" in self.values) or bool(reviewer_names & self.values)
            return not matched if self.negate else matched
        if self.column == REVIEW_OUTSTANDING_COL:
            outstanding = {ctx.config.author_name(r) for r in ctx.pr.reviewers
                           if ctx.pr.reviewer_states.get(r, "") not in ("APPROVED", "CHANGES_REQUESTED")}
            matched = (not outstanding and "none" in self.values) or bool(outstanding & self.values)
            return not matched if self.negate else matched
        val = str(ctx.pr.number) if self.column == PULL_REQUEST_COL else self.column.cell(ctx, False)
        return (val not in self.values) if self.negate else (val in self.values)


@dataclass
class ComparisonFilterSpec(FilterSpec):
    left:  str
    op:    str
    right: str

    @property
    def all_cols(self) -> set[Column]:
        return {col for side in (self.left, self.right)
                if (col := Column.col_from_name(side)) and col.is_timestamp}

    @property
    def uses_comment_time(self) -> bool:
        return "comment-time" in (self.left, self.right)

    def matches(self, ctx: "PRContext") -> bool:
        from .columns import _timestamp_val
        lv = _timestamp_val(self.left,  ctx) or "1970-01-01T00:00:00Z"
        rv = _timestamp_val(self.right, ctx) or "1970-01-01T00:00:00Z"
        return (lv > rv if self.op == ">" else lv < rv if self.op == "<" else
                lv >= rv if self.op == ">=" else lv <= rv if self.op == "<=" else lv == rv)
