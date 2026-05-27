import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from .config import Config
from .timely import fetch_events
from .timely_report_args import TimelyReportArgs


KNOWN_COLS = ["developer", "project", "title", "hours", "month"]
COL_ALIASES = {
    "dev": "developer", "d": "developer",
    "p": "project",
    "t": "title",
    "h": "hours",
    "m": "month",
}
COL_HEADERS = {
    "developer": "DEVELOPER", "project": "PROJECT", "title": "TITLE",
    "hours": "HOURS", "month": "MONTH",
}
COL_WIDTHS = {
    "developer": 15, "project": 20, "title": 50, "hours": 7, "month": 8,
}
NUMERIC_COLS = {"hours"}

_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_ABBREVS = {v: k.capitalize() for k, v in _MONTH_NAMES.items()}


class _TimelyError(Exception):
    pass


@dataclass(frozen=True)
class TimelyRow:
    developer: str
    project: str
    title: str
    hours: float
    month: str  # "Jan-26"


def _month_str(d: date) -> str:
    return "%s-%02d" % (_MONTH_ABBREVS[d.month], d.year % 100)


def _month_sort_key(month_str: str) -> tuple[int, int]:
    try:
        month_name, year_str = month_str.split("-")
        return (2000 + int(year_str), _MONTH_NAMES.get(month_name.lower(), 0))
    except (ValueError, AttributeError):
        return (0, 0)


def _parse_month_spec(s: str, today: date) -> tuple[date, date]:
    """Parse a month filter value into a (since, upto) date range.

    Accepts: integer n (last n calendar months), "mmm" (most recent named month),
    or "mmm-yy" (specific month).
    """
    s = s.strip().lower()
    if s.isdigit():
        n = int(s)
        month = today.month - n
        year = today.year
        while month <= 0:
            month += 12
            year -= 1
        return date(year, month, 1), today + timedelta(days=1)

    parts = s.split("-")
    if len(parts) == 2:
        month_name, year_str = parts[0], parts[1]
        if not year_str.isdigit() or len(year_str) != 2:
            raise _TimelyError("Invalid month %r: year must be 2 digits, e.g. jun-26" % s)
        year = 2000 + int(year_str)
    elif len(parts) == 1:
        month_name = parts[0]
        year = today.year
    else:
        raise _TimelyError("Invalid month spec %r" % s)

    month_num = _MONTH_NAMES.get(month_name)
    if month_num is None:
        raise _TimelyError("Unknown month %r — expected e.g. jan, feb, ... dec" % month_name)

    # For bare month name, use the most recent occurrence
    if len(parts) == 1 and month_num > today.month:
        year -= 1

    since = date(year, month_num, 1)
    upto = date(year + 1, 1, 1) if month_num == 12 else date(year, month_num + 1, 1)
    return since, upto


def _resolve_col(name: str) -> str:
    name = name.lower().strip()
    if name in COL_ALIASES:
        return COL_ALIASES[name]
    matches = [c for c in KNOWN_COLS if c.startswith(name)]
    if len(matches) == 1:
        return matches[0]
    if name in KNOWN_COLS:
        return name
    if not matches:
        raise _TimelyError("Unknown column: %r" % name)
    raise _TimelyError("Ambiguous column %r (matches: %s)" % (name, ", ".join(matches)))


def _cell(col: str, row: TimelyRow) -> str:
    if col == "developer": return row.developer
    if col == "project":   return row.project
    if col == "title":     return row.title[:50]
    if col == "hours":     return "%.1f" % row.hours
    if col == "month":     return row.month
    return ""


def _sort_key_val(col: str, row: TimelyRow):
    if col == "developer": return row.developer.lower()
    if col == "project":   return row.project.lower()
    if col == "title":     return row.title.lower()
    if col == "hours":     return row.hours
    if col == "month":     return _month_sort_key(row.month)
    return ""


_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _ljust(s: str, w: int) -> str:
    return s + ' ' * max(0, w - len(_ANSI_RE.sub('', s)))


def _rjust(s: str, w: int) -> str:
    return ' ' * max(0, w - len(_ANSI_RE.sub('', s))) + s


def _vlen(s: str) -> int:
    return len(_ANSI_RE.sub('', s))


class _Rev:
    __slots__ = ("val",)
    def __init__(self, val):        self.val = val
    def __lt__(self, o: "_Rev"):    return self.val > o.val
    def __le__(self, o: "_Rev"):    return self.val >= o.val
    def __gt__(self, o: "_Rev"):    return self.val < o.val
    def __ge__(self, o: "_Rev"):    return self.val <= o.val
    def __eq__(self, o: object):    return isinstance(o, _Rev) and self.val == o.val


def _build_developer_map(full_names: set[str], short_names: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    first_name_used: dict[str, str] = {}
    conflicts: set[str] = set()
    for full in sorted(full_names):
        if full in short_names:
            result[full] = short_names[full]
        else:
            first = full.split()[0] if full.split() else full
            if first in first_name_used:
                conflicts.add(first)
            first_name_used[first] = full
            result[full] = first
    if conflicts:
        details = "; ".join(
            "%r used by %s" % (f, " and ".join(
                repr(n) for n in sorted(full_names)
                if n.split()[0] == f and n not in short_names
            ))
            for f in sorted(conflicts)
        )
        raise _TimelyError(
            "Ambiguous first names — add timely-short-names entries: %s" % details
        )
    return result


def _reaggregate(rows: list[TimelyRow], col_names: list[str]) -> list[TimelyRow]:
    group_cols = [c for c in col_names if c != "hours"]
    totals: dict[tuple, float] = defaultdict(float)
    for row in rows:
        key = tuple(_cell(c, row) for c in group_cols)
        totals[key] += row.hours
    result = []
    for key, hours in totals.items():
        vals = dict(zip(group_cols, key))
        result.append(TimelyRow(
            developer=vals.get("developer", ""),
            project=vals.get("project", ""),
            title=vals.get("title", ""),
            hours=hours,
            month=vals.get("month", ""),
        ))
    return result


def run_timely_report(config: Config, args: TimelyReportArgs) -> None:
    try:
        _run(config, args)
    except _TimelyError as e:
        print(str(e), file=sys.stderr)


def _run(config: Config, args: TimelyReportArgs) -> None:
    if not config.timely_access_token or not config.timely_account_id:
        print("Error: timely-access-token and timely-account-id must be set in config.", file=sys.stderr)
        return

    today = date.today()

    # Parse columns
    default_cols = "developer,project,title,hours,month"
    col_names = [_resolve_col(c.strip()) for c in (args.columns or default_cols).split(",") if c.strip()]

    # Parse filters — month filters set the fetch range; named months also filter rows
    since, upto = _default_range(today)
    row_filters: list[tuple[str, set[str], bool]] = []

    for fspec in args.filters:
        fspec = fspec.strip()
        if not fspec:
            continue
        if "!=" in fspec:
            lhs, rhs = fspec.split("!=", 1)
            neg = True
        elif "=" in fspec:
            lhs, rhs = fspec.split("=", 1)
            neg = False
        else:
            raise _TimelyError("Invalid --filter (expected col=val): %r" % fspec)
        col = _resolve_col(lhs.strip())
        vals = {v.strip() for v in rhs.split(",")}
        if col == "month" and not neg:
            for v in vals:
                s, u = _parse_month_spec(v, today)
                since = min(since, s)
                upto = max(upto, u)
            # Named (non-integer) month values also filter rows to that month
            named = [v for v in vals if not v.strip().isdigit()]
            if named:
                normalized = {_month_str(_parse_month_spec(v, today)[0]) for v in named}
                row_filters.append(("month", normalized, False))
        else:
            row_filters.append((col, vals, neg))

    # Fetch and aggregate
    events = fetch_events(config.timely_account_id, config.timely_access_token, since, upto)
    if config.timely_ignored_projects:
        events = [e for e in events
                  if (e.get("project") or {}).get("name", "").lower() not in config.timely_ignored_projects]
    rows = _events_to_rows(events)

    # Apply developer and project short names
    dev_map = _build_developer_map({r.developer for r in rows}, config.timely_short_names)
    rows = [TimelyRow(
        developer=dev_map[r.developer],
        project=config.timely_short_projects.get(r.project, r.project),
        title=r.title, hours=r.hours, month=r.month,
    ) for r in rows]

    # Apply filters
    for col, vals, neg in row_filters:
        rows = [r for r in rows if (_cell(col, r) in vals) != neg]

    # Re-aggregate: group by displayed non-hours columns and sum hours
    rows = _reaggregate(rows, col_names)

    # Sort
    if args.sort:
        sort_items = []
        for s in args.sort.split(","):
            s = s.strip()
            rev = s.lower().endswith(":r")
            sort_items.append((_resolve_col(s[:-2].rstrip() if rev else s), rev))

        def sort_key(row: TimelyRow) -> list:
            return [_Rev(_sort_key_val(c, row)) if r else _sort_key_val(c, row)
                    for c, r in sort_items]
        rows.sort(key=sort_key)

    # Render
    headers = [COL_HEADERS[c] for c in col_names]
    widths = [max(COL_WIDTHS[c], len(h)) for c, h in zip(col_names, headers)]
    for row in rows:
        for i, col in enumerate(col_names):
            widths[i] = max(widths[i], _vlen(_cell(col, row)))

    def fmt_row(vals: list[str]) -> str:
        parts = []
        for i, (col, val) in enumerate(zip(col_names, vals)):
            if col in NUMERIC_COLS:
                parts.append(_rjust(val, widths[i]))
            elif i == len(col_names) - 1:
                parts.append(val)
            else:
                parts.append(_ljust(val, widths[i]))
        return " ".join(parts)

    print(fmt_row(headers))
    print(fmt_row(["-" * w for w in widths]))
    for row in rows:
        print(fmt_row([_cell(col, row) for col in col_names]))


def _default_range(today: date) -> tuple[date, date]:
    month = today.month - 3
    year = today.year
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1), today + timedelta(days=1)


def _events_to_rows(events: list[dict]) -> list[TimelyRow]:
    totals: dict[tuple[str, str, str, str], float] = defaultdict(float)
    for e in events:
        developer = (e.get("user") or {}).get("name", "Unknown")
        project   = (e.get("project") or {}).get("name", "Unknown")
        title     = e.get("note") or ""
        day_str   = e.get("day") or ""
        month     = _month_str(date.fromisoformat(day_str)) if day_str else "Unknown"
        hours     = (e.get("duration") or {}).get("total_hours", 0.0)
        totals[(developer, project, title, month)] += hours
    return [
        TimelyRow(developer=k[0], project=k[1], title=k[2], month=k[3], hours=v)
        for k, v in totals.items()
    ]
