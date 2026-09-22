import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from .column import Column, _ListError
from .date_utils import parse_date_literal

if TYPE_CHECKING:
    from .config import Config
    from .pr_context import PRContext
    from .github_data import GithubComment


class FilterSpec(ABC):
    @property
    @abstractmethod
    def all_cols(self) -> set[Column]: ...

    @property
    def uses_comment_time(self) -> bool:
        return False

    def search_qualifiers(self, config: "Config") -> list[str]:
        """Qualifiers that push this filter into the GitHub search for the PR list, so
        PRs it excludes are never fetched. Returning [] is always safe: the filter is
        applied to the results either way, and an un-pushed one just costs a wider
        search. What is returned must therefore never narrow past what the filter
        itself rejects.
        """
        return []

    @abstractmethod
    def matches(self, ctx: "PRContext") -> bool: ...

    @abstractmethod
    def matches_comment(self, ctx: "PRContext", cr: "GithubComment") -> bool: ...

    @staticmethod
    def resolve(spec: str, me: str = "") -> "FilterSpec":
        spec = spec.strip()
        if "@me" in spec:
            if not me:
                raise _ListError(
                    "'@me' in a filter requires 'this-author:' to be set in your config file "
                    "(it is replaced with that name). See the Config section of the README."
                )
            spec = spec.replace("@me", me)
        ne_parts = spec.split("!=", 1)
        if len(ne_parts) == 2:
            fs = FilterSpec._parse(ne_parts[0].strip())
            if not isinstance(fs, ColumnFilterSpec):
                raise _ListError("Invalid --filter: != not valid for comparison filters")
            return replace(fs, values={v.strip() for v in ne_parts[1].split(",")}, negate=True)
        fparts = re.split(r'(?<![><=!])=(?!=)', spec, maxsplit=1)
        if len(fparts) == 1:
            fs = FilterSpec._parse(fparts[0].strip())
            if not isinstance(fs, ComparisonFilterSpec):
                raise _ListError("Invalid --filter (expected col=val,...): %r" % spec)
            return fs
        fs = FilterSpec._parse(fparts[0].strip())
        if not isinstance(fs, ColumnFilterSpec):
            raise _ListError("Invalid --filter: = not valid for comparison filters")
        return replace(fs, values={v.strip() for v in fparts[1].split(",")})

    @staticmethod
    def _parse(spec: str) -> "FilterSpec":
        spec = spec.strip()
        m = re.match(r'^(.+?)\s*(>=|<=|==|>|<)\s*(.+)$', spec)
        if m:
            op = m.group(2)
            def _parse_side(s: str) -> str:
                lit = parse_date_literal(s.strip())
                return lit if lit is not None else Column.resolve(s.strip()).name
            left  = _parse_side(m.group(1))
            right = _parse_side(m.group(3))
            for val in (left, right):
                col = Column.col_from_name(val)
                if col and not col.is_timestamp:
                    raise _ListError("Column %r is not a timestamp column" % val)
            return ComparisonFilterSpec(left=left, op=op, right=right)
        return ColumnFilterSpec(column=Column.resolve(spec), values=set(), negate=False)


@dataclass
class ColumnFilterSpec(FilterSpec):
    column: Column
    values: set[str]
    negate: bool

    @property
    def all_cols(self) -> set[Column]:
        return {self.column}

    @property
    def uses_comment_time(self) -> bool:
        from .columns import COMMENT_TIME_COL
        return self.column == COMMENT_TIME_COL

    @property
    def wants_empty(self) -> bool:
        """Whether the filter is asking for rows the column has no value for. 'null' says
        so for any column; the reviewer columns have always spelt it 'none'."""
        return "null" in self.values

    def search_qualifiers(self, config: "Config") -> list[str]:
        from .columns import AUTHOR_COL, REVIEW_OUTSTANDING_COL
        if self.negate or self.wants_empty or "none" in self.values:
            # A negated qualifier over a login GitHub does not know matches nothing at
            # all rather than everything, and neither 'none' nor 'null' names a login to
            # ask about.
            return []
        if self.column == AUTHOR_COL:
            # Repeated author: qualifiers are ORed, which is what a multi-valued filter
            # means, so every login a value could name can be asked for at once.
            return ["author:" + login
                    for value in sorted(self.values)
                    for login in config.logins_for_name(value)]
        if self.column == REVIEW_OUTSTANDING_COL and len(self.values) == 1:
            # Repeated review-requested: qualifiers are not ORed — GitHub returns
            # something that is neither the union nor the intersection — so only a
            # filter naming exactly one login can be pushed into the search.
            login = config.login_for_name(next(iter(self.values)))
            return ["review-requested:" + login] if login else []
        return []

    def matches(self, ctx: "PRContext") -> bool:
        from .columns import PULL_REQUEST_COL, REVIEWERS_COL, REVIEW_OUTSTANDING_COL
        empty = self.wants_empty or "none" in self.values
        if self.column == REVIEWERS_COL:
            reviewer_names = {ctx.config.author_name(r) for r in ctx.pr.reviewers}
            matched = (not ctx.pr.reviewers and empty) or bool(reviewer_names & self.values)
            return not matched if self.negate else matched
        if self.column == REVIEW_OUTSTANDING_COL:
            outstanding = {ctx.config.author_name(r) for r in ctx.pr.outstanding_reviewers}
            matched = (not outstanding and empty) or bool(outstanding & self.values)
            return not matched if self.negate else matched
        val = str(ctx.pr.number) if self.column == PULL_REQUEST_COL else self.column.cell(ctx, False)
        matched = val in self.values or (not val and self.wants_empty)
        return not matched if self.negate else matched

    def matches_comment(self, ctx: "PRContext", cr: "GithubComment") -> bool:
        from .columns import COMMENT_TIME_COL
        from .date_utils import fmt_ts
        if self.column == COMMENT_TIME_COL:
            val = fmt_ts(cr.timestamp, show_time=True)
            matched = val in self.values or (not val and self.wants_empty)
            return not matched if self.negate else matched
        return self.matches(ctx)


@dataclass
class ComparisonFilterSpec(FilterSpec):
    left:  str
    op:    str
    right: str

    @property
    def all_cols(self) -> set[Column]:
        return {col for side in (self.left, self.right)
                if (col := Column.col_from_name(side)) and col.is_timestamp}

    @property
    def uses_comment_time(self) -> bool:
        return "comment-time" in (self.left, self.right)

    def matches(self, ctx: "PRContext") -> bool:
        from .columns import _timestamp_val
        lv = _timestamp_val(self.left,  ctx) or "1970-01-01T00:00:00Z"
        rv = _timestamp_val(self.right, ctx) or "1970-01-01T00:00:00Z"
        return (lv > rv if self.op == ">" else lv < rv if self.op == "<" else
                lv >= rv if self.op == ">=" else lv <= rv if self.op == "<=" else lv == rv)

    def matches_comment(self, ctx: "PRContext", cr: "GithubComment") -> bool:
        from .columns import _timestamp_val
        def _ts(col: str) -> str:
            if col == "comment-time": return cr.timestamp
            return _timestamp_val(col, ctx)
        lv = _ts(self.left)  or "1970-01-01T00:00:00Z"
        rv = _ts(self.right) or "1970-01-01T00:00:00Z"
        return (lv > rv if self.op == ">" else lv < rv if self.op == "<" else
                lv >= rv if self.op == ">=" else lv <= rv if self.op == "<=" else lv == rv)
