import json
import subprocess
import sys

from .config import GithubInfo
from .loc import LOC
from .node import Node
from .pr_number import PRNumber

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
          }
        }
        labels(first: 20) {
          nodes { name }
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


def get_gh_user() -> str:
    r = subprocess.run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True)
    if r.returncode != 0:
        print("Error: Could not determine GitHub username. Are you logged in? Run 'gh auth login'.", file=sys.stderr)
        sys.exit(1)
    return r.stdout.strip()


def fetch_pr_nodes(repo: GithubInfo) -> list[Node]:
    nodes: list[Node] = []
    cursor: str | None = None
    while True:
        cmd = ["gh", "api", "graphql",
               "-f", "query=" + GRAPHQL_QUERY_LIGHT,
               "-f", "owner=" + repo.owner,
               "-f", "repo=" + repo.repo_name]
        if cursor:
            cmd += ["-f", "cursor=" + cursor]
        result = subprocess.run(cmd, capture_output=True, text=True)
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
    r = subprocess.run(cmd, capture_output=True, text=True)
    lines = r.stdout.strip().splitlines() if r.returncode == 0 else []
    parsed = [json.loads(l) for l in lines if l]
    return (sum(p[0] for p in parsed), sum(p[1] for p in parsed))


def fetch_pr_comment_data(repo: GithubInfo, pr_num: PRNumber) -> Node:
    cmd = ["gh", "api", "graphql",
           "-f", "query=" + GRAPHQL_QUERY_COMMENT_COUNTS,
           "-f", "owner=" + repo.owner,
           "-f", "repo=" + repo.repo_name,
           "-F", "number=" + str(pr_num)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    try:
        pr_data = ((json.loads(r.stdout).get("data") or {}).get("repository") or {}).get("pullRequest")
        return pr_data or {}
    except Exception:
        return {}
