Utility for keeping track of PR reviews

## Usage

```
pr-status.sh [-r OWNER/REPO] [-c CONFIG] [-t THREADS]
```

Launches an interactive prompt. Available commands (single-letter abbreviations accepted):

- `list` (`l`) — List all open pull requests
- `unreviewed` (`u`) — List open PRs you haven't reviewed
- `reviewed` (`r`) — List open PRs you've reviewed, with activity timestamps
- `comments` (`c`) `<PR> [-no-ai]` — Show a one-line summary of every comment on a PR; `-no-ai` excludes comments from AI authors
- `quit` / `exit` — Exit

## Options

- `-r REPO` — Repository in OWNER/REPO format (overrides config)
- `-c CONFIG` — Path to config file (default: `~/.pr-status/config`)
- `-t THREADS` — Max review threads to fetch per PR (default: 50)
- `-h` — Show help message

## Config file

Optional file at `~/.pr-status/config` (or specified via `-c`):

```
owner: OWNER
repo-name: REPO_NAME
ignore-author: user1, user2, user3
ignore-pr: 1234, 5678
ai-author: bot1, bot2
```

## Prerequisites

- [`gh`](https://cli.github.com/) installed and authenticated (`gh auth login`)
- Python 3
