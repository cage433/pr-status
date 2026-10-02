#!/usr/bin/env bash

if ! command -v uv &>/dev/null; then
    echo "Error: 'uv' is not installed. See https://docs.astral.sh/uv/" >&2
    exit 1
fi

if ! command -v rlwrap &>/dev/null; then
    echo "Error: 'rlwrap' is not installed. Install with: brew install rlwrap" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The word list the repl wrote on its last run, for tab completion of commands, config
# aliases and column names. Touched so that a first run doesn't warn about it.
COMPLETIONS="$HOME/.cache/pr-status/completions"
mkdir -p "$(dirname "$COMPLETIONS")" && touch "$COMPLETIONS"

# -C names rlwrap's history and completion files after this repl rather than after uv,
# which is the command it actually wraps. -b drops rlwrap's default word-breaking
# characters, which include the hyphen that most command and column names carry; it only
# applies to -f options that follow it.
exec rlwrap -C pr-status -b $' \t\n' -f "$COMPLETIONS" \
     uv run --project "$SCRIPT_DIR" repl "$@"
