"""Unit tests for SQL query builders and filter parsing in loss_profile."""

import unittest
from ta_patterns_book.loss_profile.sql import (
    format_filter_expression,
    build_monthly_query,
    build_weekly_query,
    build_duration_query,
    build_loss_group_query,
    build_projected_rr_group_query,
    build_distribution_query,
    build_head_query,
)


class TestLossProfileSQL(unittest.TestCase):
    def test_format_filter_expression_equality_string(self):
        """String equality filters should be automatically single-quoted."""
        res = format_filter_expression("entry_1 = DR-UG-UG", target_pfx="t.")
        self.assertEqual(res, "t.entry_1 = 'DR-UG-UG'")

    def test_format_filter_expression_already_quoted(self):
        """Already quoted string filters should not be double-quoted."""
        res = format_filter_expression("entry_1 = 'DR-UG-UG'", target_pfx="t.")
        self.assertEqual(res, "t.entry_1 = 'DR-UG-UG'")

    def test_format_filter_expression_numeric_operators(self):
        """Numeric comparison operators (>=, <=, >, <, !=) must preserve numbers unquoted."""
        self.assertEqual(
            format_filter_expression("pfib15_bsl >= 2.0", target_pfx="t."),
            "t.pfib15_bsl >= 2.0",
        )
        self.assertEqual(
            format_filter_expression("pfib15_bsl <= 1.0", target_pfx="t."),
            "t.pfib15_bsl <= 1.0",
        )
        self.assertEqual(
            format_filter_expression("pnl > 0", target_pfx="t."),
            "t.pnl > 0",
        )
        self.assertEqual(
            format_filter_expression("duration_candel != 5", target_pfx="t."),
            "t.duration_candel != 5",
        )

    def test_format_filter_expression_prefixed_alias(self):
        """Expressions already having table prefix should remain unchanged."""
        self.assertEqual(
            format_filter_expression("t.duration_candel = 1", target_pfx="t."),
            "t.duration_candel = 1",
        )
        self.assertEqual(
            format_filter_expression("p.entry_1 = 'DR-DR-DR'", target_pfx="t."),
            "p.entry_1 = 'DR-DR-DR'",
        )

    def test_build_monthly_query(self):
        """Test monthly query generation with and without month filter."""
        q1 = build_monthly_query("my_view")
        self.assertIn('FROM "my_view"', q1)
        self.assertIn("GROUP BY month_table", q1)

        q2 = build_monthly_query("my_view", target_month="2025-05")
        self.assertIn("WHERE month_table = '2025-05'", q2)

    def test_build_weekly_query(self):
        """Test weekly query generation."""
        q = build_weekly_query("my_view")
        self.assertIn('FROM "my_view"', q)
        self.assertIn("WEEK(CAST(entry_time AS TIMESTAMP))", q)

    def test_build_duration_query_filters(self):
        """Test duration query with losses_only and pattern filter."""
        q = build_duration_query(
            "my_view",
            losses_only=True,
            pattern_filter="entry_1 = DR-UG-UG",
            has_pattern_col=True,
        )
        self.assertIn("t.pnl <= 0", q)
        self.assertIn("t.entry_1 = 'DR-UG-UG'", q)
        self.assertIn("duration_bracket", q)

    def test_build_distribution_query(self):
        """Test distribution query with wins_only and pfib filter."""
        q = build_distribution_query(
            "my_view",
            pattern_col="entry_1",
            wins_only=True,
            pattern_filter="pfib15_bsl >= 1.618",
            has_pattern_col=True,
        )
        self.assertIn('"entry_1" AS pattern', q)
        self.assertIn("t.pnl > 0", q)
        self.assertIn("t.pfib15_bsl >= 1.618", q)

    def test_build_head_query(self):
        """Test head query with limit and filters."""
        q = build_head_query("my_view", limit=20, duration=3, losses_only=True)
        self.assertIn("LIMIT 20", q)
        self.assertIn("t.duration_candel = 3", q)
        self.assertIn("t.pnl <= 0", q)


if __name__ == "__main__":
    unittest.main()
