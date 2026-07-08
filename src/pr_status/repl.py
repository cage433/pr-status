#!/usr/bin/env python3
import os
import sys
from datetime import date, timedelta

from .config import Config
from . import gh_api
from .marks import Marks
from .pr_number import PRNumber
from .report import run_report
from .report_args import ReportArgs
from .timely_cache import CACHE_START, ensure_cache_current, is_cache_current, refresh_range
from .timely_report import parse_month_spec, run_timely_report
from .timely_report_args import TimelyReportArgs

DEFAULT_CONFIG = os.path.expanduser("~/.config/pr-status/config")
MARKS_FILE     = os.path.expanduser("~/.cache/pr-status/marks")


def run_repl(
    config: Config,
    marks: Marks,
) -> None:
    focused_pr: PRNumber | None = None

    while True:
        try:
            prompt = "#%d> " % focused_pr if focused_pr else "> "
            try:
                line = input(prompt)
            except EOFError:
                print()
                break

            line = line.strip()
            if not line:
                break

            parts = line.split(None, 1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd in config.aliases:
                expanded = config.aliases[cmd]
                parts2 = expanded.split(None, 1)
                cmd        = parts2[0].lower()
                alias_arg  = parts2[1] if len(parts2) > 1 else ""
                arg        = (alias_arg + " " + arg).strip()

            if cmd in ("report", "r"):
                focus_filter = "--filter PR=%d " % focused_pr if focused_pr else ""
                if (report_args := ReportArgs.parse(focus_filter + arg)) is not None:
                    run_report(config, marks, report_args)

            elif cmd in ("mark", "m"):
                pr_str = arg.split()[0] if arg.strip() else None
                if pr_str is None:
                    print("Usage: mark PR", file=sys.stderr)
                else:
                    try:
                        marks.mark(PRNumber(int(pr_str)))
                    except ValueError:
                        print("Invalid PR number: %s" % pr_str, file=sys.stderr)

            elif cmd in ("unmark",):
                pr_str = arg.split()[0] if arg.strip() else None
                if pr_str is None:
                    print("Usage: unmark PR", file=sys.stderr)
                else:
                    try:
                        marks.unmark(PRNumber(int(pr_str)))
                    except ValueError:
                        print("Invalid PR number: %s" % pr_str, file=sys.stderr)

            elif cmd in ("focus", "f"):
                pr_str = arg.split()[0] if arg.strip() else None
                if pr_str is None:
                    print("Usage: focus PR", file=sys.stderr)
                else:
                    try:
                        focused_pr = PRNumber(int(pr_str))
                        print("Focused on PR #%d." % focused_pr)
                    except ValueError:
                        print("Invalid PR number: %s" % pr_str, file=sys.stderr)

            elif cmd in ("unfocus", "u"):
                focused_pr = None
                print("Unfocused.")

            elif cmd in ("timely", "t"):
                if not config.timely_access_token or not config.timely_account_id:
                    print("Error: timely-access-token and timely-account-id must be set in config.", file=sys.stderr)
                else:
                    if not is_cache_current():
                        print("Updating cache…", flush=True)
                        ensure_cache_current(config.timely_account_id, config.timely_access_token)
                    if (timely_args := TimelyReportArgs.parse(arg)) is not None:
                        run_timely_report(config, timely_args)

            elif cmd in ("refresh-timely-cache", "rtc"):
                if not config.timely_access_token or not config.timely_account_id:
                    print("Error: timely-access-token and timely-account-id must be set in config.", file=sys.stderr)
                else:
                    today = date.today()
                    tokens = arg.split()
                    upto = today + timedelta(days=1)
                    _KNOWN_RTC_FLAGS = {"--all", "--month", "--num-days"}
                    unknown = [t for t in tokens if t.startswith("--")
                               and t.split("=", 1)[0] not in _KNOWN_RTC_FLAGS]
                    if unknown:
                        print("Error: unknown rtc option(s): %s" % ", ".join(unknown), file=sys.stderr)
                        since = None
                    elif "--all" in tokens:
                        since = CACHE_START
                    else:
                        def _flag_val(flag: str) -> str | None:
                            for i, t in enumerate(tokens):
                                if t == flag and i + 1 < len(tokens):
                                    return tokens[i + 1]
                                if t.startswith(flag + "="):
                                    return t.split("=", 1)[1]
                            return None
                        month_val    = _flag_val("--month")
                        num_days_val = _flag_val("--num-days")
                        if month_val is not None:
                            try:
                                since, upto = parse_month_spec(month_val, today)
                            except Exception as e:
                                print("Error: %s" % e, file=sys.stderr)
                                since = None
                        elif num_days_val is not None:
                            try:
                                num_days = int(num_days_val)
                                since = today - timedelta(days=num_days - 1)
                            except ValueError:
                                since = today - timedelta(days=6)
                        else:
                            since = today - timedelta(days=6)
                    if since is not None:
                        print("Refreshing cache from %s to %s…" % (since, upto - timedelta(days=1)))
                        refresh_range(config.timely_account_id, config.timely_access_token,
                                      since, upto)
                    print("Done.")

            elif cmd in ("reload", "rl"):
                config = Config.load(DEFAULT_CONFIG)
                config.repo.gh_user = gh_api.get_gh_user()
                print("Config reloaded.")

            elif cmd in ("alias", "aliases"):
                if config.aliases:
                    for name, expansion in sorted(config.aliases.items()):
                        print("  %s -> %s" % (name, expansion))
                else:
                    print("No aliases configured.")

            elif cmd in ("quit", "exit"):
                break

            else:
                print("Unknown command '%s'. Use: report, timely (t), rtc, mark, unmark, focus, unfocus, reload, alias, quit" % cmd, file=sys.stderr)

        except KeyboardInterrupt:
            print()
            continue


def main() -> None:
    if not os.path.isfile(DEFAULT_CONFIG):
        print("Error: no config file found at %s.\n"
              "Create one as described in the Config section of the README." % DEFAULT_CONFIG,
              file=sys.stderr)
        sys.exit(1)

    config = Config.load(DEFAULT_CONFIG)
    config.repo.gh_user = gh_api.get_gh_user()

    if not config.repo.owner or not config.repo.repo_name:
        print("Error: no repository specified. Set 'owner:' and 'repo-name:' in config.", file=sys.stderr)
        sys.exit(1)

    run_repl(config, Marks(MARKS_FILE))


if __name__ == "__main__":
    main()
