"""Unit tests for SMA Crossover reference strategy."""

import unittest
import numpy as np
import pandas as pd

from strategies.sma_cross import SmaCrossStrategy


class TestSmaCrossStrategy(unittest.TestCase):
    def setUp(self):
        self.strat = SmaCrossStrategy()

    def test_metadata(self):
        """Strategy should have correct name and version."""
        self.assertEqual(self.strat.name, "sma_cross")
        self.assertEqual(self.strat.version, "1.0.0")

    def test_window_validation(self):
        """fast_window >= slow_window should raise ValueError."""
        df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
        with self.assertRaises(ValueError):
            self.strat.generate_signals(df, {"fast_window": 50, "slow_window": 10})
        with self.assertRaises(ValueError):
            self.strat.generate_signals(df, {"fast_window": 20, "slow_window": 20})

    def test_generate_signals_crossover(self):
        """Generate entry on golden cross and exit on death cross."""
        # Create prices that trend down then trend sharply up then down
        prices = [10.0] * 20 + list(range(10, 40)) + list(range(40, 10, -1))
        df = pd.DataFrame({"close": prices})

        entries, exits = self.strat.generate_signals(df, {"fast_window": 3, "slow_window": 8})
        self.assertIsInstance(entries, pd.Series)
        self.assertIsInstance(exits, pd.Series)
        self.assertEqual(len(entries), len(prices))
        self.assertEqual(len(exits), len(prices))
        # There should be at least one entry signal and at least one exit signal
        self.assertTrue(entries.any())
        self.assertTrue(exits.any())


if __name__ == "__main__":
    unittest.main()
