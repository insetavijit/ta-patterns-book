#!/usr/bin/env python3
"""3-Candle & Entry Candle Pattern Classifier Script (Notebooks/patterns/3candel_patterns.py).

Reads each trade from `trades` in Shared/Data/eur_usd_trades_5m.duckdb and evaluates candle combinations across 4 alignment variants:
  - entry_1: 3 candles before entry (c1-c2-c3) -> pos-3, pos-2, pos-1
  - entry_2: 2 candles before entry + entry candle (c1-c2-entry) -> pos-2, pos-1, pos
  - entry_3: 1 candle before entry + entry + 1 candle after entry (c1-entry-c2) -> pos-1, pos, pos+1
  - entry_4: entry candle + 3 candles after entry (entry-c1-c2-c3) -> pos, pos+1, pos+2, pos+3 (or 4 candles total)

Creates/replaces table `3candels_patterns` and view `3candels_patterns_view` in DuckDB with schema:
  (trade_id BIGINT PRIMARY KEY, entry_1 VARCHAR, entry_2 VARCHAR, entry_3 VARCHAR, entry_4 VARCHAR)

Supports `--distribution` flag to display win/loss performance for each variant.
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


def get_candle_state(idx: int, open_arr: np.ndarray, close_arr: np.ndarray) -> str:
    """Safely classifies candle at index `idx` using close[idx-1] as prev_close."""
    if idx < 0 or idx >= len(close_arr):
        return "UNK"
    prev_close = close_arr[idx - 1] if idx >= 1 else open_arr[idx]
    return classify_candle(open_arr[idx], close_arr[idx], prev_close)


def compute_3candel_patterns(show_distribution: bool = False):
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at: {DB_PATH}")

    print(f"[+] Connecting to DuckDB: {DB_PATH}")
    conn = duckdb.connect(str(DB_PATH), read_only=False)

    # 1. Fetch trades (trade_id, entry_time)
    trades_df = conn.execute(
        "SELECT trade_id, entry_time FROM trades ORDER BY trade_id;"
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
        t_id = int(row["trade_id"])
        entry_ts = pd.to_datetime(row["entry_time"])
        if entry_ts.tzinfo is not None:
            entry_ts_val = entry_ts.tz_localize(None).to_datetime64()
        else:
            entry_ts_val = entry_ts.to_datetime64()

        # Find bar index at or prior to entry_ts (pos = entry candle)
        pos = np.searchsorted(ohlcv_ts, entry_ts_val, side="right") - 1

        # Variant entry_1: 3 candles before entry (c1-c2-c3 -> pos-3, pos-2, pos-1)
        e1_c1 = get_candle_state(pos - 3, open_arr, close_arr)
        e1_c2 = get_candle_state(pos - 2, open_arr, close_arr)
        e1_c3 = get_candle_state(pos - 1, open_arr, close_arr)
        entry_1_code = f"{e1_c1}-{e1_c2}-{e1_c3}"

        # Variant entry_2: c1-c2=entry -> pos-2, pos-1, pos (entry candle is 3rd)
        e2_c1 = get_candle_state(pos - 2, open_arr, close_arr)
        e2_c2 = get_candle_state(pos - 1, open_arr, close_arr)
        e2_e = get_candle_state(pos, open_arr, close_arr)
        entry_2_code = f"{e2_c1}-{e2_c2}-{e2_e}"

        # Variant entry_3: c1=entry-c2-c3 -> pos-1, pos, pos+1, pos+2 (or c1-entry-c2: pos-1, pos, pos+1)
        e3_c1 = get_candle_state(pos - 1, open_arr, close_arr)
        e3_e = get_candle_state(pos, open_arr, close_arr)
        e3_c2 = get_candle_state(pos + 1, open_arr, close_arr)
        entry_3_code = f"{e3_c1}-{e3_e}-{e3_c2}"

        # Variant entry_4: entry-c1-c2-c3-c4 -> pos, pos+1, pos+2, pos+3
        e4_e = get_candle_state(pos, open_arr, close_arr)
        e4_c1 = get_candle_state(pos + 1, open_arr, close_arr)
        e4_c2 = get_candle_state(pos + 2, open_arr, close_arr)
        e4_c3 = get_candle_state(pos + 3, open_arr, close_arr)
        entry_4_code = f"{e4_e}-{e4_c1}-{e4_c2}-{e4_c3}"

        results.append(
            {
                "trade_id": t_id,
                "entry_1": entry_1_code,
                "entry_2": entry_2_code,
                "entry_3": entry_3_code,
                "entry_4": entry_4_code,
            }
        )

    res_df = pd.DataFrame(results).drop_duplicates(subset=["trade_id"])

    # Write table "3candels_patterns" into DuckDB
    conn.execute('DROP TABLE IF EXISTS "3candels_patterns";')
    conn.execute(
        """
        CREATE TABLE "3candels_patterns" (
            trade_id BIGINT PRIMARY KEY,
            entry_1 VARCHAR,
            entry_2 VARCHAR,
            entry_3 VARCHAR,
            entry_4 VARCHAR
        );
    """
    )
    conn.register("res_df_view", res_df)
    conn.execute(
        'INSERT INTO "3candels_patterns" SELECT trade_id, entry_1, entry_2, entry_3, entry_4 FROM res_df_view;'
    )
    conn.unregister("res_df_view")

    # Create view "3candels_patterns_view"
    conn.execute(
        """
        CREATE OR REPLACE VIEW "3candels_patterns_view" AS 
        SELECT trade_id, entry_1, entry_2, entry_3, entry_4 
        FROM "3candels_patterns";
    """
    )

    total_trades = len(res_df)

    print(f'[+] Successfully updated table `"3candels_patterns"` and view `"3candels_patterns_view"` in {DB_PATH}')
    print(f"[+] Summary: Processed {total_trades} trades across 4 entry pattern variants.")

    sample = conn.execute('SELECT * FROM "3candels_patterns" ORDER BY trade_id ASC LIMIT 5;').fetchdf()
    print("\nSample Preview:")
    print(sample.to_string(index=False))

    if show_distribution:
        for col in ["entry_1", "entry_2", "entry_3", "entry_4"]:
            print("\n" + "=" * 85)
            print(f" PATTERN PERFORMANCE DISTRIBUTION FOR {col.upper()}")
            print("=" * 85)
            dist_query = f"""
            SELECT 
                p.{col} AS pattern,
                COUNT(*) AS total_trades,
                SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN t.pnl <= 0 THEN 1 ELSE 0 END) AS losses,
                ROUND(SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS win_rate_pct,
                ROUND(SUM(t.pnl), 2) AS net_pnl
            FROM trades t
            JOIN "3candels_patterns" p ON t.trade_id = p.trade_id
            GROUP BY p.{col}
            ORDER BY total_trades DESC, win_rate_pct DESC
            LIMIT 15;
            """
            dist_df = conn.execute(dist_query).fetchdf()
            pd.set_option("display.max_rows", 100)
            print(dist_df.to_string(index=False))
            print("=" * 85 + "\n")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="3-Candle & Entry Candle Multi-Variant Pattern Classifier.")
    parser.add_argument(
        "--distribution",
        action="store_true",
        help="Display the win/loss performance distribution for all 4 entry pattern variants.",
    )
    args = parser.parse_args()

    compute_3candel_patterns(show_distribution=args.distribution)


if __name__ == "__main__":
    main()
