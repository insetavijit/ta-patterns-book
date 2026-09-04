#!/usr/bin/env python3
"""Run Filtered Loss Profile Script (.tmp/run_filtered_loss_profile.py)

Dynamically merges `trades_view` and `3RedCanels_view` in DuckDB (read-only mode)
to filter trades where `3Red_candles = False`, and reports monthly performance
without mutating or altering the database file.
"""

from pathlib import Path
import sys

import duckdb
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "Shared" / "Data" / "eur_usd_trades_5m.duckdb"


def run_filtered_loss_profile():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    print(f"[+] Connecting to DuckDB (read-only): {DB_PATH}")
    conn = duckdb.connect(str(DB_PATH), read_only=True)

    # Dynamic SQL join without altering persistent views or tables
    query = """
        SELECT 
            t.month_table AS mnth,
            COUNT(*) AS "number of trades",
            COUNT(CASE WHEN t.pnl > 0 THEN 1 END) AS win,
            COUNT(CASE WHEN t.pnl <= 0 THEN 1 END) AS loss,
            ROUND(COUNT(CASE WHEN t.pnl > 0 THEN 1 END) * 100.0 / COUNT(*), 2) AS "win%",
            SUM(t.pnl) AS raw_pnl
        FROM trades_view t
        JOIN "3RedCanels_view" f ON t.uid = f.uid
        WHERE f."3Red_candles" = False
        GROUP BY t.month_table
        ORDER BY MIN(t.entry_time) ASC;
    """

    df_monthly = conn.execute(query).df()
    conn.close()

    if df_monthly.empty:
        print("No matching trades found.")
        return

    df_monthly["ammount ( sum )"] = df_monthly["raw_pnl"].apply(
        lambda x: f"+${x:,.2f}" if x >= 0 else f"-${abs(x):,.2f}"
    )

    display_df = df_monthly[
        ["mnth", "number of trades", "win", "loss", "win%", "ammount ( sum )"]
    ].copy()

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1000)

    title = "MONTHLY PERFORMANCE BREAKDOWN (Filtered: 3Red_candles = False)"
    print("\n" + "=" * 85)
    print(f" {title}")
    print("=" * 85)
    print(display_df.to_string(index=False))
    print("=" * 85)

    tot_trades = display_df["number of trades"].sum()
    tot_win = display_df["win"].sum()
    tot_loss = display_df["loss"].sum()
    tot_win_pct = (
        round(tot_win / tot_trades * 100.0, 2) if tot_trades > 0 else 0.0
    )
    tot_pnl = df_monthly["raw_pnl"].sum()
    tot_pnl_str = (
        f"+${tot_pnl:,.2f}" if tot_pnl >= 0 else f"-${abs(tot_pnl):,.2f}"
    )

    print(
        f" TOTALS : {tot_trades:,} Trades | {tot_win:,} Wins | {tot_loss:,} Losses | Win%: {tot_win_pct:.2f}% | Net PnL: {tot_pnl_str}"
    )
    print("=" * 85 + "\n")


def main():
    run_filtered_loss_profile()


if __name__ == "__main__":
    main()
