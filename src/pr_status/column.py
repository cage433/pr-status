from dataclasses import dataclass, field


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
