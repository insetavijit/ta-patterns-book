"""Loss amount bracket performance breakdown reporter."""

import duckdb
import pandas as pd

from .db import get_db_connection
from .formatter import print_dataframe


def generate_loss_group_table(
    db_path: str,
    view_name: str = "trades",
    pattern_filter: str = None,
    output_fmt: str = "text",
):
    con = get_db_connection(db_path, read_only=True)

    where_clauses = []
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
                WHEN t.pnl > 0 THEN '01. Wins (PnL > $0)'
                WHEN ABS(t.pnl) <= 50 THEN '02. Small Loss ($0 - $50)'
                WHEN ABS(t.pnl) > 50 AND ABS(t.pnl) <= 100 THEN '03. Medium Loss ($50 - $100)'
                WHEN ABS(t.pnl) > 100 AND ABS(t.pnl) <= 200 THEN '04. Large Loss ($100 - $200)'
                ELSE '05. Severe Loss (> $200)'
            END AS loss_bracket,
            COUNT(*) AS "number of trades",
            COUNT(CASE WHEN t.pnl > 0 THEN 1 END) AS win,
            COUNT(CASE WHEN t.pnl <= 0 THEN 1 END) AS loss,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM {from_clause} {where_str}), 2) AS "pct_of_total_trades%",
            SUM(t.pnl) AS raw_pnl,
            MIN(CASE 
                WHEN t.pnl > 0 THEN 1
                WHEN ABS(t.pnl) <= 50 THEN 2
                WHEN ABS(t.pnl) > 50 AND ABS(t.pnl) <= 100 THEN 3
                WHEN ABS(t.pnl) > 100 AND ABS(t.pnl) <= 200 THEN 4
                ELSE 5
            END) AS sort_order
        FROM {from_clause}
        {where_str}
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

    tot_trades = display_df["number of trades"].sum()
    tot_win = display_df["win"].sum()
    tot_loss = display_df["loss"].sum()
    tot_win_pct = round(tot_win / tot_trades * 100.0, 2) if tot_trades > 0 else 0.0
    tot_pnl = df_loss_grp["raw_pnl"].sum()
    tot_pnl_str = f"+${tot_pnl:,.2f}" if tot_pnl >= 0 else f"-${abs(tot_pnl):,.2f}"

    title_suffix = f" [FILTER: {pattern_filter}]" if pattern_filter else ""
    title_text = f"LOSS AMOUNT BRACKET STRATEGY PERFORMANCE BREAKDOWN{title_suffix}"
    totals_str = f"TOTALS : {tot_trades:,} Trades | {tot_win:,} Wins | {tot_loss:,} Losses | Win%: {tot_win_pct:.2f}% | Net PnL: {tot_pnl_str}"

    print_dataframe(display_df, title_text=title_text, totals_str=totals_str, output_fmt=output_fmt)
