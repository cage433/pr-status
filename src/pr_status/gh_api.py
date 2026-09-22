import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

from ._util import timing_log
from .config import GithubInfo
from .loc import LOC
from .node import Node
from .pr_number import PRNumber


T = TypeVar("T")


def _run_gh(cmd: list[str], label: str) -> "subprocess.CompletedProcess[str]":
    t0 = time.monotonic()
    r = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.monotonic() - t0
    if r.returncode != 0:
        timing_log("%s %.3fs FAILED rc=%d %s" % (label, dt, r.returncode, r.stderr.strip()[:200]))
    else:
        timing_log("%s %.3fs" % (label, dt))
    return r

# The light PR query, split into two groups of fields fetched concurrently. GitHub
# takes roughly as long for a group as for the whole query, so asking for both at once
# costs the time of the slower group rather than the sum: about 5s rather than 8s for
# this repo's 100 open PRs.
PR_FIELDS_CORE = """
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
"""

# `body` rather than `bodyText`: only its emptiness is read (see _is_submitted_review),
# and GitHub renders bodyText per review, which costs several seconds a page here.
PR_FIELDS_REVIEWS = """
        number
        reviews(first: 100) {
          nodes {
            author { login }
            state
            body
          }
        }
"""

# The open PRs are listed through the search API rather than the repository's
# pullRequests connection, because only search can leave out drafts (about half the
# open PRs here) and narrow to an author or a requested reviewer server-side. Search
# reads a separate, eventually-consistent index, so a PR opened — or a review requested
# — a moment ago may take a little while to appear.
SEARCH_QUERY = """
query($q: String!, $cursor: String) {
  search(query: $q, type: ISSUE, first: 100, after: $cursor) {
    issueCount
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      ... on PullRequest {%s      }
    }
  }
}
"""

# Search will not return more than this many results however many match, so a query
# reaching it is answered from the repository's pullRequests connection instead.
SEARCH_RESULT_LIMIT = 1000

CONNECTION_QUERY = """
query($owner: String!, $repo: String!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequests(states: OPEN, first: 100, after: $cursor) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {%s      }
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


def _fetch_search_pages(query: str, fields: str, label: str) -> tuple[list[Node], int]:
    """The PRs matching a search query, and how many GitHub says match in all — which
    exceeds what it will hand over once it passes SEARCH_RESULT_LIMIT."""
    nodes: list[Node] = []
    issue_count = 0
    cursor: str | None = None
    page = 0
    while True:
        page += 1
        cmd = ["gh", "api", "graphql",
               "-f", "query=" + SEARCH_QUERY % fields,
               "-f", "q=" + query]
        if cursor:
            cmd += ["-f", "cursor=" + cursor]
        result = _run_gh(cmd, "pr-search(%s) page %d" % (label, page))
        if result.returncode != 0:
            print("Error fetching PRs: " + result.stderr, file=sys.stderr)
            sys.exit(1)
        data = json.loads(result.stdout)["data"]["search"]
        nodes.extend(data["nodes"])
        issue_count = data["issueCount"]
        if data["pageInfo"]["hasNextPage"]:
            cursor = data["pageInfo"]["endCursor"]
        else:
            return nodes, issue_count


def _fetch_connection_pages(repo: GithubInfo, fields: str, label: str) -> list[Node]:
    nodes: list[Node] = []
    cursor: str | None = None
    page = 0
    while True:
        page += 1
        cmd = ["gh", "api", "graphql",
               "-f", "query=" + CONNECTION_QUERY % fields,
               "-f", "owner=" + repo.owner,
               "-f", "repo=" + repo.repo_name]
        if cursor:
            cmd += ["-f", "cursor=" + cursor]
        result = _run_gh(cmd, "pr-nodes(%s) page %d" % (label, page))
        if result.returncode != 0:
            print("Error fetching PRs: " + result.stderr, file=sys.stderr)
            sys.exit(1)
        data = json.loads(result.stdout)["data"]["repository"]["pullRequests"]
        nodes.extend(data["nodes"])
        if data["pageInfo"]["hasNextPage"]:
            cursor = data["pageInfo"]["endCursor"]
        else:
            return nodes


def _merge_field_groups(core: list[Node], reviews: list[Node]) -> list[Node]:
    """One node per PR carrying both field groups.

    The core group decides which PRs are reported: a PR the reviews group saw but the
    core group did not (one opened between the two fetches) is dropped, since without
    the core fields there is nothing to report about it. One the core group saw but the
    reviews group did not simply has no reviews recorded.
    """
    by_number = {n["number"]: n for n in core}
    for n in reviews:
        if (node := by_number.get(n["number"])) is not None:
            node.update(n)
    return sorted(by_number.values(), key=lambda n: n["number"])


def _fetch_both_groups(fetch_group: "Callable[[str, str], T]") -> "tuple[T, T]":
    """Run a fetch for each field group at once, returning what each answered. GitHub
    takes roughly as long over a group of PR fields as over all of them, so asking for
    both together costs the slower group rather than the sum."""
    with ThreadPoolExecutor(max_workers=2) as ex:
        core_future    = ex.submit(fetch_group, PR_FIELDS_CORE,    "core")
        reviews_future = ex.submit(fetch_group, PR_FIELDS_REVIEWS, "reviews")
        return core_future.result(), reviews_future.result()


def fetch_pr_nodes(repo: GithubInfo, search_query: str) -> list[Node]:
    (core, issue_count), (reviews, _) = _fetch_both_groups(
        lambda fields, label: _fetch_search_pages(search_query, fields, label))
    if issue_count > SEARCH_RESULT_LIMIT:
        timing_log("search matched %d PRs, past the %d it will return; using the "
                   "pullRequests connection instead" % (issue_count, SEARCH_RESULT_LIMIT))
        core, reviews = _fetch_both_groups(
            lambda fields, label: _fetch_connection_pages(repo, fields, label))
    return _merge_field_groups(core, reviews)


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
