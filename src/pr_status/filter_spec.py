import re
from abc import ABC
from dataclasses import dataclass

from .column import Column, _ListError
from .date_utils import parse_date_literal


class FilterSpec(ABC):
    @staticmethod
    def parse(spec: str) -> "FilterSpec":
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


@dataclass
class ComparisonFilterSpec(FilterSpec):
    left:  str
    op:    str
    right: str
