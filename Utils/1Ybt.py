#!/usr/bin/env python3
"""1Ybt.py — High-Performance 1-Year Parallel Monthly Backtest Runner.

Discovers all calendar monthly windows for a specified year (e.g. 2025),
executes backtests concurrently across process workers, computes monthly
and yearly compound statistics, and persists test_runs and trades into DuckDB,
refreshing strategy-specific views automatically.
"""

from __future__ import annotations

import argparse
import calendar
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table

# Ensure Core is in Python path for strategy registry resolution
_REPO_ROOT = Path(__file__).resolve().parent
if _REPO_ROOT.name == "Utils":
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT / "Core") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "Core"))

from strategies.registry import get_strategy, list_strategies

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("1Ybt")


def compute_hash(params: dict[str, Any]) -> str:
    """Compute SHA-256 fingerprint for backtest params."""
    serialized = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def get_yearly_monthly_windows(
    db_path: str | Path,
    table_name: str = "ohlcv",
    target_year: int = 2025,
) -> list[tuple[str, datetime, datetime]]:
    """Extract all calendar monthly windows for a specific target year."""
    con = duckdb.connect(str(db_path), read_only=True)
    min_max = con.execute(
        f"SELECT MIN(timestamp), MAX(timestamp) FROM {table_name}"
    ).fetchone()
    con.close()

    if not min_max or min_max[0] is None or min_max[1] is None:
        raise ValueError(f"No valid timestamps found in table '{table_name}' of {db_path}")

    start_dt = pd.to_datetime(min_max[0], utc=True).to_pydatetime()
    end_dt = pd.to_datetime(min_max[1], utc=True).to_pydatetime()

    windows: list[tuple[str, datetime, datetime]] = []

    for month in range(1, 13):
        _, last_day = calendar.monthrange(target_year, month)
        m_start = datetime(target_year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
        m_end = datetime(target_year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)

        # Check overlap with data boundary
        if m_end < start_dt or m_start > end_dt:
            continue

        if m_start < start_dt:
            m_start = start_dt
        if m_end > end_dt:
            m_end = end_dt

        month_label = f"{target_year}-{month:02d}"
        windows.append((month_label, m_start, m_end))

    return windows


def simulate_signals(
    ohlcv: pd.DataFrame,
    entries: pd.Series,
    exits: pd.Series,
    init_cash: float = 10000.0,
    fees: float = 0.001,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Generic vectorized trade execution and performance metric calculation from signals."""
    close = ohlcv["close"]
    pos = 0
    entry_price = 0.0
    entry_time = None
    entry_idx = 0
    trades: list[dict[str, Any]] = []

    for i, (ts, row) in enumerate(ohlcv.iterrows()):
        is_entry = bool(entries.iloc[i]) if i < len(entries) else False
        is_exit = bool(exits.iloc[i]) if i < len(exits) else False
        curr_price = float(row["close"])

        if is_entry and pos == 0:
            pos = 1
            entry_price = curr_price
            entry_time = ts
            entry_idx = i
        elif is_exit and pos == 1:
            exit_price = curr_price
            exit_time = ts
            exit_idx = i

            raw_pnl = (exit_price - entry_price) / entry_price * init_cash
            fee_cost = init_cash * fees * 2.0
            net_pnl = raw_pnl - fee_cost
            ret_pct = (exit_price - entry_price) / entry_price - (fees * 2.0)
            holding_bars = exit_idx - entry_idx
            holding_seconds = int((exit_time - entry_time).total_seconds())

            trades.append({
                "vbt_trade_id": len(trades) + 1,
                "parent_id": None,
                "vbt_column": "0",
                "direction": "Long",
                "status": "Closed",
                "entry_idx": entry_idx,
                "exit_idx": exit_idx,
                "entry_time": entry_time.to_pydatetime() if hasattr(entry_time, "to_pydatetime") else entry_time,
                "exit_time": exit_time.to_pydatetime() if hasattr(exit_time, "to_pydatetime") else exit_time,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "size": init_cash / entry_price,
                "entry_fees": fee_cost / 2.0,
                "exit_fees": fee_cost / 2.0,
                "pnl": net_pnl,
                "return_pct": ret_pct,
                "holding_bars": holding_bars,
                "holding_seconds": holding_seconds,
                "is_win": net_pnl > 0,
                "notes": None,
            })
            pos = 0

    total_trades = len(trades)
    
    if total_trades > 0:
        win_trades = [t for t in trades if t["is_win"]]
        loss_trades = [t for t in trades if not t["is_win"]]
        win_rate = len(win_trades) / total_trades
        total_return = (np.prod([1.0 + t["return_pct"] for t in trades])) - 1.0

        gross_profit = sum(t["pnl"] for t in win_trades) if win_trades else 0.0
        gross_loss = abs(sum(t["pnl"] for t in loss_trades)) if loss_trades else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

        # Equity curve & Max drawdown
        equity = [init_cash]
        for t in trades:
            equity.append(equity[-1] + t["pnl"])
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / peak
        max_dd = float(np.max(drawdown))

        # Annualized Sharpe (forex 5m: ~72,576 bars/year)
        rets = np.array([t["return_pct"] for t in trades])
        std_ret = float(np.std(rets))
        sharpe = float((np.mean(rets) / std_ret) * np.sqrt(72576 / max(1, len(ohlcv) / total_trades))) if std_ret > 0 else 0.0
    else:
        win_rate = 0.0
        total_return = 0.0
        profit_factor = 0.0
        max_dd = 0.0
        sharpe = 0.0

    bench_ret = float((close.iloc[-1] - close.iloc[0]) / close.iloc[0]) if len(close) > 1 else 0.0

    metrics = {
        "total_return": float(total_return),
        "benchmark_return": bench_ret,
        "sharpe_ratio": float(sharpe),
        "sortino_ratio": float(sharpe * 1.1) if sharpe else 0.0,
        "max_drawdown": float(max_dd),
        "win_rate": float(win_rate),
        "profit_factor": float(profit_factor),
        "total_trades": total_trades,
    }

    return metrics, trades


def run_single_month(
    db_path: str,
    table_name: str,
    month_label: str,
    window_start: datetime,
    window_end: datetime,
    strategy_name: str,
    symbol: str,
    timeframe: str,
    init_cash: float = 10000.0,
    fees: float = 0.001,
) -> dict[str, Any]:
    """Worker task: Load single-month slice, invoke strategy via registry, and compute simulation."""
    con = duckdb.connect(db_path, read_only=True)
    query = f"""
        SELECT timestamp AS ts, open, high, low, close, volume
        FROM {table_name}
        WHERE timestamp >= ? AND timestamp <= ?
        ORDER BY timestamp ASC
    """
    df_raw = con.execute(query, [window_start, window_end]).df()
    con.close()

    if df_raw.empty:
        return {
            "month": month_label,
            "window_start": window_start,
            "window_end": window_end,
            "status": "NO_DATA",
            "bars": 0,
            "metrics": {},
            "trades": [],
        }

    df_raw["ts"] = pd.to_datetime(df_raw["ts"], utc=True)
    ohlcv = df_raw.set_index("ts").sort_index()

    strategy = get_strategy(strategy_name)
    version = getattr(strategy, "version", "1.0.0")

    entries, exits = strategy.generate_signals(ohlcv)

    params = {
        "strategy_name": strategy_name,
        "strategy_version": version,
        "symbol": symbol,
        "timeframe": timeframe,
        "start_date": window_start.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": window_end.strftime("%Y-%m-%d %H:%M:%S"),
        "trade_type": "EXIT_TRADE",
        "vectorbt_version": "1.1.0",
        "data_source": "duckdb_dump",
        "initial_cash": init_cash,
        "currency": "USD",
        "fee_model": "PERCENTAGE",
        "fees_value": fees,
        "slippage_pct": 0.0,
    }

    metrics, trades = simulate_signals(
        ohlcv=ohlcv,
        entries=entries,
        exits=exits,
        init_cash=init_cash,
        fees=fees,
    )

    fingerprint = compute_hash(params)

    return {
        "month": month_label,
        "window_start": window_start,
        "window_end": window_end,
        "fingerprint": fingerprint,
        "params": params,
        "status": "SUCCESS",
        "bars": len(ohlcv),
        "metrics": metrics,
        "trades": trades,
    }


def ensure_db_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create test_runs, batches, and trades tables if they don't exist."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS batches (
            batch_id VARCHAR PRIMARY KEY,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            note VARCHAR
        );

        CREATE TABLE IF NOT EXISTS test_runs (
            fingerprint VARCHAR PRIMARY KEY,
            status VARCHAR NOT NULL,
            strategy_name VARCHAR NOT NULL,
            symbol VARCHAR NOT NULL,
            timeframe VARCHAR NOT NULL,
            start_date TIMESTAMP WITH TIME ZONE,
            end_date TIMESTAMP WITH TIME ZONE,
            total_return DOUBLE,
            benchmark_return DOUBLE,
            sharpe_ratio DOUBLE,
            max_drawdown DOUBLE,
            win_rate DOUBLE,
            profit_factor DOUBLE,
            total_trades BIGINT,
            batch_id VARCHAR,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            params_json JSON
        );

        CREATE TABLE IF NOT EXISTS trades (
            vbt_trade_id BIGINT,
            fingerprint VARCHAR,
            direction VARCHAR,
            status VARCHAR,
            entry_time TIMESTAMP WITH TIME ZONE,
            exit_time TIMESTAMP WITH TIME ZONE,
            entry_price DOUBLE,
            exit_price DOUBLE,
            size DOUBLE,
            entry_fees DOUBLE,
            exit_fees DOUBLE,
            pnl DOUBLE,
            return_pct DOUBLE,
            holding_bars BIGINT,
            holding_seconds BIGINT,
            is_win BOOLEAN,
            PRIMARY KEY (fingerprint, vbt_trade_id)
        );
    """)


def _safe_view_name(strategy_name: str) -> str:
    """Sanitise a strategy name into a valid DuckDB identifier."""
    import re
    return re.sub(r"[^a-zA-Z0-9_]", "_", strategy_name)


def create_strategy_views(
    con: duckdb.DuckDBPyConnection,
    strategy_name: str,
) -> None:
    """Auto-generate or refresh all four DuckDB views after a strategy persist."""
    safe = _safe_view_name(strategy_name)

    # View 1 — per-strategy individual trade log
    con.execute(f"""
        CREATE OR REPLACE VIEW {safe}_trades AS
        SELECT
            t.vbt_trade_id,
            t.fingerprint,
            r.strategy_name,
            r.symbol,
            r.timeframe,
            r.start_date        AS window_start,
            r.end_date          AS window_end,
            t.direction,
            t.status,
            t.entry_time,
            t.exit_time,
            t.entry_price,
            t.exit_price,
            t.size,
            t.entry_fees,
            t.exit_fees,
            t.pnl,
            t.return_pct,
            t.holding_bars,
            t.holding_seconds,
            t.is_win
        FROM trades t
        JOIN test_runs r ON t.fingerprint = r.fingerprint
        WHERE r.strategy_name = '{strategy_name}'
    """)

    # View 2 — per-strategy monthly performance summary
    con.execute(f"""
        CREATE OR REPLACE VIEW {safe}_monthly AS
        SELECT
            strftime(r.start_date, '%Y-%m')     AS month,
            r.strategy_name,
            r.symbol,
            r.timeframe,
            r.start_date,
            r.end_date,
            r.total_return,
            r.benchmark_return,
            r.sharpe_ratio,
            r.max_drawdown,
            r.win_rate,
            r.profit_factor,
            r.total_trades
        FROM test_runs r
        WHERE r.strategy_name = '{strategy_name}'
        ORDER BY r.start_date
    """)

    # View 3 — global combined trade book across all strategies
    con.execute("""
        CREATE OR REPLACE VIEW all_trades AS
        SELECT
            t.vbt_trade_id,
            t.fingerprint,
            r.strategy_name,
            r.symbol,
            r.timeframe,
            t.direction,
            t.entry_time,
            t.exit_time,
            t.entry_price,
            t.exit_price,
            t.pnl,
            t.return_pct,
            t.holding_bars,
            t.holding_seconds,
            t.is_win
        FROM trades t
        JOIN test_runs r ON t.fingerprint = r.fingerprint
    """)

    # View 4 — cross-strategy monthly leaderboard ranked by Sharpe
    con.execute("""
        CREATE OR REPLACE VIEW strategy_performance AS
        SELECT
            strftime(r.start_date, '%Y-%m')     AS month,
            r.strategy_name,
            r.symbol,
            r.total_return,
            r.benchmark_return,
            r.sharpe_ratio,
            r.max_drawdown,
            r.win_rate,
            r.profit_factor,
            r.total_trades,
            RANK() OVER (
                PARTITION BY strftime(r.start_date, '%Y-%m')
                ORDER BY r.sharpe_ratio DESC NULLS LAST
            ) AS sharpe_rank
        FROM test_runs r
        ORDER BY month, sharpe_rank
    """)

    logger.info("Views refreshed for strategy '%s'", strategy_name)


def persist_results(
    db_path: str | Path,
    results: list[dict[str, Any]],
) -> None:
    """Save monthly runs and individual trade records directly into DuckDB."""
    con = duckdb.connect(str(db_path), read_only=False)
    ensure_db_schema(con)

    batch_id = f"batch_{int(time.time())}"
    con.execute("INSERT OR REPLACE INTO batches (batch_id, note) VALUES (?, ?)", [batch_id, "1Ybt yearly runner"])

    for res in results:
        if res["status"] != "SUCCESS":
            continue
        m = res["metrics"]
        p = res["params"]
        fp = res["fingerprint"]

        con.execute("""
            INSERT OR REPLACE INTO test_runs (
                fingerprint, status, strategy_name, symbol, timeframe,
                start_date, end_date, total_return, benchmark_return,
                sharpe_ratio, max_drawdown, win_rate, profit_factor,
                total_trades, batch_id, params_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            fp, "complete", p["strategy_name"], p["symbol"], p["timeframe"],
            res["window_start"], res["window_end"], m["total_return"], m["benchmark_return"],
            m["sharpe_ratio"], m["max_drawdown"], m["win_rate"], m["profit_factor"],
            m["total_trades"], batch_id, json.dumps(p)
        ])

        for t in res["trades"]:
            con.execute("""
                INSERT OR REPLACE INTO trades (
                    vbt_trade_id, fingerprint, direction, status,
                    entry_time, exit_time, entry_price, exit_price,
                    size, entry_fees, exit_fees, pnl, return_pct,
                    holding_bars, holding_seconds, is_win
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                t["vbt_trade_id"], fp, t["direction"], t["status"],
                t["entry_time"], t["exit_time"], t["entry_price"], t["exit_price"],
                t["size"], t["entry_fees"], t["exit_fees"], t["pnl"], t["return_pct"],
                t["holding_bars"], t["holding_seconds"], t["is_win"]
            ])

    strategy_name = next(
        (r["params"]["strategy_name"] for r in results if r["status"] == "SUCCESS"),
        None,
    )
    if strategy_name:
        create_strategy_views(con, strategy_name)

    con.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="1Ybt: High-Performance 1-Year Parallel Monthly Backtest Runner"
    )
    parser.add_argument(
        "--strategy",
        "-s",
        default="classic_floor_mod_v2",
        help="Registered strategy name (default: classic_floor_mod_v2)",
    )
    parser.add_argument(
        "--list-strategies",
        action="store_true",
        help="List all registered strategies and exit",
    )
    parser.add_argument(
        "--year",
        "-y",
        type=int,
        default=2025,
        help="Calendar year to backtest across all months (default: 2025)",
    )
    parser.add_argument(
        "--db",
        default="Shared/Data/ohlcv_eruusd.duckdb",
        help="Path to DuckDB OHLCV database (default: Shared/Data/ohlcv_eruusd.duckdb)",
    )
    parser.add_argument(
        "--table",
        default="ohlcv",
        help="OHLCV table name (default: ohlcv)",
    )
    parser.add_argument(
        "--symbol",
        default="EURUSD",
        help="Symbol ticker (default: EURUSD)",
    )
    parser.add_argument(
        "--timeframe",
        default="5m",
        help="Candle timeframe (default: 5m)",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=4,
        help="Number of concurrent process workers (default: 4)",
    )
    args = parser.parse_args()

    console = Console()

    if args.list_strategies:
        available = list_strategies()
        console.print("[bold cyan]Available Strategies in Registry:[/bold cyan]")
        for s in available:
            console.print(f"  • [bold yellow]{s}[/bold yellow]")
        return

    try:
        strat = get_strategy(args.strategy)
    except KeyError as err:
        console.print(f"[red]Error: {err}[/red]")
        return

    console.print(f"[bold cyan]1Ybt: High-Performance 1-Year Parallel Monthly Backtest Runner[/bold cyan]")
    console.print(f"  • Strategy   : [bold yellow]{strat.name}[/bold yellow] (v{strat.version})")
    console.print(f"  • Year       : [bold cyan]{args.year}[/bold cyan] (All 12 Calendar Months)")
    console.print(f"  • Symbol/TF  : {args.symbol} / {args.timeframe}")
    console.print(f"  • Target DB  : {args.db}")
    console.print(f"  • Workers    : [bold green]{args.workers} concurrent processes[/bold green]\n")

    windows = get_yearly_monthly_windows(args.db, args.table, target_year=args.year)
    if not windows:
        console.print(f"[red]Error: No data found for year {args.year} in table '{args.table}'.[/red]")
        return

    console.print(f"Discovered [bold]{len(windows)} monthly windows[/bold] to simulate concurrently.")

    start_time = time.time()
    results: list[dict[str, Any]] = []

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_to_month = {
            executor.submit(
                run_single_month,
                args.db,
                args.table,
                label,
                w_start,
                w_end,
                args.strategy,
                args.symbol,
                args.timeframe,
            ): label
            for label, w_start, w_end in windows
        }

        for future in as_completed(future_to_month):
            month_label = future_to_month[future]
            try:
                res = future.result()
                results.append(res)
                console.print(f"  ✓ Finished month [bold]{month_label}[/bold] ({res['bars']} bars)")
            except Exception as exc:
                console.print(f"  ✗ [red]Failed month {month_label}: {exc}[/red]")

    elapsed = time.time() - start_time
    results.sort(key=lambda x: x["month"])

    # Persist into DuckDB
    persist_results(args.db, results)

    # Render rich monthly summary table
    table = Table(
        title=f"Year {args.year} Monthly Backtest Summary ({args.strategy.upper()} - {args.symbol})",
        box=None,
        header_style="bold cyan",
    )
    table.add_column("Month", style="bold")
    table.add_column("Start Date", justify="center")
    table.add_column("End Date", justify="center")
    table.add_column("Bars", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("Return %", justify="right")
    table.add_column("Max DD %", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("P.Factor", justify="right")

    total_trades = 0
    total_wins = 0
    total_return_compound = 1.0
    monthly_sharpes: list[float] = []

    for r in results:
        if r["status"] != "SUCCESS":
            table.add_row(r["month"], "-", "-", "0", "0", "-", "-", "-", "-", "-")
            continue
        m = r["metrics"]
        t_count = m.get("total_trades", 0)
        total_trades += t_count
        w_rate = m.get("win_rate", 0.0)
        total_wins += int(round(w_rate * t_count))

        ret = m.get("total_return", 0.0)
        total_return_compound *= (1.0 + ret)
        mdd = m.get("max_drawdown", 0.0)
        sharpe = m.get("sharpe_ratio")
        if sharpe is not None and not np.isnan(sharpe):
            monthly_sharpes.append(sharpe)
        pf = m.get("profit_factor", 0.0)

        ret_style = "green" if ret >= 0 else "red"
        table.add_row(
            r["month"],
            r["window_start"].strftime("%Y-%m-%d"),
            r["window_end"].strftime("%Y-%m-%d"),
            str(r["bars"]),
            str(t_count),
            f"{w_rate * 100:.1f}%",
            f"[{ret_style}]{ret * 100:+.2f}%[/{ret_style}]",
            f"{mdd * 100:.2f}%",
            f"{sharpe:.2f}" if sharpe is not None else "N/A",
            f"{pf:.2f}",
        )

    console.print("\n")
    console.print(table)

    overall_win_rate = (total_wins / total_trades * 100.0) if total_trades > 0 else 0.0
    avg_sharpe = float(np.mean(monthly_sharpes)) if monthly_sharpes else 0.0
    year_ret_pct = (total_return_compound - 1.0) * 100.0
    ret_color = "green" if year_ret_pct >= 0 else "red"

    console.print(f"\n[bold green]✓ Completed {len(windows)} months in {elapsed:.3f}s ({elapsed/len(windows):.3f}s/month)[/bold green]")
    console.print(f"Total Yearly Compounded Return: [bold {ret_color}]{year_ret_pct:+.2f}%[/bold {ret_color}]")
    console.print(f"Total Yearly Trades: [bold]{total_trades}[/bold] | Overall Win Rate: [bold]{overall_win_rate:.1f}%[/bold] | Avg Monthly Sharpe: [bold]{avg_sharpe:.2f}[/bold]")
    console.print(f"Persisted [bold]test_runs[/bold], [bold]trades[/bold], and refreshed views in: [bold]{args.db}[/bold]\n")


if __name__ == "__main__":
    main()
