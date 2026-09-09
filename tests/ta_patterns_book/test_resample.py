"""Unit tests for data/resample.py in ta_patterns_book."""

import unittest
import pandas as pd
from ta_patterns_book.data.resample import (
    normalize_timeframe_rule,
    resample_ohlcv,
)


class TestResample(unittest.TestCase):
    def test_normalize_timeframe_rule(self):
        """Verify shorthand aliases map to pandas offset rules."""
        self.assertEqual(normalize_timeframe_rule("1m"), "1min")
        self.assertEqual(normalize_timeframe_rule("5m"), "5min")
        self.assertEqual(normalize_timeframe_rule("1h"), "1h")
        self.assertEqual(normalize_timeframe_rule("1d"), "1D")

    def test_resample_ohlcv_aggregation(self):
        """Verify resampling 1m candles into 5m candles aggregates open/high/low/close correctly."""
        timestamps = pd.date_range("2025-01-01 09:00:00", periods=10, freq="1min")
        df = pd.DataFrame({
            "timestamp": timestamps,
            "open": [1.1000, 1.1005, 1.1010, 1.1008, 1.1012, 1.1020, 1.1025, 1.1015, 1.1018, 1.1022],
            "high": [1.1010, 1.1015, 1.1020, 1.1015, 1.1025, 1.1030, 1.1035, 1.1025, 1.1028, 1.1032],
            "low":  [1.0995, 1.1000, 1.1005, 1.1000, 1.1008, 1.1015, 1.1010, 1.1010, 1.1012, 1.1018],
            "close":[1.1005, 1.1010, 1.1008, 1.1012, 1.1020, 1.1025, 1.1015, 1.1018, 1.1022, 1.1030],
            "volume":[10, 15, 20, 25, 30, 12, 18, 22, 28, 35],
        })

        resampled = resample_ohlcv(df, target_timeframe="5m")
        self.assertEqual(len(resampled), 2)
        self.assertEqual(resampled.iloc[0]["open"], 1.1000)
        self.assertEqual(resampled.iloc[0]["high"], 1.1025)
        self.assertEqual(resampled.iloc[0]["low"], 1.0995)
        self.assertEqual(resampled.iloc[0]["close"], 1.1020)
        self.assertEqual(resampled.iloc[0]["volume"], 100)


if __name__ == "__main__":
    unittest.main()
