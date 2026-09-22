import unittest

from pr_status.youtrack_issue import YoutrackIssue


def custom_fields(**values) -> list[dict]:
    return [{"name": name, "value": value} for name, value in values.items()]


class TestReleaseCycle(unittest.TestCase):
    """Release cycles are named rather than structured, and the naming is not
    consistent — every case below is a name in live use."""

    def cycle(self, name: str) -> YoutrackIssue:
        return YoutrackIssue(release_cycle=name)

    def test_four_digit_year(self):
        issue = self.cycle("Release 2.36 9th October 2026")
        self.assertEqual(issue.release_number, "2.36")
        self.assertEqual(issue.release_date, "2026-10-09")

    def test_two_digit_year(self):
        self.assertEqual(self.cycle("Release 2.34 26th June 26").release_date, "2026-06-26")

    def test_abbreviated_month(self):
        self.assertEqual(self.cycle("Release 2.27 17th Oct 25").release_date, "2025-10-17")

    def test_four_letter_month_abbreviation(self):
        # "Sept" is neither the full month nor the usual three-letter form.
        self.assertEqual(self.cycle("Release 2.26 5th Sept 25").release_date, "2025-09-05")

    def test_every_ordinal_suffix(self):
        for name, expected in [("Release 2.1 1st May 26",  "2026-05-01"),
                               ("Release 2.1 2nd May 26",  "2026-05-02"),
                               ("Release 2.1 23rd May 26", "2026-05-23"),
                               ("Release 2.1 4th May 26",  "2026-05-04")]:
            self.assertEqual(self.cycle(name).release_date, expected, name)

    def test_missing_ordinal_suffix(self):
        self.assertEqual(self.cycle("Release 2.1 4 May 26").release_date, "2026-05-04")

    def test_unset_cycle_gives_neither(self):
        issue = YoutrackIssue()
        self.assertEqual(issue.release_number, "")
        self.assertEqual(issue.release_date, "")

    def test_cycle_with_no_date_keeps_its_number(self):
        issue = self.cycle("Release 3.0")
        self.assertEqual(issue.release_number, "3.0")
        self.assertEqual(issue.release_date, "")

    def test_cycle_that_is_not_a_release_is_shown_as_it_stands(self):
        # Rather than dropping a name this cannot read, the number column shows it whole.
        issue = self.cycle("Backlog")
        self.assertEqual(issue.release_number, "Backlog")
        self.assertEqual(issue.release_date, "")

    def test_unreadable_month_gives_no_date(self):
        self.assertEqual(self.cycle("Release 2.1 4th Smarch 26").release_date, "")

    def test_impossible_day_gives_no_date(self):
        self.assertEqual(self.cycle("Release 2.1 31st February 26").release_date, "")


class TestFromCustomFields(unittest.TestCase):

    def test_named_values(self):
        issue = YoutrackIssue.from_custom_fields(custom_fields(**{
            "State":                {"name": "Review"},
            "Type":                 {"name": "Feature"},
            "Committed":            {"name": "Not Committed"},
            "Risk Complexity":      {"name": "Small"},
            "Estimate Uncertainty": {"name": "Medium"},
            "Release Cycle":        {"name": "Release 2.36 9th October 2026"},
        }))
        self.assertEqual(issue.state, "Review")
        self.assertEqual(issue.issue_type, "Feature")
        self.assertEqual(issue.committed, "Not Committed")
        self.assertEqual(issue.risk_complexity, "Small")
        self.assertEqual(issue.estimate_uncertainty, "Medium")
        self.assertEqual(issue.release_cycle, "Release 2.36 9th October 2026")

    def test_dev_deadline_is_an_epoch(self):
        # YouTrack stores a date field at midday UTC, so the day it names is the same
        # whatever the reader's timezone.
        issue = YoutrackIssue.from_custom_fields(custom_fields(**{"Dev Deadline": 1789473600000}))
        self.assertEqual(issue.dev_deadline, "2026-09-15")

    def test_estimate_is_read_in_working_days(self):
        # A YouTrack week is five working days of eight hours.
        for minutes, days in [(480, 1.0), (960, 2.0), (2400, 5.0), (9600, 20.0)]:
            issue = YoutrackIssue.from_custom_fields(
                custom_fields(**{"Estimate (dev only)": {"minutes": minutes, "presentation": "x"}}))
            self.assertEqual(issue.estimate_days, days, minutes)

    def test_unset_fields_are_empty(self):
        issue = YoutrackIssue.from_custom_fields(custom_fields(**{
            "Dev Deadline": None, "Estimate (dev only)": None, "Release Cycle": None,
            "Committed": None, "Type": None,
        }))
        self.assertEqual(issue.dev_deadline, "")
        self.assertIsNone(issue.estimate_days)
        self.assertEqual(issue.release_cycle, "")
        self.assertEqual(issue.committed, "")
        self.assertEqual(issue.issue_type, "")

    def test_absent_fields_are_empty(self):
        # A project need not define every field.
        issue = YoutrackIssue.from_custom_fields([])
        self.assertEqual(issue.issue_type, "")
        self.assertIsNone(issue.estimate_days)

    def test_a_ticket_with_no_state_reads_as_unknown(self):
        self.assertEqual(YoutrackIssue.from_custom_fields([]).state, "—")


if __name__ == "__main__":
    unittest.main()
