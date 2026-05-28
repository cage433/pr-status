from abc import ABC
from dataclasses import dataclass


class FilterSpec(ABC):
    pass


@dataclass(frozen=True)
class Column:
    name:              str
    header:            str
    width:             int
    aliases:           tuple[str, ...]         = ()
    is_timestamp:      bool                    = False
    is_numeric:        bool                    = False
    abbrev:            str | None              = None
    multi_line_header: tuple[str, ...] | None  = None
    long_name:         bool                    = False
