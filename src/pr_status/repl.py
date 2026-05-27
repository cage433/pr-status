#!/usr/bin/env python3
import argparse
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
from .timely_report import run_timely_report
from .timely_report_args import TimelyReportArgs

DEFAULT_CONFIG = os.path.expanduser("~/.config/pr-status/config")
MARKS_FILE     = os.path.expanduser("~/.cache/pr-status/marks")


_HELP_TOPICS = {
    "columns":   "help_columns.txt",
    "filtering": "help_filtering.txt",
    "examples":  "help_examples.txt",
}


def show_help(script_name: str, config_file: str, topic: str = "") -> None:
    help_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "help")
    topic = topic.strip().lower()
    if topic:
        filename = _HELP_TOPICS.get(topic)
        if filename is None:
            print("Unknown help topic '%s'. Available topics: %s" % (topic, ", ".join(_HELP_TOPICS)), file=sys.stderr)
            return
        print(open(os.path.join(help_dir, filename)).read().rstrip())
    else:
        print(open(os.path.join(help_dir, "help_text.txt")).read().rstrip().format(script=script_name, config=config_file))


def run_repl(
    config: Config,
    marks: Marks,
    script_name: str,
    config_file: str,
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
                    if "--all" in tokens:
                        since = CACHE_START
                    else:
                        num_days = 7
                        for tok in tokens:
                            if tok.startswith("--num-days="):
                                try:
                                    num_days = int(tok.split("=", 1)[1])
                                except ValueError:
                                    pass
                        since = today - timedelta(days=num_days - 1)
                    print("Refreshing cache from %s to %s…" % (since, today))
                    refresh_range(config.timely_account_id, config.timely_access_token,
                                  since, today + timedelta(days=1))
                    print("Done.")

            elif cmd in ("reload", "rl"):
                config = Config.load(config_file)
                config.repo.gh_user = gh_api.get_gh_user()
                print("Config reloaded.")

            elif cmd in ("help", "h"):
                show_help(script_name, config.config_file or DEFAULT_CONFIG, arg)

            elif cmd in ("alias", "aliases"):
                if config.aliases:
                    for name, expansion in sorted(config.aliases.items()):
                        print("  %s -> %s" % (name, expansion))
                else:
                    print("No aliases configured.")

            elif cmd in ("quit", "exit"):
                break

            else:
                print("Unknown command '%s'. Use: report, timely (t), rtc, mark, unmark, focus, unfocus, reload, alias, help, quit" % cmd, file=sys.stderr)

        except KeyboardInterrupt:
            print()
            continue


def _offer_create_config() -> None:
    sample_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample.config")
    print("No config file found at %s." % DEFAULT_CONFIG)
    try:
        answer = input("Create one from the sample? [y/N] ").strip().lower()
    except EOFError:
        return
    if answer != "y":
        return
    os.makedirs(os.path.dirname(DEFAULT_CONFIG), exist_ok=True)
    with open(sample_path) as src, open(DEFAULT_CONFIG, "w") as dst:
        dst.write(src.read())
    print("Created %s — please edit it to set your owner and repo-name." % DEFAULT_CONFIG)


def main() -> None:
    parser = argparse.ArgumentParser(prog=os.path.basename(sys.argv[0]), add_help=False)
    parser.add_argument("-c", dest="config_file", default="",         metavar="CONFIG")
    parser.add_argument("-m", dest="marks_file",  default=MARKS_FILE, metavar="MARKS")
    parser.add_argument("-h", dest="show_help",   action="store_true")
    args = parser.parse_args()

    script_name = os.path.basename(sys.argv[0])

    if args.config_file and not os.path.isfile(args.config_file):
        print("Error: Config file not found: %s" % args.config_file, file=sys.stderr)
        sys.exit(1)

    if not args.config_file and not os.path.isfile(DEFAULT_CONFIG):
        _offer_create_config()

    config_file = args.config_file or (DEFAULT_CONFIG if os.path.isfile(DEFAULT_CONFIG) else "")

    if args.show_help:
        show_help(script_name, config_file or DEFAULT_CONFIG)
        sys.exit(0)

    config = Config.load(config_file)
    config.repo.gh_user = gh_api.get_gh_user()

    if not config.repo.owner or not config.repo.repo_name:
        print("Error: no repository specified. Set 'owner:' and 'repo-name:' in config.", file=sys.stderr)
        sys.exit(1)

    run_repl(config, Marks(args.marks_file), script_name, config_file)


if __name__ == "__main__":
    main()
