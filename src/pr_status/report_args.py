import argparse
import shlex
import sys
from dataclasses import dataclass


@dataclass
class ReportArgs:
    include_ai: bool
    include_drafts: bool
    sort: str
    filters: list[str]
    columns: str

    @staticmethod
    def parse(arg_str: str) -> "ReportArgs | None":
        lp = argparse.ArgumentParser(prog="report", add_help=False, exit_on_error=False)
        lp.add_argument("--include-ai", action="store_true")
        lp.add_argument("--include-drafts", action="store_true")
        lp.add_argument("--sort", default="")
        lp.add_argument("--filter", dest="filters", action="append", default=[])
        # Several column lists are joined into one, so that columns added after an
        # alias - which may come after the alias's options - extend the alias's own.
        lp.add_argument("columns", nargs="*", default=[])
        try:
            tokens = shlex.split(arg_str)
        except ValueError as e:
            print("Error parsing list arguments: %s" % e, file=sys.stderr)
            return None
        try:
            largs = lp.parse_intermixed_args(tokens)
        except (argparse.ArgumentError, SystemExit) as e:
            print("Error parsing list arguments: %s" % e, file=sys.stderr)
            return None
        return ReportArgs(
            include_ai=largs.include_ai,
            include_drafts=largs.include_drafts,
            sort=largs.sort,
            filters=largs.filters,
            columns=",".join(largs.columns),
        )
