#!/usr/bin/env python3
"""3-Candle Patterns Classification Script (Notebooks/patterns/3candel_patterns.py).

Reads each trade from `trades` in Shared/Data/eur_usd_trades_5m.duckdb, evaluates the 3 setup candles
strictly BEFORE entry (`pos - 3`, `pos - 2`, `pos - 1` -> Entry), and classifies each candle into one of 4 states:
  - UR: Up-Red (close >= prev_close AND close < open)
  - UG: Up-Green (close >= prev_close AND close > open)
  - DR: Down-Red (close < prev_close AND close < open)
  - DG: Down-Green (close < prev_close AND close > open)

Creates/replaces table `3candels_patterns` and view `3candels_patterns_view` in DuckDB with schema:
  (trade_id BIGINT PRIMARY KEY, "3candel_patterns" VARCHAR)

Supports `--distribution` flag to display win/loss performance for all 64 3-candle patterns.
"""

import argparse
from pathlib import Path
import sys

import duckdb
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "Shared" / "Data" / "eur_usd_trades_5m.duckdb"


def classify_candle(open_price: float, close_price: float, prev_close: float) -> str:
    """Classifies a candle into UR, UG, DR, or DG."""
    is_up = close_price >= prev_close
    is_green = close_price > open_price  # Green if close > open, Red if close <= open

    direction_str = "U" if is_up else "D"
    color_str = "G" if is_green else "R"

    return f"{direction_str}{color_str}"


def compute_3candel_patterns(show_distribution: bool = False):
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

    open_arr = ohlcv_df["open"].to_numpy(dtype=np.float64)
    close_arr = ohlcv_df["close"].to_numpy(dtype=np.float64)

    results = []

    for _, row in trades_df.iterrows():
        trade_id = int(row["uid"])
        entry_ts = pd.to_datetime(row["entry_time"])
        if entry_ts.tzinfo is not None:
            entry_ts_val = entry_ts.tz_localize(None).to_datetime64()
        else:
            entry_ts_val = entry_ts.to_datetime64()

        # Find bar index at or prior to entry_ts (pos)
        pos = np.searchsorted(ohlcv_ts, entry_ts_val, side="right") - 1

        # Check 3 candles BEFORE pos: pos-3 (c1), pos-2 (c2), pos-1 (c3)
        if pos >= 3:
            # Prev close for c1 (pos-3) is pos-4 if available, else open[pos-3]
            c1_prev_close = close_arr[pos - 4] if pos >= 4 else open_arr[pos - 3]
            c1_state = classify_candle(open_arr[pos - 3], close_arr[pos - 3], c1_prev_close)

            c2_prev_close = close_arr[pos - 3]
            c2_state = classify_candle(open_arr[pos - 2], close_arr[pos - 2], c2_prev_close)

            c3_prev_close = close_arr[pos - 2]
            c3_state = classify_candle(open_arr[pos - 1], close_arr[pos - 1], c3_prev_close)

            pattern_code = f"{c1_state}-{c2_state}-{c3_state}"
        else:
            pattern_code = "UNKNOWN"

        results.append({"trade_id": trade_id, "3candel_patterns": pattern_code})

    res_df = pd.DataFrame(results)

    # Write table "3candels_patterns" into DuckDB
    conn.execute('DROP TABLE IF EXISTS "3candels_patterns";')
    conn.execute(
        """
        CREATE TABLE "3candels_patterns" (
            trade_id BIGINT PRIMARY KEY,
            "3candel_patterns" VARCHAR
        );
    """
    )
    conn.register("res_df_view", res_df)
    conn.execute(
        'INSERT INTO "3candels_patterns" SELECT trade_id, "3candel_patterns" FROM res_df_view;'
    )
    conn.unregister("res_df_view")

    # Create view "3candels_patterns_view"
    conn.execute(
        """
        CREATE OR REPLACE VIEW "3candels_patterns_view" AS 
        SELECT trade_id, "3candel_patterns" 
        FROM "3candels_patterns";
    """
    )

    unique_patterns = res_df["3candel_patterns"].nunique()
    total_trades = len(res_df)

    print(f'[+] Successfully created table `"3candels_patterns"` and view `"3candels_patterns_view"` in {DB_PATH}')
    print(f"[+] Summary: Classified {total_trades} trades across {unique_patterns} unique 3-candle patterns.")

    sample = conn.execute('SELECT * FROM "3candels_patterns" ORDER BY trade_id ASC LIMIT 5;').fetchdf()
    print("\nSample Preview:")
    print(sample.to_string(index=False))

    if show_distribution:
        print("\n" + "=" * 85)
        print(" 3-CANDLE PATTERNS WIN / LOSS DISTRIBUTION (BEFORE ENTRY)")
        print("=" * 85)
        dist_query = """
        SELECT 
            p."3candel_patterns" AS pattern,
            COUNT(*) AS total_trades,
            SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN t.pnl <= 0 THEN 1 ELSE 0 END) AS losses,
            ROUND(SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS win_rate_pct,
            ROUND(SUM(t.pnl), 2) AS net_pnl
        FROM trades t
        JOIN "3candels_patterns" p ON t.trade_id = p.trade_id
        GROUP BY p."3candel_patterns"
        ORDER BY total_trades DESC, win_rate_pct DESC;
        """
        dist_df = conn.execute(dist_query).fetchdf()
        pd.set_option("display.max_rows", 100)
        print(dist_df.to_string(index=False))
        print("=" * 85 + "\n")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="3-Candle Pattern Classifier for Trades Dataset.")
    parser.add_argument(
        "--distribution",
        action="store_true",
        help="Display the win/loss performance distribution for all classified 3-candle patterns.",
    )
    args = parser.parse_args()

    compute_3candel_patterns(show_distribution=args.distribution)


if __name__ == "__main__":
    main()
