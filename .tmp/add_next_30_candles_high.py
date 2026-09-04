#!/usr/bin/env python3
"""Add Next 30 Candles High Column Script (.tmp/add_next_30_candles_high.py)

Calculates the maximum HIGH price of the next 30 candles after entry (from ohlcv)
for every trade in `trades` table in Shared/Data/eur_usd_trades_5m.duckdb.

Creates/replaces table `next_30_candles_high` and updates view `filtered_trades`
to include `next_30_candles_high` and `next_30_max_pips` columns.
"""

from pathlib import Path
import sys

import duckdb
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "Shared" / "Data" / "eur_usd_trades_5m.duckdb"


def compute_next_30_candles_high():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at: {DB_PATH}")

    print(f"[+] Connecting to DuckDB: {DB_PATH}")
    conn = duckdb.connect(str(DB_PATH), read_only=False)

    # 1. Fetch trades (uid, entry_time, entry_price)
    trades_df = conn.execute(
        "SELECT uid, entry_time, entry_price FROM trades ORDER BY uid;"
    ).fetchdf()

    # 2. Fetch ohlcv (timestamp, high)
    ohlcv_df = conn.execute(
        "SELECT timestamp, high FROM ohlcv ORDER BY timestamp;"
    ).fetchdf()

    ohlcv_df["timestamp"] = pd.to_datetime(ohlcv_df["timestamp"])

    # Pre-strip timezone for fast datetime comparison
    if ohlcv_df["timestamp"].dt.tz is not None:
        ohlcv_ts = ohlcv_df["timestamp"].dt.tz_localize(None).values
    else:
        ohlcv_ts = ohlcv_df["timestamp"].values

    high_arr = ohlcv_df["high"].to_numpy()
    n_ohlcv = len(high_arr)

    results = []

    for _, row in trades_df.iterrows():
        uid = int(row["uid"])
        entry_price = float(row["entry_price"])
        entry_ts = pd.to_datetime(row["entry_time"])
        if entry_ts.tzinfo is not None:
            entry_ts_val = entry_ts.tz_localize(None).to_datetime64()
        else:
            entry_ts_val = entry_ts.to_datetime64()

        # Find bar index at or prior to entry_ts
        pos = np.searchsorted(ohlcv_ts, entry_ts_val, side="right") - 1

        # Next 30 candles starting AFTER entry candle: pos+1 to pos+30 inclusive
        start_idx = pos + 1
        end_idx = min(pos + 31, n_ohlcv)

        if start_idx < n_ohlcv:
            next_30_high = float(np.max(high_arr[start_idx:end_idx]))
            # Calculate max pips favorable excursion (for EUR/USD 1 pip = 0.0001)
            next_30_max_pips = float(round((next_30_high - entry_price) * 10000.0, 2))
        else:
            next_30_high = None
            next_30_max_pips = None

        results.append({
            "uid": uid, 
            "next_30_candles_high": next_30_high,
            "next_30_max_pips": next_30_max_pips
        })

    res_df = pd.DataFrame(results)

    # Write table "next_30_candles_high" into DuckDB
    conn.execute('DROP TABLE IF EXISTS "next_30_candles_high";')
    conn.execute(
        """
        CREATE TABLE "next_30_candles_high" (
            uid BIGINT PRIMARY KEY,
            "next_30_candles_high" DOUBLE,
            "next_30_max_pips" DOUBLE
        );
    """
    )
    conn.register("res_df_view", res_df)
    conn.execute(
        'INSERT INTO "next_30_candles_high" SELECT uid, "next_30_candles_high", "next_30_max_pips" FROM res_df_view;'
    )
    conn.unregister("res_df_view")

    # Update view filtered_trades to include next_30_candles_high and next_30_max_pips
    conn.execute(
        """
        CREATE OR REPLACE VIEW filtered_trades AS
        SELECT 
            t.uid AS trade_id,
            t.entry_time,
            t.entry_price,
            t.sl_price,
            t.tp_price,
            t.exit_price,
            t.exit_reason,
            t.pnl,
            t.duration_candel,
            t.month_table,
            f1."3_red_candels",
            f2.red_green_red,
            f3."3_red_candels_v2",
            f4.red_green_red_v2,
            h.next_30_candles_high,
            h.next_30_max_pips
        FROM trades t
        LEFT JOIN "3_red_candels" f1 ON t.uid = f1.uid
        LEFT JOIN red_green_red f2 ON t.uid = f2.uid
        LEFT JOIN "3_red_candels_v2" f3 ON t.uid = f3.uid
        LEFT JOIN red_green_red_v2 f4 ON t.uid = f4.uid
        LEFT JOIN "next_30_candles_high" h ON t.uid = h.uid
        ORDER BY t.uid ASC;
    """
    )

    print(f'[+] Successfully created table `"next_30_candles_high"` and updated view `filtered_trades` in {DB_PATH}')
    
    sample = conn.execute(
        'SELECT trade_id, entry_time, entry_price, next_30_candles_high, next_30_max_pips FROM filtered_trades LIMIT 5;'
    ).fetchdf()
    print("\nSample Preview:")
    print(sample.to_string(index=False))

    conn.close()


def main():
    compute_next_30_candles_high()


if __name__ == "__main__":
    main()
