from abc import ABC
from dataclasses import dataclass


class FilterSpec(ABC):
    pass


@dataclass(frozen=True)
class Column:
    name:              str
    label:             str
    width:             int
    aliases:           tuple[str, ...]        = ()
    is_timestamp:      bool                   = False
    is_numeric:        bool                   = False
    multi_line_header: tuple[str, ...] | None = None


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
