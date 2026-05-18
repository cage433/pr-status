import json
import sys
import urllib.error
import urllib.request


def _fetch_state(url: str, token: str, ticket_id: str) -> str:
    api_url = "%s/api/issues/%s?fields=customFields(name,value(name))" % (url.rstrip("/"), ticket_id)
    req = urllib.request.Request(
        api_url,
        headers={"Authorization": "Bearer %s" % token, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        for field in data.get("customFields", []):
            if field.get("name") == "State":
                val = field.get("value")
                if isinstance(val, dict):
                    return val.get("name", "—")
        return "—"
    except urllib.error.HTTPError as e:
        print("YouTrack error for %s: HTTP %d" % (ticket_id, e.code), file=sys.stderr)
        return "NOT FOUND" if e.code == 404 else "ERROR"
    except Exception as e:
        print("YouTrack error for %s: %s" % (ticket_id, e), file=sys.stderr)
        return "ERROR"


def fetch_states(url: str, token: str, ticket_ids: list[str]) -> dict[str, str]:
    return {tid: _fetch_state(url, token, tid) for tid in ticket_ids}
