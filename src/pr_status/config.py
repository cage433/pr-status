import os
import re
from dataclasses import dataclass

from .pr_number import PRNumber


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
    max_threads: int = 50
    config_file: str = ""
    youtrack_url: str = ""
    youtrack_token: str = ""

    def author_name(self, author: str) -> str:
        return self.author_names.get(author, author)

    def is_ai_author(self, login: str) -> bool:
        return login in self.ai_authors or login.removesuffix("[bot]") in self.ai_authors

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
        max_threads = 50
        youtrack_url = ""
        youtrack_token = ""

        if config_file and os.path.isfile(config_file):
            with open(config_file) as f:
                for line in f:
                    line = line.rstrip("\n")
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

        return Config(
            repo=GithubInfo(owner=owner, repo_name=repo_name),
            ignored_authors=ignored_authors, ignored_prs=ignored_prs,
            ai_authors=ai_authors, author_names=author_names,
            ignored_comment_patterns=ignored_comment_patterns,
            ignored_title_patterns=ignored_title_patterns,
            ignored_labels=ignored_labels,
            aliases=aliases,
            max_threads=max_threads,
            config_file=config_file,
            youtrack_url=youtrack_url,
            youtrack_token=youtrack_token,
        )
