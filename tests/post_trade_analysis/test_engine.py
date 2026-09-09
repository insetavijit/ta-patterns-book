"""Unit tests for post_trade_analysis multi-horizon Fibonacci excursion engine.

Complies with DOCs/pfib_bsl-v3.md and DOCs/feature_pfibs.md.
"""

import unittest
from datetime import datetime, timedelta, timezone
import pandas as pd

from post_trade_analysis.constants import (
    DEFAULT_HORIZONS,
    PFIB_RATIO_GRID,
)
from post_trade_analysis.engine import analyze_trade_multi_horizon


class TestPostTradeAnalysisEngine(unittest.TestCase):
    def test_section_5_1_long_trade_worked_example(self):
        """Verify Section 5.1 Long Trade worked example from spec across horizons."""
        entry = 1.1000
        sl = 1.0950
        tp = 1.1050
        direction = "Long"

        base_time = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
        # Generate 15 consecutive 5m candles
        candles = []
        for k in range(1, 16):
            ts = base_time + timedelta(minutes=5 * k)
            o, h, l, c = 1.1050, 1.1060, 1.1040, 1.1050
            if k == 3:  # Candle 45: High reaches 1.1120 (touches 1.618 = 1.11118)
                h = 1.1120
            elif k == 6:  # Candle 48: Low crosses below Entry (1.1000)
                l = 1.0990
            elif k == 13:  # Candle 55: Low crosses below SL (1.0950)
                l = 1.0945

            candles.append({"timestamp": ts, "open": o, "high": h, "low": l, "close": c})

        df = pd.DataFrame(candles)
        res = analyze_trade_multi_horizon(
            entry_price=entry,
            sl_price=sl,
            tp_price=tp,
            direction=direction,
            forward_candles=df,
            exit_time=base_time,
            horizons=(15, 30, 60),
        )

        self.assertIsNotNone(res)
        self.assertEqual(res["pfib_direction"], "long")
        self.assertFalse(res["pfib_gap_crossed"])

        # 15-candle horizon (and legacy alias)
        self.assertEqual(res["pfib15_bsl"], 1.618)
        self.assertEqual(res["pfib15_candles"], 3)
        self.assertTrue(res["pfib15_be_hit"])
        self.assertTrue(res["pfib15_sl_hit"])
        self.assertEqual(res["pfib15_window_candles"], 15)
        self.assertTrue(res["pfib15_window_complete"])
        self.assertEqual(res["pfib_bsl"], 1.618)

        # 30-candle horizon: window only had 15 candles
        self.assertEqual(res["pfib30_bsl"], 1.618)
        self.assertTrue(res["pfib30_sl_hit"])
        self.assertEqual(res["pfib30_window_candles"], 15)
        self.assertFalse(res["pfib30_window_complete"])

        # 60-candle horizon
        self.assertEqual(res["pfib60_bsl"], 1.618)
        self.assertTrue(res["pfib60_sl_hit"])
        self.assertEqual(res["pfib60_window_candles"], 15)
        self.assertFalse(res["pfib60_window_complete"])

    def test_section_5_2_short_trade_partial_window(self):
        """Verify Section 5.2 Short Trade partial window worked example from spec."""
        entry = 1.1000
        sl = 1.1050
        tp = 1.0950
        direction = "Short"

        base_time = datetime(2025, 1, 1, 14, 0, tzinfo=timezone.utc)
        # Only 11 candles exist before data end
        candles = []
        for k in range(1, 12):
            ts = base_time + timedelta(minutes=5 * k)
            o, h, l, c = 1.0950, 1.0960, 1.0940, 1.0950
            if k == 2:  # Candle 90: Low reaches 1.0885 (touches 1.618 = 1.08882)
                l = 1.0885
            elif k == 4:  # Candle 92: High crosses above Entry (1.1000)
                h = 1.1005

            candles.append({"timestamp": ts, "open": o, "high": h, "low": l, "close": c})

        df = pd.DataFrame(candles)
        res = analyze_trade_multi_horizon(
            entry_price=entry,
            sl_price=sl,
            tp_price=tp,
            direction=direction,
            forward_candles=df,
            exit_time=base_time,
            horizons=(15, 30, 60),
        )

        self.assertIsNotNone(res)
        self.assertEqual(res["pfib_direction"], "short")
        self.assertEqual(res["pfib15_bsl"], 1.618)
        self.assertEqual(res["pfib15_candles"], 2)
        self.assertTrue(res["pfib15_be_hit"])
        self.assertFalse(res["pfib15_sl_hit"])
        self.assertEqual(res["pfib15_window_candles"], 11)
        self.assertFalse(res["pfib15_window_complete"])

        self.assertEqual(res["pfib30_bsl"], 1.618)
        self.assertEqual(res["pfib30_window_candles"], 11)
        self.assertFalse(res["pfib30_window_complete"])

        self.assertEqual(res["pfib60_bsl"], 1.618)
        self.assertEqual(res["pfib60_window_candles"], 11)
        self.assertFalse(res["pfib60_window_complete"])

    def test_multi_horizon_monotonicity_expansion(self):
        """Verify monotonic excursion across 15 -> 30 -> 60 candles when price trends further."""
        entry = 1.1000
        sl = 1.0950
        tp = 1.1050  # span = 0.0100
        # 1.272 = 1.10772, 1.618 = 1.11118, 2.000 = 1.11500
        direction = "Long"
        base_time = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

        candles = []
        for k in range(1, 61):
            ts = base_time + timedelta(minutes=5 * k)
            o, h, l, c = 1.1050, 1.1060, 1.1040, 1.1050
            if k == 10:
                h = 1.1080  # reaches 1.272
            elif k == 25:
                h = 1.1120  # reaches 1.618
            elif k == 45:
                h = 1.1160  # reaches 2.000
            candles.append({"timestamp": ts, "open": o, "high": h, "low": l, "close": c})

        df = pd.DataFrame(candles)
        res = analyze_trade_multi_horizon(
            entry_price=entry,
            sl_price=sl,
            tp_price=tp,
            direction=direction,
            forward_candles=df,
            exit_time=base_time,
            horizons=(15, 30, 60),
        )

        self.assertIsNotNone(res)
        self.assertEqual(res["pfib15_bsl"], 1.272)
        self.assertEqual(res["pfib15_candles"], 10)
        self.assertTrue(res["pfib15_window_complete"])
        self.assertFalse(res["pfib15_sl_hit"])

        self.assertEqual(res["pfib30_bsl"], 1.618)
        self.assertEqual(res["pfib30_candles"], 25)
        self.assertTrue(res["pfib30_window_complete"])
        self.assertFalse(res["pfib30_sl_hit"])

        self.assertEqual(res["pfib60_bsl"], 2.000)
        self.assertEqual(res["pfib60_candles"], 45)
        self.assertTrue(res["pfib60_window_complete"])
        self.assertFalse(res["pfib60_sl_hit"])

        # Monotonicity checks
        self.assertLessEqual(res["pfib15_bsl"], res["pfib30_bsl"])
        self.assertLessEqual(res["pfib30_bsl"], res["pfib60_bsl"])
        self.assertLessEqual(res["pfib15_candles"], res["pfib30_candles"])
        self.assertLessEqual(res["pfib30_candles"], res["pfib60_candles"])

    def test_invalidation_midway_between_horizons(self):
        """Verify that an SL hit at candle 20 leaves H=15 untouched, but caps H=30 and H=60."""
        entry = 1.1000
        sl = 1.0950
        tp = 1.1050
        direction = "Long"
        base_time = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

        candles = []
        for k in range(1, 61):
            ts = base_time + timedelta(minutes=5 * k)
            o, h, l, c = 1.1050, 1.1060, 1.1040, 1.1050
            if k == 10:
                h = 1.1080  # reaches 1.272
            elif k == 20:
                l = 1.0940  # hits SL!
            elif k == 40:
                h = 1.1200  # should NEVER be counted because trade was invalidated at k=20
            candles.append({"timestamp": ts, "open": o, "high": h, "low": l, "close": c})

        df = pd.DataFrame(candles)
        res = analyze_trade_multi_horizon(
            entry_price=entry,
            sl_price=sl,
            tp_price=tp,
            direction=direction,
            forward_candles=df,
            exit_time=base_time,
            horizons=(15, 30, 60),
        )

        self.assertIsNotNone(res)
        # Horizon 15 was evaluated before SL hit:
        self.assertEqual(res["pfib15_bsl"], 1.272)
        self.assertFalse(res["pfib15_sl_hit"])
        self.assertTrue(res["pfib15_window_complete"])

        # Horizon 30 was hit by SL at candle 20:
        self.assertEqual(res["pfib30_bsl"], 1.272)
        self.assertTrue(res["pfib30_sl_hit"])
        self.assertTrue(res["pfib30_window_complete"])

        # Horizon 60 was also stopped at candle 20; candle 40 level (1.1200) is rejected
        self.assertEqual(res["pfib60_bsl"], 1.272)
        self.assertTrue(res["pfib60_sl_hit"])
        self.assertTrue(res["pfib60_window_complete"])

    def test_session_gap_detection(self):
        """Verify session / weekend gap is detected when candle diff exceeds 1.5 * nominal_step."""
        entry = 1.1000
        sl = 1.0950
        tp = 1.1050
        direction = "Long"
        base_time = datetime(2025, 1, 3, 21, 55, tzinfo=timezone.utc)  # Friday night

        candles = []
        # 5 candles Friday
        for k in range(1, 6):
            ts = base_time + timedelta(minutes=5 * k)
            candles.append({"timestamp": ts, "open": 1.1050, "high": 1.1060, "low": 1.1040, "close": 1.1050})

        # Weekend gap (jump to Sunday night)
        sunday_open = datetime(2025, 1, 5, 22, 0, tzinfo=timezone.utc)
        for k in range(0, 10):
            ts = sunday_open + timedelta(minutes=5 * k)
            candles.append({"timestamp": ts, "open": 1.1050, "high": 1.1060, "low": 1.1040, "close": 1.1050})

        df = pd.DataFrame(candles)
        res = analyze_trade_multi_horizon(
            entry_price=entry,
            sl_price=sl,
            tp_price=tp,
            direction=direction,
            forward_candles=df,
            exit_time=base_time,
            horizons=(15, 30),
        )

        self.assertIsNotNone(res)
        self.assertTrue(res["pfib_gap_crossed"])
        self.assertTrue(res["pfib15_gap_crossed"])

    def test_degenerate_leg_rejected(self):
        """Verify abs(tp - sl) < 1e-9 is safely rejected with None."""
        res = analyze_trade_multi_horizon(
            entry_price=1.1000,
            sl_price=1.1000,
            tp_price=1.1000,
            direction="Long",
            forward_candles=pd.DataFrame([{"timestamp": "2025-01-01", "high": 1.1050, "low": 1.0950}]),
        )
        self.assertIsNone(res)


if __name__ == "__main__":
    unittest.main()
