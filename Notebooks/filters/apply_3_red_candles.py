#!/usr/bin/env python3
"""Apply 3 Red Candles Filter to DuckDB Trades Table.

Evaluates the 3-red-candles filter (3 consecutive red candles ending at or prior to trade entry)
for all trades in Shared/Data/eur_usd_trades_5m.duckdb.
Creates/replaces the table `filter_3_red_candles` with columns: (uid BIGINT, filter_3_red_candles BOOLEAN).
"""

from pathlib import Path
import sys

import duckdb
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "Shared" / "Data" / "eur_usd_trades_5m.duckdb"


def compute_3_red_candles_filter():
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
    ohlcv_df["is_red"] = ohlcv_df["close"] < ohlcv_df["open"]

    # Pre-strip timezone for fast datetime comparison
    if ohlcv_df["timestamp"].dt.tz is not None:
        ohlcv_ts = ohlcv_df["timestamp"].dt.tz_localize(None).values
    else:
        ohlcv_ts = ohlcv_df["timestamp"].values

    is_red_arr = ohlcv_df["is_red"].to_numpy()

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
            # Check 3 candles ending at pos
            three_red = bool(
                is_red_arr[pos] and is_red_arr[pos - 1] and is_red_arr[pos - 2]
            )
        else:
            three_red = False

        results.append({"uid": uid, "filter_3_red_candles": three_red})

    res_df = pd.DataFrame(results)

    # Write table filter_3_red_candles into DuckDB
    conn.execute("DROP TABLE IF EXISTS filter_3_red_candles;")
    conn.execute(
        """
        CREATE TABLE filter_3_red_candles (
            uid BIGINT PRIMARY KEY,
            filter_3_red_candles BOOLEAN
        );
    """
    )
    conn.register("res_df_view", res_df)
    conn.execute(
        "INSERT INTO filter_3_red_candles SELECT uid, filter_3_red_candles FROM res_df_view;"
    )
    conn.unregister("res_df_view")

    count_true = res_df["filter_3_red_candles"].sum()
    total_trades = len(res_df)

    conn.close()

    print(f"[+] Successfully created table `filter_3_red_candles` in {DB_PATH}")
    print(f"[+] Summary: {count_true} / {total_trades} trades matched the 3-red-candles filter ({count_true / total_trades * 100:.2f}%).")


def main():
    compute_3_red_candles_filter()


if __name__ == "__main__":
    main()
