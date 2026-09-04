"""Reporters module for monthly, weekly, duration, loss group, and distribution breakdowns."""

import os
import duckdb
import pandas as pd
from trade_book_charts import generate_trade_book
from trade_book_charts.db import _load_tradebook_deps, build_ohlcv_column_map

from .db import get_db_connection, get_outs_dir


def generate_monthly_table(db_path: str, view_name: str = "trades", month_filter=None, show_loss_head: int = None):
    con = get_db_connection(db_path, read_only=True)
    
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
        
        id_col = "trade_id" if "trade_id" in df_loss_head.columns else "uid AS trade_id"
        sql_query = f'SELECT {id_col}, entry_time, entry_price, sl_price, tp_price, exit_price, exit_reason, pnl FROM "{view_name}" {where_cond} ORDER BY entry_time ASC LIMIT {show_loss_head}'
        
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
    con = get_db_connection(db_path, read_only=True)
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
    con = get_db_connection(db_path, read_only=True)
    
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

    tot_trades_full = df_dur["number of trades"].sum()
    tot_win_full = df_dur["win"].sum()
    tot_loss_full = df_dur["loss"].sum()
    tot_win_pct_full = round(tot_win_full / tot_trades_full * 100.0, 2) if tot_trades_full > 0 else 0.0
    tot_pnl_full = df_dur["raw_pnl"].sum()
    tot_pnl_str_full = f"+${tot_pnl_full:,.2f}" if tot_pnl_full >= 0 else f"-${abs(tot_pnl_full):,.2f}"

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


def generate_loss_group_table(db_path: str, view_name: str = "trades"):
    con = get_db_connection(db_path, read_only=True)
    query = f"""
        SELECT 
            CASE 
                WHEN pnl > 0 THEN '01. Wins (PnL > $0)'
                WHEN ABS(pnl) <= 50 THEN '02. Small Loss ($0 - $50)'
                WHEN ABS(pnl) > 50 AND ABS(pnl) <= 100 THEN '03. Medium Loss ($50 - $100)'
                WHEN ABS(pnl) > 100 AND ABS(pnl) <= 200 THEN '04. Large Loss ($100 - $200)'
                ELSE '05. Severe Loss (> $200)'
            END AS loss_bracket,
            COUNT(*) AS "number of trades",
            COUNT(CASE WHEN pnl > 0 THEN 1 END) AS win,
            COUNT(CASE WHEN pnl <= 0 THEN 1 END) AS loss,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM "{view_name}"), 2) AS "pct_of_total_trades%",
            SUM(pnl) AS raw_pnl,
            MIN(CASE 
                WHEN pnl > 0 THEN 1
                WHEN ABS(pnl) <= 50 THEN 2
                WHEN ABS(pnl) > 50 AND ABS(pnl) <= 100 THEN 3
                WHEN ABS(pnl) > 100 AND ABS(pnl) <= 200 THEN 4
                ELSE 5
            END) AS sort_order
        FROM "{view_name}"
        GROUP BY loss_bracket
        ORDER BY sort_order ASC;
    """
    df_loss_grp = con.execute(query).df()
    con.close()

    if df_loss_grp.empty:
        print("No trades found for loss grouping.")
        return

    df_loss_grp["ammount ( sum )"] = df_loss_grp["raw_pnl"].apply(
        lambda x: f"+${x:,.2f}" if x >= 0 else f"-${abs(x):,.2f}"
    )

    display_df = df_loss_grp[["loss_bracket", "number of trades", "win", "loss", "pct_of_total_trades%", "ammount ( sum )"]].copy()

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1000)

    print("\n" + "="*85)
    print(" LOSS AMOUNT BRACKET STRATEGY PERFORMANCE BREAKDOWN")
    print("="*85)
    print(display_df.to_string(index=False))
    print("="*85)

    tot_trades = display_df["number of trades"].sum()
    tot_win = display_df["win"].sum()
    tot_loss = display_df["loss"].sum()
    tot_win_pct = round(tot_win / tot_trades * 100.0, 2) if tot_trades > 0 else 0.0
    tot_pnl = df_loss_grp["raw_pnl"].sum()
    tot_pnl_str = f"+${tot_pnl:,.2f}" if tot_pnl >= 0 else f"-${abs(tot_pnl):,.2f}"

    print(f" TOTALS : {tot_trades:,} Trades | {tot_win:,} Wins | {tot_loss:,} Losses | Win%: {tot_win_pct:.2f}% | Net PnL: {tot_pnl_str}")
    print("="*85 + "\n")


def generate_distribution_table(
    db_path: str,
    view_name: str = "trades",
    pattern_col: str = "entry_1",
    losses_only: bool = False,
    pattern_filter: str = None,
    output_fmt: str = "text",
):
    con = get_db_connection(db_path, read_only=True)
    
    cols_df = con.execute(f'SELECT * FROM "{view_name}" LIMIT 0;').df()
    has_pattern_col = pattern_col in cols_df.columns

    where_clauses = []
    if losses_only:
        where_clauses.append("t.pnl <= 0")
    if pattern_filter:
        filter_expr = pattern_filter.strip()
        if "=" in filter_expr and not ("'" in filter_expr or '"' in filter_expr):
            col_part, val_part = filter_expr.split("=", 1)
            filter_expr = f"{col_part.strip()} = '{val_part.strip()}'"
        
        if not filter_expr.startswith("p.") and not filter_expr.startswith("t."):
            where_clauses.append(f"p.{filter_expr}")
        else:
            where_clauses.append(filter_expr)

    where_str = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    if has_pattern_col:
        query = f"""
            SELECT 
                "{pattern_col}" AS pattern,
                COUNT(*) AS "number of trades",
                COUNT(CASE WHEN pnl > 0 THEN 1 END) AS win,
                COUNT(CASE WHEN pnl <= 0 THEN 1 END) AS loss,
                ROUND(COUNT(CASE WHEN pnl > 0 THEN 1 END) * 100.0 / COUNT(*), 2) AS "win%",
                SUM(pnl) AS raw_pnl
            FROM "{view_name}" t
            {where_str}
            GROUP BY "{pattern_col}"
            ORDER BY "number of trades" DESC, "win%" DESC;
        """
    else:
        query = f"""
            SELECT 
                p."{pattern_col}" AS pattern,
                COUNT(*) AS "number of trades",
                COUNT(CASE WHEN t.pnl > 0 THEN 1 END) AS win,
                COUNT(CASE WHEN t.pnl <= 0 THEN 1 END) AS loss,
                ROUND(COUNT(CASE WHEN t.pnl > 0 THEN 1 END) * 100.0 / COUNT(*), 2) AS "win%",
                SUM(t.pnl) AS raw_pnl
            FROM "{view_name}" t
            JOIN "3candels_patterns" p ON t.trade_id = p.trade_id
            {where_str}
            GROUP BY p."{pattern_col}"
            ORDER BY "number of trades" DESC, "win%" DESC;
        """
    
    df_dist = con.execute(query).df()
    con.close()

    if df_dist.empty:
        print(f"No trades found for pattern column '{pattern_col}' with filter '{pattern_filter}'.")
        return

    df_dist["ammount ( sum )"] = df_dist["raw_pnl"].apply(
        lambda x: f"+${x:,.2f}" if x >= 0 else f"-${abs(x):,.2f}"
    )

    display_df = df_dist[["pattern", "number of trades", "win", "loss", "win%", "ammount ( sum )"]].copy()

    tot_trades = display_df["number of trades"].sum()
    tot_win = display_df["win"].sum()
    tot_loss = display_df["loss"].sum()
    tot_win_pct = round(tot_win / tot_trades * 100.0, 2) if tot_trades > 0 else 0.0
    tot_pnl = df_dist["raw_pnl"].sum()
    tot_pnl_str = f"+${tot_pnl:,.2f}" if tot_pnl >= 0 else f"-${abs(tot_pnl):,.2f}"

    title_suffix = ""
    if losses_only:
        title_suffix += " [LOSSES ONLY]"
    if pattern_filter:
        title_suffix += f" [FILTER: {pattern_filter}]"

    title_text = f"PATTERN PERFORMANCE DISTRIBUTION FOR '{pattern_col}'{title_suffix} (View: {view_name})"

    if output_fmt == "markdown":
        print(f"### {title_text}\n")
        print(display_df.to_markdown(index=False))
        print(f"\n**TOTALS**: `{tot_trades:,}` Trades | `{tot_win:,}` Wins | `{tot_loss:,}` Losses | **Win%**: `{tot_win_pct:.2f}%` | **Net PnL**: `{tot_pnl_str}`\n")
    else:
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 1000)
        pd.set_option("display.max_rows", 200)

        print("\n" + "="*85)
        print(f" {title_text}")
        print("="*85)
        print(display_df.to_string(index=False))
        print("="*85)
        print(f" TOTALS : {tot_trades:,} Trades | {tot_win:,} Wins | {tot_loss:,} Losses | Win%: {tot_win_pct:.2f}% | Net PnL: {tot_pnl_str}")
        print("="*85 + "\n")


def generate_loss_profile(db_path: str, view_name: str = "trades"):
    con = get_db_connection(db_path, read_only=True)
    count = con.execute(f'SELECT COUNT(*) FROM "{view_name}" WHERE pnl <= 0;').fetchone()[0]
    con.close()
    print(f"Total Losing Trades: {count}")
