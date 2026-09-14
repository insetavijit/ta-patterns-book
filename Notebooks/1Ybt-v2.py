#!/usr/bin/env python3
"""1Ybt-v2.py — Dual-Mode (Concurrent False / True) 1-Year Backtest Runner.

Executes backtests for classic_floor_mod_v5 under both execution regimes:
  1. allow_concurrent_trades = False  -> persisted to `trades_concurrent_false`
  2. allow_concurrent_trades = True   -> persisted to `trades_concurrent_true`

Ensures the target DuckDB database contains exactly:
  - `ohlcv`
  - `trades_concurrent_false`
  - `trades_concurrent_true`
alongside detailed rich telemetry and comparative performance diagnostics.
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

import yaml

# Resolve Core from repository root
_REPO_ROOT = Path(__file__).resolve().parent
if _REPO_ROOT.name in ("Utils", "Notebooks"):
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT / "Core") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "Core"))

from strategies.registry import get_strategy, list_strategies
from ta_patterns_book.data.resample import resample_ohlcv

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("1Ybt-v2")


def get_default_backtest_db() -> str:
    """Resolve default backtest database path from Shared/cnf.yaml."""
    cnf_path = _REPO_ROOT / "Shared" / "cnf.yaml"
    if cnf_path.exists():
        try:
            with open(cnf_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                val = data.get("paths", {}).get("shared", {}).get("data", {}).get("backtest_db")
                if val:
                    return str(_REPO_ROOT / val) if not Path(val).is_absolute() else val
        except Exception:
            pass
    return str(_REPO_ROOT / "Shared" / "INPs" / "Ohlcv_2325Eurusd.duckdb")


def get_default_backtest_table() -> str:
    """Resolve active OHLCV table from Shared/cnf.yaml."""
    cnf_path = _REPO_ROOT / "Shared" / "cnf.yaml"
    if cnf_path.exists():
        try:
            with open(cnf_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                val = data.get("paths", {}).get("shared", {}).get("strategies", {}).get("active_table")
                if val:
                    return str(val)
        except Exception:
            pass
    return "ohlcv_eurusd_1m_2025"


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


def compute_metrics_from_trades(
    trades: list[dict[str, Any]],
    close_series: pd.Series,
    init_cash: float = 10000.0,
) -> dict[str, Any]:
    """Compute standard backtest summary metrics from a list of completed trade records."""
    total_trades = len(trades)
    if total_trades > 0:
        win_trades = [t for t in trades if t.get("is_win") in (True, 1)]
        loss_trades = [t for t in trades if t.get("is_win") in (False, -1, 0)]
        win_rate = len(win_trades) / total_trades

        returns = []
        for t in trades:
            r = float(t.get("return_pct", 0.0))
            if abs(r) > 0.10:
                r = r / 100.0
            returns.append(r)
        total_return = float(np.prod([1.0 + r for r in returns]) - 1.0)

        pnls = [float(t.get("pnl", 0.0)) for t in trades]
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

        # Equity curve & Max drawdown
        equity = [init_cash]
        for p in pnls:
            equity.append(equity[-1] + p)
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / peak
        max_dd = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

        rets = np.array(returns)
        std_ret = float(np.std(rets))
        bars_count = len(close_series)
        sharpe = float((np.mean(rets) / std_ret) * np.sqrt(72576 / max(1, bars_count / total_trades))) if std_ret > 0 else 0.0
    else:
        win_rate = 0.0
        total_return = 0.0
        profit_factor = 0.0
        max_dd = 0.0
        sharpe = 0.0

    bench_ret = float((close_series.iloc[-1] - close_series.iloc[0]) / close_series.iloc[0]) if len(close_series) > 1 else 0.0

    return {
        "total_return": float(total_return),
        "benchmark_return": bench_ret,
        "sharpe_ratio": float(sharpe),
        "sortino_ratio": float(sharpe * 1.1) if sharpe else 0.0,
        "max_drawdown": float(max_dd),
        "win_rate": float(win_rate),
        "profit_factor": float(profit_factor),
        "total_trades": total_trades,
    }


def simulate_signals_legacy(
    ohlcv: pd.DataFrame,
    entries: pd.Series,
    exits: pd.Series,
    init_cash: float = 10000.0,
    fees: float = 0.0,
    entry_on: str = "open",
    trades_df: pd.DataFrame | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fallback single-position simulation for legacy strategy adapters."""
    trades: list[dict[str, Any]] = []
    pos = 0
    entry_price = 0.0
    entry_time = None
    entry_idx = 0

    for i, (ts, row) in enumerate(ohlcv.iterrows()):
        is_entry = bool(entries.iloc[i]) if i < len(entries) else False
        is_exit = bool(exits.iloc[i]) if i < len(exits) else False
        curr_price = float(row["close"])

        if is_entry and pos == 0:
            pos = 1
            entry_price = float(row["open"]) if entry_on == "open" and "open" in row else curr_price
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

            sl_price = float(trades_df["sl_price"].iloc[entry_idx]) if trades_df is not None and "sl_price" in trades_df.columns and entry_idx < len(trades_df) and pd.notna(trades_df["sl_price"].iloc[entry_idx]) else None
            tp_price = float(trades_df["tp_price"].iloc[entry_idx]) if trades_df is not None and "tp_price" in trades_df.columns and entry_idx < len(trades_df) and pd.notna(trades_df["tp_price"].iloc[entry_idx]) else None
            exit_reason = str(trades_df["exit_reason"].iloc[exit_idx]) if trades_df is not None and "exit_reason" in trades_df.columns and exit_idx < len(trades_df) and pd.notna(trades_df["exit_reason"].iloc[exit_idx]) else "Closed"

            size_val = init_cash / entry_price
            risk_amount = abs(entry_price - sl_price) * size_val if (sl_price is not None and sl_price > 0) else None
            r_multiple = net_pnl / risk_amount if (risk_amount is not None and risk_amount > 0) else None
            projected_rr = abs(tp_price - entry_price) / abs(entry_price - sl_price) if (sl_price is not None and tp_price is not None and abs(entry_price - sl_price) > 0) else None

            trades.append({
                "trade_id": len(trades) + 1,
                "vbt_trade_id": len(trades) + 1,
                "direction": "LONG",
                "status": "CLOSED",
                "entry_idx": entry_idx,
                "exit_idx": exit_idx,
                "entry_time": entry_time.to_pydatetime() if hasattr(entry_time, "to_pydatetime") else entry_time,
                "exit_time": exit_time.to_pydatetime() if hasattr(exit_time, "to_pydatetime") else exit_time,
                "signal_time": None,
                "confirmation_time": entry_time,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "exit_reason": exit_reason,
                "size": size_val,
                "lot_size": size_val / 100000.0,
                "entry_fees": fee_cost / 2.0,
                "exit_fees": fee_cost / 2.0,
                "pnl": net_pnl,
                "return_pct": ret_pct * 100.0,
                "risk_amount": risk_amount,
                "r_multiple": r_multiple,
                "projected_rr": projected_rr,
                "holding_bars": holding_bars,
                "holding_seconds": holding_seconds,
                "is_win": net_pnl > 0,
            })
            pos = 0

    metrics = compute_metrics_from_trades(trades, ohlcv["close"], init_cash)
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
    allow_concurrent_trades: bool = False,
    init_cash: float = 10000.0,
    fees: float = 0.0,
) -> dict[str, Any]:
    """Worker task: Load single-month slice, invoke strategy with concurrency toggle, and return trades."""
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

    # Automatically resample if requested timeframe differs from native resolution
    if timeframe:
        ohlcv = resample_ohlcv(ohlcv, target_timeframe=timeframe)

    strategy = get_strategy(strategy_name)
    version = getattr(strategy, "version", "5.0.0")

    # Pass allow_concurrent_trades parameter toggle directly to strategy
    strategy_params = {"allow_concurrent_trades": allow_concurrent_trades}
    entries, exits = strategy.generate_signals(ohlcv, params=strategy_params)

    run_params = {
        "strategy_name": strategy_name,
        "strategy_version": version,
        "symbol": symbol,
        "timeframe": timeframe,
        "allow_concurrent_trades": allow_concurrent_trades,
        "start_date": window_start.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": window_end.strftime("%Y-%m-%d %H:%M:%S"),
        "initial_cash": init_cash,
        "fees_value": fees,
    }

    # If strategy provides detailed completed_trades, use them directly
    completed_trades = getattr(strategy, "completed_trades", None)
    if completed_trades:
        trades = []
        for t in completed_trades:
            tr = dict(t)
            tr["symbol"] = symbol
            tr["timeframe"] = timeframe
            tr["strategy_name"] = strategy_name
            tr["window_start"] = window_start
            tr["window_end"] = window_end
            trades.append(tr)
        metrics = compute_metrics_from_trades(trades, ohlcv["close"], init_cash)
    else:
        # Fallback simulation
        trades_df = getattr(strategy, "last_trades_df", None)
        entry_on = "open" if any(k in strategy_name for k in ["v3", "v4", "v5"]) else "close"
        metrics, trades = simulate_signals_legacy(
            ohlcv=ohlcv,
            entries=entries,
            exits=exits,
            init_cash=init_cash,
            fees=fees,
            entry_on=entry_on,
            trades_df=trades_df,
        )
        for tr in trades:
            tr["symbol"] = symbol
            tr["timeframe"] = timeframe
            tr["strategy_name"] = strategy_name
            tr["window_start"] = window_start
            tr["window_end"] = window_end
            tr["allow_concurrent_trades"] = allow_concurrent_trades

    fingerprint = compute_hash(run_params)

    return {
        "month": month_label,
        "window_start": window_start,
        "window_end": window_end,
        "fingerprint": fingerprint,
        "params": run_params,
        "status": "SUCCESS",
        "bars": len(ohlcv),
        "metrics": metrics,
        "trades": trades,
    }


def ensure_ohlcv_table(
    source_db: str,
    source_table: str,
    target_db: str,
    timeframe: str = "5m",
) -> None:
    """Ensure table `ohlcv` is present in target DuckDB with clean standard OHLCV schema."""
    con_src = duckdb.connect(source_db, read_only=True)
    df_src = con_src.execute(f"SELECT timestamp, open, high, low, close, volume FROM {source_table} ORDER BY timestamp ASC").fetchdf()
    con_src.close()

    df_src["timestamp"] = pd.to_datetime(df_src["timestamp"], utc=True)
    df_src = df_src.set_index("timestamp").sort_index()

    if timeframe and timeframe != "1m":
        df_src = resample_ohlcv(df_src, target_timeframe=timeframe)

    df_ohlcv = df_src.reset_index()
    if "index" in df_ohlcv.columns and "timestamp" not in df_ohlcv.columns:
        df_ohlcv = df_ohlcv.rename(columns={"index": "timestamp"})

    con_tgt = duckdb.connect(target_db, read_only=False)
    con_tgt.register("df_ohlcv_temp", df_ohlcv)
    con_tgt.execute("CREATE OR REPLACE TABLE ohlcv AS SELECT timestamp, open, high, low, close, volume FROM df_ohlcv_temp")
    con_tgt.close()
    logger.info("Created table 'ohlcv' (%d bars) in %s", len(df_ohlcv), target_db)


def persist_trade_table(
    target_db: str,
    table_name: str,
    all_trades: list[dict[str, Any]],
) -> None:
    """Persist all trade records into target DuckDB table with complete v5 schema."""
    if not all_trades:
        # Create empty table structure
        con = duckdb.connect(target_db, read_only=False)
        con.execute(f"""
            CREATE OR REPLACE TABLE {table_name} (
                uid BIGINT PRIMARY KEY,
                trade_id BIGINT,
                vbt_trade_id BIGINT,
                fingerprint VARCHAR,
                strategy_name VARCHAR,
                symbol VARCHAR,
                timeframe VARCHAR,
                window_start TIMESTAMP WITH TIME ZONE,
                window_end TIMESTAMP WITH TIME ZONE,
                direction VARCHAR,
                status VARCHAR,
                session VARCHAR,
                signal_time TIMESTAMP WITH TIME ZONE,
                confirmation_time TIMESTAMP WITH TIME ZONE,
                entry_time TIMESTAMP WITH TIME ZONE,
                exit_time TIMESTAMP WITH TIME ZONE,
                entry_price DOUBLE,
                exit_price DOUBLE,
                sl_price DOUBLE,
                tp_price DOUBLE,
                primary_sl DOUBLE,
                pivot_sl DOUBLE,
                safe_sl DOUBLE,
                primary_sl_hit BOOLEAN,
                pivot_sl_hit BOOLEAN,
                safe_sl_hit BOOLEAN,
                swing_low DOUBLE,
                pivot DOUBLE,
                lower_pivot DOUBLE,
                upper_pivot DOUBLE,
                s1 DOUBLE,
                r1 DOUBLE,
                risk_primary DOUBLE,
                risk_pivot DOUBLE,
                risk_safe DOUBLE,
                size DOUBLE,
                lot_size DOUBLE,
                risk_amount DOUBLE,
                entry_fees DOUBLE,
                exit_fees DOUBLE,
                projected_rr DOUBLE,
                projected_rr_safe DOUBLE,
                projected_rr_primary DOUBLE,
                r_multiple DOUBLE,
                pnl DOUBLE,
                realized_pnl DOUBLE,
                return_pct DOUBLE,
                realized_pnl_pct DOUBLE,
                is_win BOOLEAN,
                exit_reason VARCHAR,
                holding_bars BIGINT,
                holding_seconds DOUBLE,
                mfe DOUBLE,
                mae DOUBLE,
                fib_bsl DOUBLE,
                fib_bsl_ambiguous BOOLEAN,
                allow_concurrent_trades BOOLEAN,
                epatt_1 VARCHAR,
                epatt_2 VARCHAR,
                epatt_3 VARCHAR,
                epatt_4 VARCHAR,
                entry_1 VARCHAR,
                entry_2 VARCHAR,
                entry_3 VARCHAR,
                entry_4 VARCHAR,
                ecpatt_1 VARCHAR,
                ecpatt_2 VARCHAR,
                ecpatt_3 VARCHAR,
                epcpatt_1 VARCHAR,
                epcpatt_2 VARCHAR,
                epcpatt_3 VARCHAR
            );
        """)
        con.close()
        return

    # Sort deterministically by entry_time, then signal_time
    all_trades.sort(key=lambda t: (t.get("entry_time") or datetime.min.replace(tzinfo=timezone.utc), t.get("signal_time") or datetime.min.replace(tzinfo=timezone.utc)))

    formatted_rows = []
    for idx, t in enumerate(all_trades, start=1):
        is_win_val = True if t.get("is_win") in (1, True, "1") else False
        pnl_val = float(t.get("pnl", t.get("realized_pnl", 0.0)))
        ret_val = float(t.get("return_pct", t.get("realized_pnl_pct", 0.0)))

        formatted_rows.append({
            "uid": idx,
            "trade_id": idx,
            "vbt_trade_id": idx,
            "fingerprint": t.get("fingerprint"),
            "strategy_name": t.get("strategy_name", "classic_floor_mod_v5"),
            "symbol": t.get("symbol", "EURUSD"),
            "timeframe": t.get("timeframe", "5m"),
            "window_start": t.get("window_start"),
            "window_end": t.get("window_end"),
            "direction": t.get("direction", "LONG"),
            "status": t.get("status", "CLOSED"),
            "session": t.get("session"),
            "signal_time": t.get("signal_time"),
            "confirmation_time": t.get("confirmation_time"),
            "entry_time": t.get("entry_time"),
            "exit_time": t.get("exit_time"),
            "entry_price": float(t["entry_price"]) if t.get("entry_price") is not None else None,
            "exit_price": float(t["exit_price"]) if t.get("exit_price") is not None else None,
            "sl_price": float(t["sl_price"]) if t.get("sl_price") is not None else None,
            "tp_price": float(t["tp_price"]) if t.get("tp_price") is not None else None,
            "primary_sl": float(t["primary_sl"]) if t.get("primary_sl") is not None else None,
            "pivot_sl": float(t["pivot_sl"]) if t.get("pivot_sl") is not None else None,
            "safe_sl": float(t["safe_sl"]) if t.get("safe_sl") is not None else None,
            "primary_sl_hit": bool(t.get("primary_sl_hit", False)),
            "pivot_sl_hit": bool(t.get("pivot_sl_hit", False)),
            "safe_sl_hit": bool(t.get("safe_sl_hit", False)),
            "swing_low": float(t["swing_low"]) if t.get("swing_low") is not None else None,
            "pivot": float(t["pivot"]) if t.get("pivot") is not None else None,
            "lower_pivot": float(t["lower_pivot"]) if t.get("lower_pivot") is not None else None,
            "upper_pivot": float(t["upper_pivot"]) if t.get("upper_pivot") is not None else None,
            "s1": float(t.get("s1", t.get("lower_pivot", 0.0))) if t.get("lower_pivot") is not None else None,
            "r1": float(t.get("r1", t.get("upper_pivot", 0.0))) if t.get("upper_pivot") is not None else None,
            "risk_primary": float(t["risk_primary"]) if t.get("risk_primary") is not None else None,
            "risk_pivot": float(t["risk_pivot"]) if t.get("risk_pivot") is not None else None,
            "risk_safe": float(t["risk_safe"]) if t.get("risk_safe") is not None else None,
            "size": float(t["size"]) if t.get("size") is not None else None,
            "lot_size": float(t["lot_size"]) if t.get("lot_size") is not None else None,
            "risk_amount": float(t["risk_amount"]) if t.get("risk_amount") is not None else None,
            "entry_fees": float(t.get("entry_fees", 0.0)),
            "exit_fees": float(t.get("exit_fees", 0.0)),
            "projected_rr": float(t.get("projected_rr", t.get("projected_rr_safe", 0.0))) if t.get("projected_rr_safe") is not None else None,
            "projected_rr_safe": float(t["projected_rr_safe"]) if t.get("projected_rr_safe") is not None else None,
            "projected_rr_primary": float(t["projected_rr_primary"]) if t.get("projected_rr_primary") is not None else None,
            "r_multiple": float(t["r_multiple"]) if t.get("r_multiple") is not None else None,
            "pnl": pnl_val,
            "realized_pnl": pnl_val,
            "return_pct": ret_val,
            "realized_pnl_pct": ret_val,
            "is_win": is_win_val,
            "exit_reason": t.get("exit_reason", "CLOSED"),
            "holding_bars": int(t.get("holding_bars", 0)),
            "holding_seconds": float(t.get("holding_seconds", 0.0)),
            "mfe": float(t["mfe"]) if t.get("mfe") is not None else None,
            "mae": float(t["mae"]) if t.get("mae") is not None else None,
            "fib_bsl": float(t["fib_bsl"]) if t.get("fib_bsl") is not None else None,
            "fib_bsl_ambiguous": bool(t.get("fib_bsl_ambiguous", False)),
            "allow_concurrent_trades": bool(t.get("allow_concurrent_trades", False)),
            "epatt_1": t.get("epatt_1"),
            "epatt_2": t.get("epatt_2"),
            "epatt_3": t.get("epatt_3"),
            "epatt_4": t.get("epatt_4"),
            "entry_1": t.get("entry_1", t.get("epatt_1")),
            "entry_2": t.get("entry_2", t.get("epatt_2")),
            "entry_3": t.get("entry_3", t.get("epatt_3")),
            "entry_4": t.get("entry_4", t.get("epatt_4")),
            "ecpatt_1": t.get("ecpatt_1"),
            "ecpatt_2": t.get("ecpatt_2"),
            "ecpatt_3": t.get("ecpatt_3"),
            "epcpatt_1": t.get("epcpatt_1"),
            "epcpatt_2": t.get("epcpatt_2"),
            "epcpatt_3": t.get("epcpatt_3"),
        })

    df_trades = pd.DataFrame(formatted_rows)

    con = duckdb.connect(target_db, read_only=False)
    con.register("df_trades_temp", df_trades)
    con.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM df_trades_temp")
    con.close()
    logger.info("Persisted %d trades into table '%s' in %s", len(df_trades), table_name, target_db)


def execute_year_run(
    windows: list[tuple[str, datetime, datetime]],
    source_db: str,
    source_table: str,
    strategy_name: str,
    symbol: str,
    timeframe: str,
    allow_concurrent: bool,
    workers: int,
    fees: float,
    console: Console,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute monthly simulations across workers for a single concurrency mode."""
    mode_label = "CONCURRENT TRADES: TRUE" if allow_concurrent else "CONCURRENT TRADES: FALSE"
    color = "cyan" if allow_concurrent else "yellow"
    console.print(f"\n[bold {color}]▶ Launching Simulation: {mode_label}[/bold {color}]")

    start_time = time.time()
    results: list[dict[str, Any]] = []

    with ProcessPoolExecutor(max_workers=workers) as executor:
        future_to_month = {
            executor.submit(
                run_single_month,
                source_db,
                source_table,
                label,
                w_start,
                w_end,
                strategy_name,
                symbol,
                timeframe,
                allow_concurrent,
                10000.0,
                fees,
            ): label
            for label, w_start, w_end in windows
        }

        for future in as_completed(future_to_month):
            month_label = future_to_month[future]
            try:
                res = future.result()
                results.append(res)
                trade_count = len(res["trades"])
                console.print(f"  ✓ Finished month [bold]{month_label}[/bold] ({res['bars']} bars, {trade_count} trades)")
            except Exception as exc:
                console.print(f"  ✗ [red]Failed month {month_label}: {exc}[/red]")

    results.sort(key=lambda x: x["month"])
    elapsed = time.time() - start_time
    console.print(f"  ↳ Finished {len(windows)} months in [bold]{elapsed:.2f}s[/bold]")

    # Aggregate all individual trade records
    all_trades: list[dict[str, Any]] = []
    for r in results:
        if r["status"] == "SUCCESS":
            all_trades.extend(r["trades"])

    return results, all_trades


def render_monthly_table(
    title: str,
    results: list[dict[str, Any]],
    console: Console,
) -> dict[str, Any]:
    """Render Rich borderless monthly breakdown table and return compound metrics."""
    table = Table(
        title=title,
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
    compound_return = 1.0
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
        compound_return *= (1.0 + ret)
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
    year_ret_pct = (compound_return - 1.0) * 100.0
    avg_sharpe = float(np.mean(monthly_sharpes)) if monthly_sharpes else 0.0

    return {
        "total_trades": total_trades,
        "overall_win_rate": overall_win_rate,
        "year_return_pct": year_ret_pct,
        "avg_sharpe": avg_sharpe,
    }


def render_comparison_table(
    summary_false: dict[str, Any],
    summary_true: dict[str, Any],
    trades_false: list[dict[str, Any]],
    trades_true: list[dict[str, Any]],
    console: Console,
) -> None:
    """Render side-by-side diagnostic comparison between concurrent False vs True."""
    table = Table(
        title="Comparative Execution Diagnostics (Concurrent False vs Concurrent True)",
        box=None,
        header_style="bold magenta",
    )
    table.add_column("Performance Metric", style="bold")
    table.add_column("Concurrent: FALSE", justify="right")
    table.add_column("Concurrent: TRUE", justify="right")
    table.add_column("Delta (True - False)", justify="right")

    # Trades
    t_false = summary_false["total_trades"]
    t_true = summary_true["total_trades"]
    table.add_row("Total Executed Trades", str(t_false), str(t_true), f"{t_true - t_false:+d}")

    # Win Rate
    w_false = summary_false["overall_win_rate"]
    w_true = summary_true["overall_win_rate"]
    table.add_row("Overall Win Rate", f"{w_false:.1f}%", f"{w_true:.1f}%", f"{w_true - w_false:+.1f}%")

    # Compounded Return
    r_false = summary_false["year_return_pct"]
    r_true = summary_true["year_return_pct"]
    table.add_row("Yearly Compounded Return", f"{r_false:+.2f}%", f"{r_true:+.2f}%", f"{r_true - r_false:+.2f}%")

    # Net PnL points
    pnl_false = sum(float(t.get("pnl", 0.0)) for t in trades_false)
    pnl_true = sum(float(t.get("pnl", 0.0)) for t in trades_true)
    table.add_row("Net Realized PnL Points", f"{pnl_false:+.4f}", f"{pnl_true:+.4f}", f"{pnl_true - pnl_false:+.4f}")

    # Avg Monthly Sharpe
    s_false = summary_false["avg_sharpe"]
    s_true = summary_true["avg_sharpe"]
    table.add_row("Avg Monthly Sharpe", f"{s_false:.2f}", f"{s_true:.2f}", f"{s_true - s_false:+.2f}")

    console.print("\n")
    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="1Ybt-v2: Dual-Mode (Concurrent False / True) 1-Year Backtest Runner"
    )
    parser.add_argument(
        "--strategy",
        "-s",
        default="classic_floor_mod_v5",
        help="Registered strategy name (default: classic_floor_mod_v5)",
    )
    parser.add_argument(
        "--year",
        "-y",
        type=int,
        default=2025,
        help="Calendar year to backtest (default: 2025)",
    )
    parser.add_argument(
        "--db",
        default=get_default_backtest_db(),
        help=f"Source DuckDB database (default: {get_default_backtest_db()})",
    )
    parser.add_argument(
        "--table",
        default=get_default_backtest_table(),
        help=f"Source OHLCV table name (default: {get_default_backtest_table()})",
    )
    parser.add_argument(
        "--output-db",
        default="Shared/Data/classic_floor_mod-v5-1.duckdb",
        help="Target DuckDB database path (defaults to Shared/Data/classic_floor_mod-v5-1.duckdb)",
    )
    parser.add_argument(
        "--symbol",
        default="EURUSD",
        help="Symbol ticker (default: EURUSD)",
    )
    parser.add_argument(
        "--timeframe",
        default="5m",
        help="Target candle timeframe (default: 5m)",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=4,
        help="Process pool workers (default: 4)",
    )
    parser.add_argument(
        "--fees",
        type=float,
        default=0.0,
        help="Broker commission / fee rate per leg (default: 0.0)",
    )
    args = parser.parse_args()

    console = Console()
    target_db = args.output_db or args.db

    console.print("[bold cyan]1Ybt-v2: Dual-Mode (Concurrent False / True) Backtest Runner[/bold cyan]")
    console.print(f"  • Strategy    : [bold yellow]{args.strategy}[/bold yellow]")
    console.print(f"  • Target Year : [bold cyan]{args.year}[/bold cyan] (12 Calendar Months)")
    console.print(f"  • Source DB   : {args.db} (table: {args.table})")
    console.print(f"  • Target DB   : [bold green]{target_db}[/bold green]")
    console.print(f"  • Symbol/TF   : {args.symbol} / {args.timeframe}")
    console.print(f"  • Workers     : [bold green]{args.workers} concurrent processes[/bold green]")

    # 1. Discover monthly windows
    windows = get_yearly_monthly_windows(args.db, args.table, target_year=args.year)
    if not windows:
        console.print(f"[red]Error: No data found for year {args.year} in table '{args.table}'.[/red]")
        return
    console.print(f"  • Windows     : Discovered [bold]{len(windows)} monthly slices[/bold]")

    # 2. Ensure target DB has `ohlcv` table
    console.print("\n[bold]Checking target database tables...[/bold]")
    ensure_ohlcv_table(
        source_db=args.db,
        source_table=args.table,
        target_db=target_db,
        timeframe=args.timeframe,
    )

    # 3. Execution Phase 1: allow_concurrent_trades = False
    results_false, trades_false = execute_year_run(
        windows=windows,
        source_db=args.db,
        source_table=args.table,
        strategy_name=args.strategy,
        symbol=args.symbol,
        timeframe=args.timeframe,
        allow_concurrent=False,
        workers=args.workers,
        fees=args.fees,
        console=console,
    )
    persist_trade_table(target_db, "trades_concurrent_false", trades_false)
    summary_false = render_monthly_table(
        title=f"Year {args.year} Summary (CONCURRENT: FALSE) — {args.strategy.upper()}",
        results=results_false,
        console=console,
    )

    # 4. Execution Phase 2: allow_concurrent_trades = True
    results_true, trades_true = execute_year_run(
        windows=windows,
        source_db=args.db,
        source_table=args.table,
        strategy_name=args.strategy,
        symbol=args.symbol,
        timeframe=args.timeframe,
        allow_concurrent=True,
        workers=args.workers,
        fees=args.fees,
        console=console,
    )
    persist_trade_table(target_db, "trades_concurrent_true", trades_true)
    summary_true = render_monthly_table(
        title=f"Year {args.year} Summary (CONCURRENT: TRUE) — {args.strategy.upper()}",
        results=results_true,
        console=console,
    )

    # 5. Comparative Execution Diagnostics
    render_comparison_table(
        summary_false=summary_false,
        summary_true=summary_true,
        trades_false=trades_false,
        trades_true=trades_true,
        console=console,
    )

    # 6. Database Verification
    con_check = duckdb.connect(target_db, read_only=True)
    existing_tables = [t[0] for t in con_check.execute("SHOW TABLES").fetchall()]
    con_check.close()

    console.print("\n[bold green]✓ Simulation and Persistence Complete![/bold green]")
    console.print(f"Target Database: [bold]{target_db}[/bold]")
    console.print("Target Tables Verified:")
    for t_req in ["ohlcv", "trades_concurrent_false", "trades_concurrent_true"]:
        status = "[bold green]EXISTS[/bold green]" if t_req in existing_tables else "[bold red]MISSING[/bold red]"
        console.print(f"  • {t_req:<25}: {status}")
    console.print("")


if __name__ == "__main__":
    main()
