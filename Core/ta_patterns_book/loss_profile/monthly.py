"""Monthly performance breakdown reporter."""

import os
import duckdb
import pandas as pd
from trade_book_charts import generate_trade_book
from trade_book_charts.db import _load_tradebook_deps, build_ohlcv_column_map

from .db import get_db_connection, get_outs_dir
from .formatter import print_dataframe


def generate_monthly_table(
    db_path: str,
    view_name: str = "trades",
    month_filter=None,
    show_loss_head: int = None,
    output_fmt: str = "text",
):
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

    tot_trades = display_df["number of trades"].sum()
    tot_win = display_df["win"].sum()
    tot_loss = display_df["loss"].sum()
    tot_win_pct = round(tot_win / tot_trades * 100.0, 2) if tot_trades > 0 else 0.0
    tot_pnl = df_monthly["raw_pnl"].sum()
    tot_pnl_str = f"+${tot_pnl:,.2f}" if tot_pnl >= 0 else f"-${abs(tot_pnl):,.2f}"

    title_text = f"MONTHLY STRATEGY PERFORMANCE BREAKDOWN (Month: {target_month or 'ALL'} | View: {view_name})"
    totals_str = f"TOTALS : {tot_trades:,} Trades | {tot_win:,} Wins | {tot_loss:,} Losses | Win%: {tot_win_pct:.2f}% | Net PnL: {tot_pnl_str}"

    print_dataframe(display_df, title_text=title_text, totals_str=totals_str, output_fmt=output_fmt)
