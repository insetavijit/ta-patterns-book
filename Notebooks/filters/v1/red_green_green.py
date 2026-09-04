#!/usr/bin/env python3
"""Apply Red-Green-Green (RGG) & Detailed Pattern Classification Filter to DuckDB Trades Table.

Evaluates the Red-Green-Green filter on the 3 candles prior to / ending at entry candle index `pos`:
- Candle pos - 2: RED (close < open)
- Candle pos - 1: GREEN (close > open)
- Candle pos:     GREEN (close > open)
- Condition:      close of Candle pos > max(open, close) of Candle pos - 1 (closing of 2nd green is above 1st green body high)

In addition, each candle's relative direction (U = Up/Higher, D = Down/Lower) relative to the previous candle's close is detected:
- Candle pos - 2: UR (Up-Red, close >= close[pos-3]) or DR (Down-Red, close < close[pos-3])
- Candle pos - 1: UG (Up-Green, close >= close[pos-2]) or DG (Down-Green, close < close[pos-2])
- Candle pos:     UG (Up-Green, close >= close[pos-1]) or DG (Down-Green, close < close[pos-1])

Classifies all 8 RGG sub-patterns:
UR-UG-UG, UR-UG-DG, UR-DG-UG, UR-DG-DG, DR-UG-UG, DR-UG-DG, DR-DG-UG, DR-DG-DG.

Creates/replaces table `red_green_green` and view `red_green_green_view` in Shared/Data/eur_usd_trades_5m.duckdb.
Accepts `--distribution` flag to display win/loss distribution per sub-pattern.
"""

import argparse
from pathlib import Path
import sys

import duckdb
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
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

            # Standard RGG Condition: RGG pattern AND close of 2nd green > 1st green body high
            is_rgg = bool(c1_red and c2_green and c3_green and (green2_close > green1_body_high))

            # Relative direction detection (U = Up/Higher close, D = Down/Lower close)
            # Candle pos-2 relative to pos-3 (if pos >= 3, else relative to pos-2 open)
            c1_prev_close = close_arr[pos - 3] if pos >= 3 else open_arr[pos - 2]
            c1_rel = "U" if close_arr[pos - 2] >= c1_prev_close else "D"
            c1_code = f"{c1_rel}R" if c1_red else ("UG" if c2_green else "X")

            c2_rel = "U" if close_arr[pos - 1] >= close_arr[pos - 2] else "D"
            c2_code = f"{c2_rel}G" if c2_green else ("UR" if c1_red else "X")

            c3_rel = "U" if close_arr[pos] >= close_arr[pos - 1] else "D"
            c3_code = f"{c3_rel}G" if c3_green else ("UR" if is_red_arr[pos] else "X")

            rgg_pattern_code = f"{c1_rel}R-{c2_rel}G-{c3_rel}G"
        else:
            is_rgg = False
            rgg_pattern_code = "NONE"

        results.append({
            "uid": uid, 
            "red_green_green": is_rgg,
            "rgg_pattern": rgg_pattern_code if is_rgg else "NONE"
        })

    res_df = pd.DataFrame(results)

    # Write table "red_green_green" into DuckDB
    conn.execute('DROP TABLE IF EXISTS "red_green_green";')
    conn.execute(
        """
        CREATE TABLE "red_green_green" (
            uid BIGINT PRIMARY KEY,
            "red_green_green" BOOLEAN,
            "rgg_pattern" VARCHAR
        );
    """
    )
    conn.register("res_df_view", res_df)
    conn.execute(
        'INSERT INTO "red_green_green" SELECT uid, "red_green_green", "rgg_pattern" FROM res_df_view;'
    )
    conn.unregister("res_df_view")

    # Create view red_green_green_view
    conn.execute(
        """
        CREATE OR REPLACE VIEW red_green_green_view AS 
        SELECT uid, "red_green_green", "rgg_pattern" 
        FROM "red_green_green";
    """
    )

    count_true = res_df["red_green_green"].sum()
    total_trades = len(res_df)

    print(f'[+] Successfully created table `"red_green_green"` and view `red_green_green_view` in {DB_PATH}')
    print(f"[+] Summary: {count_true} / {total_trades} trades matched the Red-Green-Green filter ({count_true / total_trades * 100:.2f}%).")

    if show_distribution:
        print("\n" + "=" * 80)
        print(" RED-GREEN-GREEN FILTER OVERALL WIN / LOSS DISTRIBUTION")
        print("=" * 80)
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

        print("\n" + "=" * 80)
        print(" RED-GREEN-GREEN SUB-PATTERN WIN / LOSS DISTRIBUTION")
        print("=" * 80)
        sub_dist_query = """
            SELECT 
                f.rgg_pattern,
                COUNT(*) as total_trades,
                SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN t.pnl <= 0 THEN 1 ELSE 0 END) as losses,
                ROUND(SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as win_rate_pct,
                ROUND(SUM(t.pnl), 2) as net_pnl
            FROM trades t
            JOIN "red_green_green" f ON t.uid = f.uid
            WHERE f.red_green_green = True
            GROUP BY f.rgg_pattern
            ORDER BY total_trades DESC, win_rate_pct DESC;
        """
        sub_dist_df = conn.execute(sub_dist_query).fetchdf()
        print(sub_dist_df.to_string(index=False))
        print("=" * 80 + "\n")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Apply Red-Green-Green filter & relative pattern breakdown.")
    parser.add_argument(
        "--distribution",
        action="store_true",
        help="Display the win/loss distribution breakdown for overall and sub-patterns.",
    )
    args = parser.parse_args()

    compute_red_green_green_filter(show_distribution=args.distribution)


if __name__ == "__main__":
    main()
