from abc import ABC
from dataclasses import dataclass


class FilterSpec(ABC):
    pass


@dataclass(frozen=True)
class Column:
    name:              str
    label:             str
    width:             int
    aliases:           tuple[str, ...]         = ()
    is_timestamp:      bool                    = False
    is_numeric:        bool                    = False
    multi_line_header: tuple[str, ...] | None  = None
    long_name:         bool                    = False

    @property
    def header(self) -> str:
        return self.name.upper() if self.long_name else self.label

    @property
    def header_lines(self) -> list[str]:
        if self.long_name and self.multi_line_header:
            return list(self.multi_line_header)
        return [self.header]

    @property
    def display_width(self) -> int:
        if self.long_name:
            return max(self.width, max(len(line) for line in self.header_lines))
        return self.width
