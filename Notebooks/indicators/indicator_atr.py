#!/usr/bin/env python3
"""Indicator ATR Computation Script (Notebooks/indicators/indicator_atr.py).

Calculates Average True Range (ATR) for 3 period variants (fast=7, normal=14, slow=28)
using the 5m OHLCV price data from Shared/Data/eur_usd_trades_5m.duckdb.

Creates/replaces table `indicator_atr` and view `indicator_atr_view` in DuckDB with schema:
  (timestamp TIMESTAMP, atr_fast DOUBLE, atr_normal DOUBLE, atr_slow DOUBLE)
"""

from pathlib import Path
import sys

import duckdb
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "Shared" / "Data" / "eur_usd_trades_5m.duckdb"

FAST_PERIOD = 7
NORMAL_PERIOD = 14
SLOW_PERIOD = 28


def compute_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """Computes Wilders Average True Range (ATR) using NumPy."""
    n = len(close)
    if n == 0:
        return np.array([], dtype=np.float64)

    tr = np.zeros(n, dtype=np.float64)
    # TR[0] = High[0] - Low[0]
    tr[0] = high[0] - low[0]

    prev_close = close[:-1]
    curr_high = high[1:]
    curr_low = low[1:]

    tr_1 = curr_high - curr_low
    tr_2 = np.abs(curr_high - prev_close)
    tr_3 = np.abs(curr_low - prev_close)

    tr[1:] = np.maximum(tr_1, np.maximum(tr_2, tr_3))

    atr = np.full(n, np.nan, dtype=np.float64)
    if n >= period:
        # Initial ATR: Simple average over first `period` bars
        atr[period - 1] = np.mean(tr[:period])
        # Subsequent ATR: Wilder's smoothing -> ATR = (prev_atr * (period - 1) + curr_tr) / period
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return atr


def compute_indicator_atr():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at: {DB_PATH}")

    print(f"[+] Connecting to DuckDB: {DB_PATH}")
    conn = duckdb.connect(str(DB_PATH), read_only=False)

    # 1. Fetch OHLCV (timestamp, high, low, close)
    ohlcv_df = conn.execute(
        "SELECT timestamp, high, low, close FROM ohlcv ORDER BY timestamp;"
    ).fetchdf()

    if ohlcv_df.empty:
        print("[-] OHLCV table is empty.")
        conn.close()
        return

    high_arr = ohlcv_df["high"].to_numpy(dtype=np.float64)
    low_arr = ohlcv_df["low"].to_numpy(dtype=np.float64)
    close_arr = ohlcv_df["close"].to_numpy(dtype=np.float64)

    print(f"[+] Computing ATR for {len(ohlcv_df):,} candles (Fast={FAST_PERIOD}, Normal={NORMAL_PERIOD}, Slow={SLOW_PERIOD})...")
    atr_fast = compute_atr(high_arr, low_arr, close_arr, FAST_PERIOD)
    atr_normal = compute_atr(high_arr, low_arr, close_arr, NORMAL_PERIOD)
    atr_slow = compute_atr(high_arr, low_arr, close_arr, SLOW_PERIOD)

    res_df = pd.DataFrame({
        "timestamp": ohlcv_df["timestamp"],
        "atr_fast": np.round(atr_fast * 10000.0, 4),      # In pips (0.0001)
        "atr_normal": np.round(atr_normal * 10000.0, 4),  # In pips (0.0001)
        "atr_slow": np.round(atr_slow * 10000.0, 4)       # In pips (0.0001)
    })

    # Write table "indicator_atr" into DuckDB
    conn.execute('DROP TABLE IF EXISTS "indicator_atr";')
    conn.execute(
        """
        CREATE TABLE "indicator_atr" (
            timestamp TIMESTAMP PRIMARY KEY,
            atr_fast DOUBLE,
            atr_normal DOUBLE,
            atr_slow DOUBLE
        );
    """
    )
    conn.register("res_df_view", res_df)
    conn.execute(
        'INSERT INTO "indicator_atr" SELECT timestamp, atr_fast, atr_normal, atr_slow FROM res_df_view;'
    )
    conn.unregister("res_df_view")

    # Create view indicator_atr_view
    conn.execute(
        """
        CREATE OR REPLACE VIEW indicator_atr_view AS 
        SELECT timestamp, atr_fast, atr_normal, atr_slow 
        FROM "indicator_atr";
    """
    )

    print(f'[+] Successfully created table `"indicator_atr"` and view `indicator_atr_view` in {DB_PATH}')
    
    sample = conn.execute("SELECT * FROM indicator_atr ORDER BY timestamp DESC LIMIT 5;").fetchdf()
    print("\nSample Data (Latest 5 Candles, ATR values in pips):")
    print(sample.to_string(index=False))

    conn.close()


def main():
    compute_indicator_atr()


if __name__ == "__main__":
    main()
