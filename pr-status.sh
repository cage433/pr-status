#!/usr/bin/env bash

if ! command -v uv &>/dev/null; then
    echo "Error: 'uv' is not installed. See https://docs.astral.sh/uv/" >&2
    exit 1
fi

if ! command -v rlwrap &>/dev/null; then
    echo "Error: 'rlwrap' is not installed. Install with: brew install rlwrap" >&2
    exit 1
fi

exec rlwrap uv run repl "$@"
