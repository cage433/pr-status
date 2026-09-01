import json
import subprocess
import sys
import time

from ._util import timing_log
from .config import GithubInfo
from .loc import LOC
from .node import Node
from .pr_number import PRNumber


def _run_gh(cmd: list[str], label: str) -> "subprocess.CompletedProcess[str]":
    t0 = time.monotonic()
    r = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.monotonic() - t0
    if r.returncode != 0:
        timing_log("%s %.3fs FAILED rc=%d %s" % (label, dt, r.returncode, r.stderr.strip()[:200]))
    else:
        timing_log("%s %.3fs" % (label, dt))
    return r

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
        headRefName
        author {
          login
        }
        reviewRequests(first: 20) {
          nodes {
            requestedReviewer {
              ... on User { login }
              ... on Team { name }
            }
          }
        }
        reviews(first: 100) {
          nodes {
            author { login }
            state
            bodyText
          }
        }
        timelineItems(last: 20, itemTypes: [REVIEW_REQUESTED_EVENT]) {
          nodes {
            ... on ReviewRequestedEvent {
              requestedReviewer {
                ... on User { login }
                ... on Team { name }
              }
            }
          }
        }
        labels(first: 20) {
          nodes { name }
        }
        commits(last: 1) {
          nodes {
            commit {
              statusCheckRollup {
                state
                contexts { totalCount }
              }
            }
          }
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
        nodes { author { login } createdAt body }
      }
      reviews(first: 100) {
        nodes { author { login } submittedAt body }
      }
      reviewThreads(first: 100) {
        nodes {
          isResolved
          isOutdated
          comments(first: 50) {
            nodes { author { login } createdAt body }
          }
        }
      }
    }
  }
}
"""

# Minimal variant for reports that only need unresolved-thread counts (e.g. the UH/UA
# columns): no comment/review bodies, no top-level comments/reviews, and threads at
# depth 1 (only the first comment's author is used). ~25x fewer nodes than the full
# query, which cuts GitHub response time and payload for reports like 'all'.
GRAPHQL_QUERY_UNRESOLVED_ONLY = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        nodes {
          isResolved
          isOutdated
          comments(first: 1) {
            nodes { author { login } }
          }
        }
      }
    }
  }
}
"""


def get_gh_user() -> str:
    r = subprocess.run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True)
    if r.returncode != 0:
        print("Error: Could not determine GitHub username. Are you logged in? Run 'gh auth login'.", file=sys.stderr)
        sys.exit(1)
    return r.stdout.strip()


def fetch_pr_nodes(repo: GithubInfo) -> list[Node]:
    nodes: list[Node] = []
    cursor: str | None = None
    page = 0
    while True:
        page += 1
        cmd = ["gh", "api", "graphql",
               "-f", "query=" + GRAPHQL_QUERY_LIGHT,
               "-f", "owner=" + repo.owner,
               "-f", "repo=" + repo.repo_name]
        if cursor:
            cmd += ["-f", "cursor=" + cursor]
        result = _run_gh(cmd, "pr-nodes page %d" % page)
        if result.returncode != 0:
            print("Error fetching PRs: " + result.stderr, file=sys.stderr)
            sys.exit(1)
        data = json.loads(result.stdout)
        pr_data = data["data"]["repository"]["pullRequests"]
        nodes.extend(pr_data["nodes"])
        if pr_data["pageInfo"]["hasNextPage"]:
            cursor = pr_data["pageInfo"]["endCursor"]
        else:
            break
    return nodes


def fetch_scala_loc(repo: GithubInfo, pr_num: PRNumber) -> LOC:
    cmd = ["gh", "api", "--paginate",
           "repos/%s/%s/pulls/%d/files?per_page=100" % (repo.owner, repo.repo_name, pr_num),
           "--jq", '.[] | select(.filename | endswith(".scala")) | [.additions, .deletions]']
    r = _run_gh(cmd, "loc pr#%d" % pr_num)
    lines = r.stdout.strip().splitlines() if r.returncode == 0 else []
    parsed = [json.loads(l) for l in lines if l]
    return (sum(p[0] for p in parsed), sum(p[1] for p in parsed))


def fetch_pr_comment_data(repo: GithubInfo, pr_num: PRNumber, minimal: bool = False) -> Node:
    query = GRAPHQL_QUERY_UNRESOLVED_ONLY if minimal else GRAPHQL_QUERY_COMMENT_COUNTS
    cmd = ["gh", "api", "graphql",
           "-f", "query=" + query,
           "-f", "owner=" + repo.owner,
           "-f", "repo=" + repo.repo_name,
           "-F", "number=" + str(pr_num)]
    r = _run_gh(cmd, "comments pr#%d" % pr_num)
    if r.returncode != 0:
        return {}
    try:
        pr_data = ((json.loads(r.stdout).get("data") or {}).get("repository") or {}).get("pullRequest")
        return pr_data or {}
    except Exception:
        return {}
