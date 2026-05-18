import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime

LOG_FILE = os.path.expanduser("~/.cache/pr-status/youtrack.log")


def _log(msg: str) -> None:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write("[%s] %s\n" % (datetime.now().isoformat(timespec="seconds"), msg))


def _fetch_state(url: str, token: str, ticket_id: str) -> str:
    api_url = "%s/api/issues/%s?fields=customFields(name,value(name))" % (url.rstrip("/"), ticket_id)
    req = urllib.request.Request(
        api_url,
        headers={"Authorization": "Bearer %s" % token, "Accept": "application/json"},
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        elapsed = time.monotonic() - t0
        result = "—"
        for field in data.get("customFields", []):
            if field.get("name") == "State":
                val = field.get("value")
                if isinstance(val, dict):
                    result = val.get("name", "—")
                    break
        _log("%.3fs %s -> %s" % (elapsed, ticket_id, result))
        return result
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        _log("%.3fs HTTP %d for %s: %s" % (time.monotonic() - t0, e.code, ticket_id, body[:300]))
        return "NOT FOUND" if e.code == 404 else "ERROR"
    except Exception as e:
        _log("%.3fs error for %s: %s" % (time.monotonic() - t0, ticket_id, e))
        return "ERROR"


def fetch_states(url: str, token: str, ticket_ids: list[str]) -> dict[str, str]:
    return {tid: _fetch_state(url, token, tid) for tid in ticket_ids}
