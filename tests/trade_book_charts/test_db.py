"""Unit tests for SQL validation and column mapping in trade_book_charts."""

import unittest
from trade_book_charts.models import TradebookInputError
from trade_book_charts.db import (
    _validate_identifier,
    _validate_select_sql,
    build_ohlcv_column_map,
)


class TestTradeBookDB(unittest.TestCase):
    def test_validate_identifier_valid(self):
        """Valid SQL identifiers should pass."""
        self.assertEqual(_validate_identifier("trades", "--table"), "trades")
        self.assertEqual(_validate_identifier("ohlcv_eurusd_5m_2025", "--table"), "ohlcv_eurusd_5m_2025")

    def test_validate_identifier_invalid(self):
        """Invalid identifiers (spaces, punctuation, sql injection) should raise TradebookInputError."""
        with self.assertRaises(TradebookInputError):
            _validate_identifier("trades; DROP TABLE", "--table")
        with self.assertRaises(TradebookInputError):
            _validate_identifier("123trades", "--table")
        with self.assertRaises(TradebookInputError):
            _validate_identifier("", "--table")

    def test_validate_select_sql_valid(self):
        """SELECT and WITH queries should pass validation."""
        sql1 = "SELECT trade_id, entry_time, entry_price FROM trades"
        self.assertEqual(_validate_select_sql(sql1), sql1)
        sql2 = "WITH cte AS (SELECT * FROM trades) SELECT * FROM cte"
        self.assertEqual(_validate_select_sql(sql2), sql2)

    def test_validate_select_sql_invalid(self):
        """Non-select queries (INSERT, UPDATE, DELETE) should raise TradebookInputError."""
        with self.assertRaises(TradebookInputError):
            _validate_select_sql("DELETE FROM trades")
        with self.assertRaises(TradebookInputError):
            _validate_select_sql("")

    def test_build_ohlcv_column_map(self):
        """Test OHLCV column map construction and validation."""
        cmap = build_ohlcv_column_map(
            time_col="timestamp",
            open_col="open",
            high_col="high",
            low_col="low",
            close_col="close",
            volume_col="volume",
        )
        self.assertEqual(cmap["time"], "timestamp")
        self.assertEqual(cmap["volume"], "volume")


if __name__ == "__main__":
    unittest.main()
