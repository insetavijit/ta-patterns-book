#!/usr/bin/env python3
"""Projected Risk-Reward Ratio Calculation Script (.tmp/add_projected_rr.py)

Calculates the projected Risk-Reward Ratio (projected_rr) for every trade in `trades`:
  risk = abs(entry_price - sl_price)
  reward = abs(tp_price - entry_price)
  projected_rr = round(reward / risk, 2)

Creates/replaces table `projected_rr` and updates view `filtered_trades` to include `projected_rr`.
"""

from pathlib import Path
import sys

import duckdb
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "Shared" / "Data" / "eur_usd_trades_5m.duckdb"


def compute_projected_rr():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at: {DB_PATH}")

    print(f"[+] Connecting to DuckDB: {DB_PATH}")
    conn = duckdb.connect(str(DB_PATH), read_only=False)

    # 1. Fetch trades (uid, entry_price, sl_price, tp_price)
    trades_df = conn.execute(
        "SELECT uid, entry_price, sl_price, tp_price FROM trades ORDER BY uid;"
    ).fetchdf()

    results = []

    for _, row in trades_df.iterrows():
        uid = int(row["uid"])
        entry_p = float(row["entry_price"])
        sl_p = float(row["sl_price"])
        tp_p = float(row["tp_price"])

        risk = abs(entry_p - sl_p)
        reward = abs(tp_p - entry_p)

        if risk > 0:
            rr = float(round(reward / risk, 2))
        else:
            rr = None

        results.append({"uid": uid, "projected_rr": rr})

    res_df = pd.DataFrame(results)

    # Write table "projected_rr" into DuckDB
    conn.execute('DROP TABLE IF EXISTS "projected_rr";')
    conn.execute(
        """
        CREATE TABLE "projected_rr" (
            uid BIGINT PRIMARY KEY,
            "projected_rr" DOUBLE
        );
    """
    )
    conn.register("res_df_view", res_df)
    conn.execute(
        'INSERT INTO "projected_rr" SELECT uid, "projected_rr" FROM res_df_view;'
    )
    conn.unregister("res_df_view")

    # Update view filtered_trades to include projected_rr
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
            h.next_30_max_pips,
            rr.projected_rr
        FROM trades t
        LEFT JOIN "3_red_candels" f1 ON t.uid = f1.uid
        LEFT JOIN red_green_red f2 ON t.uid = f2.uid
        LEFT JOIN "3_red_candels_v2" f3 ON t.uid = f3.uid
        LEFT JOIN red_green_red_v2 f4 ON t.uid = f4.uid
        LEFT JOIN "next_30_candles_high" h ON t.uid = h.uid
        LEFT JOIN "projected_rr" rr ON t.uid = rr.uid
        ORDER BY t.uid ASC;
    """
    )

    print(f'[+] Successfully created table `"projected_rr"` and updated view `filtered_trades` in {DB_PATH}')
    
    sample = conn.execute(
        'SELECT trade_id, entry_price, sl_price, tp_price, projected_rr FROM filtered_trades LIMIT 5;'
    ).fetchdf()
    print("\nSample Preview:")
    print(sample.to_string(index=False))

    conn.close()


def main():
    compute_projected_rr()


if __name__ == "__main__":
    main()
