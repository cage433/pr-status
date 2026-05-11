import datetime
import re

_DAY_MAP = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


def fmt_date(d: str) -> str:
    if not d:
        return "n/a"
    return d[:10] + " " + d[11:16]


def fmt_ts(
    val: str,
    show_time: bool = False,
    blank_if_empty: bool = False,
) -> str:
    if not val: return "" if blank_if_empty else "n/a"
    return (val[:10] + " " + val[11:16]) if show_time else val[:10]


def parse_date_literal(s: str) -> str | None:
    sl = s.strip().lower()
    today = datetime.date.today()
    if sl == "today":
        return today.isoformat() + "T00:00:00Z"
    if sl == "yesterday":
        return (today - datetime.timedelta(days=1)).isoformat() + "T00:00:00Z"
    if sl in _DAY_MAP:
        days_back = (today.weekday() - _DAY_MAP[sl]) % 7 or 7
        return (today - datetime.timedelta(days=days_back)).isoformat() + "T00:00:00Z"
    s = s.strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        return s + "T00:00:00Z"
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$', s):
        return s + ":00Z"
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$', s):
        return s + "Z"
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$', s):
        return s
    return None
