"""Pattern performance distribution reporter."""

import duckdb
import pandas as pd

from .db import get_db_connection
from .formatter import print_dataframe


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
            JOIN "3candels_patterns" p ON t.uid = p.trade_number
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
    totals_str = f"TOTALS : {tot_trades:,} Trades | {tot_win:,} Wins | {tot_loss:,} Losses | Win%: {tot_win_pct:.2f}% | Net PnL: {tot_pnl_str}"

    print_dataframe(display_df, title_text=title_text, totals_str=totals_str, output_fmt=output_fmt)


def generate_loss_profile(db_path: str, view_name: str = "trades"):
    con = get_db_connection(db_path, read_only=True)
    count = con.execute(f'SELECT COUNT(*) FROM "{view_name}" WHERE pnl <= 0;').fetchone()[0]
    con.close()
    print(f"Total Losing Trades: {count}")
