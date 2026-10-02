import os
import re
import sys
from dataclasses import dataclass, field

from .pr_number import PRNumber

# Every setting that carries a credential. The list is deliberately independent of the
# parse branches below: some of these are other tools' credentials that this parser
# never reads, but they must stay out of a config kept in version control all the same.
CREDENTIAL_KEYS = frozenset({
    "youtrack-token",
    "teamcity-token",
    "timely-access-token",
    "timely-refresh-token",
    "timely-account-id",
    "timely-application-id",
    "timely-secret",
    "timely-code",
})


def credential_key(line: str) -> str:
    """The credential a line carries, or "" for any other line. A commented-out line
    still counts: a secret is no less exposed for being switched off."""
    key = line.lstrip("#").split(":", 1)[0].strip()
    return key if key in CREDENTIAL_KEYS else ""


def broken_symlink(path: str) -> bool:
    """Whether a path is a symlink to something that isn't there — which is how a file
    kept in cloud storage looks whenever that storage isn't mounted. Worth telling apart
    from a file that was never created, since the two call for opposite remedies."""
    return os.path.islink(path) and not os.path.exists(path)


def _read_lines(path: str) -> list[str]:
    """The lines of a config or keys file, or none when it isn't there. A keys file
    symlinked into cloud storage goes missing whenever that storage isn't mounted, so
    say which file was unreadable rather than leaving the tokens silently blank."""
    if not path:
        return []
    if not os.path.exists(path):
        if broken_symlink(path):
            print("Warning: %s is a broken symlink — is its storage mounted?" % path,
                  file=sys.stderr)
        return []
    try:
        with open(path) as f:
            return f.read().splitlines()
    except OSError as e:
        print("Warning: could not read %s: %s" % (path, e), file=sys.stderr)
        return []


@dataclass
class GithubInfo:
    owner: str
    repo_name: str
    gh_user: str = ""


@dataclass
class Config:
    repo: GithubInfo
    ignored_authors: set[str]
    ignored_prs: set[PRNumber]
    ai_authors: set[str]
    author_names: dict[str, str]
    ignored_comment_patterns: list[re.Pattern]
    ignored_title_patterns: list[re.Pattern]
    ignored_labels: set[str]
    aliases: dict[str, str]
    this_author: str = ""
    max_threads: int = 50
    config_file: str = ""
    youtrack_url: str = ""
    youtrack_token: str = ""
    youtrack_verify_ssl: bool = True
    youtrack_threads: int = 10
    timely_access_token: str = ""
    timely_account_id: str = ""
    timely_ignored_projects: set[str] = field(default_factory=set)
    timely_short_names: dict[str, str] = field(default_factory=dict)
    timely_short_projects: dict[str, str] = field(default_factory=dict)
    timely_yt_map: dict[str, str] = field(default_factory=dict)

    def author_name(self, author: str) -> str:
        return self.author_names.get(author, author)

    def logins_for_name(self, name: str) -> list[str]:
        """Every login a filter value names — exactly those whose author_name is `name`.
        That is the logins the config gives that display name, plus the value itself
        unless the config names it, since author_name falls back to the login.
        """
        logins = [login for login, n in self.author_names.items() if n == name]
        if name not in self.author_names:
            logins.append(name)
        return logins

    def login_for_name(self, name: str) -> str:
        """The one login a value names, for a search qualifier that cannot be repeated,
        or "" when no single login will do. Unlike logins_for_name this reads a value
        the config maps as that mapping alone, dropping the chance that it is also the
        login of an account the config says nothing about: a qualifier that cannot be
        ORed has no way to cover both.
        """
        mapped = [login for login, n in self.author_names.items() if n == name]
        if mapped:
            return mapped[0] if len(mapped) == 1 else ""
        return name

    def is_ai_author(self, login: str) -> bool:
        return login in self.ai_authors or login.removesuffix("[bot]") in self.ai_authors

    @staticmethod
    def keys_file_for(config_file: str) -> str:
        """Where the credentials live: a `keys` file beside the config. Keeping it out
        of the config is what lets the config itself be version controlled."""
        return os.path.join(os.path.dirname(config_file), "keys") if config_file else ""

    @staticmethod
    def load(config_file: str) -> "Config":
        owner = ""
        repo_name = ""
        ignored_authors: set[str] = set()
        ignored_prs: set[PRNumber] = set()
        ai_authors: set[str] = set()
        author_names: dict[str, str] = {}
        ignored_comment_patterns: list[re.Pattern] = []
        ignored_title_patterns: list[re.Pattern] = []
        ignored_labels: set[str] = set()
        aliases: dict[str, str] = {}
        this_author = ""
        max_threads = 50
        youtrack_url = ""
        youtrack_token = ""
        youtrack_verify_ssl = True
        youtrack_threads = 10
        timely_access_token = ""
        timely_account_id = ""
        timely_ignored_projects: set[str] = set()
        timely_short_names: dict[str, str] = {}
        timely_short_projects: dict[str, str] = {}
        timely_yt_map: dict[str, str] = {}

        keys_file  = Config.keys_file_for(config_file)
        main_lines = _read_lines(config_file)

        # The point of the keys file is that the config can be committed, so say so when
        # a credential is still sitting in the committed half.
        if (left := sorted({k for line in main_lines if (k := credential_key(line))})):
            print("Warning: %s holds credentials (%s). Move them to %s."
                  % (config_file, ", ".join(left), keys_file), file=sys.stderr)

        # Keys are read last, so that one kept in both files wins there.
        for line in main_lines + _read_lines(keys_file):
            if not line or line.startswith("#"):
                continue
            m = re.match(r'^owner:\s*(.*)', line)
            if m:
                owner = m.group(1).strip(); continue
            m = re.match(r'^repo-name:\s*(.*)', line)
            if m:
                repo_name = m.group(1).strip(); continue
            m = re.match(r'^ignore-author:\s*(.*)', line)
            if m:
                for a in m.group(1).split(","):
                    a = a.strip()
                    if a: ignored_authors.add(a)
                continue
            m = re.match(r'^ignore-pr:\s*(.*)', line)
            if m:
                for p in m.group(1).split(","):
                    p = p.strip()
                    try:
                        if p: ignored_prs.add(PRNumber(int(p)))
                    except ValueError:
                        pass
                continue
            m = re.match(r'^ignore-label:\s*(.*)', line)
            if m:
                for lb in m.group(1).split(","):
                    lb = lb.strip()
                    if lb: ignored_labels.add(lb)
                continue
            m = re.match(r'^ai-author:\s*(.*)', line)
            if m:
                for a in m.group(1).split(","):
                    a = a.strip()
                    if a: ai_authors.add(a)
                continue
            m = re.match(r'^author-name:\s*(.*)', line)
            if m:
                for mapping in m.group(1).split(","):
                    mapping = mapping.strip()
                    if "=" in mapping:
                        handle, name = mapping.split("=", 1)
                        author_names[handle.strip()] = name.strip()
                continue
            m = re.match(r'^ignore-comment:\s*(.*)', line)
            if m:
                pat = m.group(1).strip()
                if pat:
                    try:
                        ignored_comment_patterns.append(re.compile(pat))
                    except re.error:
                        pass
                continue
            m = re.match(r'^ignore-title:\s*(.*)', line)
            if m:
                pat = m.group(1).strip()
                if pat:
                    try:
                        ignored_title_patterns.append(re.compile(pat))
                    except re.error:
                        pass
                continue
            m = re.match(r'^this-author:\s*(.*)', line)
            if m:
                this_author = m.group(1).strip(); continue
            m = re.match(r'^max-threads:\s*(.*)', line)
            if m:
                try:
                    max_threads = int(m.group(1).strip())
                except ValueError:
                    pass
                continue
            m = re.match(r'^alias:\s*([^:]+):(.*)', line)
            if m:
                aname = m.group(1).strip().lower()
                acmd  = m.group(2).strip()
                if aname and acmd:
                    aliases[aname] = acmd
                continue
            m = re.match(r'^youtrack-url:\s*(.*)', line)
            if m:
                youtrack_url = m.group(1).strip(); continue
            m = re.match(r'^youtrack-token:\s*(.*)', line)
            if m:
                youtrack_token = m.group(1).strip(); continue
            m = re.match(r'^youtrack-verify-ssl:\s*(.*)', line)
            if m:
                youtrack_verify_ssl = m.group(1).strip().lower() != "false"; continue
            m = re.match(r'^youtrack-threads:\s*(.*)', line)
            if m:
                try:
                    youtrack_threads = int(m.group(1).strip())
                except ValueError:
                    pass
                continue
            m = re.match(r'^timely-access-token:\s*(.*)', line)
            if m:
                timely_access_token = m.group(1).strip(); continue
            m = re.match(r'^timely-account-id:\s*(.*)', line)
            if m:
                timely_account_id = m.group(1).strip(); continue
            m = re.match(r'^timely-ignore-project:\s*(.*)', line)
            if m:
                for p in m.group(1).split(","):
                    p = p.strip().lower()
                    if p: timely_ignored_projects.add(p)
                continue
            m = re.match(r'^timely-short-names:\s*(.*)', line)
            if m:
                for mapping in m.group(1).split(","):
                    mapping = mapping.strip()
                    if "=" in mapping:
                        full, short = mapping.split("=", 1)
                        timely_short_names[full.strip()] = short.strip()
                continue
            m = re.match(r'^timely-short-projects:\s*(.*)', line)
            if m:
                for mapping in m.group(1).split(","):
                    mapping = mapping.strip()
                    if "=" in mapping:
                        full, short = mapping.split("=", 1)
                        timely_short_projects[full.strip()] = short.strip()
                continue
            m = re.match(r'^timely-yt-map:\s*(.*)', line)
            if m:
                for mapping in m.group(1).split(","):
                    mapping = mapping.strip()
                    if "=" in mapping:
                        pr_ticket, timely_ticket = mapping.split("=", 1)
                        timely_yt_map[pr_ticket.strip().upper()] = timely_ticket.strip().upper()
                continue

        return Config(
            repo=GithubInfo(owner=owner, repo_name=repo_name),
            ignored_authors=ignored_authors, ignored_prs=ignored_prs,
            ai_authors=ai_authors, author_names=author_names,
            ignored_comment_patterns=ignored_comment_patterns,
            ignored_title_patterns=ignored_title_patterns,
            ignored_labels=ignored_labels,
            aliases=aliases,
            this_author=this_author,
            max_threads=max_threads,
            config_file=config_file,
            youtrack_url=youtrack_url,
            youtrack_token=youtrack_token,
            youtrack_verify_ssl=youtrack_verify_ssl,
            youtrack_threads=youtrack_threads,
            timely_access_token=timely_access_token,
            timely_account_id=timely_account_id,
            timely_ignored_projects=timely_ignored_projects,
            timely_short_names=timely_short_names,
            timely_short_projects=timely_short_projects,
            timely_yt_map=timely_yt_map,
        )
