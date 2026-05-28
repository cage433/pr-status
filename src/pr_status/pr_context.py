from dataclasses import dataclass

from .config import Config
from .github_data import GithubComment, GithubPR
from .marks import Marks
from .pr_number import PRNumber


@dataclass
class PRContext:
    config:           Config
    marks:            Marks
    pr:               GithubPR
    comments:         list[GithubComment]    # rows_all[pr.number]
    marked_comments:  list[GithubComment]    # rows_marked[pr.number]
    loc:              tuple[int, int]        # (adds, dels)
    unresolved:       tuple[int, int, int]   # (uc, uh, ua)
    last_activity_ts: str
    youtrack_states:  dict[str, str]
    yt_workdays:      dict[str, float]
