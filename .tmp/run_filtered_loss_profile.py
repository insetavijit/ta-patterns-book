#!/usr/bin/env python3
"""Run Filtered Loss Profile Script (.tmp/run_filtered_loss_profile.py)

Dynamically merges `trades_view` and `3RedCanels_view` in DuckDB (read-only mode)
to filter trades where `3Red_candles = False`, and supports --monthly, --weekly, --duration flags.

Usage:
    uv run python .tmp/run_filtered_loss_profile.py --duration
    uv run python .tmp/run_filtered_loss_profile.py --weekly
    uv run python .tmp/run_filtered_loss_profile.py --monthly
"""

import argparse
from pathlib import Path
import sys

import duckdb
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "Shared" / "Data" / "eur_usd_trades_5m.duckdb"


def generate_duration_table(conn):
    query = """
        SELECT 
            CASE 
                WHEN t.duration_candel = 1 THEN '1 candle (5m)'
                WHEN t.duration_candel = 2 THEN '2 candles (10m)'
                WHEN t.duration_candel = 3 THEN '3 candles (15m)'
                WHEN t.duration_candel = 4 THEN '4 candles (20m)'
                WHEN t.duration_candel = 5 THEN '5 candles (25m)'
                WHEN t.duration_candel BETWEEN 6 AND 10 THEN '6-10 candles (30-50m)'
                WHEN t.duration_candel BETWEEN 11 AND 15 THEN '11-15 candles (55-75m)'
                WHEN t.duration_candel BETWEEN 16 AND 30 THEN '16-30 candles (80-150m)'
                WHEN t.duration_candel BETWEEN 31 AND 60 THEN '31-60 candles (155-300m)'
                ELSE '60+ candles (> 300m)'
            END AS duration_bracket,
            COUNT(*) AS "number of trades",
            COUNT(CASE WHEN t.pnl > 0 THEN 1 END) AS win,
            COUNT(CASE WHEN t.pnl <= 0 THEN 1 END) AS loss,
            ROUND(COUNT(CASE WHEN t.pnl > 0 THEN 1 END) * 100.0 / COUNT(*), 2) AS "win%",
            SUM(t.pnl) AS raw_pnl,
            MIN(t.duration_candel) AS min_dur
        FROM trades_view t
        JOIN "3RedCanels_view" f ON t.uid = f.uid
        WHERE f."3Red_candles" = False
        GROUP BY duration_bracket
        ORDER BY min_dur ASC;
    """
    df_dur = conn.execute(query).df()
    if df_dur.empty:
        print("No matching trades found.")
        return

    df_dur["ammount ( sum )"] = df_dur["raw_pnl"].apply(
        lambda x: f"+${x:,.2f}" if x >= 0 else f"-${abs(x):,.2f}"
    )

    display_df = df_dur[
        ["duration_bracket", "number of trades", "win", "loss", "win%", "ammount ( sum )"]
    ].copy()

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1000)

    print("\n" + "=" * 85)
    print(" DURATION BRACKET STRATEGY PERFORMANCE (Filtered: 3Red_candles = False)")
    print("=" * 85)
    print(display_df.to_string(index=False))
    print("=" * 85)

    tot_trades = display_df["number of trades"].sum()
    tot_win = display_df["win"].sum()
    tot_loss = display_df["loss"].sum()
    tot_win_pct = round(tot_win / tot_trades * 100.0, 2) if tot_trades > 0 else 0.0
    tot_pnl = df_dur["raw_pnl"].sum()
    tot_pnl_str = f"+${tot_pnl:,.2f}" if tot_pnl >= 0 else f"-${abs(tot_pnl):,.2f}"

    print(
        f" TOTALS : {tot_trades:,} Trades | {tot_win:,} Wins | {tot_loss:,} Losses | Win%: {tot_win_pct:.2f}% | Net PnL: {tot_pnl_str}"
    )
    print("=" * 85 + "\n")


def generate_weekly_table(conn):
    query = """
        SELECT 
            'W' || LPAD(CAST(WEEK(CAST(t.entry_time AS TIMESTAMP)) AS VARCHAR), 2, '0') AS week,
            COUNT(*) AS "number of trades",
            COUNT(CASE WHEN t.pnl > 0 THEN 1 END) AS win,
            COUNT(CASE WHEN t.pnl <= 0 THEN 1 END) AS loss,
            ROUND(COUNT(CASE WHEN t.pnl > 0 THEN 1 END) * 100.0 / COUNT(*), 2) AS "win%",
            SUM(t.pnl) AS raw_pnl
        FROM trades_view t
        JOIN "3RedCanels_view" f ON t.uid = f.uid
        WHERE f."3Red_candles" = False
        GROUP BY WEEK(CAST(t.entry_time AS TIMESTAMP))
        ORDER BY WEEK(CAST(t.entry_time AS TIMESTAMP)) ASC;
    """
    df_weekly = conn.execute(query).df()
    if df_weekly.empty:
        print("No matching trades found.")
        return

    df_weekly["ammount ( sum )"] = df_weekly["raw_pnl"].apply(
        lambda x: f"+${x:,.2f}" if x >= 0 else f"-${abs(x):,.2f}"
    )

    display_df = df_weekly[
        ["week", "number of trades", "win", "loss", "win%", "ammount ( sum )"]
    ].copy()

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1000)

    print("\n" + "=" * 85)
    print(" WEEKLY STRATEGY PERFORMANCE (Filtered: 3Red_candles = False)")
    print("=" * 85)
    print(display_df.to_string(index=False))
    print("=" * 85)

    tot_trades = display_df["number of trades"].sum()
    tot_win = display_df["win"].sum()
    tot_loss = display_df["loss"].sum()
    tot_win_pct = round(tot_win / tot_trades * 100.0, 2) if tot_trades > 0 else 0.0
    tot_pnl = df_weekly["raw_pnl"].sum()
    tot_pnl_str = f"+${tot_pnl:,.2f}" if tot_pnl >= 0 else f"-${abs(tot_pnl):,.2f}"

    print(
        f" TOTALS : {tot_trades:,} Trades | {tot_win:,} Wins | {tot_loss:,} Losses | Win%: {tot_win_pct:.2f}% | Net PnL: {tot_pnl_str}"
    )
    print("=" * 85 + "\n")


def generate_monthly_table(conn):
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

    print("\n" + "=" * 85)
    print(" MONTHLY STRATEGY PERFORMANCE (Filtered: 3Red_candles = False)")
    print("=" * 85)
    print(display_df.to_string(index=False))
    print("=" * 85)

    tot_trades = display_df["number of trades"].sum()
    tot_win = display_df["win"].sum()
    tot_loss = display_df["loss"].sum()
    tot_win_pct = round(tot_win / tot_trades * 100.0, 2) if tot_trades > 0 else 0.0
    tot_pnl = df_monthly["raw_pnl"].sum()
    tot_pnl_str = f"+${tot_pnl:,.2f}" if tot_pnl >= 0 else f"-${abs(tot_pnl):,.2f}"

    print(
        f" TOTALS : {tot_trades:,} Trades | {tot_win:,} Wins | {tot_loss:,} Losses | Win%: {tot_win_pct:.2f}% | Net PnL: {tot_pnl_str}"
    )
    print("=" * 85 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Filtered Strategy Loss Profiler (3Red_candles = False)")
    parser.add_argument("--duration-group", "--duration", "--dur", action="store_true", help="Display duration bracket breakdown")
    parser.add_argument("--weekly", "--wk", action="store_true", help="Display weekly performance breakdown")
    parser.add_argument("--monthly", "--month", "--mnth", action="store_true", help="Display monthly performance breakdown")

    args = parser.parse_args()

    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    conn = duckdb.connect(str(DB_PATH), read_only=True)

    if args.duration_group:
        generate_duration_table(conn)
    elif args.weekly:
        generate_weekly_table(conn)
    else:
        generate_monthly_table(conn)

    conn.close()


if __name__ == "__main__":
    main()
