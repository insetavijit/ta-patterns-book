#!/usr/bin/env python3
"""
compare_trade_by_trade.py — Granular Trade-by-Trade Comparison Engine.

Compares two trade tables from a DuckDB database (e.g. mt5_trades vs vbt_tsts_tbl)
by matching trades on entry timestamps, calculating execution deltas, and providing
a complete breakdown of entry/exit prices, timing, PnL, exit reasons, and SL modes.

Usage:
  uv run python compare-trade-by-trade.py --db Shared/OUTs/duckdb/CFMV0601B-20260916_112845.duckdb --tabls mt5_trades,vbt_tsts_tbl
  uv run python Utils/compare_trade_by_trade.py --db outs/mt5_backtests.duckdb --tables mt5_trades,vbt_tsts_tbl
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DUCKDB_DIR = _REPO_ROOT / "Shared" / "OUTs" / "duckdb"


def find_latest_db() -> Path | None:
    """Find the most recent DuckDB database with multiple trade tables."""
    candidates = sorted(list(_DEFAULT_DUCKDB_DIR.glob("*.duckdb")), key=lambda p: p.stat().st_mtime, reverse=True)
    for c in candidates:
        try:
            con = duckdb.connect(str(c), read_only=True)
            tbls = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
            con.close()
            trade_tbls = [t for t in tbls if "trades" in t or "tsts" in t or "vbt" in t]
            if len(trade_tbls) >= 2:
                return c
        except Exception:
            continue
    return candidates[0] if candidates else None


def load_trades_table(con: duckdb.DuckDBPyConnection, table_name: str) -> pd.DataFrame:
    """Load and standardize trade records from a DuckDB table."""
    df = con.execute(f"SELECT * FROM {table_name}").df()
    if df.empty:
        return df

    # Standardize column names to lowercase
    df.columns = [str(c).lower() for c in df.columns]

    # Standardize timestamps
    for t_col in ["entry_time", "exit_time"]:
        if t_col in df.columns:
            df[t_col] = pd.to_datetime(df[t_col].astype(str).str.replace(".", "-", regex=False), utc=True)

    # Standardize numeric columns
    for num_col in ["entry_price", "exit_price", "pnl", "realized_pnl", "return_pct", "lot_size"]:
        if num_col in df.columns:
            df[num_col] = pd.to_numeric(df[num_col], errors="coerce")

    # Sort chronologically by entry_time
    if "entry_time" in df.columns:
        df = df.sort_values("entry_time").reset_index(drop=True)

    return df


def match_trades(
    df1: pd.DataFrame,
    df2: pd.DataFrame,
    name1: str,
    name2: str,
    tolerance_seconds: float = 1800.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Greedily match trades between df1 and df2 based on closest entry timestamp within tolerance."""
    matched_pairs: list[dict[str, Any]] = []
    used_indices1 = set()
    used_indices2 = set()

    for idx1, t1 in df1.iterrows():
        t1_entry = t1["entry_time"]
        best_idx2 = None
        best_diff = float("inf")

        for idx2, t2 in df2.iterrows():
            if idx2 in used_indices2:
                continue
            t2_entry = t2["entry_time"]
            diff_sec = abs((t1_entry - t2_entry).total_seconds())
            if diff_sec <= tolerance_seconds and diff_sec < best_diff:
                best_diff = diff_sec
                best_idx2 = idx2

        if best_idx2 is not None:
            used_indices1.add(idx1)
            used_indices2.add(best_idx2)
            t2 = df2.loc[best_idx2]

            entry_delta_sec = (t2["entry_time"] - t1["entry_time"]).total_seconds()
            exit_delta_sec = None
            if pd.notna(t1.get("exit_time")) and pd.notna(t2.get("exit_time")):
                exit_delta_sec = (t2["exit_time"] - t1["exit_time"]).total_seconds()

            p1_entry = float(t1.get("entry_price", 0.0))
            p2_entry = float(t2.get("entry_price", 0.0))
            entry_price_delta = p2_entry - p1_entry

            p1_exit = float(t1.get("exit_price", 0.0))
            p2_exit = float(t2.get("exit_price", 0.0))
            exit_price_delta = p2_exit - p1_exit

            p1_pnl = float(t1.get("pnl", 0.0))
            p2_pnl = float(t2.get("pnl", 0.0))
            pnl_delta = p2_pnl - p1_pnl

            reason1 = str(t1.get("exit_reason", "")).upper()
            reason2 = str(t2.get("exit_reason", "")).upper()
            reason_match = (reason1 == reason2) if reason1 and reason2 else None

            sl_mode1 = str(t1.get("sl_mode", "")).upper()
            sl_mode2 = str(t2.get("sl_mode", "")).upper()
            sl_mode_match = (sl_mode1 == sl_mode2) if sl_mode1 and sl_mode2 else None

            matched_pairs.append({
                "t1_id": t1.get("trade_id", idx1 + 1),
                "t2_id": t2.get("trade_id", best_idx2 + 1),
                "t1_entry_time": t1["entry_time"],
                "t2_entry_time": t2["entry_time"],
                "entry_delta_sec": entry_delta_sec,
                "t1_exit_time": t1.get("exit_time"),
                "t2_exit_time": t2.get("exit_time"),
                "exit_delta_sec": exit_delta_sec,
                "t1_entry_price": p1_entry,
                "t2_entry_price": p2_entry,
                "entry_price_delta": entry_price_delta,
                "t1_exit_price": p1_exit,
                "t2_exit_price": p2_exit,
                "exit_price_delta": exit_price_delta,
                "t1_pnl": p1_pnl,
                "t2_pnl": p2_pnl,
                "pnl_delta": pnl_delta,
                "t1_reason": reason1,
                "t2_reason": reason2,
                "reason_match": reason_match,
                "t1_sl_mode": sl_mode1,
                "t2_sl_mode": sl_mode2,
                "sl_mode_match": sl_mode_match,
            })

    unmatched1 = [df1.iloc[i].to_dict() for i in range(len(df1)) if i not in used_indices1]
    unmatched2 = [df2.iloc[i].to_dict() for i in range(len(df2)) if i not in used_indices2]

    return matched_pairs, unmatched1, unmatched2


def _get_short_label(name: str) -> str:
    """Derive clean, short column label from table name."""
    low = name.lower()
    if "mt5" in low:
        return "MT5"
    if "vbt" in low:
        return "VBT"
    return name[:6].capitalize()


def render_trade_by_trade_table(
    matched_pairs: list[dict[str, Any]],
    name1: str,
    name2: str,
    console: Console,
) -> None:
    """Render a clean, compact trade-by-trade alignment table."""
    lbl1 = _get_short_label(name1)
    lbl2 = _get_short_label(name2)

    table = Table(
        title=f"Trade-by-Trade Execution Alignment: {name1} ({lbl1}) ⟷ {name2} ({lbl2})",
        box=None,
        header_style="bold cyan",
    )

    table.add_column("Pair", justify="right", style="bold", no_wrap=True)
    table.add_column("Entry Time (UTC)", style="cyan", no_wrap=True)
    table.add_column("Δ Time", justify="right", no_wrap=True)
    table.add_column(f"{lbl1} Px", justify="right", no_wrap=True)
    table.add_column(f"{lbl2} Px", justify="right", no_wrap=True)
    table.add_column("Δ Pts", justify="right", no_wrap=True)
    table.add_column("Exit Rsn", justify="center", no_wrap=True)
    table.add_column("SL Mode", justify="center", no_wrap=True)
    table.add_column(f"{lbl1} PnL", justify="right", no_wrap=True)
    table.add_column(f"{lbl2} PnL", justify="right", no_wrap=True)
    table.add_column("Δ PnL", justify="right", no_wrap=True)

    for idx, p in enumerate(matched_pairs, 1):
        t1_t = p["t1_entry_time"].strftime("%m-%d %H:%M") if pd.notna(p["t1_entry_time"]) else "-"
        d_sec = p["entry_delta_sec"]
        time_delta_str = f"{int(d_sec):+d}s" if abs(d_sec) < 60 else f"{d_sec / 60.0:+.1f}m"

        pts_delta = p["entry_price_delta"] * 100000.0

        r1 = p["t1_reason"] or "-"
        r2 = p["t2_reason"] or "-"
        if p["reason_match"]:
            reason_str = f"[bold green]{r1} ✓[/bold green]"
        else:
            reason_str = f"[bold red]{r1} ≠ {r2}[/bold red]"

        sl1 = p["t1_sl_mode"] or "-"
        sl2 = p["t2_sl_mode"] or "-"
        if p["sl_mode_match"]:
            sl_str = f"[bold green]{sl1} ✓[/bold green]"
        else:
            sl_str = f"[bold red]{sl1} ≠ {sl2}[/bold red]"

        p1_val = p["t1_pnl"]
        p2_val = p["t2_pnl"]
        p1_style = "green" if p1_val >= 0 else "red"
        p2_style = "green" if p2_val >= 0 else "red"

        pnl_diff = p["pnl_delta"]
        diff_style = "green" if pnl_diff >= 0 else "red"

        table.add_row(
            f"#{idx}",
            t1_t,
            time_delta_str,
            f"{p['t1_entry_price']:.5f}",
            f"{p['t2_entry_price']:.5f}",
            f"{pts_delta:+.1f}",
            reason_str,
            sl_str,
            f"[{p1_style}]${p1_val:+,.2f}[/{p1_style}]",
            f"[{p2_style}]${p2_val:+,.2f}[/{p2_style}]",
            f"[{diff_style}]${pnl_diff:+,.2f}[/{diff_style}]",
        )

    console.print("\n")
    console.print(table)


def render_unmatched_table(
    unmatched1: list[dict[str, Any]],
    unmatched2: list[dict[str, Any]],
    name1: str,
    name2: str,
    console: Console,
) -> None:
    """Render details for trades present in only one table."""
    if not unmatched1 and not unmatched2:
        return

    table = Table(
        title="Unmatched Trades (Executed in Only One Engine)",
        box=None,
        header_style="bold yellow",
    )
    table.add_column("Source", style="bold cyan", no_wrap=True)
    table.add_column("ID", justify="right", no_wrap=True)
    table.add_column("Entry Time (UTC)", style="cyan", no_wrap=True)
    table.add_column("Exit Time (UTC)", style="cyan", no_wrap=True)
    table.add_column("Entry Px", justify="right", no_wrap=True)
    table.add_column("Exit Px", justify="right", no_wrap=True)
    table.add_column("Exit Rsn", justify="center", no_wrap=True)
    table.add_column("SL Mode", justify="center", no_wrap=True)
    table.add_column("PnL ($)", justify="right", no_wrap=True)

    for t in unmatched1:
        e_time = pd.to_datetime(t.get("entry_time")).strftime("%m-%d %H:%M") if pd.notna(t.get("entry_time")) else "-"
        x_time = pd.to_datetime(t.get("exit_time")).strftime("%m-%d %H:%M") if pd.notna(t.get("exit_time")) else "-"
        pnl = float(t.get("pnl", 0.0))
        pnl_style = "green" if pnl >= 0 else "red"
        table.add_row(
            name1,
            str(t.get("trade_id", "-")),
            e_time,
            x_time,
            f"{float(t.get('entry_price', 0.0)):.5f}",
            f"{float(t.get('exit_price', 0.0)):.5f}",
            str(t.get("exit_reason", "-")).upper(),
            str(t.get("sl_mode", "-")).upper(),
            f"[{pnl_style}]${pnl:+,.2f}[/{pnl_style}]",
        )

    for t in unmatched2:
        e_time = pd.to_datetime(t.get("entry_time")).strftime("%m-%d %H:%M") if pd.notna(t.get("entry_time")) else "-"
        x_time = pd.to_datetime(t.get("exit_time")).strftime("%m-%d %H:%M") if pd.notna(t.get("exit_time")) else "-"
        pnl = float(t.get("pnl", 0.0))
        pnl_style = "green" if pnl >= 0 else "red"
        table.add_row(
            name2,
            str(t.get("trade_id", "-")),
            e_time,
            x_time,
            f"{float(t.get('entry_price', 0.0)):.5f}",
            f"{float(t.get('exit_price', 0.0)):.5f}",
            str(t.get("exit_reason", "-")).upper(),
            str(t.get("sl_mode", "-")).upper(),
            f"[{pnl_style}]${pnl:+,.2f}[/{pnl_style}]",
        )

    console.print("\n")
    console.print(table)


def render_summary_diagnostics(
    df1: pd.DataFrame,
    df2: pd.DataFrame,
    matched_pairs: list[dict[str, Any]],
    unmatched1: list[dict[str, Any]],
    unmatched2: list[dict[str, Any]],
    name1: str,
    name2: str,
    console: Console,
) -> None:
    """Render overall execution agreement statistics."""
    lbl1 = _get_short_label(name1)
    lbl2 = _get_short_label(name2)

    summary_table = Table(title="Execution Diagnostics & Alignment Summary", box=None, header_style="bold magenta")
    summary_table.add_column("Metric", style="bold cyan")
    summary_table.add_column("Value", justify="right")

    n1, n2 = len(df1), len(df2)
    n_match = len(matched_pairs)
    match_pct1 = (n_match / n1 * 100.0) if n1 else 0.0
    match_pct2 = (n_match / n2 * 100.0) if n2 else 0.0

    reason_agreements = sum(1 for p in matched_pairs if p["reason_match"])
    reason_rate = (reason_agreements / n_match * 100.0) if n_match else 0.0

    sl_mode_agreements = sum(1 for p in matched_pairs if p["sl_mode_match"])
    sl_rate = (sl_mode_agreements / n_match * 100.0) if n_match else 0.0

    mean_entry_pts = np.mean([abs(p["entry_price_delta"]) * 100000.0 for p in matched_pairs]) if matched_pairs else 0.0
    mean_exit_pts = np.mean([abs(p["exit_price_delta"]) * 100000.0 for p in matched_pairs]) if matched_pairs else 0.0

    pnl1 = df1["pnl"].sum() if not df1.empty and "pnl" in df1.columns else 0.0
    pnl2 = df2["pnl"].sum() if not df2.empty and "pnl" in df2.columns else 0.0
    pnl_delta = pnl2 - pnl1

    summary_table.add_row(f"Total Trades in {name1} ({lbl1})", f"{n1:,}")
    summary_table.add_row(f"Total Trades in {name2} ({lbl2})", f"{n2:,}")
    summary_table.add_row("Matched Trades", f"{n_match:,} ({match_pct1:.1f}% of {lbl1}, {match_pct2:.1f}% of {lbl2})")
    summary_table.add_row(f"Unmatched (Only in {lbl1})", f"{len(unmatched1):,}")
    summary_table.add_row(f"Unmatched (Only in {lbl2})", f"{len(unmatched2):,}")
    summary_table.add_row("Exit Reason Agreement Rate", f"[bold green]{reason_rate:.1f}%[/bold green] ({reason_agreements}/{n_match})")
    summary_table.add_row("SL Mode Agreement Rate", f"[bold green]{sl_rate:.1f}%[/bold green] ({sl_mode_agreements}/{n_match})")
    summary_table.add_row("Mean Entry Price Delta", f"{mean_entry_pts:.1f} points ({mean_entry_pts / 10.0:.2f} pips)")
    summary_table.add_row("Mean Exit Price Delta", f"{mean_exit_pts:.1f} points ({mean_exit_pts / 10.0:.2f} pips)")
    summary_table.add_row(f"Net Realized PnL ({lbl1})", f"${pnl1:+,.2f}")
    summary_table.add_row(f"Net Realized PnL ({lbl2})", f"${pnl2:+,.2f}")
    summary_table.add_row(f"PnL Delta ({lbl2} - {lbl1})", f"${pnl_delta:+,.2f}")

    console.print("\n")
    console.print(summary_table)
    console.print("\n")


def _safe_drop(con: duckdb.DuckDBPyConnection, name: str) -> None:
    """Drop a view or table safely regardless of its catalog type."""
    try:
        con.execute(f"DROP VIEW IF EXISTS {name}")
    except Exception:
        pass
    try:
        con.execute(f"DROP TABLE IF EXISTS {name}")
    except Exception:
        pass


def save_comparison_to_db(
    db_path: Path,
    matched_pairs: list[dict[str, Any]],
    unmatched1: list[dict[str, Any]],
    unmatched2: list[dict[str, Any]],
    name1: str,
    name2: str,
    table_name: str = "trades_comparision",
) -> int:
    """Persist granular trade-by-trade comparison records into DuckDB."""
    rows: list[dict[str, Any]] = []

    # 1. Matched Pairs
    for idx, p in enumerate(matched_pairs, 1):
        pts_entry = p.get("entry_price_delta", 0.0) * 100000.0 if p.get("entry_price_delta") is not None else None
        pts_exit = p.get("exit_price_delta", 0.0) * 100000.0 if p.get("exit_price_delta") is not None else None
        rows.append({
            "pair_id": idx,
            "match_status": "MATCHED",
            "t1_table": name1,
            "t1_id": p.get("t1_id"),
            "t2_table": name2,
            "t2_id": p.get("t2_id"),
            "t1_entry_time": p.get("t1_entry_time"),
            "t2_entry_time": p.get("t2_entry_time"),
            "entry_delta_sec": p.get("entry_delta_sec"),
            "t1_exit_time": p.get("t1_exit_time"),
            "t2_exit_time": p.get("t2_exit_time"),
            "exit_delta_sec": p.get("exit_delta_sec"),
            "t1_entry_price": p.get("t1_entry_price"),
            "t2_entry_price": p.get("t2_entry_price"),
            "entry_price_delta": p.get("entry_price_delta"),
            "entry_price_delta_pts": pts_entry,
            "t1_exit_price": p.get("t1_exit_price"),
            "t2_exit_price": p.get("t2_exit_price"),
            "exit_price_delta": p.get("exit_price_delta"),
            "exit_price_delta_pts": pts_exit,
            "t1_pnl": p.get("t1_pnl"),
            "t2_pnl": p.get("t2_pnl"),
            "pnl_delta": p.get("pnl_delta"),
            "t1_exit_reason": p.get("t1_reason"),
            "t2_exit_reason": p.get("t2_reason"),
            "reason_match": p.get("reason_match"),
            "t1_sl_mode": p.get("t1_sl_mode"),
            "t2_sl_mode": p.get("t2_sl_mode"),
            "sl_mode_match": p.get("sl_mode_match"),
        })

    # 2. Unmatched in Table 1
    for t in unmatched1:
        rows.append({
            "pair_id": None,
            "match_status": f"ONLY_IN_{name1}",
            "t1_table": name1,
            "t1_id": t.get("trade_id"),
            "t2_table": name2,
            "t2_id": None,
            "t1_entry_time": t.get("entry_time"),
            "t2_entry_time": None,
            "entry_delta_sec": None,
            "t1_exit_time": t.get("exit_time"),
            "t2_exit_time": None,
            "exit_delta_sec": None,
            "t1_entry_price": float(t.get("entry_price", 0.0)) if t.get("entry_price") is not None else None,
            "t2_entry_price": None,
            "entry_price_delta": None,
            "entry_price_delta_pts": None,
            "t1_exit_price": float(t.get("exit_price", 0.0)) if t.get("exit_price") is not None else None,
            "t2_exit_price": None,
            "exit_price_delta": None,
            "exit_price_delta_pts": None,
            "t1_pnl": float(t.get("pnl", 0.0)) if t.get("pnl") is not None else None,
            "t2_pnl": None,
            "pnl_delta": None,
            "t1_exit_reason": str(t.get("exit_reason", "")).upper() if t.get("exit_reason") else None,
            "t2_exit_reason": None,
            "reason_match": None,
            "t1_sl_mode": str(t.get("sl_mode", "")).upper() if t.get("sl_mode") else None,
            "t2_sl_mode": None,
            "sl_mode_match": None,
        })

    # 3. Unmatched in Table 2
    for t in unmatched2:
        rows.append({
            "pair_id": None,
            "match_status": f"ONLY_IN_{name2}",
            "t1_table": name1,
            "t1_id": None,
            "t2_table": name2,
            "t2_id": t.get("trade_id"),
            "t1_entry_time": None,
            "t2_entry_time": t.get("entry_time"),
            "entry_delta_sec": None,
            "t1_exit_time": None,
            "t2_exit_time": t.get("exit_time"),
            "exit_delta_sec": None,
            "t1_entry_price": None,
            "t2_entry_price": float(t.get("entry_price", 0.0)) if t.get("entry_price") is not None else None,
            "entry_price_delta": None,
            "entry_price_delta_pts": None,
            "t1_exit_price": None,
            "t2_exit_price": float(t.get("exit_price", 0.0)) if t.get("exit_price") is not None else None,
            "exit_price_delta": None,
            "exit_price_delta_pts": None,
            "t1_pnl": None,
            "t2_pnl": float(t.get("pnl", 0.0)) if t.get("pnl") is not None else None,
            "pnl_delta": None,
            "t1_exit_reason": None,
            "t2_exit_reason": str(t.get("exit_reason", "")).upper() if t.get("exit_reason") else None,
            "reason_match": None,
            "t1_sl_mode": None,
            "t2_sl_mode": str(t.get("sl_mode", "")).upper() if t.get("sl_mode") else None,
            "sl_mode_match": None,
        })

    df_comp = pd.DataFrame(rows)
    con = duckdb.connect(str(db_path), read_only=False)
    con.register("df_comp_tmp", df_comp)
    for t_name in (table_name, "trades_comparision", "trade_by_trade_comparison"):
        _safe_drop(con, t_name)
        con.execute(f"CREATE TABLE {t_name} AS SELECT * FROM df_comp_tmp")
    con.close()
    return len(df_comp)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="compare-trade-by-trade: Granular Trade-by-Trade Comparison Engine."
    )
    parser.add_argument("--db", default=None, help="Target DuckDB database path")
    parser.add_argument(
        "--tables", "--tabls", "--tbls", "-t",
        dest="tables",
        default="mt5_trades,vbt_trades",
        help="Comma-separated table names to compare (default: mt5_trades,vbt_trades)",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1800.0,
        help="Matching tolerance window in seconds (default: 1800s / 30min)",
    )
    parser.add_argument(
        "--comp-table",
        default="trades_comparision",
        help="Target table name in DuckDB for trade comparisons (default: trades_comparision)",
    )
    parser.add_argument(
        "--no-save-db",
        action="store_true",
        help="Skip saving the comparison table to DuckDB",
    )
    parser.add_argument(
        "--output",
        choices=["terminal", "json"],
        default="terminal",
        help="Output format (default: terminal)",
    )

    args = parser.parse_args()
    console = Console()
    if console.width < 140:
        console.size = (140, console.height or 40)

    # Resolve database path
    if args.db:
        db_path = Path(args.db)
    else:
        latest = find_latest_db()
        if not latest:
            console.print("[bold red]Error: No DuckDB database found. Please specify --db <path>[/bold red]")
            sys.exit(1)
        db_path = latest

    if not db_path.exists():
        console.print(f"[bold red]Error: DuckDB file not found at: {db_path}[/bold red]")
        sys.exit(1)

    # Parse tables
    raw_tbls = [t.strip() for t in args.tables.split(",") if t.strip()]
    if len(raw_tbls) < 2:
        console.print(f"[bold red]Error: Please specify two tables to compare via --tables table1,table2[/bold red]")
        sys.exit(1)

    table1, table2 = raw_tbls[0], raw_tbls[1]

    # Connect to DuckDB
    con = duckdb.connect(str(db_path), read_only=True)
    existing_tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]

    for t in (table1, table2):
        if t not in existing_tables:
            console.print(f"[bold red]Error: Table '{t}' not found in database {db_path}. Available: {', '.join(existing_tables)}[/bold red]")
            con.close()
            sys.exit(1)

    df1 = load_trades_table(con, table1)
    df2 = load_trades_table(con, table2)
    con.close()

    matched_pairs, unmatched1, unmatched2 = match_trades(
        df1=df1,
        df2=df2,
        name1=table1,
        name2=table2,
        tolerance_seconds=args.tolerance,
    )

    if args.output == "json":
        out_payload = {
            "database": str(db_path),
            "table1": table1,
            "table2": table2,
            "total_t1": len(df1),
            "total_t2": len(df2),
            "matched_count": len(matched_pairs),
            "matched_pairs": [
                {
                    k: (v.isoformat() if isinstance(v, (datetime, pd.Timestamp)) else v)
                    for k, v in p.items()
                }
                for p in matched_pairs
            ],
            "unmatched_t1": len(unmatched1),
            "unmatched_t2": len(unmatched2),
        }
        print(json.dumps(out_payload, indent=2))
        return

    console.print(f"[bold yellow]═══════════════════════════════════════════════════════════════════════════════[/bold yellow]")
    console.print(f"             [bold]Trade-by-Trade Alignment Engine[/bold]")
    console.print(f" Database : [bold green]{db_path}[/bold green]")
    console.print(f" Tables   : [bold cyan]{table1}[/bold cyan] ({len(df1)} trades)  ⟷  [bold cyan]{table2}[/bold cyan] ({len(df2)} trades)")
    console.print(f"[bold yellow]═══════════════════════════════════════════════════════════════════════════════[/bold yellow]")

    render_trade_by_trade_table(matched_pairs, table1, table2, console)
    if unmatched1 or unmatched2:
        render_unmatched_table(unmatched1, unmatched2, table1, table2, console)
    render_summary_diagnostics(df1, df2, matched_pairs, unmatched1, unmatched2, table1, table2, console)

    # Persist comparison table to DuckDB
    if not args.no_save_db:
        saved_count = save_comparison_to_db(
            db_path=db_path,
            matched_pairs=matched_pairs,
            unmatched1=unmatched1,
            unmatched2=unmatched2,
            name1=table1,
            name2=table2,
            table_name=args.comp_table,
        )
        console.print(f"[bold green]✓ Persisted Table to DuckDB:[/bold green] [bold cyan]{args.comp_table}[/bold cyan] ({saved_count} rows in {db_path.name})\n")


if __name__ == "__main__":
    main()
