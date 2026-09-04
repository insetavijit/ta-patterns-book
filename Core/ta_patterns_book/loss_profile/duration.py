"""Duration bracket performance breakdown reporter."""

import duckdb
import pandas as pd

from .db import get_db_connection
from .formatter import print_dataframe


def generate_duration_table(
    db_path: str,
    view_name: str = "trades",
    duration_till: int = None,
    losses_only: bool = False,
    pattern_filter: str = None,
    output_fmt: str = "text",
):
    con = get_db_connection(db_path, read_only=True)
    
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

    from_clause = f'"{view_name}" t JOIN "3candels_patterns" p ON t.uid = p.trade_number' if pattern_filter else f'"{view_name}" t'

    query = f"""
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
            MIN(t.duration_candel) AS min_dur,
            MAX(t.duration_candel) AS max_dur
        FROM {from_clause}
        {where_str}
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

    title_suffix = ""
    if losses_only:
        title_suffix += " [LOSSES ONLY]"
    if pattern_filter:
        title_suffix += f" [FILTER: {pattern_filter}]"
    if duration_till is not None:
        title_suffix += f" (TILL DURATION <= {duration_till})"

    title_text = f"DURATION BRACKET STRATEGY PERFORMANCE BREAKDOWN{title_suffix}"

    if duration_till is not None:
        tot_trades_till = display_df["number of trades"].sum()
        tot_win_till = display_df["win"].sum()
        tot_loss_till = display_df["loss"].sum()
        tot_win_pct_till = round(tot_win_till / tot_trades_till * 100.0, 2) if tot_trades_till > 0 else 0.0
        tot_pnl_till = df_dur["raw_pnl"].sum()
        tot_pnl_str_till = f"+${tot_pnl_till:,.2f}" if tot_pnl_till >= 0 else f"-${abs(tot_pnl_till):,.2f}"

        totals_str = (
            f"TOTALS (FULL)    : {tot_trades_full:,} Trades | {tot_win_full:,} Wins | {tot_loss_full:,} Losses | Win%: {tot_win_pct_full:.2f}% | Net PnL: {tot_pnl_str_full}\n"
            f"TOTALS (TILL <={duration_till}) : {tot_trades_till:,} Trades | {tot_win_till:,} Wins | {tot_loss_till:,} Losses | Win%: {tot_win_pct_till:.2f}% | Net PnL: {tot_pnl_str_till}"
        )
    else:
        totals_str = f"TOTALS : {tot_trades_full:,} Trades | {tot_win_full:,} Wins | {tot_loss_full:,} Losses | Win%: {tot_win_pct_full:.2f}% | Net PnL: {tot_pnl_str_full}"

    print_dataframe(display_df, title_text=title_text, totals_str=totals_str, output_fmt=output_fmt)
