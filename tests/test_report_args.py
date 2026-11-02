import io
import unittest
from contextlib import redirect_stderr

from pr_status.report_args import ReportArgs
from pr_status.timely_report_args import TimelyReportArgs


class TestReportArgs(unittest.TestCase):

    def test_a_single_column_list_is_kept_as_it_is(self) -> None:
        args = ReportArgs.parse("P,T,A --sort A")
        self.assertEqual(args.columns, "P,T,A")
        self.assertEqual(args.sort, "A")

    def test_column_lists_after_the_options_join_the_first(self) -> None:
        # How an alias with added columns arrives: its own columns, its options, then the additions.
        args = ReportArgs.parse("P,T,A --filter RO=@me V,LOC_ --filter A=bob")
        self.assertEqual(args.columns, "P,T,A,V,LOC_")
        self.assertEqual(args.filters, ["RO=@me", "A=bob"])

    def test_no_columns_is_an_empty_list(self) -> None:
        self.assertEqual(ReportArgs.parse("--include-ai").columns, "")

    def test_an_unknown_option_is_still_an_error(self) -> None:
        with redirect_stderr(io.StringIO()):
            self.assertIsNone(ReportArgs.parse("P,T --nonesuch"))


class TestTimelyReportArgs(unittest.TestCase):

    def test_column_lists_after_the_options_join_the_first(self) -> None:
        args = TimelyReportArgs.parse("D,P --filter month=3 H")
        self.assertEqual(args.columns, "D,P,H")
        self.assertEqual(args.filters, ["month=3"])


if __name__ == "__main__":
    unittest.main()
