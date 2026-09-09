"""Unit tests for post_trade_analysis CLI and report generation."""

import unittest
from unittest.mock import patch
import duckdb
from post_trade_analysis.cli import print_summary_report, main


class TestPostTradeAnalysisCLI(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect(":memory:")
        # Create a mock view classic_floor_mod_v4c_trades_pfib
        self.con.execute("""
            CREATE TABLE classic_floor_mod_v4c_trades_pfib (
                trade_id BIGINT,
                exit_reason VARCHAR,
                pfib15_window_complete BOOLEAN,
                pfib15_gap_crossed BOOLEAN,
                pfib15_bsl DOUBLE,
                pfib15_sl_hit BOOLEAN,
                pfib15_be_hit BOOLEAN,
                pfib15_candles INTEGER
            );
            INSERT INTO classic_floor_mod_v4c_trades_pfib VALUES
            (1, 'tp', TRUE, FALSE, 1.5, FALSE, FALSE, 5),
            (2, 'tp', TRUE, FALSE, 2.1, FALSE, FALSE, 8),
            (3, 'tp', TRUE, FALSE, 0.8, TRUE, FALSE, 12),
            (4, 'sl', TRUE, FALSE, 0.0, TRUE, FALSE, 2);
        """)

    def tearDown(self):
        self.con.close()

    def test_print_summary_report_runs_without_error(self):
        """print_summary_report should query the view and print table cleanly."""
        with patch("duckdb.connect", return_value=self.con):
            print_summary_report("dummy.duckdb", "classic_floor_mod_v4c", (15,))

    def test_main_help(self):
        """CLI main should respond to --help by exiting with status 0."""
        with patch("sys.argv", ["post-trade-analysis", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
