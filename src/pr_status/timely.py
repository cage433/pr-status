import urllib.request
import urllib.error
import json
from collections import defaultdict
from datetime import date, timedelta


def _get(url: str, token: str) -> list:
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "User-Agent": "pr-status/1.0",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_events(account_id: str, token: str, since: date, upto: date, user_id: int | None = None) -> list[dict]:
    events = []
    page = 1
    per_page = 1000
    while True:
        url = (
            "https://api.timelyapp.com/1.1/%s/events"
            "?since=%s&upto=%s&per_page=%d&page=%d"
            % (account_id, since.isoformat(), upto.isoformat(), per_page, page)
        )
        batch = _get(url, token)
        raw_count = len(batch)
        if user_id is not None:
            batch = [e for e in batch if (e.get("user") or {}).get("id") == user_id]
        events.extend(batch)
        if raw_count < per_page:
            break
        page += 1
    return events


def hours_by_project(events: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for e in events:
        project = (e.get("project") or {}).get("name", "Unknown")
        hours = (e.get("duration") or {}).get("total_hours", 0.0)
        totals[project] += hours
    return dict(sorted(totals.items(), key=lambda x: x[1], reverse=True))


def print_hours_by_project(account_id: str, token: str, user_id: int, months: int = 3) -> None:
    upto = date.today()
    since = upto - timedelta(days=months * 30)
    print("Fetching events for user %d from %s to %s..." % (user_id, since, upto))
    events = fetch_events(account_id, token, since, upto, user_id)
    print("Total events: %d\n" % len(events))
    totals = hours_by_project(events)
    print("%-40s %8s" % ("Project", "Hours"))
    print("-" * 50)
    for project, hours in totals.items():
        print("%-40s %8.1f" % (project, hours))
    print("-" * 50)
    print("%-40s %8.1f" % ("TOTAL", sum(totals.values())))
