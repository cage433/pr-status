import os
import sys
from typing import Iterable

from .columns import ALL_COLUMNS
from .repl_command import COMMANDS


def completion_words(config_aliases: Iterable[str]) -> list[str]:
    """Every word rlwrap completes on: the repl's own commands, the report aliases the
    config defines, and the report columns. A column whose name carries a space — such
    as `unresolved (all)` — is left out, since rlwrap breaks its word list on
    whitespace and would complete the halves rather than the name."""
    words = {name for c in COMMANDS for name in c.names}
    words |= {a for a in config_aliases if a and not any(ch.isspace() for ch in a)}
    for col in ALL_COLUMNS:
        if not any(ch.isspace() for ch in col.name):
            words.add(col.name)
        words.update(col.aliases)
    return sorted(words)


def write_completions(path: str, config_aliases: Iterable[str]) -> None:
    """Write the word list rlwrap reads at its next start (see pr-status.sh). The repl
    writing its own list keeps it in step with the config and the columns without a
    second interpreter at launch — at the cost of it being one session behind, which
    only shows when an alias has just been added."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("\n".join(completion_words(config_aliases)) + "\n")
    except OSError as e:
        print("Warning: could not write completions to %s: %s" % (path, e), file=sys.stderr)
