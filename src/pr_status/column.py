from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar


class _ListError(Exception):
    pass


_noop_cell:     Callable = lambda ctx, _: ""
_noop_sort_key: Callable = lambda ctx: ""


@dataclass(frozen=True)
class Column:
    name:              str
    label:             str
    width:             int
    aliases:           tuple[str, ...]        = ()
    is_timestamp:      bool                   = False
    is_numeric:        bool                   = False
    multi_line_header: tuple[str, ...] | None = None
    cell:              Callable               = field(default=_noop_cell,     compare=False)
    sort_key:          Callable               = field(default=_noop_sort_key, compare=False)

    _registry:  ClassVar[dict[str, "Column"]] = {}
    _aliases_d: ClassVar[dict[str, "Column"]] = {}

    def __post_init__(self) -> None:
        Column._registry[self.name] = self
        for a in self.aliases:
            Column._aliases_d[a] = self

    @staticmethod
    def col_from_name(name: str) -> "Column | None":
        return Column._registry.get(name)

    @staticmethod
    def col_from_alias(alias: str) -> "Column | None":
        return Column._aliases_d.get(alias)

    @staticmethod
    def resolve(name: str) -> "Column":
        name = name.lower().strip()
        col = Column.col_from_alias(name)
        if col:
            return col
        matches = [c for c in Column._registry.values() if c.name.startswith(name)]
        if len(matches) == 1:
            return matches[0]
        col = Column.col_from_name(name)
        if col:
            return col
        if not matches:
            raise _ListError("Unknown column: %r" % name)
        raise _ListError("Ambiguous column %r (matches: %s)" % (name, ", ".join(c.name for c in matches)))
