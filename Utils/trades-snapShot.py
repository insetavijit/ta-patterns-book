#!/usr/bin/env python3
"""Trade Diagnostics & Backtest Performance Snapshot Generator.

Extracts comprehensive trade diagnostics, comparative execution performance
(Concurrent: FALSE vs Concurrent: TRUE), monthly breakdowns, SL architecture stats,
and database schema profiling from a DuckDB backtest file, saving the result as a
clean Markdown report in the corresponding DOCs/NOTEs/{strategy_dir}/ directory.

Usage:
    uv run python Utils/trades-snapShot.py
    uv run python Utils/trades-snapShot.py --target Shared/OUTs/duckdb/classic_floor_mod_v6_1.duckdb
    uv run python Utils/trades-snapShot.py --strategy classic_floor_mod_v6_1 --output DOCs/NOTEs/classic_floor_v6/trades-snapshot.md
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Resolve repository root
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

console = Console()


def resolve_target_db(repo_root: Path, target_cli: str | None = None) -> Path:
    """Resolve target database from CLI, Shared/OUTs/duckdb, or cnf.yaml."""
    if target_cli:
        p = Path(target_cli)
        p = repo_root / p if not p.is_absolute() else p
        if p.exists():
            return p
        raise FileNotFoundError(f"Target DuckDB database '{p}' not found.")

    # 1. Search Shared/OUTs/duckdb for newest database
    outs_dir = repo_root / "Shared" / "OUTs" / "duckdb"
    if outs_dir.exists():
        dbs = sorted(outs_dir.glob("*.duckdb"), key=lambda x: x.stat().st_mtime, reverse=True)
        if dbs:
            return dbs[0]

    # 2. Check Shared/cnf.yaml
    cnf_file = repo_root / "Shared" / "cnf.yaml"
    if cnf_file.exists():
        try:
            with open(cnf_file, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            b_db = cfg.get("paths", {}).get("shared", {}).get("data", {}).get("backtest_db")
            if b_db and (repo_root / b_db).exists():
                return repo_root / b_db
        except Exception:
            pass

    # 3. Fallback
    fallback = repo_root / "Shared" / "Data" / "Ohlcv_2325Eurusd.duckdb"
    if fallback.exists():
        return fallback

    raise FileNotFoundError("Could not auto-detect a target DuckDB database.")


def detect_strategy_name(con: duckdb.DuckDBPyConnection, db_path: Path) -> str:
    """Infer strategy name from trade records or database filename."""
    try:
        tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        for t in ["trades_concurrent_false", "trades_concurrent_true", "trades"]:
            if t in tables:
                cols = [c[0] for c in con.execute(f"DESCRIBE {t}").fetchall()]
                if "strategy_name" in cols:
                    res = con.execute(f"SELECT strategy_name FROM {t} WHERE strategy_name IS NOT NULL LIMIT 1").fetchone()
                    if res and res[0]:
                        return str(res[0])
                if "sl_mode" in cols or "primary_sl_hit_timestamp" in cols:
                    return "classic_floor_mod_v6_1"
                if "pfib15_bsl" in cols:
                    return "classic_floor_mod_v6"
    except Exception:
        pass

    fname = db_path.stem.lower()
    if "v6_1" in fname or "v6-1" in fname:
        return "classic_floor_mod_v6_1"
    elif "v6" in fname:
        return "classic_floor_mod_v6"
    elif "v5" in fname:
        return "classic_floor_mod_v5"
    return "classic_floor_mod_v6_1"


def resolve_notes_dir(repo_root: Path, strategy_name: str, notes_dir_cli: str | None = None) -> Path:
    """Determine destination notes directory."""
    if notes_dir_cli:
        p = Path(notes_dir_cli)
        p = repo_root / p if not p.is_absolute() else p
        p.mkdir(parents=True, exist_ok=True)
        return p

    strat_lower = strategy_name.lower()
    if "v6" in strat_lower:
        out_dir = repo_root / "DOCs" / "NOTEs" / "classic_floor_v6"
    elif "v5" in strat_lower:
        out_dir = repo_root / "DOCs" / "NOTEs" / "classic_floor_v5"
    else:
        out_dir = repo_root / "DOCs" / "NOTEs" / strategy_name

    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def compute_trade_metrics(df: pd.DataFrame) -> dict[str, Any]:
    """Compute high-level trade statistics from a trade DataFrame."""
    if df.empty:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "net_pnl": 0.0,
            "profit_factor": 0.0,
            "avg_trade_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "payoff_ratio": 0.0,
            "max_dd_pct": 0.0,
            "max_consecutive_losses": 0,
            "avg_holding_bars": 0.0,
            "long_trades": 0,
            "long_win_rate": 0.0,
            "short_trades": 0,
            "short_win_rate": 0.0,
        }

    pnl_col = "pnl" if "pnl" in df.columns else ("realized_pnl" if "realized_pnl" in df.columns else None)
    pnls = df[pnl_col].to_numpy() if pnl_col else np.zeros(len(df))

    wins = pnls > 0
    losses = pnls <= 0
    n_wins = int(np.sum(wins))
    n_losses = int(np.sum(losses))
    total_trades = len(df)
    win_rate = (n_wins / total_trades) * 100.0 if total_trades > 0 else 0.0

    gross_profit = float(np.sum(pnls[wins])) if n_wins > 0 else 0.0
    gross_loss = abs(float(np.sum(pnls[losses]))) if n_losses > 0 else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    avg_win = (gross_profit / n_wins) if n_wins > 0 else 0.0
    avg_loss = (gross_loss / n_losses) if n_losses > 0 else 0.0
    payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0

    # Max Drawdown calculation from cumulative PnL
    cum_pnl = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum_pnl)
    drawdowns = peak - cum_pnl
    max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    # Max consecutive losses
    max_cons_losses = 0
    cur_cons = 0
    for p in pnls:
        if p <= 0:
            cur_cons += 1
            if cur_cons > max_cons_losses:
                max_cons_losses = cur_cons
        else:
            cur_cons = 0

    # Holding bars
    holding_col = "holding_bars" if "holding_bars" in df.columns else None
    avg_bars = float(df[holding_col].mean()) if holding_col and holding_col in df.columns else 0.0

    # Direction breakdown
    dir_col = "direction" if "direction" in df.columns else None
    if dir_col:
        longs = df[df[dir_col].astype(str).str.upper() == "LONG"]
        shorts = df[df[dir_col].astype(str).str.upper() == "SHORT"]
        long_wr = (len(longs[longs[pnl_col] > 0]) / len(longs) * 100.0) if len(longs) > 0 else 0.0
        short_wr = (len(shorts[shorts[pnl_col] > 0]) / len(shorts) * 100.0) if len(shorts) > 0 else 0.0
        n_longs = len(longs)
        n_shorts = len(shorts)
    else:
        n_longs, long_wr, n_shorts, short_wr = 0, 0.0, 0, 0.0

    return {
        "total_trades": total_trades,
        "wins": n_wins,
        "losses": n_losses,
        "win_rate": win_rate,
        "net_pnl": float(np.sum(pnls)),
        "profit_factor": profit_factor,
        "avg_trade_pnl": float(np.mean(pnls)),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff_ratio,
        "max_dd_points": max_dd,
        "max_consecutive_losses": max_cons_losses,
        "avg_holding_bars": avg_bars,
        "long_trades": n_longs,
        "long_win_rate": long_wr,
        "short_trades": n_shorts,
        "short_win_rate": short_wr,
    }


def compute_monthly_breakdown(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Group trades by month and compute per-month metrics."""
    if df.empty or "entry_time" not in df.columns:
        return []

    pnl_col = "pnl" if "pnl" in df.columns else "realized_pnl"
    work_df = df.copy()
    work_df["month"] = pd.to_datetime(work_df["entry_time"]).dt.strftime("%Y-%m")

    monthly_stats = []
    for month, m_df in work_df.groupby("month", sort=True):
        m_pnls = m_df[pnl_col].to_numpy()
        n_trades = len(m_df)
        wins = m_pnls > 0
        n_wins = int(np.sum(wins))
        n_losses = n_trades - n_wins
        win_rate = (n_wins / n_trades * 100.0) if n_trades > 0 else 0.0
        net_pnl = float(np.sum(m_pnls))

        gross_profit = float(np.sum(m_pnls[wins])) if n_wins > 0 else 0.0
        gross_loss = abs(float(np.sum(m_pnls[~wins]))) if n_losses > 0 else 0.0
        pf = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

        # Monthly return pct if present
        ret_pct = float(m_df["return_pct"].sum()) if "return_pct" in m_df.columns else 0.0

        monthly_stats.append({
            "month": str(month),
            "trades": n_trades,
            "wins": n_wins,
            "losses": n_losses,
            "win_rate": win_rate,
            "net_pnl": net_pnl,
            "return_pct": ret_pct,
            "profit_factor": pf,
        })

    return monthly_stats


def generate_markdown_snapshot(
    target_db: Path,
    strategy_name: str,
    output_path: Path,
) -> Path:
    """Generate comprehensive markdown snapshot of trades and write to file."""
    con = duckdb.connect(str(target_db), read_only=True)
    tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]

    # Load trades
    df_false = con.execute("SELECT * FROM trades_concurrent_false").df() if "trades_concurrent_false" in tables else pd.DataFrame()
    df_true = con.execute("SELECT * FROM trades_concurrent_true").df() if "trades_concurrent_true" in tables else pd.DataFrame()

    m_false = compute_trade_metrics(df_false)
    m_true = compute_trade_metrics(df_true)

    month_false = compute_monthly_breakdown(df_false)
    month_true = compute_monthly_breakdown(df_true)

    # Active primary trade dataframe for detailed inspection
    active_df = df_false if not df_false.empty else df_true

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Time range
    time_range_str = "2025"
    if not active_df.empty and "entry_time" in active_df.columns:
        min_date = str(pd.to_datetime(active_df["entry_time"]).min())[:10]
        max_date = str(pd.to_datetime(active_df["entry_time"]).max())[:10]
        time_range_str = f"{min_date} to {max_date}"

    # Prepare markdown blocks
    md: list[str] = []
    md.append(f"# Strategy Backtest & Trade Diagnostics Snapshot")
    md.append(f"")
    md.append(f"**Document Generated:** `{now_str}`  ")
    md.append(f"**Target Database:** [`{target_db.name}`]({target_db.resolve().as_uri()})  ")
    md.append(f"**Strategy:** `{strategy_name}`  ")
    md.append(f"**Evaluated Period:** `{time_range_str}`  ")
    md.append(f"")
    md.append(f"---")
    md.append(f"")

    # Section 1: Comparative Executive Summary
    md.append(f"## 1. Executive Performance Comparison (Concurrent: FALSE vs Concurrent: TRUE)")
    md.append(f"")
    md.append(f"| Performance Metric | Concurrent: `FALSE` (Single Position) | Concurrent: `TRUE` (Overlapping Positions) | Variance (True - False) |")
    md.append(f"| :--- | :---: | :---: | :---: |")
    md.append(f"| **Total Executed Trades** | **{m_false['total_trades']}** | **{m_true['total_trades']}** | `+{m_true['total_trades'] - m_false['total_trades']}` |")
    md.append(f"| **Overall Win Rate** | **{m_false['win_rate']:.1f}%** | **{m_true['win_rate']:.1f}%** | `{m_true['win_rate'] - m_false['win_rate']:+.1f}%` |")
    md.append(f"| **Net Realized PnL** | **{m_false['net_pnl']:+,.2f} pts** | **{m_true['net_pnl']:+,.2f} pts** | `{m_true['net_pnl'] - m_false['net_pnl']:+,.2f} pts` |")
    md.append(f"| **Profit Factor** | **{m_false['profit_factor']:.2f}** | **{m_true['profit_factor']:.2f}** | `{m_true['profit_factor'] - m_false['profit_factor']:+.2f}` |")
    md.append(f"| **Average Trade PnL** | **{m_false['avg_trade_pnl']:+,.2f} pts** | **{m_true['avg_trade_pnl']:+,.2f} pts** | `{m_true['avg_trade_pnl'] - m_false['avg_trade_pnl']:+,.2f} pts` |")
    md.append(f"| **Average Win / Average Loss** | `{m_false['avg_win']:.1f} / {m_false['avg_loss']:.1f}` | `{m_true['avg_win']:.1f} / {m_true['avg_loss']:.1f}` | — |")
    md.append(f"| **Payoff Ratio (W/L)** | **{m_false['payoff_ratio']:.2f}** | **{m_true['payoff_ratio']:.2f}** | `{m_true['payoff_ratio'] - m_false['payoff_ratio']:+.2f}` |")
    md.append(f"| **Max Drawdown (Points)** | **{m_false['max_dd_points']:,.1f} pts** | **{m_true['max_dd_points']:,.1f} pts** | `{m_true['max_dd_points'] - m_false['max_dd_points']:+,.1f} pts` |")
    md.append(f"| **Max Consecutive Losses** | **{m_false['max_consecutive_losses']}** | **{m_true['max_consecutive_losses']}** | `{m_true['max_consecutive_losses'] - m_false['max_consecutive_losses']:+d}` |")
    md.append(f"| **Avg Holding Duration** | **{m_false['avg_holding_bars']:.1f} bars** | **{m_true['avg_holding_bars']:.1f} bars** | `{m_true['avg_holding_bars'] - m_false['avg_holding_bars']:+.1f} bars` |")
    md.append(f"| **Long Trades (Win Rate)** | {m_false['long_trades']} ({m_false['long_win_rate']:.1f}%) | {m_true['long_trades']} ({m_true['long_win_rate']:.1f}%) | — |")
    md.append(f"| **Short Trades (Win Rate)** | {m_false['short_trades']} ({m_false['short_win_rate']:.1f}%) | {m_true['short_trades']} ({m_true['short_win_rate']:.1f}%) | — |")
    md.append(f"")
    md.append(f"---")
    md.append(f"")

    # Section 2: Monthly Breakdown
    md.append(f"## 2. Monthly Performance Breakdown (`Concurrent: TRUE`)")
    md.append(f"")
    md.append(f"| Month | Trades | Wins | Losses | Win Rate % | Net Realized PnL (pts) | Profit Factor |")
    md.append(f"| :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for row in month_true:
        md.append(
            f"| **{row['month']}** | {row['trades']} | {row['wins']} | {row['losses']} | "
            f"**{row['win_rate']:.1f}%** | {row['net_pnl']:+,.1f} | {row['profit_factor']:.2f} |"
        )
    md.append(f"")
    md.append(f"---")
    md.append(f"")

    # Section 3: v6.1 Dynamic Stop-Loss Architecture & Breach Diagnostics
    md.append(f"## 3. Dynamic Stop-Loss Architecture & Breach Diagnostics")
    md.append(f"")
    if "sl_mode" in active_df.columns:
        md.append(f"### 3.1 SL Switching Mode (`sl_mode`: `PIVOT` vs `SAFE`)")
        md.append(f"")
        md.append(f"| SL Mode | Trade Count | Share % | Win Rate % | Realized PnL (pts) | Avg Trade PnL |")
        md.append(f"| :--- | :---: | :---: | :---: | :---: | :---: |")
        pnl_col = "pnl" if "pnl" in active_df.columns else "realized_pnl"
        for mode, g_df in active_df.groupby("sl_mode"):
            cnt = len(g_df)
            share = (cnt / len(active_df)) * 100.0
            wr = (len(g_df[g_df[pnl_col] > 0]) / cnt) * 100.0 if cnt > 0 else 0.0
            tot_pnl = float(g_df[pnl_col].sum())
            avg_pnl = tot_pnl / cnt if cnt > 0 else 0.0
            md.append(f"| **`{mode}`** | {cnt} | {share:.1f}% | **{wr:.1f}%** | {tot_pnl:+,.1f} | {avg_pnl:+,.2f} |")
        md.append(f"")

    # SL Breach Timestamps Analysis
    ts_cols = [c for c in active_df.columns if c.endswith("_hit_timestamp")]
    if ts_cols:
        md.append(f"### 3.2 First-Touch Breach Frequency")
        md.append(f"")
        md.append(f"| Breach Signal Column | Breached Trades Count | Breach Frequency % | Description |")
        md.append(f"| :--- | :---: | :---: | :--- |")
        for c in sorted(ts_cols):
            non_null_cnt = int(active_df[c].notna().sum())
            pct = (non_null_cnt / len(active_df)) * 100.0 if len(active_df) > 0 else 0.0
            descr = "First price action breach timestamp"
            if "primary" in c:
                descr = "First-touch breach of active execution SL (`safe` or `pivot`)"
            elif "safe" in c:
                descr = "First-touch breach of safe structural SL"
            elif "pivot" in c:
                descr = "First-touch breach of tight pivot SL"
            elif "base" in c:
                descr = "First-touch breach of baseline swing SL"
            elif "be" in c:
                descr = "First-touch breach of Break-Even level"
            md.append(f"| **`{c}`** | {non_null_cnt:,} | {pct:.1f}% | {descr} |")
        md.append(f"")

    # Section 4: 3-Candle Pattern Setup Distribution
    patt_col = "epatt_1" if "epatt_1" in active_df.columns else ("entry_1" if "entry_1" in active_df.columns else None)
    if patt_col and patt_col in active_df.columns:
        md.append(f"---")
        md.append(f"")
        md.append(f"## 4. 3-Candle Setup Pattern Distribution (`{patt_col}`)")
        md.append(f"")
        md.append(f"| Setup Pattern | Total Trades | Wins | Losses | Win Rate % | Realized PnL (pts) |")
        md.append(f"| :--- | :---: | :---: | :---: | :---: | :---: |")
        pnl_col = "pnl" if "pnl" in active_df.columns else "realized_pnl"
        top_patts = active_df.groupby(patt_col).agg(
            trades=(pnl_col, "count"),
            wins=(pnl_col, lambda s: (s > 0).sum()),
            pnl=(pnl_col, "sum"),
        ).reset_index()
        top_patts["losses"] = top_patts["trades"] - top_patts["wins"]
        top_patts["win_rate"] = (top_patts["wins"] / top_patts["trades"]) * 100.0
        top_patts = top_patts.sort_values(by="trades", ascending=False).head(12)

        for _, r in top_patts.iterrows():
            md.append(
                f"| **`{r[patt_col]}`** | {r['trades']} | {r['wins']} | {r['losses']} | "
                f"**{r['win_rate']:.1f}%** | {r['pnl']:+,.1f} |"
            )
        md.append(f"")

    # Section 5: Database Relations Profiling
    md.append(f"---")
    md.append(f"")
    md.append(f"## 5. DuckDB Database Relations Profiling (`{target_db.name}`)")
    md.append(f"")
    md.append(f"| # | Table / View Name | Row Count | Column Count | Relation Purpose |")
    md.append(f"| :---: | :--- | :---: | :---: | :--- |")
    for idx, tbl in enumerate(tables, 1):
        try:
            r_cnt = con.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
            c_cnt = len(con.execute(f"DESCRIBE {tbl}").fetchall())
        except Exception:
            r_cnt, c_cnt = -1, -1

        purpose = "Database Relation"
        if tbl == "ohlcv":
            purpose = "Resampled market OHLCV price history"
        elif "candel_patters" in tbl:
            purpose = "62-pattern Technical Analysis reference table / view"
        elif "portfolio_metrics" in tbl:
            purpose = "Overall portfolio risk and performance metrics"
        elif "monthly_performance" in tbl:
            purpose = "Aggregated month-by-month performance records"
        elif "equity_curve" in tbl:
            purpose = "Continuous bar-by-bar portfolio value and drawdown timeseries"
        elif "drawdown_events" in tbl:
            purpose = "Peak-to-trough drawdown episodes and recovery metrics"
        elif "sl_risk_summary" in tbl:
            purpose = "Dynamic SL architecture risk distribution (v6.1)"
        elif "concurrent_false" in tbl:
            purpose = "Single active position trade simulations & telemetry"
        elif "concurrent_true" in tbl:
            purpose = "Overlapping / concurrent trade simulations & telemetry"
        elif tbl == "info":
            purpose = "Canonical data dictionary & column metadata"

        md.append(f"| {idx} | **`{tbl}`** | {r_cnt:,} | {c_cnt} | {purpose} |")
    md.append(f"")

    con.close()

    # Write markdown to output path
    output_path.write_text("\n".join(md), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract trade diagnostics from DuckDB and generate a Markdown snapshot in DOCs/NOTEs/{strategy}/."
    )
    parser.add_argument(
        "--target",
        "-t",
        help="Path to target DuckDB database. Defaults to newest in Shared/OUTs/duckdb/.",
    )
    parser.add_argument(
        "--strategy",
        "-s",
        help="Strategy name override (e.g. classic_floor_mod_v6_1).",
    )
    parser.add_argument(
        "--notes-dir",
        help="Destination directory inside DOCs/NOTEs/ (defaults to matching version folder).",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Explicit destination filepath for the Markdown report.",
    )
    parser.add_argument(
        "--filename",
        "-f",
        default="trades-snapshot.md",
        help="Output Markdown filename (default: trades-snapshot.md).",
    )

    args = parser.parse_args()

    target_db = resolve_target_db(_REPO_ROOT, args.target)

    # Detect strategy
    con = duckdb.connect(str(target_db), read_only=True)
    strategy_name = args.strategy or detect_strategy_name(con, target_db)
    con.close()

    # Resolve output path
    if args.output:
        out_file = Path(args.output)
        out_file = _REPO_ROOT / out_file if not out_file.is_absolute() else out_file
        out_file.parent.mkdir(parents=True, exist_ok=True)
    else:
        notes_dir = resolve_notes_dir(_REPO_ROOT, strategy_name, args.notes_dir)
        out_file = notes_dir / args.filename

    console.print(Panel(
        f"[bold cyan]TRADE DIAGNOSTICS & SNAPSHOT GENERATOR[/bold cyan]\n"
        f"Database : [bold white]{target_db}[/bold white]\n"
        f"Strategy : [bold green]{strategy_name}[/bold green]\n"
        f"Output   : [bold yellow]{out_file}[/bold yellow]",
        border_style="cyan"
    ))

    res_path = generate_markdown_snapshot(
        target_db=target_db,
        strategy_name=strategy_name,
        output_path=out_file,
    )

    console.print(f"[bold green]✓ Snapshot successfully written to: {res_path}[/bold green]\n")


if __name__ == "__main__":
    main()
