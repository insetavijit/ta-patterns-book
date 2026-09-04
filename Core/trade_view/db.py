"""DuckDB Data Access Layer & OHLCV Trade Window Resolvers."""

from __future__ import annotations

import re

from .models import TRADE_REQUIRED_COLUMNS, TradebookInputError, _IDENTIFIER_RE, _TradebookDeps


def _load_tradebook_deps() -> _TradebookDeps:
    """First-stage lazy import: duckdb + pandas only."""
    import duckdb
    import pandas as pd

    return _TradebookDeps(duckdb, pd)


def _validate_identifier(name: str, flag_name: str) -> str:
    """Validates plain SQL identifier (letters, digits, underscore)."""
    if not name or not _IDENTIFIER_RE.match(name):
        raise TradebookInputError(
            f"{flag_name} must be a plain SQL identifier (letters, digits, "
            f"underscore, not starting with a digit); got: {name!r}"
        )
    return name


def _validate_select_sql(sql: str) -> str:
    """Validates that query starts with SELECT or WITH...SELECT."""
    if not sql or not sql.strip():
        raise TradebookInputError("--sql (or --sql-file) must not be empty")
    m = re.match(r"^\s*(?:--[^\n]*\n\s*)*(\w+)", sql)
    first_word = m.group(1).lower() if m else ""
    if first_word not in ("select", "with"):
        raise TradebookInputError(
            "--sql must be a read-only SELECT (or WITH ... SELECT) query, "
            f"got a query starting with: {first_word!r}"
        )
    return sql


def build_ohlcv_column_map(
    time_col: str,
    open_col: str,
    high_col: str,
    low_col: str,
    close_col: str,
    volume_col: str | None,
) -> dict:
    """Validates and returns {role: actual_column_name} map."""
    mapping = {
        "time": time_col,
        "open": open_col,
        "high": high_col,
        "low": low_col,
        "close": close_col,
    }
    if volume_col:
        mapping["volume"] = volume_col
    for role, col in mapping.items():
        _validate_identifier(col, f"--ohlcv-{role}-col")
    return mapping


def _ohlcv_select_clause(ohlcv_cols: dict) -> str:
    """Builds SELECT clause mapping custom column names to Open/High/Low/Close/Volume."""
    display_names = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    parts = [f'"{ohlcv_cols["time"]}" AS "Time"']
    for role, disp in display_names.items():
        if role in ohlcv_cols:
            parts.append(f'"{ohlcv_cols[role]}" AS "{disp}"')
    return ", ".join(parts)


def _check_table_exists(deps: _TradebookDeps, con, table: str) -> None:
    """Verifies table/view existence in DuckDB."""
    try:
        con.execute(f'SELECT 1 FROM "{table}" LIMIT 0')
    except deps.duckdb.Error as e:
        raise TradebookInputError(
            f"--ohlcv-table {table!r} could not be queried -- does it exist "
            f"in this database (as a table or view)? Underlying error: {e}"
        )


def normalize_trade_columns(df):
    """Lowercases column names and validates presence of required columns."""
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in TRADE_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise TradebookInputError(
            f"--sql result is missing required column(s): {missing}. "
            "Alias your columns to satisfy the contract, e.g. "
            "'SELECT ts AS entry_time, px AS entry_price, ... FROM ...'. "
            f"Columns returned: {list(df.columns)}"
        )
    return df


def _to_naive_ts(pd, value):
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts


def _concat_window(deps: _TradebookDeps, before, main, after):
    """Assembles final chart window from before, main, after slices."""
    pd = deps.pd
    parts = [d for d in (before, main, after) if d is not None and not d.empty]
    if not parts:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close"])
    df = pd.concat(parts, ignore_index=True).drop_duplicates(subset="Time").sort_values("Time")
    df["Time"] = pd.to_datetime(df["Time"])
    df = df.set_index("Time")
    return df


def fetch_trade_window(
    deps: _TradebookDeps,
    con,
    ohlcv_table: str,
    ohlcv_cols: dict,
    entry_dt,
    exit_dt,
    pad_candles: int,
):
    """Fetches candle window when exit timestamp and price are explicitly provided."""
    pd = deps.pd
    select_clause = _ohlcv_select_clause(ohlcv_cols)
    time_col = ohlcv_cols["time"]

    q_before = (
        f'SELECT {select_clause} FROM "{ohlcv_table}" '
        f'WHERE "{time_col}" < ? ORDER BY "{time_col}" DESC LIMIT ?'
    )
    before = con.execute(q_before, [entry_dt, pad_candles]).df().iloc[::-1]

    q_main = (
        f'SELECT {select_clause} FROM "{ohlcv_table}" '
        f'WHERE "{time_col}" >= ? AND "{time_col}" <= ? ORDER BY "{time_col}" ASC'
    )
    main = con.execute(q_main, [entry_dt, exit_dt]).df()

    q_after = (
        f'SELECT {select_clause} FROM "{ohlcv_table}" '
        f'WHERE "{time_col}" > ? ORDER BY "{time_col}" ASC LIMIT ?'
    )
    after = con.execute(q_after, [exit_dt, pad_candles]).df()

    return _concat_window(deps, before, main, after)


def resolve_exit_and_window(
    deps: _TradebookDeps,
    con,
    ohlcv_table: str,
    ohlcv_cols: dict,
    entry_dt,
    entry_p: float,
    sl_p: float | None,
    tp_p: float | None,
    pad_candles: int,
    exit_lookahead: int,
):
    """Performs forward SL/TP scan and extracts the trade candle window in 2 queries."""
    pd = deps.pd
    select_clause = _ohlcv_select_clause(ohlcv_cols)
    time_col = ohlcv_cols["time"]

    q_before = (
        f'SELECT {select_clause} FROM "{ohlcv_table}" '
        f'WHERE "{time_col}" < ? ORDER BY "{time_col}" DESC LIMIT ?'
    )
    before = con.execute(q_before, [entry_dt, pad_candles]).df().iloc[::-1]

    forward_limit = exit_lookahead + pad_candles + 1
    q_forward = (
        f'SELECT {select_clause} FROM "{ohlcv_table}" '
        f'WHERE "{time_col}" >= ? ORDER BY "{time_col}" ASC LIMIT ?'
    )
    forward = con.execute(q_forward, [entry_dt, forward_limit]).df()

    if forward.empty:
        return entry_dt, entry_p, "NO_DATA", _concat_window(deps, before, pd.DataFrame(), pd.DataFrame())

    forward["Time"] = pd.to_datetime(forward["Time"])

    if forward.iloc[0]["Time"] == entry_dt:
        scan = forward.iloc[1 : 1 + exit_lookahead]
    else:
        scan = forward.iloc[0:exit_lookahead]

    if scan.empty:
        main = forward[forward["Time"] <= entry_dt]
        after = forward[forward["Time"] > entry_dt].iloc[:pad_candles]
        return entry_dt, entry_p, "NO_DATA", _concat_window(deps, before, main, after)

    if sl_p is None and tp_p is None:
        main = forward[forward["Time"] <= entry_dt]
        after = forward[forward["Time"] > entry_dt].iloc[:pad_candles]
        return entry_dt, entry_p, "N/A", _concat_window(deps, before, main, after)

    is_long = True
    if sl_p is not None and tp_p is not None:
        is_long = tp_p > sl_p
    elif sl_p is not None:
        is_long = entry_p > sl_p

    if is_long:
        sl_hit = scan["Low"].le(sl_p) if sl_p is not None else None
        tp_hit = scan["High"].ge(tp_p) if tp_p is not None else None
    else:
        sl_hit = scan["High"].ge(sl_p) if sl_p is not None else None
        tp_hit = scan["Low"].le(tp_p) if tp_p is not None else None

    sl_idx = sl_hit.idxmax() if sl_hit is not None and sl_hit.any() else None
    tp_idx = tp_hit.idxmax() if tp_hit is not None and tp_hit.any() else None

    if sl_idx is not None and (tp_idx is None or sl_idx <= tp_idx):
        row = scan.loc[sl_idx]
        exit_dt, exit_p, exit_reason = _to_naive_ts(pd, row["Time"]), sl_p, "SL"
    elif tp_idx is not None:
        row = scan.loc[tp_idx]
        exit_dt, exit_p, exit_reason = _to_naive_ts(pd, row["Time"]), tp_p, "TP"
    else:
        row = scan.iloc[-1]
        exit_dt, exit_p, exit_reason = _to_naive_ts(pd, row["Time"]), float(row["Close"]), "TIME"

    exit_time_val = row["Time"]
    main = forward[forward["Time"] <= exit_time_val]
    after = forward[forward["Time"] > exit_time_val].iloc[:pad_candles]
    return exit_dt, exit_p, exit_reason, _concat_window(deps, before, main, after)
