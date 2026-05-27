import argparse
import shlex
import sys
from dataclasses import dataclass


@dataclass
class TimelyReportArgs:
    sort: str
    filters: list[str]
    columns: str

    @staticmethod
    def parse(arg_str: str) -> "TimelyReportArgs | None":
        lp = argparse.ArgumentParser(prog="timely", add_help=False, exit_on_error=False)
        lp.add_argument("--sort", default="")
        lp.add_argument("--filter", dest="filters", action="append", default=[])
        lp.add_argument("columns", nargs="?", default="")
        try:
            tokens = shlex.split(arg_str)
        except ValueError as e:
            print("Error parsing timely arguments: %s" % e, file=sys.stderr)
            return None
        try:
            largs = lp.parse_args(tokens)
        except (argparse.ArgumentError, SystemExit) as e:
            print("Error parsing timely arguments: %s" % e, file=sys.stderr)
            return None
        return TimelyReportArgs(sort=largs.sort, filters=largs.filters, columns=largs.columns)
