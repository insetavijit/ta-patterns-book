"""Unit tests for models, constants, and errors in trade_book_charts."""

import unittest
from trade_book_charts.models import (
    EXIT_OK,
    EXIT_BAD_INPUT,
    EXIT_DB_NOT_FOUND,
    LayoutConfig,
    TradebookInputError,
    TRADE_REQUIRED_COLUMNS,
    _DEFAULT_DUMMY_CANDLES,
)


class TestTradeBookModels(unittest.TestCase):
    def test_constants(self):
        """Verify semantic exit codes and required columns."""
        self.assertEqual(EXIT_OK, 0)
        self.assertEqual(EXIT_BAD_INPUT, 2)
        self.assertEqual(EXIT_DB_NOT_FOUND, 3)
        self.assertIn("entry_time", TRADE_REQUIRED_COLUMNS)
        self.assertIn("entry_price", TRADE_REQUIRED_COLUMNS)
        self.assertTrue(len(_DEFAULT_DUMMY_CANDLES) > 0)

    def test_layout_config_defaults(self):
        """Verify LayoutConfig default parameter initialization."""
        cfg = LayoutConfig()
        self.assertEqual(cfg.row_capacity_candles, 500)
        self.assertEqual(cfg.px_per_candle, 3.0)
        self.assertEqual(cfg.gap_candles, 2)
        self.assertEqual(cfg.packing_strategy, "optimal")
        self.assertEqual(cfg.max_charts_per_canvas, 12)

    def test_custom_layout_config(self):
        """Verify LayoutConfig custom parameter overrides."""
        cfg = LayoutConfig(row_capacity_candles=800, packing_strategy="wordwrap")
        self.assertEqual(cfg.row_capacity_candles, 800)
        self.assertEqual(cfg.packing_strategy, "wordwrap")


if __name__ == "__main__":
    unittest.main()
