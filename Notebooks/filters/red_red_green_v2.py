#!/usr/bin/env python3
"""Apply Red-Red-Green v2 (RRG v2) Filter to DuckDB Trades Table (Excluding Entry Candle).

Evaluates the Red-Red-Green filter on the 3 candles BEFORE the entry candle (`pos`):
- Candle pos - 3: RED (close < open)
- Candle pos - 2: RED (close < open)
- Candle pos - 1: GREEN (close > open)
- Condition:      close of Candle pos - 1 < max(open, close) of Candle pos - 2 (closing of green is below preceding red's body high)
- Candle pos:     ENTRY CANDLE

Creates/replaces table `red_red_green_v2` and view `red_red_green_v2_view` in Shared/Data/eur_usd_trades_5m.duckdb.
Optionally accepts `--distribution` flag to display win/loss distribution.
"""

import argparse
from pathlib import Path
import sys

import duckdb
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "Shared" / "Data" / "eur_usd_trades_5m.duckdb"


def compute_red_red_green_v2_filter(show_distribution: bool = False):
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at: {DB_PATH}")

    print(f"[+] Connecting to DuckDB: {DB_PATH}")
    conn = duckdb.connect(str(DB_PATH), read_only=False)

    # 1. Fetch trades (uid, entry_time)
    trades_df = conn.execute(
        "SELECT uid, entry_time FROM trades ORDER BY uid;"
    ).fetchdf()

    # 2. Fetch ohlcv (timestamp, open, close)
    ohlcv_df = conn.execute(
        "SELECT timestamp, open, close FROM ohlcv ORDER BY timestamp;"
    ).fetchdf()

    ohlcv_df["timestamp"] = pd.to_datetime(ohlcv_df["timestamp"])

    # Pre-strip timezone for fast datetime comparison
    if ohlcv_df["timestamp"].dt.tz is not None:
        ohlcv_ts = ohlcv_df["timestamp"].dt.tz_localize(None).values
    else:
        ohlcv_ts = ohlcv_df["timestamp"].values

    open_arr = ohlcv_df["open"].to_numpy()
    close_arr = ohlcv_df["close"].to_numpy()

    # Candle types: red (close < open), green (close > open)
    is_red_arr = close_arr < open_arr
    is_green_arr = close_arr > open_arr
    # Body high for red candle is max(open, close) = open (since open > close for red)
    body_high_arr = np.maximum(open_arr, close_arr)

    results = []

    for _, row in trades_df.iterrows():
        uid = int(row["uid"])
        entry_ts = pd.to_datetime(row["entry_time"])
        if entry_ts.tzinfo is not None:
            entry_ts_val = entry_ts.tz_localize(None).to_datetime64()
        else:
            entry_ts_val = entry_ts.to_datetime64()

        # Find bar index at or prior to entry_ts
        pos = np.searchsorted(ohlcv_ts, entry_ts_val, side="right") - 1

        # Evaluate 3 candles BEFORE entry (pos-3, pos-2, pos-1)
        if pos >= 3:
            # pos - 3: RED (1st red)
            # pos - 2: RED (2nd red)
            # pos - 1: GREEN
            c1_red = is_red_arr[pos - 3]
            c2_red = is_red_arr[pos - 2]
            c3_green = is_green_arr[pos - 1]

            red2_body_high = body_high_arr[pos - 2]
            green_close = close_arr[pos - 1]

            # Condition: RRG sequence AND green close < preceding red body high
            is_rrg_v2 = bool(c1_red and c2_red and c3_green and (green_close < red2_body_high))
        else:
            is_rrg_v2 = False

        results.append({"uid": uid, "red_red_green_v2": is_rrg_v2})

    res_df = pd.DataFrame(results)

    # Write table "red_red_green_v2" into DuckDB
    conn.execute('DROP TABLE IF EXISTS "red_red_green_v2";')
    conn.execute(
        """
        CREATE TABLE "red_red_green_v2" (
            uid BIGINT PRIMARY KEY,
            "red_red_green_v2" BOOLEAN
        );
    """
    )
    conn.register("res_df_view", res_df)
    conn.execute(
        'INSERT INTO "red_red_green_v2" SELECT uid, "red_red_green_v2" FROM res_df_view;'
    )
    conn.unregister("res_df_view")

    # Create view red_red_green_v2_view
    conn.execute(
        """
        CREATE OR REPLACE VIEW red_red_green_v2_view AS 
        SELECT uid, "red_red_green_v2" 
        FROM "red_red_green_v2";
    """
    )

    count_true = res_df["red_red_green_v2"].sum()
    total_trades = len(res_df)

    print(f'[+] Successfully created table `"red_red_green_v2"` and view `red_red_green_v2_view` in {DB_PATH}')
    print(f"[+] Summary: {count_true} / {total_trades} trades matched the Red-Red-Green v2 filter ({count_true / total_trades * 100:.2f}%).")

    if show_distribution:
        print("\n" + "=" * 75)
        print(" RED-RED-GREEN v2 FILTER WIN / LOSS DISTRIBUTION")
        print("=" * 75)
        dist_query = """
            SELECT 
                f.red_red_green_v2,
                COUNT(*) as total_trades,
                SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN t.pnl <= 0 THEN 1 ELSE 0 END) as losses,
                ROUND(SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as win_rate_pct,
                ROUND(SUM(t.pnl), 2) as net_pnl
            FROM trades t
            JOIN "red_red_green_v2" f ON t.uid = f.uid
            GROUP BY f.red_red_green_v2
            ORDER BY f.red_red_green_v2 DESC;
        """
        dist_df = conn.execute(dist_query).fetchdf()
        print(dist_df.to_string(index=False))
        print("=" * 75 + "\n")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Apply Red-Red-Green v2 filter to trades dataset.")
    parser.add_argument(
        "--distribution",
        action="store_true",
        help="Display the win/loss distribution breakdown for the filter.",
    )
    args = parser.parse_args()

    compute_red_red_green_v2_filter(show_distribution=args.distribution)


if __name__ == "__main__":
    main()
