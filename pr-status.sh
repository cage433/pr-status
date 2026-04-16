#!/usr/bin/env bash
set -uo pipefail

SCRIPT_NAME="$(basename "$0")"
GH_USER="$(gh api user --jq '.login' 2>/dev/null)" || {
    echo "Error: Could not determine GitHub username. Are you logged in? Run 'gh auth login'." >&2
    exit 1
}

usage() {
    cat <<EOF
Usage: $SCRIPT_NAME [-r OWNER/REPO] [-c CONFIG] [-t THREADS]

Options:
  -r REPO       Repository in OWNER/REPO format (overrides config)
  -c CONFIG     Path to config file (default: ~/.pr-status/config)
  -t THREADS    Max review threads to fetch per PR (default: 50)
  -h            Show this help message

Config file format:
  owner: OWNER
  repo-name: REPO_NAME
  ignore-author: user1, user2, user3
  ignore-pr: 1234, 5678
  ai-author: bot1, bot2
EOF
    exit 0
}

REPO=""
CONFIG_FILE=""
DEFAULT_CONFIG="$HOME/.pr-status/config"
MAX_THREADS=50

while getopts ":r:c:t:h" opt; do
    case "$opt" in
        r) REPO="$OPTARG" ;;
        c) CONFIG_FILE="$OPTARG" ;;
        t) MAX_THREADS="$OPTARG" ;;
        h) usage ;;
        :) echo "Error: -$OPTARG requires an argument." >&2; exit 1 ;;
        *) echo "Error: Unknown option -$OPTARG" >&2; exit 1 ;;
    esac
done
shift $((OPTIND - 1))

# -- Config parsing ------------------------------------------------------------

OWNER=""
REPO_NAME=""
IGNORED_AUTHORS=""
IGNORED_PRS=""
AI_AUTHORS=""

# Use explicit config, or fall back to default if it exists
if [[ -z "$CONFIG_FILE" ]]; then
    if [[ -f "$DEFAULT_CONFIG" ]]; then
        CONFIG_FILE="$DEFAULT_CONFIG"
    fi
elif [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Error: Config file not found: $CONFIG_FILE" >&2
    exit 1
fi

load_config() {
    OWNER=""
    REPO_NAME=""
    IGNORED_AUTHORS=""
    IGNORED_PRS=""
    AI_AUTHORS=""

    if [[ -n "$CONFIG_FILE" ]]; then
        while IFS= read -r line; do
            case "$line" in
                ""|\#*) continue ;;
            esac
            if [[ "$line" =~ ^owner:[[:space:]]*(.*) ]]; then
                OWNER="$(echo "${BASH_REMATCH[1]}" | xargs)"
            fi
            if [[ "$line" =~ ^repo-name:[[:space:]]*(.*) ]]; then
                REPO_NAME="$(echo "${BASH_REMATCH[1]}" | xargs)"
            fi
            if [[ "$line" =~ ^ignore-author:[[:space:]]*(.*) ]]; then
                IFS=',' read -ra authors <<< "${BASH_REMATCH[1]}"
                for author in "${authors[@]}"; do
                    author="$(echo "$author" | xargs)"
                    if [[ -n "$author" ]]; then
                        IGNORED_AUTHORS="${IGNORED_AUTHORS}|${author}"
                    fi
                done
            fi
            if [[ "$line" =~ ^ignore-pr:[[:space:]]*(.*) ]]; then
                IFS=',' read -ra prs <<< "${BASH_REMATCH[1]}"
                for prnum in "${prs[@]}"; do
                    prnum="$(echo "$prnum" | xargs)"
                    if [[ -n "$prnum" ]]; then
                        IGNORED_PRS="${IGNORED_PRS}|${prnum}"
                    fi
                done
            fi
            if [[ "$line" =~ ^ai-author:[[:space:]]*(.*) ]]; then
                IFS=',' read -ra authors <<< "${BASH_REMATCH[1]}"
                for author in "${authors[@]}"; do
                    author="$(echo "$author" | xargs)"
                    if [[ -n "$author" ]]; then
                        AI_AUTHORS="${AI_AUTHORS}|${author}"
                    fi
                done
            fi
        done < "$CONFIG_FILE"
    fi

    # -r OWNER/REPO_NAME overrides config
    if [[ -n "$REPO" ]]; then
        OWNER="${REPO%%/*}"
        REPO_NAME="${REPO##*/}"
    fi
}

load_config

if [[ -z "$OWNER" || -z "$REPO_NAME" ]]; then
    echo "Error: no repository specified. Use -r OWNER/REPO_NAME or set 'owner:' and 'repo-name:' in config." >&2
    exit 1
fi

# -- Write Python script to temp file ------------------------------------------

PYTHON_SCRIPT="$(mktemp /tmp/pr-status.XXXXXX.py)"
trap 'rm -f "$PYTHON_SCRIPT"' EXIT

cat > "$PYTHON_SCRIPT" <<'PYEOF'
import subprocess
import json
import sys

command = sys.argv[1]
gh_user = sys.argv[2]
ignored_str = sys.argv[3]
owner = sys.argv[4]
repo = sys.argv[5]
max_threads = int(sys.argv[6])
ignored_prs_str = sys.argv[7]
list_columns_str    = sys.argv[8]  if command == "list" and len(sys.argv) > 8  else ""
list_sort_str       = sys.argv[9]  if command == "list" and len(sys.argv) > 9  else ""
list_marks_file     = sys.argv[10] if command == "list" and len(sys.argv) > 10 else ""
list_no_ai          = sys.argv[11] == "1" if command == "list" and len(sys.argv) > 11 else False
list_ai_authors_str = sys.argv[12] if command == "list" and len(sys.argv) > 12 else ""
pr_number = int(sys.argv[8]) if command != "list" and len(sys.argv) > 8 else None
ai_authors_str = sys.argv[9] if command != "list" and len(sys.argv) > 9 else ""
no_ai = sys.argv[10] == "1" if command != "list" and len(sys.argv) > 10 else False
no_inline = sys.argv[11] == "1" if len(sys.argv) > 11 else False
mark_timestamp = sys.argv[12] if len(sys.argv) > 12 else ""
show_all = sys.argv[13] == "1" if len(sys.argv) > 13 else False

ai_authors = set()
if ai_authors_str:
    for a in ai_authors_str.split("|"):
        a = a.strip()
        if a:
            ai_authors.add(a)

def is_ai_author(login):
    return login in ai_authors or login.removesuffix("[bot]") in ai_authors

ignored = set()
if ignored_str:
    for a in ignored_str.split("|"):
        a = a.strip()
        if a:
            ignored.add(a)

ignored_prs = set()
if ignored_prs_str:
    for p in ignored_prs_str.split("|"):
        p = p.strip()
        if p:
            try:
                ignored_prs.add(int(p))
            except ValueError:
                pass

GRAPHQL_QUERY_LIGHT = """
query($owner: String!, $repo: String!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequests(states: OPEN, first: 100, after: $cursor) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        number
        title
        isDraft
        createdAt
        author {
          login
        }
      }
    }
  }
}
"""

GRAPHQL_QUERY_COMMENTS_ISSUE = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      title
      comments(first: 100) {
        nodes {
          author { login }
          createdAt
          body
        }
      }
    }
  }
}
"""

GRAPHQL_QUERY_COMMENTS_REVIEWS = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviews(first: 100) {
        nodes {
          author { login }
          submittedAt
          body
        }
      }
      reviewThreads(first: 100) {
        nodes {
          comments(first: 50) {
            nodes {
              author { login }
              createdAt
              body
            }
          }
        }
      }
    }
  }
}
"""

GRAPHQL_QUERY_COMMENTS_REVIEWS_NO_INLINE = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviews(first: 100) {
        nodes {
          author { login }
          submittedAt
          body
        }
      }
    }
  }
}
"""

GRAPHQL_QUERY_COMMENT_COUNTS = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      comments(first: 100) {
        nodes { author { login } createdAt }
      }
      reviews(first: 100) {
        nodes { author { login } submittedAt }
      }
      reviewThreads(first: 100) {
        nodes {
          comments(first: 50) {
            nodes { author { login } createdAt }
          }
        }
      }
    }
  }
}
"""

def fetch_all_prs(query):
    all_prs = []
    cursor = None
    while True:
        cmd = ["gh", "api", "graphql",
               "-f", "query=" + query,
               "-f", "owner=" + owner,
               "-f", "repo=" + repo]
        if cursor:
            cmd += ["-f", "cursor=" + cursor]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print("Error fetching PRs: " + result.stderr, file=sys.stderr)
            sys.exit(1)

        data = json.loads(result.stdout)
        pr_data = data["data"]["repository"]["pullRequests"]
        all_prs.extend(pr_data["nodes"])

        if pr_data["pageInfo"]["hasNextPage"]:
            cursor = pr_data["pageInfo"]["endCursor"]
        else:
            break
    return all_prs

def get_author(pr):
    if pr.get("author") and pr["author"].get("login"):
        return pr["author"]["login"]
    return ""

def fmt_date(d):
    if not d:
        return "n/a"
    return d[:10] + " " + d[11:16]


# Fetch and filter (only needed for list command)
if command == "list":
    all_prs = fetch_all_prs(GRAPHQL_QUERY_LIGHT)
    all_prs.sort(key=lambda pr: pr["number"])
    all_prs = [pr for pr in all_prs
               if get_author(pr) not in ignored
               and pr["number"] not in ignored_prs
               and not pr.get("isDraft", False)]

if command == "list":
    import re, threading, os, datetime
    if list_no_ai and list_ai_authors_str:
        ai_authors = set()
        for _a in list_ai_authors_str.split("|"):
            _a = _a.strip()
            if _a:
                ai_authors.add(_a)
    _now = datetime.datetime.now(datetime.timezone.utc)
    _week_ago = (_now - datetime.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")

    def fmt_date_only(d):
        return d[:10] if d else "n/a"

    def fmt_recent(d, blank_if_empty=False):
        if not d: return "" if blank_if_empty else "n/a"
        return (d[:10] + " " + d[11:16]) if d > _week_ago else d[:10]
    KNOWN_COLS   = ["pr", "title", "author", "loc", "num-comments",
                    "creation-date", "last-comment-time", "my-last-comment-time", "mark"]
    COL_ALIASES  = {"nc": "num-comments"}
    COL_HEADERS  = {"pr": "PR", "title": "TITLE", "author": "AUTHOR", "loc": "LOC",
                    "num-comments": "NC", "creation-date": "CREATED",
                    "last-comment-time": "LAST COMMENT", "my-last-comment-time": "MY LAST COMMENT",
                    "mark": "MARK"}
    COL_WIDTHS   = {"pr": 6,    "title": 60,       "author": 20,       "loc": 15,
                    "num-comments": 4, "creation-date": 11,
                    "last-comment-time": 17, "my-last-comment-time": 17, "mark": 17}

    def resolve_col(name):
        name = name.lower().strip()
        if name in COL_ALIASES:
            return COL_ALIASES[name]
        matches = [c for c in KNOWN_COLS if c.startswith(name)]
        if len(matches) == 1:
            return matches[0]
        if name in KNOWN_COLS:
            return name
        if not matches:
            print("Unknown column: %r" % name, file=sys.stderr); sys.exit(1)
        print("Ambiguous column %r (matches: %s)" % (name, ", ".join(matches)), file=sys.stderr); sys.exit(1)

    TIMESTAMP_COLS = {"creation-date", "last-comment-time", "my-last-comment-time", "mark"}
    COL_ABBREVS = {
        "pr": "PR", "title": "TTL", "author": "AUTH", "loc": "LOC",
        "num-comments": "NC", "creation-date": "CD",
        "last-comment-time": "LC", "my-last-comment-time": "MLC", "mark": "MARK",
    }

    def parse_col_spec(spec):
        spec = spec.strip()
        m = re.match(r'^(.+?)\s*(>|<)\s*(.+)$', spec)
        if m:
            left  = resolve_col(m.group(1).strip())
            right = resolve_col(m.group(3).strip())
            op    = m.group(2)
            for side, col in (("left", left), ("right", right)):
                if col not in TIMESTAMP_COLS:
                    print("Column %r is not a timestamp column" % col, file=sys.stderr); sys.exit(1)
            return ("cmp", left, op, right)
        return resolve_col(spec)

    def col_header(spec):
        if isinstance(spec, tuple):
            _, left, op, right = spec
            return "%s%s%s" % (COL_ABBREVS[left], op, COL_ABBREVS[right])
        return COL_HEADERS[spec]

    def col_width(spec):
        if isinstance(spec, tuple):
            return max(len(col_header(spec)), 5)  # 5 for "false"
        return COL_WIDTHS[spec]

    cols      = [parse_col_spec(c) for c in list_columns_str.split(",") if c.strip()] if list_columns_str else ["pr", "title", "author"]
    sort_cols = [resolve_col(c)    for c in list_sort_str.split(",")    if c.strip()] if list_sort_str    else []

    def _referenced_cols():
        names = set()
        for s in cols:
            if isinstance(s, tuple): names.add(s[1]); names.add(s[3])
            else: names.add(s)
        return names | set(sort_cols)
    _all_cols = _referenced_cols()

    # Read marks file
    marks = {}
    if list_marks_file and os.path.isfile(list_marks_file):
        with open(list_marks_file) as _f:
            for _line in _f:
                _parts = _line.strip().split(",", 1)
                if len(_parts) == 2:
                    try:
                        marks[int(_parts[0])] = _parts[1].strip()
                    except ValueError:
                        pass

    loc_results = {}
    if "loc" in _all_cols:
        def fetch_scala_loc(pr_num):
            cmd = ["gh", "api", "--paginate",
                   "repos/%s/%s/pulls/%d/files?per_page=100" % (owner, repo, pr_num),
                   "--jq", '.[] | select(.filename | endswith(".scala")) | [.additions, .deletions]']
            r = subprocess.run(cmd, capture_output=True, text=True)
            additions, deletions = 0, 0
            if r.returncode == 0:
                for line in r.stdout.strip().splitlines():
                    if line:
                        vals = json.loads(line)
                        additions += vals[0]
                        deletions += vals[1]
            loc_results[pr_num] = (additions, deletions)

        threads = [threading.Thread(target=fetch_scala_loc, args=(pr["number"],))
                   for pr in all_prs]
        for t in threads: t.start()
        for t in threads: t.join()

    COMMENT_COLS = {"num-comments", "last-comment-time", "my-last-comment-time"}
    comment_data = {}
    if COMMENT_COLS & _all_cols:
        def fetch_comment_data(pr_num):
            cmd = ["gh", "api", "graphql",
                   "-f", "query=" + GRAPHQL_QUERY_COMMENT_COUNTS,
                   "-f", "owner=" + owner,
                   "-f", "repo=" + repo,
                   "-F", "number=" + str(pr_num)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            comment_data[pr_num] = (json.loads(r.stdout)["data"]["repository"]["pullRequest"] or {}) \
                                   if r.returncode == 0 else {}

        threads = [threading.Thread(target=fetch_comment_data, args=(pr["number"],))
                   for pr in all_prs]
        for t in threads: t.start()
        for t in threads: t.join()

    def count_since(data, since):
        n = 0
        for c in data.get("comments", {}).get("nodes", []):
            if list_no_ai and is_ai_author((c.get("author") or {}).get("login", "")): continue
            if not since or c.get("createdAt", "") >= since: n += 1
        for rev in data.get("reviews", {}).get("nodes", []):
            if list_no_ai and is_ai_author((rev.get("author") or {}).get("login", "")): continue
            if not since or rev.get("submittedAt", "") >= since: n += 1
        for thread in data.get("reviewThreads", {}).get("nodes", []):
            for c in thread.get("comments", {}).get("nodes", []):
                if list_no_ai and is_ai_author((c.get("author") or {}).get("login", "")): continue
                if not since or c.get("createdAt", "") >= since: n += 1
        return n

    def get_last_comment(pr_num, user_only=False):
        data = comment_data.get(pr_num, {})
        dates = []
        for c in data.get("comments", {}).get("nodes", []):
            login = (c.get("author") or {}).get("login", "")
            if user_only and login != gh_user: continue
            if list_no_ai and is_ai_author(login): continue
            if c.get("createdAt"): dates.append(c["createdAt"])
        for rev in data.get("reviews", {}).get("nodes", []):
            login = (rev.get("author") or {}).get("login", "")
            if user_only and login != gh_user: continue
            if list_no_ai and is_ai_author(login): continue
            if rev.get("submittedAt"): dates.append(rev["submittedAt"])
        for thread in data.get("reviewThreads", {}).get("nodes", []):
            for c in thread.get("comments", {}).get("nodes", []):
                login = (c.get("author") or {}).get("login", "")
                if user_only and login != gh_user: continue
                if list_no_ai and is_ai_author(login): continue
                if c.get("createdAt"): dates.append(c["createdAt"])
        return max(dates) if dates else ""

    def timestamp_val(col, pr):
        if col == "creation-date":       return pr.get("createdAt", "")
        if col == "last-comment-time":   return get_last_comment(pr["number"])
        if col == "my-last-comment-time":return get_last_comment(pr["number"], user_only=True)
        if col == "mark":                return marks.get(pr["number"], "")
        return ""

    if sort_cols:
        def sort_key(pr):
            key = []
            for col in sort_cols:
                if col == "pr":                    key.append(pr["number"])
                elif col == "title":               key.append(pr["title"].lower())
                elif col == "author":              key.append(get_author(pr).lower())
                elif col == "creation-date":       key.append(pr.get("createdAt", "Z"))
                elif col == "last-comment-time":   key.append(get_last_comment(pr["number"]) or "Z")
                elif col == "my-last-comment-time":key.append(get_last_comment(pr["number"], user_only=True) or "Z")
                elif col == "loc":
                    adds, dels = loc_results.get(pr["number"], (0, 0))
                    key.append(-(adds + dels))
                elif col == "num-comments":
                    key.append(-count_since(comment_data.get(pr["number"], {}), marks.get(pr["number"])))
            return key
        all_prs.sort(key=sort_key)

    def cell(spec, pr):
        if isinstance(spec, tuple):
            _, left, op, right = spec
            lv = timestamp_val(left, pr)
            rv = timestamp_val(right, pr)
            if not lv or not rv: return "n/a"
            return "true" if (lv > rv if op == ">" else lv < rv) else "false"
        col = spec
        if col == "pr":                  return "#%-5s" % pr["number"]
        if col == "title":               return pr["title"][:58]
        if col == "author":              return get_author(pr)
        if col == "creation-date":       return fmt_date_only(pr.get("createdAt", ""))
        if col == "last-comment-time":   return fmt_recent(get_last_comment(pr["number"]))
        if col == "my-last-comment-time":return fmt_recent(get_last_comment(pr["number"], user_only=True), blank_if_empty=True)
        if col == "mark":                return fmt_recent(marks.get(pr["number"], ""), blank_if_empty=True)
        if col == "loc":
            adds, dels = loc_results.get(pr["number"], (0, 0))
            return "+%d/-%d" % (adds, dels) if (adds or dels) else "-"
        if col == "num-comments":
            return str(count_since(comment_data.get(pr["number"], {}), marks.get(pr["number"])))

    def fmt_row(vals):
        parts = ["%-*s" % (col_width(col), val) if i < len(cols) - 1 else val
                 for i, (col, val) in enumerate(zip(cols, vals))]
        return " ".join(parts)

    print(fmt_row([col_header(c) for c in cols]))
    print(fmt_row(["-" * col_width(c) for c in cols]))
    for pr in all_prs:
        print(fmt_row([cell(c, pr) for c in cols]))

elif command == "comments":
    import threading
    reviews_query = GRAPHQL_QUERY_COMMENTS_REVIEWS_NO_INLINE if no_inline else GRAPHQL_QUERY_COMMENTS_REVIEWS
    fetch_results = {}
    fetch_errors = []

    def run_fetch(key, query):
        cmd = ["gh", "api", "graphql",
               "-f", "query=" + query,
               "-f", "owner=" + owner,
               "-f", "repo=" + repo,
               "-F", "number=" + str(pr_number)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            fetch_errors.append("Error fetching PR: " + r.stderr)
        else:
            fetch_results[key] = json.loads(r.stdout)["data"]["repository"]["pullRequest"]

    t1 = threading.Thread(target=run_fetch, args=("issue", GRAPHQL_QUERY_COMMENTS_ISSUE))
    t2 = threading.Thread(target=run_fetch, args=("reviews", reviews_query))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    if fetch_errors:
        print(fetch_errors[0], file=sys.stderr)
        sys.exit(1)

    pr_issue = fetch_results.get("issue") or {}
    pr_reviews = fetch_results.get("reviews") or {}
    if not pr_issue and not pr_reviews:
        print("PR #%d not found." % pr_number, file=sys.stderr)
        sys.exit(1)

    # Build events sorted by primary date.
    # Issue comments and review bodies are individual events.
    # Each review thread (original inline comment + all replies) is one event,
    # so replies always follow their original comment regardless of submission date.
    events = []
    for c in pr_issue.get("comments", {}).get("nodes", []):
        author = (c.get("author") or {}).get("login", "")
        if no_ai and is_ai_author(author):
            continue
        date = c.get("createdAt", "")
        events.append((date, [(date, author, "comment", c.get("body", ""), False)]))
    for rev in pr_reviews.get("reviews", {}).get("nodes", []):
        author = (rev.get("author") or {}).get("login", "")
        if no_ai and is_ai_author(author):
            continue
        body = rev.get("body", "").strip()
        if body:
            date = rev.get("submittedAt", "")
            events.append((date, [(date, author, "review", body, False)]))
    if not no_inline:
        for thread in pr_reviews.get("reviewThreads", {}).get("nodes", []):
            all_comments = thread.get("comments", {}).get("nodes", [])
            thread_rows = []
            for i, c in enumerate(all_comments):
                author = (c.get("author") or {}).get("login", "")
                if no_ai and is_ai_author(author):
                    continue
                thread_rows.append((c.get("createdAt", ""), author, "inline", c.get("body", ""), i > 0))
            if thread_rows:
                events.append((thread_rows[0][0], thread_rows))
    events.sort(key=lambda x: x[0])
    if mark_timestamp and not show_all:
        events = [(d, rows) for d, rows in events
                  if max((r[0] for r in rows), default="") >= mark_timestamp]
    rows = [row for _, event_rows in events for row in event_rows]

    print("PR #%d: %s" % (pr_number, pr_issue.get("title", "")))
    print()
    print("%-17s %-20s %-8s %s" % ("DATE", "AUTHOR", "TYPE", "COMMENT"))
    print("%-17s %-20s %-8s %s" % ("-" * 17, "-" * 20, "-" * 8, "-" * 60))
    for date, author, typ, body, indent in rows:
        summary = ("  " if indent else "") + body.split("\n")[0][:70]
        print("%-17s %-20s %-8s %s" % (fmt_date(date), author[:20], typ, summary))
    if not rows:
        print("  No comments on this PR.")
PYEOF

# -- Interactive loop ----------------------------------------------------------

FOCUSED_PR=""
MARKS_FILE="$HOME/.pr-status/marks.csv"

echo "$OWNER/$REPO_NAME  (commands: list, comments <PR>)"
while true; do
    if [[ -n "$FOCUSED_PR" ]]; then
        printf "#%s> " "$FOCUSED_PR"
    else
        printf "> "
    fi
    IFS= read -r INPUT || { echo; break; }
    CMD="${INPUT%% *}"
    ARG="${INPUT#* }"
    [[ "$ARG" == "$INPUT" ]] && ARG=""
    ARG="${ARG#\#}"
    # A bare number focuses on that PR
    if [[ "$CMD" =~ ^[0-9]+$ && -z "$ARG" ]]; then
        FOCUSED_PR="$CMD"
        continue
    fi
    case "$CMD" in
        list|l)
            load_config
            NO_AI=0; [[ "$ARG" == *"--no-ai"* ]] && NO_AI=1
            SORT_COLS=""
            if [[ "$ARG" =~ --sort[[:space:]]+([^[:space:]]+) ]]; then
                SORT_COLS="${BASH_REMATCH[1]}"
            fi
            COLUMNS_ARG="$ARG"
            [[ "$COLUMNS_ARG" == *" --no-ai"* ]] && COLUMNS_ARG="${COLUMNS_ARG/ --no-ai/}"
            [[ "$COLUMNS_ARG" == "--no-ai"* ]] && COLUMNS_ARG="${COLUMNS_ARG#--no-ai}"
            [[ "$COLUMNS_ARG" == *" --sort"* ]] && COLUMNS_ARG="${COLUMNS_ARG%% --sort*}"
            [[ "$COLUMNS_ARG" == "--sort"* ]] && COLUMNS_ARG=""
            COLUMNS_ARG="${COLUMNS_ARG## }"
            COLUMNS_ARG="${COLUMNS_ARG%% }"
            python3 "$PYTHON_SCRIPT" "list" "$GH_USER" "$IGNORED_AUTHORS" "$OWNER" "$REPO_NAME" "$MAX_THREADS" "$IGNORED_PRS" "$COLUMNS_ARG" "$SORT_COLS" "$MARKS_FILE" "$NO_AI" "$AI_AUTHORS"
            ;;
        comments|c)
            load_config
            NO_AI=0; [[ "$ARG" == *"--no-ai"* ]] && NO_AI=1
            NO_INLINE=0; [[ "$ARG" == *"--no-inline"* ]] && NO_INLINE=1
            SHOW_ALL=0; [[ "$ARG" == *"--all"* ]] && SHOW_ALL=1
            PR_ARG="${ARG%% *}"
            [[ "$PR_ARG" == -* || -z "$PR_ARG" ]] && PR_ARG="$FOCUSED_PR"
            if [[ -z "$PR_ARG" ]]; then
                echo "Usage: comments <PR number> [--no-ai] [--no-inline] [--all]" >&2
            else
                MARK_TIMESTAMP=""
                [[ -f "$MARKS_FILE" ]] && MARK_TIMESTAMP="$(grep "^${PR_ARG}," "$MARKS_FILE" | cut -d',' -f2 | tail -1)"
                python3 "$PYTHON_SCRIPT" "comments" "$GH_USER" "$IGNORED_AUTHORS" "$OWNER" "$REPO_NAME" "$MAX_THREADS" "$IGNORED_PRS" "$PR_ARG" "$AI_AUTHORS" "$NO_AI" "$NO_INLINE" "$MARK_TIMESTAMP" "$SHOW_ALL"
            fi
            ;;
        mark|m)
            PR_ARG="${ARG%% *}"
            [[ -z "$PR_ARG" ]] && PR_ARG="$FOCUSED_PR"
            if [[ -z "$PR_ARG" ]]; then
                echo "Usage: mark [PR]" >&2
            else
                TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
                TMP="$(mktemp)"
                [[ -f "$MARKS_FILE" ]] && grep -v "^${PR_ARG}," "$MARKS_FILE" > "$TMP"
                echo "${PR_ARG},${TIMESTAMP}" >> "$TMP"
                mv "$TMP" "$MARKS_FILE"
                echo "Marked PR #${PR_ARG} at ${TIMESTAMP}"
            fi
            ;;
        unmark|n)
            PR_ARG="${ARG%% *}"
            [[ -z "$PR_ARG" ]] && PR_ARG="$FOCUSED_PR"
            if [[ -z "$PR_ARG" ]]; then
                echo "Usage: unmark [PR]" >&2
            elif [[ -f "$MARKS_FILE" ]] && grep -q "^${PR_ARG}," "$MARKS_FILE"; then
                TMP="$(mktemp)"
                grep -v "^${PR_ARG}," "$MARKS_FILE" > "$TMP"
                mv "$TMP" "$MARKS_FILE"
                echo "Unmarked PR #${PR_ARG}"
            else
                echo "PR #${PR_ARG} is not marked" >&2
            fi
            ;;
        up)
            FOCUSED_PR=""
            ;;
        help|h)
            cat <<HELP
Commands:
  list (l) [cols]       List PRs; cols = comma-separated from:
                        pr, title, author, loc, num-comments (nc),
                        creation-date, last-comment-time, my-last-comment-time, mark
                        Boolean comparison: col1>col2 or col1<col2 (timestamp cols only)
                          e.g. last-comment>my-last-comment  (true/false/n/a)
                        (default: pr,title,author); prefix abbreviations ok
                        --sort col,col,...  sort by columns (loc/nc descending, dates ascending)
                        --no-ai            exclude AI authors from comment counts/times
  comments (c) [PR]     Show comments for a PR [--no-ai] [--no-inline] [--all]
  mark (m) [PR]         Record current time for PR; comments hides older threads
  unmark (n) [PR]       Remove mark for PR
  <number>              Focus on a specific PR (prompt changes to #PR>)
  up                    Stop focusing on the current PR
  help (h)              Show this help message
  quit / exit           Exit

Config file format ($CONFIG_FILE):
  owner: OWNER
  repo-name: REPO_NAME
  ignore-author: user1, user2, user3
  ignore-pr: 1234, 5678
  ai-author: bot1, bot2
HELP
            ;;
        quit|exit|"")
            break
            ;;
        *)
            echo "Unknown command '$CMD'. Use: list, comments, help" >&2
            ;;
    esac
done
