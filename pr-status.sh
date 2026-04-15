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
pr_number = int(sys.argv[8]) if len(sys.argv) > 8 else None
ai_authors_str = sys.argv[9] if len(sys.argv) > 9 else ""
no_ai = sys.argv[10] == "1" if len(sys.argv) > 10 else False

ai_authors = set()
if ai_authors_str:
    for a in ai_authors_str.split("|"):
        a = a.strip()
        if a:
            ai_authors.add(a)

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

GRAPHQL_QUERY_COMMENTS = """
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
      reviews(first: 100) {
        nodes {
          author { login }
          submittedAt
          body
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
    print("%-6s %-60s %s" % ("PR", "TITLE", "AUTHOR"))
    print("%-6s %-60s %s" % ("------", "-" * 60, "-" * 20))
    for pr in all_prs:
        num = pr["number"]
        title = pr["title"][:58]
        author = get_author(pr)
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
    cmd = ["gh", "api", "graphql",
           "-f", "query=" + GRAPHQL_QUERY_COMMENTS,
           "-f", "owner=" + owner,
           "-f", "repo=" + repo,
           "-F", "number=" + str(pr_number)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("Error fetching PR: " + result.stderr, file=sys.stderr)
        sys.exit(1)
    pr = json.loads(result.stdout)["data"]["repository"]["pullRequest"]
    if pr is None:
        print("PR #%d not found." % pr_number, file=sys.stderr)
        sys.exit(1)

    rows = []
    for c in pr.get("comments", {}).get("nodes", []):
        author = (c.get("author") or {}).get("login", "")
        if no_ai and author in ai_authors:
            continue
        rows.append((c.get("createdAt", ""), author, "comment", c.get("body", "")))
    for rev in pr.get("reviews", {}).get("nodes", []):
        author = (rev.get("author") or {}).get("login", "")
        body = rev.get("body", "").strip()
        if not (no_ai and author in ai_authors):
            if body:
                rows.append((rev.get("submittedAt", ""), author, "review", body))
            for c in rev.get("comments", {}).get("nodes", []):
                rows.append((c.get("createdAt", ""), author, "inline", c.get("body", "")))
    rows.sort(key=lambda x: x[0])

    print("PR #%d: %s" % (pr_number, pr.get("title", "")))
    print()
    print("%-17s %-20s %-8s %s" % ("DATE", "AUTHOR", "TYPE", "COMMENT"))
    print("%-17s %-20s %-8s %s" % ("-" * 17, "-" * 20, "-" * 8, "-" * 60))
    for date, author, typ, body in rows:
        summary = body.split("\n")[0][:70]
        print("%-17s %-20s %-8s %s" % (fmt_date(date), author[:20], typ, summary))
    if not rows:
        print("  No comments on this PR.")
PYEOF

# -- Interactive loop ----------------------------------------------------------

echo "$OWNER/$REPO_NAME  (commands: list, unreviewed, reviewed, comments <PR>)"
while true; do
    printf "> "
    IFS= read -r INPUT || { echo; break; }
    CMD="${INPUT%% *}"
    ARG="${INPUT#* }"
    [[ "$ARG" == "$INPUT" ]] && ARG=""
    ARG="${ARG#\#}"
    case "$CMD" in
        list|l)
            python3 "$PYTHON_SCRIPT" "list" "$GH_USER" "$IGNORED_AUTHORS" "$OWNER" "$REPO_NAME" "$MAX_THREADS" "$IGNORED_PRS"
            ;;
        unreviewed|u)
            python3 "$PYTHON_SCRIPT" "unreviewed" "$GH_USER" "$IGNORED_AUTHORS" "$OWNER" "$REPO_NAME" "$MAX_THREADS" "$IGNORED_PRS"
            ;;
        reviewed|r)
            python3 "$PYTHON_SCRIPT" "reviewed" "$GH_USER" "$IGNORED_AUTHORS" "$OWNER" "$REPO_NAME" "$MAX_THREADS" "$IGNORED_PRS"
            ;;
        comments|c)
            PR_ARG="${ARG%% *}"
            REST="${ARG#* }"; [[ "$REST" == "$ARG" ]] && REST=""
            NO_AI=0; [[ "$REST" == *"-no-ai"* ]] && NO_AI=1
            if [[ -z "$PR_ARG" ]]; then
                echo "Usage: comments <PR number> [-no-ai]" >&2
            else
                python3 "$PYTHON_SCRIPT" "comments" "$GH_USER" "$IGNORED_AUTHORS" "$OWNER" "$REPO_NAME" "$MAX_THREADS" "$IGNORED_PRS" "$PR_ARG" "$AI_AUTHORS" "$NO_AI"
            fi
            ;;
        quit|exit|"")
            break
            ;;
        *)
            echo "Unknown command '$CMD'. Use: list, unreviewed, reviewed, comments <PR>" >&2
            ;;
    esac
done
