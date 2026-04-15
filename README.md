Utility for keeping track of PR reviews

## Usage

```
pr-status.sh [-r OWNER/REPO] [-c CONFIG] [-t THREADS] <command>
```

## Commands

- `list` — List all open pull requests
- `unreviewed` — List open PRs you haven't reviewed
- `reviewed` — List open PRs you've reviewed, with activity timestamps

## Options

- `-r REPO` — Repository in OWNER/REPO format (overrides config)
- `-c CONFIG` — Path to config file (default: `~/.pr-status.conf`)
- `-t THREADS` — Max review threads to fetch per PR (default: 50)
- `-h` — Show help message

## Config file

Optional file at `~/.pr-status.conf` (or specified via `-c`):

```
owner: OWNER
repo: REPO
ignore-author: user1, user2, user3
ignore-pr: 1234, 5678
```

## Prerequisites

- [`gh`](https://cli.github.com/) installed and authenticated (`gh auth login`)
- Python 3
