"""Weekly performance breakdown reporter."""

import duckdb
import pandas as pd

from .db import get_db_connection
from .formatter import print_dataframe


def generate_weekly_table(db_path: str, view_name: str = "trades", output_fmt: str = "text"):
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

    tot_trades = display_df["number of trades"].sum()
    tot_win = display_df["win"].sum()
    tot_loss = display_df["loss"].sum()
    tot_win_pct = round(tot_win / tot_trades * 100.0, 2) if tot_trades > 0 else 0.0
    tot_pnl = df_weekly["raw_pnl"].sum()
    tot_pnl_str = f"+${tot_pnl:,.2f}" if tot_pnl >= 0 else f"-${abs(tot_pnl):,.2f}"

    title_text = "WEEKLY STRATEGY PERFORMANCE BREAKDOWN"
    totals_str = f"TOTALS : {tot_trades:,} Trades | {tot_win:,} Wins | {tot_loss:,} Losses | Win%: {tot_win_pct:.2f}% | Net PnL: {tot_pnl_str}"

    print_dataframe(display_df, title_text=title_text, totals_str=totals_str, output_fmt=output_fmt)
