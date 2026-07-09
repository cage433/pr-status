import os
from datetime import datetime
from typing import Any

_TIMING_LOG = os.path.expanduser("~/.cache/pr-status/timing.log")


def timing_log(msg: str) -> None:
    """Append a timestamped line to the timing log (for analysing API latency)."""
    os.makedirs(os.path.dirname(_TIMING_LOG), exist_ok=True)
    with open(_TIMING_LOG, "a") as f:
        f.write("[%s] %s\n" % (datetime.now().isoformat(timespec="seconds"), msg))


class _Rev:
    """Wraps a value so it sorts in reverse order."""
    __slots__ = ("val",)
    def __init__(self, val: Any) -> None: self.val = val
    def __lt__(self, o: "_Rev") -> bool: return self.val > o.val
    def __le__(self, o: "_Rev") -> bool: return self.val >= o.val
    def __gt__(self, o: "_Rev") -> bool: return self.val < o.val
    def __ge__(self, o: "_Rev") -> bool: return self.val <= o.val
    def __eq__(self, o: object) -> bool: return isinstance(o, _Rev) and self.val == o.val
