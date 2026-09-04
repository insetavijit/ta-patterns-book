#!/usr/bin/env python3
"""Apply Red-Green-Red (RGR) Filter to DuckDB Trades Table.

Evaluates the Red-Green-Red filter on the 3 candles prior to / ending at entry candle index `pos`:
- Candle pos - 2: RED (close < open)
- Candle pos - 1: GREEN (close > open)
- Candle pos:     RED (close < open)
- Condition:      close of Candle pos < min(open, close) of Candle pos - 1 (closing of 2nd red is below green body low)

Creates/replaces table `red_green_red` in Shared/Data/eur_usd_trades_5m.duckdb.
"""

from pathlib import Path
import sys

import duckdb
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
DB_PATH = BASE_DIR / "Shared" / "Data" / "eur_usd_trades_5m.duckdb"


def compute_red_green_red_filter():
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
    # Body low for green candle is min(open, close)
    body_low_arr = np.minimum(open_arr, close_arr)

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
            # pos - 2: RED (1st red)
            # pos - 1: GREEN
            # pos:     RED (2nd red)
            c1_red = is_red_arr[pos - 2]
            c2_green = is_green_arr[pos - 1]
            c3_red = is_red_arr[pos]

            green_body_low = body_low_arr[pos - 1]
            red2_close = close_arr[pos]

            # Condition: RGR pattern AND close of 2nd red < green body low
            is_rgr = bool(c1_red and c2_green and c3_red and (red2_close < green_body_low))
        else:
            is_rgr = False

        results.append({"uid": uid, "red_green_red": is_rgr})

    res_df = pd.DataFrame(results)

    # Write table "red_green_red" into DuckDB
    conn.execute('DROP TABLE IF EXISTS "red_green_red";')
    conn.execute(
        """
        CREATE TABLE "red_green_red" (
            uid BIGINT PRIMARY KEY,
            "red_green_red" BOOLEAN
        );
    """
    )
    conn.register("res_df_view", res_df)
    conn.execute(
        'INSERT INTO "red_green_red" SELECT uid, "red_green_red" FROM res_df_view;'
    )
    conn.unregister("res_df_view")

    count_true = res_df["red_green_red"].sum()
    total_trades = len(res_df)

    conn.close()

    print(f'[+] Successfully created table `"red_green_red"` in {DB_PATH}')
    print(f"[+] Summary: {count_true} / {total_trades} trades matched the Red-Green-Red filter ({count_true / total_trades * 100:.2f}%).")


def main():
    compute_red_green_red_filter()


if __name__ == "__main__":
    main()
