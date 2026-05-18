import json
import os
import urllib.error
import urllib.request

CACHE_FILE = os.path.expanduser("~/.cache/pr-status/youtrack_cache.json")


def load_cache() -> dict[str, str]:
    if os.path.isfile(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: dict[str, str]) -> None:
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)


def clear_cache() -> None:
    if os.path.isfile(CACHE_FILE):
        os.remove(CACHE_FILE)


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
        return "NOT FOUND" if e.code == 404 else "ERROR"
    except Exception:
        return "ERROR"


def fetch_states(url: str, token: str, ticket_ids: list[str]) -> dict[str, str]:
    cache = load_cache()
    missing = [tid for tid in ticket_ids if tid not in cache]
    for tid in missing:
        cache[tid] = _fetch_state(url, token, tid)
    if missing:
        save_cache(cache)
    return {tid: cache.get(tid, "—") for tid in ticket_ids}
