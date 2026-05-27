import csv
import os
import re
from collections import defaultdict
from datetime import date, timedelta

from .timely import fetch_events

_YT_RE = re.compile(r'^([A-Za-z0-9][A-Za-z0-9-]*)-(\d+)')

CACHE_BASE  = os.path.expanduser("~/.cache/pr-status/timely")
CACHE_START = date(2025, 1, 1)

_CSV_FIELDS = ["developer", "project", "note", "day", "hours"]


def _cache_path(day: date) -> str:
    return os.path.join(CACHE_BASE, day.strftime("%Y-%m"), day.strftime("%Y-%m-%d") + ".csv")


def is_cached(day: date) -> bool:
    return os.path.exists(_cache_path(day))


def is_cache_current() -> bool:
    return is_cached(date.today())


def _read_day(day: date) -> list[dict]:
    path = _cache_path(day)
    if not os.path.exists(path):
        return []
    events = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            events.append({
                "user":     {"name": row["developer"]},
                "project":  {"name": row["project"]},
                "note":     row["note"],
                "day":      row["day"],
                "duration": {"total_hours": float(row["hours"])},
            })
    return events


def _write_day(day: date, events: list[dict]) -> None:
    path = _cache_path(day)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for e in events:
            writer.writerow({
                "developer": (e.get("user") or {}).get("name", ""),
                "project":   (e.get("project") or {}).get("name", ""),
                "note":      e.get("note") or "",
                "day":       e.get("day") or "",
                "hours":     (e.get("duration") or {}).get("total_hours", 0.0),
            })


def _fetch_and_cache_range(account_id: str, token: str, since: date, upto: date) -> None:
    """Fetch [since, upto) from the API and write one CSV per calendar day."""
    events = fetch_events(account_id, token, since, upto)
    by_day: dict[str, list[dict]] = {}
    for e in events:
        day_str = e.get("day") or ""
        if day_str:
            by_day.setdefault(day_str, []).append(e)
    d = since
    while d < upto:
        _write_day(d, by_day.get(d.isoformat(), []))
        d += timedelta(days=1)


def _last_cached_day() -> date | None:
    """Return the most recent day that has a cache file, or None."""
    if not os.path.isdir(CACHE_BASE):
        return None
    months = sorted(
        (m for m in os.listdir(CACHE_BASE) if os.path.isdir(os.path.join(CACHE_BASE, m))),
        reverse=True,
    )
    for month in months:
        month_dir = os.path.join(CACHE_BASE, month)
        files = sorted(
            (f for f in os.listdir(month_dir) if f.endswith(".csv")),
            reverse=True,
        )
        for fname in files:
            try:
                return date.fromisoformat(fname[:-4])
            except ValueError:
                continue
    return None


def ensure_cache_current(account_id: str, token: str) -> None:
    """Fetch any missing days up to and including today."""
    today = date.today()
    last = _last_cached_day()
    since = (last + timedelta(days=1)) if last else CACHE_START
    if since > today:
        return
    _fetch_and_cache_range(account_id, token, since, today + timedelta(days=1))


def fetch_events_from_cache(since: date, upto: date) -> list[dict]:
    """Read events from cached CSV files for [since, upto)."""
    events: list[dict] = []
    d = since
    while d < upto:
        events.extend(_read_day(d))
        d += timedelta(days=1)
    return events


def refresh_range(account_id: str, token: str, since: date, upto: date) -> None:
    """Force-refresh cache for [since, upto), month by month, printing progress."""
    d = since
    while d < upto:
        month_end = date(d.year + (d.month // 12), (d.month % 12) + 1, 1)
        chunk_end = min(month_end, upto)
        print("  %s…" % d.strftime("%Y-%m"), flush=True)
        _fetch_and_cache_range(account_id, token, d, chunk_end)
        d = month_end


def load_yt_workdays() -> dict[str, float]:
    """Return total workdays (hours/8) per YT ticket ID across all cached data."""
    totals: dict[str, float] = defaultdict(float)
    if not os.path.isdir(CACHE_BASE):
        return {}
    for month_dir in sorted(os.listdir(CACHE_BASE)):
        month_path = os.path.join(CACHE_BASE, month_dir)
        if not os.path.isdir(month_path):
            continue
        for fname in os.listdir(month_path):
            if not fname.endswith(".csv"):
                continue
            with open(os.path.join(month_path, fname), newline="") as f:
                for row in csv.DictReader(f):
                    m = _YT_RE.match(row.get("note", ""))
                    if m:
                        totals[(m.group(1) + "-" + m.group(2)).upper()] += float(row.get("hours", 0) or 0)
    return {k: v / 8 for k, v in totals.items()}
