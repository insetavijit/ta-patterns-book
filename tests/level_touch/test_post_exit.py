"""Unit tests for post_exit Fibonacci excursion engine per DOCs/pfib_bsl-v3.md."""

from datetime import datetime, timedelta, timezone
import pandas as pd

from Core.ta_patterns_book.level_touch.post_exit import (
    PFIB_RATIO_GRID,
    analyze_trade_post_exit,
)


def test_section_5_1_long_trade_worked_example():
    """Verify Section 5.1 Long Trade worked example from spec."""
    entry = 1.1000
    sl = 1.0950
    tp = 1.1050
    direction = "Long"

    base_time = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    # Generate 15 consecutive 5m candles
    candles = []
    for k in range(1, 16):
        ts = base_time + timedelta(minutes=5 * k)
        # Default neutral candle between 1.1040 and 1.1060
        o, h, l, c = 1.1050, 1.1060, 1.1040, 1.1050
        if k == 3:  # Candle 45 in worked example: High reaches 1.1120 (touches 1.618 = 1.11118)
            h = 1.1120
        elif k == 6:  # Candle 48: Low crosses below Entry (1.1000)
            l = 1.0990
        elif k == 13:  # Candle 55: Low crosses below SL (1.0950)
            l = 1.0945

        candles.append({"timestamp": ts, "open": o, "high": h, "low": l, "close": c})

    df = pd.DataFrame(candles)
    res = analyze_trade_post_exit(
        entry_price=entry,
        sl_price=sl,
        tp_price=tp,
        direction=direction,
        forward_candles=df,
        exit_time=base_time,
        horizon=15,
    )

    assert res is not None
    assert res["pfib_direction"] == "long"
    assert res["pfib_bsl"] == 1.618
    assert res["pfib_candles"] == 3
    assert res["pfib_be_hit"] is True
    assert res["pfib_sl_hit"] is True
    assert res["pfib_window_candles"] == 15
    assert res["pfib_window_complete"] is True  # scan stopped at candle 13 when SL was hit!
    assert res["pfib_gap_crossed"] is False


def test_section_5_2_short_trade_partial_window():
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
    res = analyze_trade_post_exit(
        entry_price=entry,
        sl_price=sl,
        tp_price=tp,
        direction=direction,
        forward_candles=df,
        exit_time=base_time,
        horizon=15,
    )

    assert res is not None
    assert res["pfib_direction"] == "short"
    assert res["pfib_bsl"] == 1.618
    assert res["pfib_candles"] == 2
    assert res["pfib_be_hit"] is True
    assert res["pfib_sl_hit"] is False
    assert res["pfib_window_candles"] == 11
    assert res["pfib_window_complete"] is False


def test_degenerate_leg_rejected():
    """Verify property test: abs(tp - sl) < 1e-9 is safely rejected."""
    res = analyze_trade_post_exit(
        entry_price=1.1000,
        sl_price=1.1000,
        tp_price=1.1000,
        direction="Long",
        forward_candles=pd.DataFrame([{"timestamp": "2025-01-01", "high": 1.1050, "low": 1.0950}]),
    )
    assert res is None
