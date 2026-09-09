"""Unit tests for SmartGrid bin packing layout algorithms in trade_book_charts."""

import unittest
from trade_book_charts.models import LayoutConfig
from trade_book_charts.engine import (
    validate_input,
    pack_wordwrap,
    pack_bestfit,
    compute_layout,
)


class TestSmartGridEngine(unittest.TestCase):
    def test_validate_input_valid(self):
        """Valid inputs should pass without exception."""
        cfg = LayoutConfig()
        validate_input([100, 200, 150], cfg)

    def test_validate_input_empty_or_negative(self):
        """Empty or invalid inputs should raise ValueError."""
        cfg = LayoutConfig()
        with self.assertRaises(ValueError):
            validate_input([], cfg)
        with self.assertRaises(ValueError):
            validate_input([100, -50], cfg)
        with self.assertRaises(ValueError):
            validate_input([100, 0], cfg)

    def test_pack_wordwrap(self):
        """Wordwrap should greedily pack rows preserving original order."""
        candles = [100, 200, 150, 400]
        # Capacity 400, gap 2
        rows = pack_wordwrap(candles, capacity=400, gap=2)
        # 100 + 2 + 200 = 302 <= 400
        # 302 + 2 + 150 = 454 > 400 -> split row 1: [0, 1]
        # row 2: [2]
        # row 3: [3] (400 alone)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], [0, 1])
        self.assertEqual(rows[1], [2])
        self.assertEqual(rows[2], [3])

    def test_pack_bestfit(self):
        """Bestfit should pack decreasing items into best-fit rows."""
        candles = [50, 300, 150, 200]
        rows = pack_bestfit(candles, capacity=400, gap=2)
        all_indices = [idx for r in rows for idx in r]
        self.assertEqual(sorted(all_indices), [0, 1, 2, 3])

    def test_compute_layout_integration(self):
        """Integration test of compute_layout."""
        candles = [100, 150, 200, 80]
        cfg = LayoutConfig(row_capacity_candles=300, packing_strategy="wordwrap")
        res = compute_layout(candles, cfg)
        self.assertIn("canvases", res)
        self.assertEqual(res["total_charts"], 4)


if __name__ == "__main__":
    unittest.main()
