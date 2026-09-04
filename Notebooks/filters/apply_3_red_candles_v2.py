#!/usr/bin/env python3
"""Apply 3 Red Candles v2 Filter (Excluding Entry Candle).

Evaluates 3 consecutive red candles BEFORE the entry candle:
- Candle pos - 3: RED (close < open)
- Candle pos - 2: RED (close < open)
- Candle pos - 1: RED (close < open)
- Candle pos:     ENTRY CANDLE

Creates/replaces table `3_red_candels_v2` and view `3_red_candels_v2_view` in Shared/Data/eur_usd_trades_5m.duckdb.
"""

from pathlib import Path
import sys

import duckdb
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "Shared" / "Data" / "eur_usd_trades_5m.duckdb"


def compute_3_red_candles_v2():
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

        # Check 3 candles BEFORE pos: pos-3, pos-2, pos-1
        if pos >= 3:
            three_red = bool(
                is_red_arr[pos - 1] and is_red_arr[pos - 2] and is_red_arr[pos - 3]
            )
        else:
            three_red = False

        results.append({"uid": uid, "3_red_candels_v2": three_red})

    res_df = pd.DataFrame(results)

    # Write table "3_red_candels_v2" into DuckDB
    conn.execute('DROP TABLE IF EXISTS "3_red_candels_v2";')
    conn.execute(
        """
        CREATE TABLE "3_red_candels_v2" (
            uid BIGINT PRIMARY KEY,
            "3_red_candels_v2" BOOLEAN
        );
    """
    )
    conn.register("res_df_view", res_df)
    conn.execute(
        'INSERT INTO "3_red_candels_v2" SELECT uid, "3_red_candels_v2" FROM res_df_view;'
    )
    conn.unregister("res_df_view")

    # Create view 3_red_candels_v2_view
    conn.execute(
        """
        CREATE OR REPLACE VIEW "3_red_candels_v2_view" AS 
        SELECT uid, "3_red_candels_v2" 
        FROM "3_red_candels_v2";
    """
    )

    count_true = res_df["3_red_candels_v2"].sum()
    total_trades = len(res_df)

    conn.close()

    print(f'[+] Successfully created table `"3_red_candels_v2"` and view `"3_red_candels_v2_view"` in {DB_PATH}')
    print(f"[+] Summary: {count_true} / {total_trades} trades matched the 3-Red-Candles v2 filter ({count_true / total_trades * 100:.2f}%).")


def main():
    compute_3_red_candles_v2()


if __name__ == "__main__":
    main()
