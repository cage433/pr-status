from dataclasses import dataclass


@dataclass(frozen=True)
class ReplCommand:
    """A command the repl answers to: the name it is listed and completed under, the
    short forms it also answers to, and what it does."""
    name:        str
    aliases:     tuple[str, ...]
    description: str

    def matches(self, cmd: str) -> bool:
        return cmd == self.name or cmd in self.aliases

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name,) + self.aliases

    @property
    def alias_str(self) -> str:
        return ", ".join(self.aliases)


REPORT   = ReplCommand("report",   ("r",),         "Run a PR report")
FOCUS    = ReplCommand("focus",    ("f",),         "Restrict later reports to one PR")
UNFOCUS  = ReplCommand("unfocus",  ("u",),         "Report on every PR again")
TIMELY   = ReplCommand("timely",   ("t",),         "Run a Timely report")
RTC      = ReplCommand("refresh-timely-cache", ("rtc",), "Refresh the Timely event cache")
COLUMNS  = ReplCommand("columns",  ("cols",),      "List the available report columns")
ALIAS    = ReplCommand("alias",    ("aliases",),   "List the aliased reports from the config")
RELOAD   = ReplCommand("reload",   ("rl",),        "Reload the config file")
HELP     = ReplCommand("help",     ("h", "?"),     "List these commands")
QUIT     = ReplCommand("quit",     ("exit",),      "Leave the repl")

COMMANDS: list[ReplCommand] = [
    REPORT, FOCUS, UNFOCUS, TIMELY, RTC,
    COLUMNS, ALIAS, RELOAD, HELP, QUIT,
]


def command_listing() -> list[str]:
    """One line per command — its name, its short forms and what it does, aligned to
    the widest entry of each."""
    rows   = [(c.name, c.alias_str, c.description) for c in COMMANDS]
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return ["  ".join(f.ljust(w) for f, w in zip(row, widths)).rstrip() for row in rows]
