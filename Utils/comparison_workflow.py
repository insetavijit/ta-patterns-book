#!/usr/bin/env python3
"""
comparison_workflow.py — Sequential MT5 & VectorBT Backtest & Comparison Workflow.

Workflow:
1. Executes MT5 Strategy Tester remotely via headless CLI.
2. Extracts native deal telemetry and exact tested OHLCV series.
3. Executes VectorBT backtest on the identical OHLCV data in blocking mode (allow_concurrent_trades=False).
4. Persists results into a unified DuckDB database: {strategy}-{timestamp}.duckdb containing:
   - ohlcv: Single source OHLCV market history tested
   - mt5_trades: Reconstructed round-trip trades from MT5 Strategy Tester
   - vbt_tsts_tbl: Completed trades from VectorBT/Python engine
   - comparison_summary: Side-by-side execution diagnostics
5. Renders a borderless Rich terminal comparison table.

Usage:
  uv run python Utils/comparison_workflow.py --strategy CFMV0601B --tf 5m --from 2026-09-07 --to 2026-09-11
  uv run python comparision-workflow.py --strategy CFMV0601B --tf 5m
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
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
if str(_REPO_ROOT / "Core") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "Core"))
if str(_REPO_ROOT / "Utils") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "Utils"))
if str(_REPO_ROOT / "Notebooks") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "Notebooks"))

from strategies.registry import get_strategy, list_strategies
from mt5_results_db import (
    parse_mt5_json,
    reconstruct_trades,
    compute_metrics,
    compute_monthly_performance,
    compute_equity_curve_and_drawdowns,
)
from compare_trade_by_trade import (
    match_trades,
    save_comparison_to_db,
    render_trade_by_trade_table,
    render_unmatched_table,
    render_summary_diagnostics,
)

_RUNNER_SCRIPT = _REPO_ROOT / "Core" / "mt5-wsl-tstSetup-01" / "Core" / "run_mt5_test.py"
if not _RUNNER_SCRIPT.exists():
    _RUNNER_SCRIPT = _REPO_ROOT / "Core" / "mt5-wsl-tstSetup-01" / ".tmp" / "run_mt5_test.py"
_DEFAULT_OUT_DIR = _REPO_ROOT / "Shared" / "OUTs" / "duckdb"
_COMMON_FILES_DIR = Path("/mnt/c/Users/avijit/AppData/Roaming/MetaQuotes/Terminal/Common/Files")


def resolve_strategy_instance(strategy_name: str) -> tuple[Any, str]:
    """Retrieve strategy instance and verified canonical name."""
    try:
        strat = get_strategy(strategy_name)
        return strat, strategy_name
    except KeyError:
        # Fallback to direct loading
        candidates = [
            _REPO_ROOT / "Shared" / "strategies" / "classic_floor_mod_v6" / f"{strategy_name}.py",
            _REPO_ROOT / "Core" / "strategies" / f"{strategy_name}.py",
            _REPO_ROOT / "Shared" / "strategies" / f"{strategy_name}.py",
        ]
        target_stem = strategy_name.lower().replace("-", "").replace("_", "")
        for base_dir in [
            _REPO_ROOT / "Shared" / "strategies" / "classic_floor_mod_v6",
            _REPO_ROOT / "Core" / "strategies",
        ]:
            if base_dir.exists():
                for p in base_dir.glob("*.py"):
                    if p.stem.lower().replace("-", "").replace("_", "") == target_stem:
                        candidates.insert(0, p)

        for cand in candidates:
            if cand.exists():
                import importlib.util
                spec = importlib.util.spec_from_file_location(cand.stem.replace("-", "_"), cand)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    candidate_classes = [
                        strategy_name,
                        strategy_name.replace("-", "").replace("_", ""),
                        "CFMV0601C1",
                        "CFMV0601C_1",
                        "CFMV0601C",
                        "CFMV0601B",
                        "Strategy",
                    ]
                    for cls_name in candidate_classes:
                        if hasattr(mod, cls_name):
                            inst = getattr(mod, cls_name)()
                            return inst, strategy_name
                    for attr_name in dir(mod):
                        attr = getattr(mod, attr_name)
                        if isinstance(attr, type) and hasattr(attr, "generate_signals") and not attr_name.startswith("_"):
                            return attr(), strategy_name
        raise ValueError(f"Could not resolve strategy: {strategy_name}")


def run_mt5_backtest(
    strategy: str,
    symbol: str,
    period: str,
    from_date: str,
    to_date: str,
    console: Console,
    timeout: int = 180,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Execute MT5 Strategy Tester and retrieve telemetry and OHLCV."""
    console.print(f"\n[bold cyan]▶ Step 1: Running MetaTrader 5 Strategy Tester ({strategy} | {symbol} {period})...[/bold cyan]")
    cmd = [
        sys.executable,
        str(_RUNNER_SCRIPT),
        "--strategy", strategy,
        "--symbol", symbol,
        "--period", period,
        "--from", from_date,
        "--to", to_date,
        "--timeout", str(timeout),
    ]
    res = subprocess.run(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"MT5 backtest execution failed with return code {res.returncode}")

    json_path = _REPO_ROOT / "outs" / f"{strategy}_results.json"
    if not json_path.exists():
        json_path = _COMMON_FILES_DIR / f"{strategy}_results.json"
    raw_json = parse_mt5_json(json_path)

    # Load OHLCV CSV
    ohlcv_candidates = [
        _REPO_ROOT / "outs" / f"{strategy}_ohlcv.csv",
        _COMMON_FILES_DIR / f"{strategy}_ohlcv.csv",
    ]
    df_ohlcv = None
    for cand in ohlcv_candidates:
        if cand.exists() and cand.stat().st_size > 50:
            df_ohlcv = pd.read_csv(cand)
            break

    if df_ohlcv is None:
        raise FileNotFoundError(f"Could not locate OHLCV CSV for strategy {strategy}")

    df_ohlcv["timestamp"] = pd.to_datetime(df_ohlcv["timestamp"].astype(str).str.replace(".", "-", regex=False), utc=True)
    df_ohlcv = df_ohlcv.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)

    return raw_json, df_ohlcv


def run_vbt_backtest(
    strategy_name: str,
    df_ohlcv: pd.DataFrame,
    console: Console,
) -> list[dict[str, Any]]:
    """Execute VectorBT backtest on exact same OHLCV."""
    is_blocking = "b" in strategy_name.lower()
    mode_str = "Blocking: Concurrent=False" if is_blocking else "Concurrent: Non-Blocking"
    console.print(f"\n[bold cyan]▶ Step 2: Running VectorBT Engine ({strategy_name} | {mode_str})...[/bold cyan]")
    strat_inst, _ = resolve_strategy_instance(strategy_name)

    df_feed = df_ohlcv.copy()
    if "timestamp" in df_feed.columns and not isinstance(df_feed.index, pd.DatetimeIndex):
        df_feed = df_feed.set_index("timestamp").sort_index()

    # Pass appropriate blocking mode if applicable
    params = {"allow_concurrent_trades": False} if is_blocking else {}
    res = strat_inst.generate_signals(df_feed, params=params)

    completed_trades = getattr(strat_inst, "completed_trades", [])
    if not completed_trades:
        # Check if inner wrapped object has completed_trades
        inner = getattr(strat_inst, "_inner", None)
        if inner:
            completed_trades = getattr(inner, "completed_trades", [])
        elif isinstance(res, tuple) and len(res) == 3 and isinstance(res[2], pd.DataFrame) and not res[2].empty:
            completed_trades = res[2].to_dict("records")

    return completed_trades


def calculate_trade_metrics(trades: list[dict[str, Any]], initial_cash: float = 10000.0) -> dict[str, Any]:
    """Derive standardized summary statistics from a trade list."""
    total_trades = len(trades)
    if total_trades == 0:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "win_rate_pct": 0.0,
            "net_pnl": 0.0, "gross_profit": 0.0, "gross_loss": 0.0,
            "profit_factor": 0.0, "max_drawdown": 0.0, "payoff_ratio": 0.0,
        }

    pnls = [float(t.get("pnl", 0.0)) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    net_pnl = sum(pnls)

    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / total_trades * 100.0) if total_trades > 0 else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

    avg_win = (gross_profit / win_count) if win_count > 0 else 0.0
    avg_loss = (gross_loss / loss_count) if loss_count > 0 else 0.0
    payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0

    cum_cash = initial_cash
    peak_cash = initial_cash
    max_dd = 0.0
    for p in pnls:
        cum_cash += p
        if cum_cash > peak_cash:
            peak_cash = cum_cash
        dd = peak_cash - cum_cash
        if dd > max_dd:
            max_dd = dd

    return {
        "total_trades": total_trades,
        "wins": win_count,
        "losses": loss_count,
        "win_rate_pct": win_rate,
        "net_pnl": net_pnl,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "max_drawdown": max_dd,
        "payoff_ratio": payoff_ratio,
    }


def persist_combined_database(
    target_db_path: Path,
    df_ohlcv: pd.DataFrame,
    mt5_trades: list[dict[str, Any]],
    vbt_trades: list[dict[str, Any]],
    comp_rows: list[dict[str, Any]],
    strategy_name: str,
    symbol: str,
    period: str,
    initial_cash: float = 10000.0,
) -> tuple[int, list[str], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], pd.DataFrame, pd.DataFrame]:
    """Save all datasets into a single DuckDB file with standardized tables."""
    target_db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(target_db_path))
    created_tables: list[str] = []

    # 1. Table: ohlcv
    con.register("df_ohlcv_tmp", df_ohlcv)
    con.execute("CREATE OR REPLACE TABLE ohlcv AS SELECT * FROM df_ohlcv_tmp")
    created_tables.append("ohlcv")

    # 2. Table: mt5_trades
    df_mt5 = pd.DataFrame(mt5_trades)
    if not df_mt5.empty:
        if "uid" not in df_mt5.columns:
            df_mt5.insert(0, "uid", range(1, len(df_mt5) + 1))
        con.register("df_mt5_tmp", df_mt5)
        con.execute("CREATE OR REPLACE TABLE mt5_trades AS SELECT * FROM df_mt5_tmp")
    else:
        con.execute("CREATE OR REPLACE TABLE mt5_trades (uid BIGINT, trade_id BIGINT, pnl DOUBLE)")
    created_tables.append("mt5_trades")

    # 3. Table: vbt_trades (+ vbt_tsts_tbl alias for backwards compatibility)
    df_vbt = pd.DataFrame(vbt_trades)
    if not df_vbt.empty:
        if "uid" not in df_vbt.columns:
            df_vbt.insert(0, "uid", range(1, len(df_vbt) + 1))
        con.register("df_vbt_tmp", df_vbt)
        con.execute("CREATE OR REPLACE TABLE vbt_trades AS SELECT * FROM df_vbt_tmp")
        con.execute("CREATE OR REPLACE VIEW vbt_tsts_tbl AS SELECT * FROM vbt_trades")
    else:
        con.execute("CREATE OR REPLACE TABLE vbt_trades (uid BIGINT, trade_id BIGINT, pnl DOUBLE)")
        con.execute("CREATE OR REPLACE VIEW vbt_tsts_tbl AS SELECT * FROM vbt_trades")
    created_tables.extend(["vbt_trades", "vbt_tsts_tbl"])

    # 4. Table: comparison_summary
    df_comp = pd.DataFrame(comp_rows)
    con.register("df_comp_tmp", df_comp)
    con.execute("CREATE OR REPLACE TABLE comparison_summary AS SELECT * FROM df_comp_tmp")
    created_tables.append("comparison_summary")

    # 5. MT5 Sub-tables: mt5_metrics, mt5_monthly_performance, mt5_equity_curve, mt5_drawdown_events
    mt5_m = compute_metrics(mt5_trades, initial_cash=initial_cash, strategy_name=strategy_name, symbol=symbol, period=period)
    df_mt5_m = pd.DataFrame([mt5_m])
    con.register("df_mt5_m_tmp", df_mt5_m)
    con.execute("CREATE OR REPLACE TABLE mt5_metrics AS SELECT * FROM df_mt5_m_tmp")
    created_tables.append("mt5_metrics")

    mt5_monthly = compute_monthly_performance(mt5_trades, strategy_name=strategy_name)
    df_mt5_monthly = pd.DataFrame(mt5_monthly) if mt5_monthly else pd.DataFrame([{"strategy_name": strategy_name, "year": None, "month": None, "trades": 0, "net_pnl": 0.0}])
    con.register("df_mt5_monthly_tmp", df_mt5_monthly)
    con.execute("CREATE OR REPLACE TABLE mt5_monthly_performance AS SELECT * FROM df_mt5_monthly_tmp")
    created_tables.append("mt5_monthly_performance")

    mt5_equity, mt5_drawdowns = compute_equity_curve_and_drawdowns(mt5_trades, initial_cash=initial_cash, strategy_name=strategy_name)
    df_mt5_equity = pd.DataFrame(mt5_equity) if mt5_equity else pd.DataFrame([{"trade_number": 0, "balance": initial_cash}])
    con.register("df_mt5_equity_tmp", df_mt5_equity)
    con.execute("CREATE OR REPLACE TABLE mt5_equity_curve AS SELECT * FROM df_mt5_equity_tmp")
    created_tables.append("mt5_equity_curve")

    df_mt5_dd = pd.DataFrame(mt5_drawdowns) if mt5_drawdowns else pd.DataFrame([{"drawdown_id": 1, "strategy_name": strategy_name, "drawdown_pct": 0.0}])
    con.register("df_mt5_dd_tmp", df_mt5_dd)
    con.execute("CREATE OR REPLACE TABLE mt5_drawdown_events AS SELECT * FROM df_mt5_dd_tmp")
    created_tables.append("mt5_drawdown_events")

    # 6. VBT Sub-tables: vbt_metrics, vbt_monthly_performance, vbt_equity_curve, vbt_drawdown_events
    vbt_m = compute_metrics(vbt_trades, initial_cash=initial_cash, strategy_name=strategy_name, symbol=symbol, period=period)
    df_vbt_m = pd.DataFrame([vbt_m])
    con.register("df_vbt_m_tmp", df_vbt_m)
    con.execute("CREATE OR REPLACE TABLE vbt_metrics AS SELECT * FROM df_vbt_m_tmp")
    created_tables.append("vbt_metrics")

    vbt_monthly = compute_monthly_performance(vbt_trades, strategy_name=strategy_name)
    df_vbt_monthly = pd.DataFrame(vbt_monthly) if vbt_monthly else pd.DataFrame([{"strategy_name": strategy_name, "year": None, "month": None, "trades": 0, "net_pnl": 0.0}])
    con.register("df_vbt_monthly_tmp", df_vbt_monthly)
    con.execute("CREATE OR REPLACE TABLE vbt_monthly_performance AS SELECT * FROM df_vbt_monthly_tmp")
    created_tables.append("vbt_monthly_performance")

    vbt_equity, vbt_drawdowns = compute_equity_curve_and_drawdowns(vbt_trades, initial_cash=initial_cash, strategy_name=strategy_name)
    df_vbt_equity = pd.DataFrame(vbt_equity) if vbt_equity else pd.DataFrame([{"trade_number": 0, "balance": initial_cash}])
    con.register("df_vbt_equity_tmp", df_vbt_equity)
    con.execute("CREATE OR REPLACE TABLE vbt_equity_curve AS SELECT * FROM df_vbt_equity_tmp")
    created_tables.append("vbt_equity_curve")

    df_vbt_dd = pd.DataFrame(vbt_drawdowns) if vbt_drawdowns else pd.DataFrame([{"drawdown_id": 1, "strategy_name": strategy_name, "drawdown_pct": 0.0}])
    con.register("df_vbt_dd_tmp", df_vbt_dd)
    con.execute("CREATE OR REPLACE TABLE vbt_drawdown_events AS SELECT * FROM df_vbt_dd_tmp")
    created_tables.append("vbt_drawdown_events")

    con.close()

    # 7. Table: trades_comparision (and alias trade_by_trade_comparison)
    df_mt5_norm = df_mt5.copy() if not df_mt5.empty else pd.DataFrame()
    df_vbt_norm = df_vbt.copy() if not df_vbt.empty else pd.DataFrame()
    for df_n in (df_mt5_norm, df_vbt_norm):
        if df_n.empty:
            continue
        for t_col in ["entry_time", "exit_time"]:
            if t_col in df_n.columns:
                df_n[t_col] = pd.to_datetime(df_n[t_col].astype(str).str.replace(".", "-", regex=False), utc=True)
        for num_col in ["entry_price", "exit_price", "pnl"]:
            if num_col in df_n.columns:
                df_n[num_col] = pd.to_numeric(df_n[num_col], errors="coerce")

    matched_pairs, unmatched1, unmatched2 = match_trades(
        df1=df_mt5_norm,
        df2=df_vbt_norm,
        name1="mt5_trades",
        name2="vbt_trades",
    )
    comp_count = save_comparison_to_db(
        db_path=target_db_path,
        matched_pairs=matched_pairs,
        unmatched1=unmatched1,
        unmatched2=unmatched2,
        name1="mt5_trades",
        name2="vbt_trades",
        table_name="trades_comparision",
    )
    created_tables.extend(["trades_comparision", "trade_by_trade_comparison"])

    return comp_count, created_tables, matched_pairs, unmatched1, unmatched2, df_mt5_norm, df_vbt_norm


def render_comparison_table(
    strategy_name: str,
    mt5_metrics: dict[str, Any],
    vbt_metrics: dict[str, Any],
    ohlcv_count: int,
    comp_trades_count: int,
    created_tables: list[str],
    db_path: Path,
    console: Console,
) -> list[dict[str, Any]]:
    """Render a borderless Rich comparison table."""
    table = Table(title=f"Execution Comparison — {strategy_name}", box=None, header_style="bold magenta")
    table.add_column("Performance Metric", style="bold cyan")
    table.add_column("MetaTrader 5 Engine", justify="right")
    table.add_column("VectorBT Engine", justify="right")
    table.add_column("Delta (VBT - MT5)", justify="right")

    m_cnt, v_cnt = mt5_metrics["total_trades"], vbt_metrics["total_trades"]
    m_wr, v_wr = mt5_metrics["win_rate_pct"], vbt_metrics["win_rate_pct"]
    m_pnl, v_pnl = mt5_metrics["net_pnl"], vbt_metrics["net_pnl"]
    m_pf, v_pf = mt5_metrics["profit_factor"], vbt_metrics["profit_factor"]
    m_dd, v_dd = mt5_metrics["max_drawdown"], vbt_metrics["max_drawdown"]
    m_payoff, v_payoff = mt5_metrics["payoff_ratio"], vbt_metrics["payoff_ratio"]

    comp_rows = [
        {"metric": "Total Executed Trades", "mt5_value": str(m_cnt), "vbt_value": str(v_cnt), "delta": f"{v_cnt - m_cnt:+d}"},
        {"metric": "Win Rate %", "mt5_value": f"{m_wr:.2f}%", "vbt_value": f"{v_wr:.2f}%", "delta": f"{v_wr - m_wr:+.2f}%"},
        {"metric": "Realized Net PnL ($)", "mt5_value": f"${m_pnl:+,.2f}", "vbt_value": f"${v_pnl:+,.2f}", "delta": f"${v_pnl - m_pnl:+,.2f}"},
        {"metric": "Profit Factor", "mt5_value": f"{m_pf:.2f}", "vbt_value": f"{v_pf:.2f}", "delta": f"{v_pf - m_pf:+.2f}"},
        {"metric": "Max Drawdown ($)", "mt5_value": f"${m_dd:,.2f}", "vbt_value": f"${v_dd:,.2f}", "delta": f"${v_dd - m_dd:+,.2f}"},
        {"metric": "Payoff Ratio", "mt5_value": f"{m_payoff:.2f}", "vbt_value": f"{v_payoff:.2f}", "delta": f"{v_payoff - m_payoff:+.2f}"},
    ]

    for row in comp_rows:
        table.add_row(row["metric"], row["mt5_value"], row["vbt_value"], row["delta"])

    console.print("\n")
    console.print(table)
    console.print(f"\n[bold green]✓ Database Saved:[/bold green] {db_path}")
    console.print(f"  • [bold]ohlcv[/bold] ({ohlcv_count:,} bars)")
    console.print(f"  • [bold]mt5_trades[/bold] ({m_cnt} trades)")
    console.print(f"  • [bold]vbt_trades[/bold] / [bold]vbt_tsts_tbl[/bold] ({v_cnt} trades)")
    console.print(f"  • [bold]trades_comparision[/bold] ({comp_trades_count} rows)")
    console.print(f"  • [bold]mt5_* tables[/bold] (mt5_metrics, mt5_monthly_performance, mt5_equity_curve, mt5_drawdown_events)")
    console.print(f"  • [bold]vbt_* tables[/bold] (vbt_metrics, vbt_monthly_performance, vbt_equity_curve, vbt_drawdown_events)")
    console.print(f"  • [bold]comparison_summary[/bold] ({len(comp_rows)} metrics)\n")

    return comp_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Automated Comparison Workflow: MT5 vs VectorBT.")
    parser.add_argument("--strategy", "-s", default="CFMV0601B", help="Active strategy name")
    parser.add_argument("--symbol", default="EURUSDm", help="Market symbol ticker")
    parser.add_argument("--tf", "--timeframe", default="5m", help="Testing timeframe (e.g. 1m, 5m, 15m)")
    parser.add_argument("--from-date", "--from", default="2026-09-07", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to-date", "--to", default="2026-09-11", help="End date (YYYY-MM-DD)")
    parser.add_argument("--out-dir", default=str(_DEFAULT_OUT_DIR), help="Output directory for DuckDB")
    parser.add_argument("--db", default=None, help="Explicit target DuckDB path")
    parser.add_argument("--timeout", type=int, default=300, help="Max wait timeout in seconds for MT5 backtest")

    args = parser.parse_args()
    console = Console()
    if console.width < 140:
        console.size = (140, console.height or 40)

    console.print("[bold yellow]══════════════════════════════════════════════════════════[/bold yellow]")
    console.print(f"[bold]        Sequential MT5 & VectorBT Comparison Workflow[/bold]")
    is_blk = "b" in args.strategy.lower()
    mode_desc = "Blocking Mode: Concurrent=False" if is_blk else "Concurrent Mode: Non-Blocking"
    console.print(f" Strategy : [bold yellow]{args.strategy}[/bold yellow] ({mode_desc})")
    console.print(f" Symbol/TF: [bold]{args.symbol}[/bold] / [bold]{args.tf}[/bold] | {args.from_date} -> {args.to_date}")
    console.print("[bold yellow]══════════════════════════════════════════════════════════[/bold yellow]")

    # Normalize timeframe format for MT5
    tf_clean = args.tf.upper().replace("PERIOD_", "")
    mt5_period = tf_clean if tf_clean.startswith("M") or tf_clean.startswith("H") or tf_clean.startswith("D") else f"M{tf_clean.replace('M', '')}"

    # Step 1: Run MT5 backtest
    raw_mt5_json, df_ohlcv = run_mt5_backtest(
        strategy=args.strategy,
        symbol=args.symbol,
        period=mt5_period,
        from_date=args.from_date,
        to_date=args.to_date,
        console=console,
        timeout=args.timeout,
    )
    mt5_trades = reconstruct_trades(raw_mt5_json)

    # Step 2: Run VectorBT backtest on same OHLCV
    vbt_trades = run_vbt_backtest(
        strategy_name=args.strategy,
        df_ohlcv=df_ohlcv,
        console=console,
    )

    # Step 3: Compute comparative metrics
    mt5_metrics = calculate_trade_metrics(mt5_trades)
    vbt_metrics = calculate_trade_metrics(vbt_trades)

    # Step 4: Resolve target DuckDB path: {strategy}-{timestamp}.duckdb
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if args.db:
        target_db = Path(args.db)
    else:
        out_dir = Path(args.out_dir)
        target_db = out_dir / f"{args.strategy}-{timestamp_str}.duckdb"

    # Preliminary comp rows for storage
    initial_comp_rows = [
        {"metric": "Total Executed Trades", "mt5_value": str(mt5_metrics["total_trades"]), "vbt_value": str(vbt_metrics["total_trades"]), "delta": f"{vbt_metrics['total_trades'] - mt5_metrics['total_trades']:+d}"},
        {"metric": "Win Rate %", "mt5_value": f"{mt5_metrics['win_rate_pct']:.2f}%", "vbt_value": f"{vbt_metrics['win_rate_pct']:.2f}%", "delta": f"{vbt_metrics['win_rate_pct'] - mt5_metrics['win_rate_pct']:+.2f}%"},
        {"metric": "Realized Net PnL ($)", "mt5_value": f"${mt5_metrics['net_pnl']:+,.2f}", "vbt_value": f"${vbt_metrics['net_pnl']:+,.2f}", "delta": f"${vbt_metrics['net_pnl'] - mt5_metrics['net_pnl']:+,.2f}"},
        {"metric": "Profit Factor", "mt5_value": f"{mt5_metrics['profit_factor']:.2f}", "vbt_value": f"{vbt_metrics['profit_factor']:.2f}", "delta": f"{vbt_metrics['profit_factor'] - mt5_metrics['profit_factor']:+.2f}"},
        {"metric": "Max Drawdown ($)", "mt5_value": f"${mt5_metrics['max_drawdown']:,.2f}", "vbt_value": f"${vbt_metrics['max_drawdown']:,.2f}", "delta": f"${vbt_metrics['max_drawdown'] - mt5_metrics['max_drawdown']:+,.2f}"},
        {"metric": "Payoff Ratio", "mt5_value": f"{mt5_metrics['payoff_ratio']:.2f}", "vbt_value": f"{vbt_metrics['payoff_ratio']:.2f}", "delta": f"{vbt_metrics['payoff_ratio'] - mt5_metrics['payoff_ratio']:+.2f}"},
    ]

    # Step 5: Persist everything to unified DuckDB (including mt5_*, vbt_*, trades_comparision)
    comp_count, created_tables, matched_pairs, unmatched1, unmatched2, df_mt5_norm, df_vbt_norm = persist_combined_database(
        target_db_path=target_db,
        df_ohlcv=df_ohlcv,
        mt5_trades=mt5_trades,
        vbt_trades=vbt_trades,
        comp_rows=initial_comp_rows,
        strategy_name=args.strategy,
        symbol=args.symbol,
        period=mt5_period,
    )

    # Step 6: Perform Trade-by-Trade Comparison at End
    console.print(f"\n[bold yellow]═══════════════════════════════════════════════════════════════════════════════[/bold yellow]")
    console.print(f"             [bold]Step 3: End-of-Workflow Trade Alignment Comparison[/bold]")
    console.print(f" Database : [bold green]{target_db}[/bold green]")
    console.print(f" Tables   : [bold cyan]mt5_trades[/bold cyan] ({len(mt5_trades)} trades)  ⟷  [bold cyan]vbt_trades[/bold cyan] ({len(vbt_trades)} trades)")
    console.print(f"[bold yellow]═══════════════════════════════════════════════════════════════════════════════[/bold yellow]")

    render_trade_by_trade_table(matched_pairs, "mt5_trades", "vbt_trades", console)
    if unmatched1 or unmatched2:
        render_unmatched_table(unmatched1, unmatched2, "mt5_trades", "vbt_trades", console)
    render_summary_diagnostics(df_mt5_norm, df_vbt_norm, matched_pairs, unmatched1, unmatched2, "mt5_trades", "vbt_trades", console)

    # Step 7: Render Summary Comparison Table
    render_comparison_table(
        strategy_name=args.strategy,
        mt5_metrics=mt5_metrics,
        vbt_metrics=vbt_metrics,
        ohlcv_count=len(df_ohlcv),
        comp_trades_count=comp_count,
        created_tables=created_tables,
        db_path=target_db,
        console=console,
    )


if __name__ == "__main__":
    main()
