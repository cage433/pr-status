from dataclasses import dataclass

from .column import Column


@dataclass(frozen=True)
class SortItem:
    column:  Column
    reverse: bool = False

    @staticmethod
    def resolve(s: str) -> "SortItem":
        s = s.strip()
        if s.lower().endswith(":r"):
            return SortItem(column=Column.resolve(s[:-2].rstrip()), reverse=True)
        return SortItem(column=Column.resolve(s))
