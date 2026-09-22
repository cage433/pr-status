import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .node import Node

# A YouTrack period is quoted in working days: a week is five of them, a day is eight
# hours. Minutes are what the API returns, so that is what the division starts from.
MINUTES_PER_WORKDAY = 480

# The release cycle a ticket belongs to is named rather than structured, e.g.
# "Release 2.36 9th October 2026" — so the release number and the release date are read
# back out of the name. Both the ordinal suffix and the century are written inconsistently
# ("5th Sept 25", "23rd Dec 2025"), and months are abbreviated at whim, so only the first
# three letters of the month are matched on.
_RELEASE_RE = re.compile(
    r'^Release\s+(?P<number>\S+)\s+'
    r'(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?P<month>[A-Za-z]+)\.?\s+(?P<year>\d{4}|\d{2})\s*$'
)
_RELEASE_NUMBER_RE = re.compile(r'^Release\s+(\S+)')
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _iso_date(epoch_millis: float) -> str:
    """The date a YouTrack date field holds. Such a field is stored at midday UTC so that
    it names the same day either side of the date line, hence reading it in UTC."""
    return datetime.fromtimestamp(epoch_millis / 1000, timezone.utc).date().isoformat()


@dataclass(frozen=True)
class YoutrackIssue:
    """The fields of one YouTrack ticket that a report can show. Every field is empty on
    a ticket that could not be read, and on one whose own field is unset — the two are
    told apart by the state, which carries NOT FOUND or ERROR."""
    state:                str         = ""
    dev_deadline:         str         = ""   # ISO date
    release_cycle:        str         = ""   # the version's name, verbatim
    committed:            str         = ""
    estimate_days:        float | None = None
    estimate_uncertainty: str         = ""
    issue_type:           str         = ""
    risk_complexity:      str         = ""

    @property
    def release_number(self) -> str:
        """The version the release cycle names, e.g. "2.36". A cycle whose name does not
        start with a version is shown as it stands rather than silently dropped."""
        if not self.release_cycle:
            return ""
        m = _RELEASE_NUMBER_RE.match(self.release_cycle)
        return m.group(1) if m else self.release_cycle

    @property
    def release_date(self) -> str:
        """The date the release cycle's name gives, as an ISO date, or "" when the name
        carries no date this can read."""
        m = _RELEASE_RE.match(self.release_cycle)
        if not m:
            return ""
        month = _MONTHS.get(m.group("month")[:3].lower())
        if month is None:
            return ""
        year = int(m.group("year"))
        try:
            return datetime(2000 + year if year < 100 else year,
                            month, int(m.group("day"))).date().isoformat()
        except ValueError:
            return ""

    @staticmethod
    def from_custom_fields(custom_fields: list[Node]) -> "YoutrackIssue":
        """Read a ticket out of the customFields of a YouTrack issue response. A field
        holds a named value (a state, an enum, a version), a period, or — for a date — a
        bare epoch; an unset field holds null."""
        def named(field: str) -> str:
            value = values.get(field)
            return value.get("name", "") if isinstance(value, dict) else ""

        values = {f.get("name", ""): f.get("value") for f in custom_fields}
        deadline = values.get("Dev Deadline")
        estimate = values.get("Estimate (dev only)")
        return YoutrackIssue(
            state                = named("State") or "—",
            dev_deadline         = _iso_date(deadline) if isinstance(deadline, (int, float)) else "",
            release_cycle        = named("Release Cycle"),
            committed            = named("Committed"),
            estimate_days        = (estimate["minutes"] / MINUTES_PER_WORKDAY
                                    if isinstance(estimate, dict) and "minutes" in estimate else None),
            estimate_uncertainty = named("Estimate Uncertainty"),
            issue_type           = named("Type"),
            risk_complexity      = named("Risk Complexity"),
        )
