#!/usr/bin/env python3
"""
Notebooks/loss_profile.py — Strategy Loss Profiler, Monthly, Weekly & Duration Performance Reporter.

Usage:
    # Outputs raw count of total losing trades:
    uv run python Notebooks/loss_profile.py

    # Outputs monthly breakdown table:
    uv run python Notebooks/loss_profile.py --month

    # Outputs weekly breakdown table:
    uv run python Notebooks/loss_profile.py --weekly

    # Outputs duration-bracket breakdown table:
    uv run python Notebooks/loss_profile.py --duration-group
"""

import argparse
import glob
import os
import duckdb
import pandas as pd
import yaml
from trade_book_charts import generate_trade_book
from trade_book_charts.db import _load_tradebook_deps, build_ohlcv_column_map

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "Shared", "cnf.yaml")
DEFAULT_DUCKDB_PATH = os.path.join(PROJECT_ROOT, "Shared", "Data", "eur_usd_trades_5m.duckdb")

def get_outs_dir():
    return os.path.join(PROJECT_ROOT, "Shared", "OUTs", "png")

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}

def get_duckdb_path():
    config = load_config()
    rel_path = config.get("data", {}).get("duckdb_path", DEFAULT_DUCKDB_PATH)
    full_path = rel_path if os.path.isabs(rel_path) else os.path.normpath(os.path.join(PROJECT_ROOT, rel_path))
    if os.path.exists(full_path):
        return full_path

    search_dirs = [
        os.path.join(PROJECT_ROOT, "Shared", "Data"),
        os.path.join(PROJECT_ROOT, ".tmp")
    ]
    for d in search_dirs:
        duck_files = glob.glob(os.path.join(d, "*.duckdb"))
        if duck_files:
            return duck_files[0]

    return DEFAULT_DUCKDB_PATH

def generate_monthly_table(db_path: str, view_name: str = "trades", month_filter=None, show_loss_head: int = None):
    con = duckdb.connect(db_path, read_only=True)
    
    # Check if month_table exists in view_name
    cols_df = con.execute(f'SELECT * FROM "{view_name}" LIMIT 0;').df()
    has_month = "month_table" in cols_df.columns

    if has_month:
        months_df = con.execute(f'SELECT month_table, MIN(entry_time) as min_t FROM "{view_name}" GROUP BY month_table ORDER BY min_t ASC;').df()
        available_months = months_df['month_table'].tolist() if not months_df.empty else []
    else:
        available_months = []

    target_month = None
    if month_filter and month_filter != "all" and available_months:
        if str(month_filter).isdigit():
            idx = int(month_filter) - 1
            if 0 <= idx < len(available_months):
                target_month = available_months[idx]
        else:
            m_lower = str(month_filter).lower()
            for m in available_months:
                if m_lower in m.lower():
                    target_month = m
                    break

    month_clause = f"WHERE month_table = '{target_month}'" if target_month else ""

    if show_loss_head is not None:
        where_cond = f"WHERE pnl <= 0 AND month_table = '{target_month}'" if target_month else "WHERE pnl <= 0"
        query_loss = f'SELECT * FROM "{view_name}" {where_cond} ORDER BY entry_time ASC LIMIT {show_loss_head};'
        df_loss_head = con.execute(query_loss).df()
        con.close()

        title = f"LOSING TRADES HEAD (First {show_loss_head} Trades | Month: {target_month or 'ALL'} | View: {view_name})"
        print("\n" + "="*95)
        print(f" {title}")
        print("="*95)
        if df_loss_head.empty:
            print("No losing trades found.")
        else:
            cols_to_print = [c for c in ['month_table', 'trade_id', 'uid', 'entry_time', 'entry_price', 'sl_price', 'tp_price', 'exit_reason', 'pnl', 'duration_candel', '3_red_candels', '3Red_candles'] if c in df_loss_head.columns]
            pd.set_option("display.max_columns", None)
            pd.set_option("display.width", 1000)
            print(df_loss_head[cols_to_print].to_string(index=False))
        print("="*95)

        outs_dir = get_outs_dir()
        output_png = os.path.join(outs_dir, f"trade_book_loss_{target_month or 'all'}.png")
        print(f"\n-> Rendering Trade Playbook canvas for first {show_loss_head} losing trades...")
        deps = _load_tradebook_deps()
        ohlcv_cols = build_ohlcv_column_map("timestamp", "open", "high", "low", "close", "volume")
        
        sql_query = f'SELECT uid AS trade_id, entry_time, entry_price, sl_price, tp_price, exit_price, exit_reason, pnl FROM "{view_name}" {where_cond} ORDER BY entry_time ASC LIMIT {show_loss_head}'
        
        generate_trade_book(
            deps=deps,
            db_path=db_path,
            sql=sql_query,
            sql_params=[],
            ohlcv_table="ohlcv",
            ohlcv_cols=ohlcv_cols,
            output_file=output_png,
            pad_candles=15,
            exit_lookahead=288,
            hline_cols=None,
            row_capacity=350,
            strategy="optimal",
            max_charts=show_loss_head,
            run_name="loss_profile",
            dry_run=False
        )
        print("="*95 + "\n")
        return

    group_col = "month_table" if has_month else "'ALL'"
    query = f"""
        SELECT 
            {group_col} AS mnth,
            COUNT(*) AS "number of trades",
            COUNT(CASE WHEN pnl > 0 THEN 1 END) AS win,
            COUNT(CASE WHEN pnl <= 0 THEN 1 END) AS loss,
            ROUND(COUNT(CASE WHEN pnl > 0 THEN 1 END) * 100.0 / COUNT(*), 2) AS "win%",
            SUM(pnl) AS raw_pnl
        FROM "{view_name}"
        {month_clause}
        GROUP BY {group_col}
        ORDER BY MIN(entry_time) ASC;
    """
    df_monthly = con.execute(query).df()
    con.close()

    if df_monthly.empty:
        print("No trades found for monthly breakdown.")
        return

    df_monthly["ammount ( sum )"] = df_monthly["raw_pnl"].apply(
        lambda x: f"+${x:,.2f}" if x >= 0 else f"-${abs(x):,.2f}"
    )

    display_df = df_monthly[["mnth", "number of trades", "win", "loss", "win%", "ammount ( sum )"]].copy()

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1000)

    title = f"MONTHLY STRATEGY PERFORMANCE BREAKDOWN (Month: {target_month or 'ALL'} | View: {view_name})"
    print("\n" + "="*85)
    print(f" {title}")
    print("="*85)
    print(display_df.to_string(index=False))
    print("="*85)

    tot_trades = display_df["number of trades"].sum()
    tot_win = display_df["win"].sum()
    tot_loss = display_df["loss"].sum()
    tot_win_pct = round(tot_win / tot_trades * 100.0, 2) if tot_trades > 0 else 0.0
    tot_pnl = df_monthly["raw_pnl"].sum()
    tot_pnl_str = f"+${tot_pnl:,.2f}" if tot_pnl >= 0 else f"-${abs(tot_pnl):,.2f}"

    print(f" TOTALS : {tot_trades:,} Trades | {tot_win:,} Wins | {tot_loss:,} Losses | Win%: {tot_win_pct:.2f}% | Net PnL: {tot_pnl_str}")
    print("="*85 + "\n")

def generate_weekly_table(db_path: str, view_name: str = "trades"):
    con = duckdb.connect(db_path, read_only=True)
    query = f"""
        SELECT 
            'W' || LPAD(CAST(WEEK(CAST(entry_time AS TIMESTAMP)) AS VARCHAR), 2, '0') AS week,
            COUNT(*) AS "number of trades",
            COUNT(CASE WHEN pnl > 0 THEN 1 END) AS win,
            COUNT(CASE WHEN pnl <= 0 THEN 1 END) AS loss,
            ROUND(COUNT(CASE WHEN pnl > 0 THEN 1 END) * 100.0 / COUNT(*), 2) AS "win%",
            SUM(pnl) AS raw_pnl
        FROM "{view_name}"
        GROUP BY WEEK(CAST(entry_time AS TIMESTAMP))
        ORDER BY WEEK(CAST(entry_time AS TIMESTAMP)) ASC;
    """
    df_weekly = con.execute(query).df()
    con.close()

    if df_weekly.empty:
        print("No trades found for weekly breakdown.")
        return

    df_weekly["ammount ( sum )"] = df_weekly["raw_pnl"].apply(
        lambda x: f"+${x:,.2f}" if x >= 0 else f"-${abs(x):,.2f}"
    )

    display_df = df_weekly[["week", "number of trades", "win", "loss", "win%", "ammount ( sum )"]].copy()

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1000)

    print("\n" + "="*85)
    print(" WEEKLY STRATEGY PERFORMANCE BREAKDOWN")
    print("="*85)
    print(display_df.to_string(index=False))
    print("="*85)

    tot_trades = display_df["number of trades"].sum()
    tot_win = display_df["win"].sum()
    tot_loss = display_df["loss"].sum()
    tot_win_pct = round(tot_win / tot_trades * 100.0, 2) if tot_trades > 0 else 0.0
    tot_pnl = df_weekly["raw_pnl"].sum()
    tot_pnl_str = f"+${tot_pnl:,.2f}" if tot_pnl >= 0 else f"-${abs(tot_pnl):,.2f}"

    print(f" TOTALS : {tot_trades:,} Trades | {tot_win:,} Wins | {tot_loss:,} Losses | Win%: {tot_win_pct:.2f}% | Net PnL: {tot_pnl_str}")
    print("="*85 + "\n")

def generate_duration_table(db_path: str, view_name: str = "trades", duration_till: int = None, losses_only: bool = False):
    con = duckdb.connect(db_path, read_only=True)
    
    where_extra = "WHERE pnl <= 0" if losses_only else ""

    query = f"""
        SELECT 
            CASE 
                WHEN duration_candel = 1 THEN '1 candle (5m)'
                WHEN duration_candel = 2 THEN '2 candles (10m)'
                WHEN duration_candel = 3 THEN '3 candles (15m)'
                WHEN duration_candel = 4 THEN '4 candles (20m)'
                WHEN duration_candel = 5 THEN '5 candles (25m)'
                WHEN duration_candel BETWEEN 6 AND 10 THEN '6-10 candles (30-50m)'
                WHEN duration_candel BETWEEN 11 AND 15 THEN '11-15 candles (55-75m)'
                WHEN duration_candel BETWEEN 16 AND 30 THEN '16-30 candles (80-150m)'
                WHEN duration_candel BETWEEN 31 AND 60 THEN '31-60 candles (155-300m)'
                ELSE '60+ candles (> 300m)'
            END AS duration_bracket,
            COUNT(*) AS "number of trades",
            COUNT(CASE WHEN pnl > 0 THEN 1 END) AS win,
            COUNT(CASE WHEN pnl <= 0 THEN 1 END) AS loss,
            ROUND(COUNT(CASE WHEN pnl > 0 THEN 1 END) * 100.0 / COUNT(*), 2) AS "win%",
            SUM(pnl) AS raw_pnl,
            MIN(duration_candel) AS min_dur,
            MAX(duration_candel) AS max_dur
        FROM "{view_name}"
        {where_extra}
        GROUP BY duration_bracket
        ORDER BY min_dur ASC;
    """
    df_dur = con.execute(query).df()
    con.close()

    if df_dur.empty:
        print("No trades found for duration breakdown.")
        return

    # Calculate overall full totals before any filtering
    tot_trades_full = df_dur["number of trades"].sum()
    tot_win_full = df_dur["win"].sum()
    tot_loss_full = df_dur["loss"].sum()
    tot_win_pct_full = round(tot_win_full / tot_trades_full * 100.0, 2) if tot_trades_full > 0 else 0.0
    tot_pnl_full = df_dur["raw_pnl"].sum()
    tot_pnl_str_full = f"+${tot_pnl_full:,.2f}" if tot_pnl_full >= 0 else f"-${abs(tot_pnl_full):,.2f}"

    # Filter rows if duration_till is specified
    if duration_till is not None:
        df_dur = df_dur[df_dur["min_dur"] <= duration_till].copy()

    df_dur["ammount ( sum )"] = df_dur["raw_pnl"].apply(
        lambda x: f"+${x:,.2f}" if x >= 0 else f"-${abs(x):,.2f}"
    )

    display_df = df_dur[["duration_bracket", "number of trades", "win", "loss", "win%", "ammount ( sum )"]].copy()

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1000)

    title_suffix = ""
    if losses_only:
        title_suffix += " [LOSSES ONLY]"
    if duration_till is not None:
        title_suffix += f" (TILL DURATION <= {duration_till})"
        
    print("\n" + "="*85)
    print(f" DURATION BRACKET STRATEGY PERFORMANCE BREAKDOWN{title_suffix}")
    print("="*85)
    print(display_df.to_string(index=False))
    print("="*85)

    if duration_till is not None:
        tot_trades_till = display_df["number of trades"].sum()
        tot_win_till = display_df["win"].sum()
        tot_loss_till = display_df["loss"].sum()
        tot_win_pct_till = round(tot_win_till / tot_trades_till * 100.0, 2) if tot_trades_till > 0 else 0.0
        tot_pnl_till = df_dur["raw_pnl"].sum()
        tot_pnl_str_till = f"+${tot_pnl_till:,.2f}" if tot_pnl_till >= 0 else f"-${abs(tot_pnl_till):,.2f}"

        print(f" TOTALS (FULL)    : {tot_trades_full:,} Trades | {tot_win_full:,} Wins | {tot_loss_full:,} Losses | Win%: {tot_win_pct_full:.2f}% | Net PnL: {tot_pnl_str_full}")
        print(f" TOTALS (TILL <={duration_till}) : {tot_trades_till:,} Trades | {tot_win_till:,} Wins | {tot_loss_till:,} Losses | Win%: {tot_win_pct_till:.2f}% | Net PnL: {tot_pnl_str_till}")
    else:
        print(f" TOTALS : {tot_trades_full:,} Trades | {tot_win_full:,} Wins | {tot_loss_full:,} Losses | Win%: {tot_win_pct_full:.2f}% | Net PnL: {tot_pnl_str_full}")
    print("="*85 + "\n")

def generate_loss_profile(db_path: str, view_name: str = "trades"):
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DuckDB database file not found at '{db_path}'")

    con = duckdb.connect(db_path, read_only=True)
    count = con.execute(f'SELECT COUNT(*) FROM "{view_name}" WHERE pnl <= 0;').fetchone()[0]
    con.close()

    print(f"Total Losing Trades: {count}")

def main():
    parser = argparse.ArgumentParser(description="Strategy Loss Profiler, Monthly, Weekly & Duration Performance Reporter")
    parser.add_argument("--db", type=str, default=None, help="Path to DuckDB database file")
    parser.add_argument("--view", type=str, default="trades", help="Source view/table (default: trades)")
    parser.add_argument("--monthly", "--month", "--mnth", nargs="?", const="all", type=str, default=None, help="Display monthly performance breakdown")
    parser.add_argument("--weekly", "--wk", action="store_true", help="Display weekly performance breakdown table")
    parser.add_argument("--duration-group", "--duration", "--dur", action="store_true", help="Display duration bracket performance breakdown table")
    parser.add_argument("--duration-till", type=int, default=None, help="Limit duration table output up to specified candle duration (e.g. 5)")
    parser.add_argument("--losses-only", action="store_true", help="Filter duration breakdown to show losses only (pnl <= 0)")
    parser.add_argument("--loss", nargs="?", const=12, type=int, default=None, help="Show head of losing trades table & render Trade Playbook (default limit: 12)")

    args = parser.parse_args()
    db_path = args.db if args.db else get_duckdb_path()

    if args.duration_group or args.duration_till is not None or args.losses_only:
        generate_duration_table(db_path, view_name=args.view, duration_till=args.duration_till, losses_only=args.losses_only)
    elif args.weekly:
        generate_weekly_table(db_path, view_name=args.view)
    elif args.monthly is not None or args.loss is not None:
        generate_monthly_table(db_path, view_name=args.view, month_filter=args.monthly, show_loss_head=args.loss)
    else:
        generate_loss_profile(db_path, view_name=args.view)

if __name__ == "__main__":
    main()
