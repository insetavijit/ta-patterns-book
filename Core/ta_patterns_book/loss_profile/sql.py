"""SQL Query Builders for Loss Profiler reporting."""


def build_monthly_query(view_name: str = "trades", target_month: str = None, has_month_col: bool = True) -> str:
    month_clause = f"WHERE month_table = '{target_month}'" if target_month else ""
    group_col = "month_table" if has_month_col else "'ALL'"
    return f"""
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


def build_weekly_query(view_name: str = "trades") -> str:
    return f"""
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


def build_duration_query(
    view_name: str = "trades",
    losses_only: bool = False,
    pattern_filter: str = None,
) -> str:
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

    return f"""
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


def build_loss_group_query(
    view_name: str = "trades",
    pattern_filter: str = None,
) -> str:
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

    return f"""
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


def build_projected_rr_group_query(
    view_name: str = "trades",
    losses_only: bool = False,
    pattern_filter: str = None,
) -> str:
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
    from_clause = f'"{view_name}" t JOIN "3candels_patterns" p ON t.uid = p.trade_number JOIN projected_rr pr ON t.uid = pr.uid' if pattern_filter else f'"{view_name}" t JOIN projected_rr pr ON t.uid = pr.uid'

    return f"""
        SELECT 
            CASE 
                WHEN pr.projected_rr < 2.0 THEN '01. < 2.0 RR'
                WHEN pr.projected_rr >= 2.0 AND pr.projected_rr < 3.0 THEN '02. 2.0 - 3.0 RR'
                WHEN pr.projected_rr >= 3.0 AND pr.projected_rr < 4.0 THEN '03. 3.0 - 4.0 RR'
                WHEN pr.projected_rr >= 4.0 AND pr.projected_rr < 5.0 THEN '04. 4.0 - 5.0 RR'
                ELSE '05. >= 5.0 RR'
            END AS rr_bracket,
            COUNT(*) AS "number of trades",
            COUNT(CASE WHEN t.pnl > 0 THEN 1 END) AS win,
            COUNT(CASE WHEN t.pnl <= 0 THEN 1 END) AS loss,
            ROUND(COUNT(CASE WHEN t.pnl > 0 THEN 1 END) * 100.0 / COUNT(*), 2) AS "win%",
            SUM(t.pnl) AS raw_pnl,
            MIN(CASE 
                WHEN pr.projected_rr < 2.0 THEN 1
                WHEN pr.projected_rr >= 2.0 AND pr.projected_rr < 3.0 THEN 2
                WHEN pr.projected_rr >= 3.0 AND pr.projected_rr < 4.0 THEN 3
                WHEN pr.projected_rr >= 4.0 AND pr.projected_rr < 5.0 THEN 4
                ELSE 5
            END) AS sort_order
        FROM {from_clause}
        {where_str}
        GROUP BY rr_bracket
        ORDER BY sort_order ASC;
    """


def build_distribution_query(
    view_name: str = "trades",
    pattern_col: str = "entry_1",
    losses_only: bool = False,
    pattern_filter: str = None,
    has_pattern_col: bool = False,
) -> str:
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
        return f"""
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
        return f"""
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


def build_head_query(
    view_name: str = "trades",
    limit: int = 10,
    pattern_filter: str = None,
    duration: int = None,
    duration_till: int = None,
    losses_only: bool = False,
) -> str:
    where_clauses = []
    if losses_only:
        where_clauses.append("t.pnl <= 0")
    if duration is not None:
        where_clauses.append(f"t.duration_candel = {duration}")
    if duration_till is not None:
        where_clauses.append(f"t.duration_candel <= {duration_till}")
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

    pattern_cols = ", p.entry_1, p.entry_2, p.entry_3, p.entry_4" if pattern_filter else ""

    return f"""
        SELECT 
            t.uid AS trade_number,
            t.entry_time,
            t.entry_price,
            t.sl_price,
            t.tp_price,
            t.exit_reason,
            t.pnl,
            t.duration_candel
            {pattern_cols}
        FROM {from_clause}
        {where_str}
        ORDER BY t.entry_time ASC
        LIMIT {limit};
    """
