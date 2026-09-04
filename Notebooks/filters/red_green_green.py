#!/usr/bin/env python3
"""Apply Red-Green-Green (RGG) Filter to DuckDB Trades Table.

Evaluates the Red-Green-Green filter on the 3 candles prior to / ending at entry candle index `pos`:
- Candle pos - 2: RED (close < open)
- Candle pos - 1: GREEN (close > open)
- Candle pos:     GREEN (close > open)
- Condition:      close of Candle pos > max(open, close) of Candle pos - 1 (closing of 2nd green is above 1st green body high)

Creates/replaces table `red_green_green` and view `red_green_green_view` in Shared/Data/eur_usd_trades_5m.duckdb.
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


def compute_red_green_green_filter(show_distribution: bool = False):
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
    # Body high for green candle is max(open, close)
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

        if pos >= 2:
            # 3 candles sequence ending at pos:
            # pos - 2: RED (1st candle)
            # pos - 1: GREEN (1st green)
            # pos:     GREEN (2nd green)
            c1_red = is_red_arr[pos - 2]
            c2_green = is_green_arr[pos - 1]
            c3_green = is_green_arr[pos]

            green1_body_high = body_high_arr[pos - 1]
            green2_close = close_arr[pos]

            # Condition: RGG pattern AND close of 2nd green > 1st green body high
            is_rgg = bool(c1_red and c2_green and c3_green and (green2_close > green1_body_high))
        else:
            is_rgg = False

        results.append({"uid": uid, "red_green_green": is_rgg})

    res_df = pd.DataFrame(results)

    # Write table "red_green_green" into DuckDB
    conn.execute('DROP TABLE IF EXISTS "red_green_green";')
    conn.execute(
        """
        CREATE TABLE "red_green_green" (
            uid BIGINT PRIMARY KEY,
            "red_green_green" BOOLEAN
        );
    """
    )
    conn.register("res_df_view", res_df)
    conn.execute(
        'INSERT INTO "red_green_green" SELECT uid, "red_green_green" FROM res_df_view;'
    )
    conn.unregister("res_df_view")

    # Create view red_green_green_view
    conn.execute(
        """
        CREATE OR REPLACE VIEW red_green_green_view AS 
        SELECT uid, "red_green_green" 
        FROM "red_green_green";
    """
    )

    count_true = res_df["red_green_green"].sum()
    total_trades = len(res_df)

    print(f'[+] Successfully created table `"red_green_green"` and view `red_green_green_view` in {DB_PATH}')
    print(f"[+] Summary: {count_true} / {total_trades} trades matched the Red-Green-Green filter ({count_true / total_trades * 100:.2f}%).")

    if show_distribution:
        print("\n" + "=" * 70)
        print(" RED-GREEN-GREEN FILTER WIN / LOSS DISTRIBUTION")
        print("=" * 70)
        dist_query = """
            SELECT 
                f.red_green_green,
                COUNT(*) as total_trades,
                SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN t.pnl <= 0 THEN 1 ELSE 0 END) as losses,
                ROUND(SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as win_rate_pct,
                ROUND(SUM(t.pnl), 2) as net_pnl
            FROM trades t
            JOIN "red_green_green" f ON t.uid = f.uid
            GROUP BY f.red_green_green
            ORDER BY f.red_green_green DESC;
        """
        dist_df = conn.execute(dist_query).fetchdf()
        print(dist_df.to_string(index=False))
        print("=" * 70 + "\n")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Apply Red-Green-Green filter to trades dataset.")
    parser.add_argument(
        "--distribution",
        action="store_true",
        help="Display the win/loss distribution breakdown for the filter.",
    )
    args = parser.parse_args()

    compute_red_green_green_filter(show_distribution=args.distribution)


if __name__ == "__main__":
    main()
