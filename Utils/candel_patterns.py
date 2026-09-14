#!/usr/bin/env python3
"""Candlestick Pattern Detector & Reference Table Generator.

Calculates single, double, triple, and multi-candlestick patterns across OHLCV data
using the pandas-ta-classic library, and persists a dedicated reference table
'candel_patters_tf' (e.g. candel_patters_5m) into the target DuckDB database.

Schema of candel_patters_tf:
    timestamp        TIMESTAMP WITH TIME ZONE PRIMARY KEY
    single_patt      VARCHAR (Primary 1-candle pattern, e.g. 'Bull_Hammer', 'Doji')
    dubble_patt      VARCHAR (Primary 2-candle pattern, e.g. 'Bull_Engulfing', 'Inside_Bar')
    triple_patt      VARCHAR (Primary 3-candle pattern, e.g. 'Bull_Morning_Star', 'Three_White_Soldiers')
    multi_patt       VARCHAR (Primary 4+ candle pattern, e.g. 'Rising_Three_Methods', 'Breakaway')
    single_patt_all  VARCHAR (All single patterns on bar, comma-separated)
    dubble_patt_all  VARCHAR (All double patterns on bar, comma-separated)
    triple_patt_all  VARCHAR (All triple patterns on bar, comma-separated)
    multi_patt_all   VARCHAR (All multi patterns on bar, comma-separated)
    candle_state     VARCHAR (1-candle state: Direction + Color, e.g. 'UG', 'DR')
    total_patterns   INTEGER (Total pattern detections on this candle)

Usage:
    uv run python candel_patterns.py --target Shared/Data/classic_floor_mod-v5-1.duckdb
    uv run python Utils/candel_patterns.py --target Shared/Data/classic_floor_mod-v5-1.duckdb --tf 5m
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pandas_ta_classic as pta
from rich.console import Console
from rich.table import Table

console = Console()

# ----------------------------------------------------------------------
# 1. Complete Classification of pandas-ta-classic Candlestick Patterns
# ----------------------------------------------------------------------
SINGLE_CANDLE_PATTERNS = [
    "CDL_BELTHOLD",
    "CDL_CLOSINGMARUBOZU",
    "CDL_DOJI_10_0.1",
    "CDL_DRAGONFLYDOJI",
    "CDL_GRAVESTONEDOJI",
    "CDL_HAMMER",
    "CDL_HANGINGMAN",
    "CDL_HIGHWAVE",
    "CDL_INVERTEDHAMMER",
    "CDL_LONGLEGGEDDOJI",
    "CDL_LONGLINE",
    "CDL_MARUBOZU",
    "CDL_RICKSHAWMAN",
    "CDL_SHOOTINGSTAR",
    "CDL_SHORTLINE",
    "CDL_SPINNINGTOP",
    "CDL_TAKURI",
]

DOUBLE_CANDLE_PATTERNS = [
    "CDL_2CROWS",
    "CDL_COUNTERATTACK",
    "CDL_DARKCLOUDCOVER",
    "CDL_DOJISTAR",
    "CDL_ENGULFING",
    "CDL_HARAMI",
    "CDL_HARAMICROSS",
    "CDL_HOMINGPIGEON",
    "CDL_INNECK",
    "CDL_INSIDE",
    "CDL_KICKING",
    "CDL_KICKINGBYLENGTH",
    "CDL_MATCHINGLOW",
    "CDL_ONNECK",
    "CDL_PIERCING",
    "CDL_SEPARATINGLINES",
    "CDL_THRUSTING",
]

TRIPLE_CANDLE_PATTERNS = [
    "CDL_3BLACKCROWS",
    "CDL_3INSIDE",
    "CDL_3OUTSIDE",
    "CDL_3STARSINSOUTH",
    "CDL_3WHITESOLDIERS",
    "CDL_ABANDONEDBABY",
    "CDL_ADVANCEBLOCK",
    "CDL_EVENINGDOJISTAR",
    "CDL_EVENINGSTAR",
    "CDL_GAPSIDESIDEWHITE",
    "CDL_IDENTICAL3CROWS",
    "CDL_MORNINGDOJISTAR",
    "CDL_MORNINGSTAR",
    "CDL_STALLEDPATTERN",
    "CDL_STICKSANDWICH",
    "CDL_TASUKIGAP",
    "CDL_TRISTAR",
    "CDL_UNIQUE3RIVER",
    "CDL_UPSIDEGAP2CROWS",
]

MULTI_CANDLE_PATTERNS = [
    "CDL_3LINESTRIKE",
    "CDL_BREAKAWAY",
    "CDL_CONCEALBABYSWALL",
    "CDL_HIKKAKE",
    "CDL_HIKKAKEMOD",
    "CDL_LADDERBOTTOM",
    "CDL_MATHOLD",
    "CDL_RISEFALL3METHODS",
    "CDL_XSIDEGAP3METHODS",
]


def _format_pattern_name(col_name: str) -> str:
    """Format raw column name 'CDL_HAMMER' into clean title 'Hammer'."""
    clean = col_name.replace("CDL_", "")
    if clean.startswith("DOJI_"):
        clean = "DOJI"
    words = clean.split("_")
    return "".join(w.capitalize() for w in words)


NAME_LOOKUP = {
    c: _format_pattern_name(c)
    for c in (
        SINGLE_CANDLE_PATTERNS
        + DOUBLE_CANDLE_PATTERNS
        + TRIPLE_CANDLE_PATTERNS
        + MULTI_CANDLE_PATTERNS
    )
}


def _extract_category_patterns(
    sub_matrix: np.ndarray,
    col_names: list[str],
    n_rows: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fast vectorized extraction of primary pattern, all patterns, and hit count."""
    primary = np.full(n_rows, None, dtype=object)
    all_pats = np.full(n_rows, None, dtype=object)
    counts = np.zeros(n_rows, dtype=np.int32)

    rows, c_idxs = np.nonzero(sub_matrix)
    if len(rows) == 0:
        return primary, all_pats, counts

    vals = sub_matrix[rows, c_idxs]
    labels: list[str] = []
    for c, v in zip(c_idxs, vals):
        base = NAME_LOOKUP.get(col_names[c], col_names[c])
        # Format direction prefix
        if v > 0:
            labels.append(base if base.startswith("Bull") else f"Bull_{base}")
        elif v < 0:
            labels.append(base if base.startswith("Bear") else f"Bear_{base}")
        else:
            labels.append(base)

    # First detected pattern per row
    unq_rows, first_idx = np.unique(rows, return_index=True)
    primary[unq_rows] = [labels[i] for i in first_idx]

    # Comma-separated all patterns per row
    df_temp = pd.DataFrame({"row": rows, "label": labels})
    agg = df_temp.groupby("row", sort=False)["label"].agg(
        lambda s: ", ".join(dict.fromkeys(s))
    )
    all_pats[agg.index.to_numpy()] = agg.to_numpy()

    # Hit counts per row
    cnts = df_temp.groupby("row", sort=False).size()
    counts[cnts.index.to_numpy()] = cnts.to_numpy()

    return primary, all_pats, counts


def compute_candle_states(df: pd.DataFrame) -> pd.Series:
    """Compute 1-candle Direction+Color states."""
    o = df["open"].to_numpy()
    c = df["close"].to_numpy()

    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]

    # Direction: U if Close >= Prev Close, else D
    direction = np.where(c >= prev_c, "U", "D")
    # Color: G if Close > Open, else R
    color = np.where(c > o, "G", "R")
    candle_state = [f"{d}{col}" for d, col in zip(direction, color)]

    return pd.Series(candle_state, index=df.index)


def detect_timeframe(timestamps: pd.Series) -> str:
    """Infer timeframe string from median interval between timestamps."""
    try:
        ts = pd.to_datetime(timestamps).dropna()
        if len(ts) < 2:
            return "5m"
        diffs = ts.diff().dropna()
        median_sec = diffs.median().total_seconds()
        if median_sec == 60:
            return "1m"
        elif median_sec == 300:
            return "5m"
        elif median_sec == 900:
            return "15m"
        elif median_sec == 1800:
            return "30m"
        elif median_sec == 3600:
            return "1h"
        elif median_sec == 14400:
            return "4h"
        elif median_sec == 86400:
            return "1d"
        elif median_sec % 60 == 0:
            return f"{int(median_sec // 60)}m"
        else:
            return f"{int(median_sec)}s"
    except Exception:
        return "5m"


def build_candlestick_patterns_table(
    ohlcv_df: pd.DataFrame,
) -> pd.DataFrame:
    """Run all 62 pandas-ta-classic candlestick patterns and assemble reference table."""
    # Ensure required lower-case column names
    col_map = {c: c.lower() for c in ohlcv_df.columns}
    df = ohlcv_df.rename(columns=col_map).copy()

    # Identify timestamp column
    ts_col = None
    for c in ["timestamp", "time", "datetime", "date"]:
        if c in df.columns:
            ts_col = c
            break

    if ts_col is None:
        if isinstance(df.index, pd.DatetimeIndex):
            df["timestamp"] = df.index
            ts_col = "timestamp"
        else:
            raise ValueError("No timestamp column or DatetimeIndex found in OHLCV DataFrame.")

    console.print(f"[bold cyan]▶ Calculating 62 candlestick patterns across {len(df):,} bars using pandas-ta-classic...[/bold cyan]")
    t0 = time.perf_counter()
    all_cdl = df.ta.cdl_pattern(name="all")
    t1 = time.perf_counter()
    console.print(f"[green]✓ Pattern computation completed in {t1 - t0:.2f}s[/green]")

    n_rows = len(df)

    # Extract Single Patterns
    s_mat = all_cdl[SINGLE_CANDLE_PATTERNS].to_numpy()
    single_p, single_a, single_cnt = _extract_category_patterns(s_mat, SINGLE_CANDLE_PATTERNS, n_rows)

    # Extract Double Patterns
    d_mat = all_cdl[DOUBLE_CANDLE_PATTERNS].to_numpy()
    double_p, double_a, double_cnt = _extract_category_patterns(d_mat, DOUBLE_CANDLE_PATTERNS, n_rows)

    # Extract Triple Patterns
    t_mat = all_cdl[TRIPLE_CANDLE_PATTERNS].to_numpy()
    triple_p, triple_a, triple_cnt = _extract_category_patterns(t_mat, TRIPLE_CANDLE_PATTERNS, n_rows)

    # Extract Multi Patterns
    m_mat = all_cdl[MULTI_CANDLE_PATTERNS].to_numpy()
    multi_p, multi_a, multi_cnt = _extract_category_patterns(m_mat, MULTI_CANDLE_PATTERNS, n_rows)

    # Compute candle state
    state_s = compute_candle_states(df)

    total_cnts = single_cnt + double_cnt + triple_cnt + multi_cnt

    res_df = pd.DataFrame({
        "timestamp": df[ts_col].values,
        "single_patt": single_p,
        "dubble_patt": double_p,
        "triple_patt": triple_p,
        "multi_patt": multi_p,
        "single_patt_all": single_a,
        "dubble_patt_all": double_a,
        "triple_patt_all": triple_a,
        "multi_patt_all": multi_a,
        "candle_state": state_s.values,
        "total_patterns": total_cnts,
    })

    return res_df


def generate_patterns_for_db(
    target_db: str,
    ohlcv_table: str | None = None,
    timeframe: str | None = None,
    table_name: str | None = None,
    dry_run: bool = False,
) -> str:
    """Read OHLCV from target DuckDB, calculate patterns, and save reference table."""
    db_path = Path(target_db).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Target DuckDB database '{db_path}' not found.")

    con = duckdb.connect(str(db_path), read_only=True)
    tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
    con.close()

    if not tables:
        raise ValueError(f"Database '{db_path}' has no tables.")

    # Auto-detect OHLCV table if not provided
    if not ohlcv_table:
        candidates = [t for t in tables if "ohlcv" in t.lower()]
        if "ohlcv" in tables:
            ohlcv_table = "ohlcv"
        elif candidates:
            ohlcv_table = candidates[0]
        else:
            ohlcv_table = tables[0]

    console.print(f"Reading OHLCV from table '[bold cyan]{ohlcv_table}[/bold cyan]' in [bold white]{db_path.name}[/bold white]...")
    con = duckdb.connect(str(db_path), read_only=True)
    ohlcv_df = con.execute(f"SELECT * FROM {ohlcv_table} ORDER BY timestamp ASC").df()
    con.close()

    # Determine timeframe
    ts_col = next((c for c in ["timestamp", "time", "datetime", "date"] if c in ohlcv_df.columns), None)
    if not timeframe:
        timeframe = detect_timeframe(ohlcv_df[ts_col]) if ts_col else "5m"

    # Determine output table name
    if not table_name:
        table_name = f"candel_patters_{timeframe}"

    # Compute reference patterns DataFrame
    pat_df = build_candlestick_patterns_table(ohlcv_df)

    if dry_run:
        console.print(f"[bold yellow][DRY-RUN][/bold yellow] Would create table '{table_name}' with {len(pat_df):,} rows.")
        return table_name

    # Write to target DuckDB
    con = duckdb.connect(str(db_path), read_only=False)
    con.register("df_patterns_temp", pat_df)
    con.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM df_patterns_temp")
    # Also create the generic view candel_patters_tf pointing to this table
    con.execute(f"CREATE OR REPLACE VIEW candel_patters_tf AS SELECT * FROM {table_name}")
    con.close()

    console.print(f"[bold green]✓ Successfully created table '[cyan]{table_name}[/cyan]' and view '[cyan]candel_patters_tf[/cyan]' in {db_path.name} ({len(pat_df):,} rows)[/bold green]")

    # Render summary inspection table
    table = Table(
        title=f"Candlestick Patterns Reference Preview ({table_name})",
        box=None,
        show_header=True,
        header_style="bold cyan",
        show_edge=False,
        pad_edge=False,
    )
    table.add_column("timestamp", style="cyan", min_width=18)
    table.add_column("single_patt", style="green", min_width=16)
    table.add_column("dubble_patt", style="yellow", min_width=16)
    table.add_column("triple_patt", style="magenta", min_width=18)
    table.add_column("multi_patt", style="blue", min_width=16)
    table.add_column("candle_state", style="white", min_width=12)

    # Filter sample rows that actually have patterns detected
    sample_df = pat_df[pat_df["total_patterns"] > 0].head(12)
    for _, row in sample_df.iterrows():
        table.add_row(
            str(row["timestamp"])[:19],
            str(row["single_patt"] or "—"),
            str(row["dubble_patt"] or "—"),
            str(row["triple_patt"] or "—"),
            str(row["multi_patt"] or "—"),
            str(row["candle_state"] or "—"),
        )

    console.print(table)
    return table_name


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calculate pandas-ta-classic candlestick patterns from OHLCV and persist candel_patters_tf table."
    )
    parser.add_argument(
        "--target",
        "-t",
        required=True,
        help="Path to the target DuckDB database (e.g. Shared/Data/classic_floor_mod-v5-1.duckdb)",
    )
    parser.add_argument(
        "--ohlcv-table",
        help="Source OHLCV table name (defaults to 'ohlcv')",
    )
    parser.add_argument(
        "--tf",
        "--timeframe",
        help="Candle resolution timeframe (e.g. '5m', '1m', '1h'). Auto-detected if omitted.",
    )
    parser.add_argument(
        "--table-name",
        help="Target table name (defaults to 'candel_patters_{tf}')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute patterns without committing table to database",
    )

    args = parser.parse_args()
    generate_patterns_for_db(
        target_db=args.target,
        ohlcv_table=args.ohlcv_table,
        timeframe=args.tf,
        table_name=args.table_name,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
