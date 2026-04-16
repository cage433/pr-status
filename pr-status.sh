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
show_loc = sys.argv[8] == "1" if command == "list" and len(sys.argv) > 8 else False
pr_number = int(sys.argv[8]) if command != "list" and len(sys.argv) > 8 else None
ai_authors_str = sys.argv[9] if len(sys.argv) > 9 else ""
no_ai = sys.argv[10] == "1" if len(sys.argv) > 10 else False
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
        author {
          login
        }
      }
    }
  }
}
"""

GRAPHQL_QUERY_FULL = """
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
        author {
          login
        }
        reviews(first: 50) {
          nodes {
            author { login }
            submittedAt
            state
          }
        }
        comments(first: 50) {
          nodes {
            author { login }
            createdAt
          }
        }
        reviewThreads(first: %d) {
          totalCount
          nodes {
            comments(first: 20) {
              nodes {
                author { login }
                createdAt
              }
            }
          }
        }
        commits(last: 1) {
          nodes {
            commit {
              committedDate
            }
          }
        }
      }
    }
  }
}
""" % max_threads

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

def get_my_dates(pr):
    dates = []
    for r in pr.get("reviews", {}).get("nodes", []):
        a = (r.get("author") or {}).get("login", "")
        if a == gh_user and r.get("submittedAt"):
            dates.append(r["submittedAt"])
    for c in pr.get("comments", {}).get("nodes", []):
        a = (c.get("author") or {}).get("login", "")
        if a == gh_user and c.get("createdAt"):
            dates.append(c["createdAt"])
    for t in pr.get("reviewThreads", {}).get("nodes", []):
        for c in t.get("comments", {}).get("nodes", []):
            a = (c.get("author") or {}).get("login", "")
            if a == gh_user and c.get("createdAt"):
                dates.append(c["createdAt"])
    return sorted(dates, reverse=True)

def get_all_comment_dates(pr):
    dates = []
    for r in pr.get("reviews", {}).get("nodes", []):
        if r.get("submittedAt") and r.get("state") in ("COMMENTED", "APPROVED", "CHANGES_REQUESTED"):
            dates.append(r["submittedAt"])
    for c in pr.get("comments", {}).get("nodes", []):
        if c.get("createdAt"):
            dates.append(c["createdAt"])
    for t in pr.get("reviewThreads", {}).get("nodes", []):
        for c in t.get("comments", {}).get("nodes", []):
            if c.get("createdAt"):
                dates.append(c["createdAt"])
    return sorted(dates, reverse=True)

def get_last_commit_date(pr):
    commits = pr.get("commits", {}).get("nodes", [])
    if commits:
        return commits[-1].get("commit", {}).get("committedDate", "")
    return ""

def fmt_date(d):
    if not d:
        return "n/a"
    return d[:10] + " " + d[11:16]


# Fetch and filter
if command == "list":
    all_prs = fetch_all_prs(GRAPHQL_QUERY_LIGHT)
else:
    all_prs = fetch_all_prs(GRAPHQL_QUERY_FULL)
all_prs.sort(key=lambda pr: pr["number"])
all_prs = [pr for pr in all_prs
           if get_author(pr) not in ignored
           and pr["number"] not in ignored_prs
           and not pr.get("isDraft", False)]

if command == "list":
    if show_loc:
        import threading
        loc_results = {}

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
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        all_prs.sort(key=lambda pr: -(sum(loc_results.get(pr["number"], (0, 0)))))

    if show_loc:
        print("%-6s %-60s %-20s %s" % ("PR", "TITLE", "AUTHOR", "LOC"))
        print("%-6s %-60s %-20s %s" % ("------", "-" * 60, "-" * 20, "-" * 12))
    else:
        print("%-6s %-60s %s" % ("PR", "TITLE", "AUTHOR"))
        print("%-6s %-60s %s" % ("------", "-" * 60, "-" * 20))
    for pr in all_prs:
        num = pr["number"]
        title = pr["title"][:58]
        author = get_author(pr)
        if show_loc:
            adds, dels = loc_results.get(num, (0, 0))
            loc = "+%d/-%d" % (adds, dels) if (adds or dels) else "-"
            print("#%-5s %-60s %-20s %s" % (num, title, author, loc))
        else:
            print("#%-5s %-60s %s" % (num, title, author))

elif command == "unreviewed":
    print("%-6s %-60s %s" % ("PR", "TITLE", "AUTHOR"))
    print("%-6s %-60s %s" % ("------", "-" * 60, "-" * 20))
    found = 0
    for pr in all_prs:
        my_dates = get_my_dates(pr)
        if not my_dates:
            num = pr["number"]
            title = pr["title"][:58]
            author = get_author(pr)
            print("#%-5s %-60s %s" % (num, title, author))
            found += 1
    if found == 0:
        print("  None -- you have reviewed every open PR!")

elif command == "reviewed":
    print("%-6s %-42s %-20s %-20s %s" % (
        "PR", "TITLE", "MY LAST COMMENT", "LAST COMMENT", "LAST COMMIT"))
    print("%-6s %-42s %-20s %-20s %s" % (
        "------", "-" * 42, "-" * 20, "-" * 20, "-" * 20))
    found = 0
    for pr in all_prs:
        my_dates = get_my_dates(pr)
        if not my_dates:
            continue
        found += 1
        num = pr["number"]
        title = pr["title"][:40]
        my_last = fmt_date(my_dates[0])
        all_dates = get_all_comment_dates(pr)
        last_any = fmt_date(all_dates[0] if all_dates else "")
        last_commit = fmt_date(get_last_commit_date(pr))
        print("#%-5s %-42s %-20s %-20s %s" % (
            num, title, my_last, last_any, last_commit))
    if found == 0:
        print("  None -- you have not reviewed any open PRs yet.")

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

echo "$OWNER/$REPO_NAME  (commands: list, unreviewed, reviewed, comments <PR>)"
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
            SHOW_LOC=0; [[ "$ARG" == *"--loc"* ]] && SHOW_LOC=1
            python3 "$PYTHON_SCRIPT" "list" "$GH_USER" "$IGNORED_AUTHORS" "$OWNER" "$REPO_NAME" "$MAX_THREADS" "$IGNORED_PRS" "$SHOW_LOC"
            ;;
        unreviewed|u)
            load_config
            python3 "$PYTHON_SCRIPT" "unreviewed" "$GH_USER" "$IGNORED_AUTHORS" "$OWNER" "$REPO_NAME" "$MAX_THREADS" "$IGNORED_PRS"
            ;;
        reviewed|r)
            load_config
            python3 "$PYTHON_SCRIPT" "reviewed" "$GH_USER" "$IGNORED_AUTHORS" "$OWNER" "$REPO_NAME" "$MAX_THREADS" "$IGNORED_PRS"
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
  list (l)              List all open PRs [--loc to add Scala LOC, sorted by size]
  unreviewed (u)        Show PRs you haven't reviewed
  reviewed (r)          Show PRs you've reviewed with timestamps
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
            echo "Unknown command '$CMD'. Use: list, unreviewed, reviewed, comments, help" >&2
            ;;
    esac
done
