#!/usr/bin/env python3
"""1Ybt-s2.py — Single-Strategy Parquet-Driven Backtest & DuckDB Persistence Engine.

Takes a Parquet OHLCV file and a strategy file path (or registered name), executes
the strategy in single-pass mode, and generates a self-contained DuckDB database with:
  1. ohlcv (clean OHLCV price series)
  2. trades (single unified canonical trades table — no concurrent_true table split)
  3. portfolio_metrics (high-level risk, return, Sharpe, Sortino, Calmar, DD metrics)
  4. monthly_performance (aggregated performance metrics per calendar month)
  5. equity_curve (continuous bar-by-bar portfolio valuation series)
  6. drawdown_events (drawdown episode profiling with peak, trough, and recovery)
  7. sl_risk_summary (v6.1 dynamic SL adaptation breakdown: SAFE vs PIVOT)
  8. post-enrichment (optional automatic 3-candle patterns enrichment pipeline)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import yaml
from rich.console import Console
from rich.table import Table

# Resolve repository paths
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_CORE_DIR = _REPO_ROOT / "Core"
if str(_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(_CORE_DIR))
_STRATEGIES_DIR = _REPO_ROOT / "Shared" / "strategies"
if str(_STRATEGIES_DIR) not in sys.path:
    sys.path.insert(0, str(_STRATEGIES_DIR))
for _sub in _STRATEGIES_DIR.iterdir():
    if _sub.is_dir() and str(_sub) not in sys.path:
        sys.path.insert(0, str(_sub))

from strategies.registry import get_strategy, list_strategies

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("1Ybt-s2")


# ---------------------------------------------------------------------------
# Strategy Adapter & Dynamic Resolver
# ---------------------------------------------------------------------------

class StrategyAdapter:
    """Standardizes arbitrary strategy class returns to conform to generate_signals."""

    def __init__(self, inner: Any, name: str) -> None:
        self._inner = inner
        self.name = name
        self.version = getattr(inner, "version", "1.0.0")
        self.completed_trades: list[dict[str, Any]] = []
        self.last_trades_df: pd.DataFrame | None = None

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict[str, Any] | None = None,
    ) -> tuple[pd.Series, pd.Series]:
        res = self._inner.generate_signals(ohlcv, params=params)
        if isinstance(res, tuple) and len(res) == 2:
            entries, exits = res
            self.last_trades_df = getattr(self._inner, "last_trades_df", None)
            self.completed_trades = getattr(self._inner, "completed_trades", [])
            return entries, exits
        elif isinstance(res, tuple) and len(res) == 3:
            entries, exits, trades_df = res
            self.last_trades_df = trades_df
            self.completed_trades = getattr(self._inner, "completed_trades", [])
            return entries, exits
        else:
            raise ValueError(f"Unexpected return from generate_signals: {type(res)}")


def resolve_strategy(strategy_input: str) -> tuple[Any, str]:
    """Resolve strategy instance and canonical name from file path or registry."""
    p = Path(strategy_input)
    if p.exists() and p.suffix == ".py":
        stem = p.stem.lower()
        # Check if registered by exact or normalized name
        for reg_name in list_strategies():
            if reg_name.lower() == stem or reg_name.replace("_", "").replace(".", "") == stem.replace("_", "").replace(".", ""):
                return get_strategy(reg_name), reg_name

        # Load file dynamically
        spec = importlib.util.spec_from_file_location(p.stem, str(p))
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for attr_name in dir(mod):
                obj = getattr(mod, attr_name)
                if isinstance(obj, type) and hasattr(obj, "generate_signals"):
                    inst = obj()
                    return StrategyAdapter(inst, name=p.stem), p.stem
            for attr_name in dir(mod):
                obj = getattr(mod, attr_name)
                if hasattr(obj, "generate_signals"):
                    return StrategyAdapter(obj, name=p.stem), p.stem
        raise ValueError(f"Could not locate a strategy class with generate_signals() in {strategy_input}")

    # Fallback: look up in registry
    return get_strategy(strategy_input), strategy_input


# ---------------------------------------------------------------------------
# Parquet Loader & Metadata Inference
# ---------------------------------------------------------------------------

def load_ohlcv_from_parquet(path_str: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load OHLCV DataFrame from parquet file and infer metadata."""
    p = Path(path_str)
    if not p.exists():
        raise FileNotFoundError(f"Parquet file not found: {path_str}")

    if p.is_file():
        df = pd.read_parquet(p)
        source_name = p.stem
    elif p.is_dir():
        parquet_files = sorted(p.glob("*.parquet"))
        if not parquet_files:
            raise FileNotFoundError(f"No .parquet files found in directory: {path_str}")
        dfs = [pd.read_parquet(f) for f in parquet_files]
        df = pd.concat(dfs, axis=0)
        source_name = p.name
    else:
        raise ValueError(f"Invalid path: {path_str}")

    # Normalize timestamp index
    time_col = None
    for cand in ["timestamp", "time", "date", "datetime"]:
        if cand in df.columns:
            time_col = cand
            break

    if time_col:
        df[time_col] = pd.to_datetime(df[time_col], utc=True)
        df = df.set_index(time_col).sort_index()
    elif not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
        df = df.sort_index()

    # Normalize OHLCV column casing
    df.columns = [c.lower() for c in df.columns]
    req = ["open", "high", "low", "close"]
    for col in req:
        if col not in df.columns:
            raise KeyError(f"Required column '{col}' missing from parquet file.")

    if "volume" not in df.columns:
        df["volume"] = 1.0

    # Deduplicate timestamps
    df = df[~df.index.duplicated(keep="first")]

    # Infer ticker symbol and timeframe from filename or metadata
    symbol_match = re.search(r"([A-Z]{6,7}|[A-Z]{3}_[A-Z]{3}|[A-Z]{6}m)", source_name, re.IGNORECASE)
    symbol = symbol_match.group(1).upper() if symbol_match else "EURUSD"

    tf_match = re.search(r"[_ -](1m|5m|15m|30m|1h|4h|1d)", source_name, re.IGNORECASE)
    if tf_match:
        timeframe = tf_match.group(1).lower()
    else:
        # Infer from median delta
        if len(df) > 1:
            diffs = pd.Series(df.index).diff().dropna()
            med_sec = diffs.median().total_seconds()
            if med_sec <= 60:
                timeframe = "1m"
            elif med_sec <= 300:
                timeframe = "5m"
            elif med_sec <= 900:
                timeframe = "15m"
            elif med_sec <= 3600:
                timeframe = "1h"
            else:
                timeframe = "5m"
        else:
            timeframe = "5m"

    start_dt = df.index.min().to_pydatetime()
    end_dt = df.index.max().to_pydatetime()

    meta = {
        "symbol": symbol,
        "timeframe": timeframe,
        "start": start_dt,
        "end": end_dt,
        "bars": len(df),
        "source": str(p),
    }
    return df, meta


# ---------------------------------------------------------------------------
# Metrics Computation Engine
# ---------------------------------------------------------------------------

def compute_metrics_from_trades(
    trades: list[dict[str, Any]],
    close_series: pd.Series,
    init_cash: float = 10000.0,
) -> dict[str, Any]:
    """Compute high-level portfolio and performance statistics from trade list."""
    if not trades:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "net_pnl": 0.0, "total_return": 0.0, "profit_factor": 0.0,
            "sharpe_ratio": 0.0, "sortino_ratio": 0.0, "calmar_ratio": 0.0,
            "max_drawdown": 0.0, "max_drawdown_points": 0.0, "avg_win": 0.0,
            "avg_loss": 0.0, "payoff_ratio": 0.0, "avg_trade_pnl": 0.0,
            "max_consecutive_losses": 0, "avg_holding_bars": 0.0,
        }

    n_trades = len(trades)
    pnls = [float(t.get("pnl", t.get("realized_pnl", 0.0))) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    n_wins = len(wins)
    n_losses = len(losses)
    win_rate = (n_wins / n_trades) if n_trades > 0 else 0.0
    net_pnl = sum(pnls)
    tot_return = net_pnl / init_cash

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    avg_win = (gross_profit / n_wins) if n_wins > 0 else 0.0
    avg_loss = (gross_loss / n_losses) if n_losses > 0 else 0.0
    payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    avg_trade_pnl = net_pnl / n_trades if n_trades > 0 else 0.0

    # Drawdown and equity computation
    cum = np.cumsum(pnls)
    equity = init_cash + cum
    peak = np.maximum.accumulate(equity)
    dd_points = peak - equity
    max_dd_points = float(np.max(dd_points)) if len(dd_points) > 0 else 0.0
    dd_pcts = (peak - equity) / peak
    max_dd = float(np.max(dd_pcts)) if len(dd_pcts) > 0 else 0.0

    # Sharpe & Sortino
    if len(pnls) > 1:
        pnl_std = float(np.std(pnls, ddof=1))
        sharpe = (float(np.mean(pnls)) / pnl_std * np.sqrt(252.0)) if pnl_std > 1e-9 else 0.0
        neg_pnls = [p for p in pnls if p < 0]
        if neg_pnls:
            downside_std = float(np.std(neg_pnls, ddof=1))
            sortino = (float(np.mean(pnls)) / downside_std * np.sqrt(252.0)) if downside_std > 1e-9 else 0.0
        else:
            sortino = sharpe * 1.5 if sharpe > 0 else 0.0
    else:
        sharpe = 0.0
        sortino = 0.0

    calmar = (tot_return / max_dd) if max_dd > 0 else 0.0

    # Consecutive losses
    max_cons = 0
    cur_cons = 0
    for p in pnls:
        if p <= 0:
            cur_cons += 1
            if cur_cons > max_cons:
                max_cons = cur_cons
        else:
            cur_cons = 0

    holding_bars = [float(t.get("holding_bars", 0)) for t in trades if t.get("holding_bars") is not None]
    avg_holding = float(np.mean(holding_bars)) if holding_bars else 0.0

    return {
        "total_trades": n_trades,
        "wins": n_wins,
        "losses": n_losses,
        "win_rate": win_rate,
        "net_pnl": net_pnl,
        "total_return": tot_return,
        "profit_factor": profit_factor,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "calmar_ratio": calmar,
        "max_drawdown": max_dd,
        "max_drawdown_points": max_dd_points,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff_ratio,
        "avg_trade_pnl": avg_trade_pnl,
        "max_consecutive_losses": max_cons,
        "avg_holding_bars": avg_holding,
    }


# ---------------------------------------------------------------------------
# DuckDB Persistence Engine
# ---------------------------------------------------------------------------

def persist_to_duckdb(
    target_db: str,
    ohlcv_df: pd.DataFrame,
    all_trades: list[dict[str, Any]],
    strategy_name: str,
    symbol: str,
    timeframe: str,
    init_cash: float = 10000.0,
) -> list[str]:
    """Persist ohlcv, unified trades table, and complete analytical report tables in DuckDB."""
    target_path = Path(target_db)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(target_path), read_only=False)
    created_tables: list[str] = []
    now_utc = datetime.now(timezone.utc)

    # 1. Table `ohlcv`
    ohlcv_clean = ohlcv_df.reset_index()
    if "ts" in ohlcv_clean.columns and "timestamp" not in ohlcv_clean.columns:
        ohlcv_clean = ohlcv_clean.rename(columns={"ts": "timestamp"})
    if "index" in ohlcv_clean.columns and "timestamp" not in ohlcv_clean.columns:
        ohlcv_clean = ohlcv_clean.rename(columns={"index": "timestamp"})

    keep_cols = [c for c in ["timestamp", "open", "high", "low", "close", "volume"] if c in ohlcv_clean.columns]
    con.register("df_ohlcv_tmp", ohlcv_clean[keep_cols])
    con.execute("CREATE OR REPLACE TABLE ohlcv AS SELECT * FROM df_ohlcv_tmp")
    created_tables.append("ohlcv")
    logger.info("Created table 'ohlcv' (%d bars) in %s", len(ohlcv_clean), target_db)

    # 2. Table `trades` (Pure Canonical Schema v6.1)
    if all_trades:
        # Deterministic sorting
        all_trades.sort(key=lambda t: (
            t.get("entry_time") or datetime.min.replace(tzinfo=timezone.utc),
            t.get("signal_time") or datetime.min.replace(tzinfo=timezone.utc)
        ))

        formatted_rows = []
        for idx, t in enumerate(all_trades, start=1):
            is_win_val = True if t.get("is_win") in (1, True, "1") else False
            pnl_val = float(t.get("pnl", t.get("realized_pnl", 0.0)))
            ret_val = float(t.get("return_pct", t.get("realized_pnl_pct", 0.0)))

            row = {
                "uid": idx,
                "trade_id": idx,
                "vbt_trade_id": idx,
                "fingerprint": t.get("fingerprint"),
                "strategy_name": t.get("strategy_name", strategy_name),
                "symbol": t.get("symbol", symbol),
                "timeframe": t.get("timeframe", timeframe),
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
                "tp_price": float(t["tp_price"]) if t.get("tp_price") is not None else None,
                "swing_low": float(t["swing_low"]) if t.get("swing_low") is not None else None,
                "pivot": float(t["pivot"]) if t.get("pivot") is not None else None,
                "lower_pivot": float(t["lower_pivot"]) if t.get("lower_pivot") is not None else None,
                "upper_pivot": float(t["upper_pivot"]) if t.get("upper_pivot") is not None else None,
                "primary_sl": float(t["primary_sl"]) if t.get("primary_sl") is not None else None,
                "pivot_sl": float(t["pivot_sl"]) if t.get("pivot_sl") is not None else None,
                "safe_sl": float(t["safe_sl"]) if t.get("safe_sl") is not None else None,
                "primary_sl_hit": bool(t.get("primary_sl_hit", False)),
                "pivot_sl_hit": bool(t.get("pivot_sl_hit", False)),
                "safe_sl_hit": bool(t.get("safe_sl_hit", False)),
                "sl_mode": t.get("sl_mode", "SAFE"),
                "primary_sl_hit_timestamp": t.get("primary_sl_hit_timestamp"),
                "safe_sl_hit_timestamp": t.get("safe_sl_hit_timestamp"),
                "pivot_sl_hit_timestamp": t.get("pivot_sl_hit_timestamp"),
                "risk_primary": float(t["risk_primary"]) if t.get("risk_primary") is not None else None,
                "risk_pivot": float(t["risk_pivot"]) if t.get("risk_pivot") is not None else None,
                "risk_safe": float(t["risk_safe"]) if t.get("risk_safe") is not None else None,
                "size": float(t["size"]) if t.get("size") is not None else None,
                "lot_size": float(t["lot_size"]) if t.get("lot_size") is not None else None,
                "risk_amount": float(t["risk_amount"]) if t.get("risk_amount") is not None else None,
                "entry_fees": float(t.get("entry_fees", 0.0)),
                "exit_fees": float(t.get("exit_fees", 0.0)),
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
                "pfib15_bsl": float(t["pfib15_bsl"]) if t.get("pfib15_bsl") is not None else 0.0,
                "pfib15_be_hit": bool(t.get("pfib15_be_hit", False)),
                "pfib15_sl_hit": bool(t.get("pfib15_sl_hit", False)),
                "pfib15_sl_hit_timestamp": t.get("pfib15_sl_hit_timestamp"),
                "pfib30_bsl": float(t["pfib30_bsl"]) if t.get("pfib30_bsl") is not None else 0.0,
                "pfib30_be_hit": bool(t.get("pfib30_be_hit", False)),
                "pfib30_sl_hit": bool(t.get("pfib30_sl_hit", False)),
                "pfib30_sl_hit_timestamp": t.get("pfib30_sl_hit_timestamp"),
                "pfib60_bsl": float(t["pfib60_bsl"]) if t.get("pfib60_bsl") is not None else 0.0,
                "pfib60_be_hit": bool(t.get("pfib60_be_hit", False)),
                "pfib60_sl_hit": bool(t.get("pfib60_sl_hit", False)),
                "pfib60_sl_hit_timestamp": t.get("pfib60_sl_hit_timestamp"),
                "allow_concurrent_trades": bool(t.get("allow_concurrent_trades", False)),
                "concurrent_trades_count": int(t.get("concurrent_trades_count", 0)),
                "epatt_1": t.get("epatt_1"),
                "epatt_2": t.get("epatt_2"),
                "epatt_3": t.get("epatt_3"),
                "epatt_4": t.get("epatt_4"),
                "ecpatt_1": t.get("ecpatt_1"),
                "ecpatt_2": t.get("ecpatt_2"),
                "ecpatt_3": t.get("ecpatt_3"),
                "epcpatt_1": t.get("epcpatt_1"),
                "epcpatt_2": t.get("epcpatt_2"),
                "epcpatt_3": t.get("epcpatt_3"),
            }
            formatted_rows.append(row)

        df_trades = pd.DataFrame(formatted_rows)
        con.register("df_trades_tmp", df_trades)
        con.execute("CREATE OR REPLACE TABLE trades AS SELECT * FROM df_trades_tmp")
        created_tables.append("trades")
        logger.info("Persisted %d trades into table 'trades' in %s", len(df_trades), target_db)
    else:
        con.execute("CREATE OR REPLACE TABLE trades (uid BIGINT, trade_id BIGINT, pnl DOUBLE)")
        created_tables.append("trades")

    # 3. Table `portfolio_metrics`
    summary_metrics = compute_metrics_from_trades(all_trades, ohlcv_df["close"], init_cash)
    pm_row = {
        "strategy_name": strategy_name,
        "symbol": symbol,
        "timeframe": timeframe,
        "initial_cash": float(init_cash),
        "ending_cash": float(init_cash + summary_metrics["net_pnl"]),
        "net_pnl": float(summary_metrics["net_pnl"]),
        "total_return_pct": float(summary_metrics["total_return"] * 100.0),
        "total_trades": int(summary_metrics["total_trades"]),
        "wins": int(summary_metrics["wins"]),
        "losses": int(summary_metrics["losses"]),
        "win_rate_pct": float(summary_metrics["win_rate"] * 100.0),
        "profit_factor": float(summary_metrics["profit_factor"]),
        "sharpe_ratio": float(summary_metrics["sharpe_ratio"]),
        "sortino_ratio": float(summary_metrics["sortino_ratio"]),
        "calmar_ratio": float(summary_metrics["calmar_ratio"]),
        "max_drawdown_pct": float(summary_metrics["max_drawdown"] * 100.0),
        "max_drawdown_points": float(summary_metrics["max_drawdown_points"]),
        "payoff_ratio": float(summary_metrics["payoff_ratio"]),
        "avg_trade_pnl": float(summary_metrics["avg_trade_pnl"]),
        "avg_win": float(summary_metrics["avg_win"]),
        "avg_loss": float(summary_metrics["avg_loss"]),
        "max_consecutive_losses": int(summary_metrics["max_consecutive_losses"]),
        "avg_holding_bars": float(summary_metrics["avg_holding_bars"]),
        "created_at": now_utc,
    }
    df_pm = pd.DataFrame([pm_row])
    con.register("df_pm_tmp", df_pm)
    con.execute("CREATE OR REPLACE TABLE portfolio_metrics AS SELECT * FROM df_pm_tmp")
    created_tables.append("portfolio_metrics")

    # 4. Table `monthly_performance`
    if all_trades:
        # Group trades by calendar month of entry_time
        months_seen = sorted(set(
            pd.to_datetime(t["entry_time"], utc=True).strftime("%Y-%m")
            for t in all_trades if t.get("entry_time") is not None
        ))
        mp_rows = []
        for m_str in months_seen:
            m_trades = [
                t for t in all_trades
                if t.get("entry_time") is not None
                and pd.to_datetime(t["entry_time"], utc=True).strftime("%Y-%m") == m_str
            ]
            m_metrics = compute_metrics_from_trades(m_trades, ohlcv_df["close"], init_cash)
            mp_rows.append({
                "year_month": m_str,
                "strategy_name": strategy_name,
                "trade_count": int(m_metrics["total_trades"]),
                "wins": int(m_metrics["wins"]),
                "losses": int(m_metrics["losses"]),
                "win_rate_pct": float(m_metrics["win_rate"] * 100.0),
                "realized_pnl": float(m_metrics["net_pnl"]),
                "return_pct": float(m_metrics["total_return"] * 100.0),
                "max_drawdown_pct": float(m_metrics["max_drawdown"] * 100.0),
                "sharpe_ratio": float(m_metrics["sharpe_ratio"]),
                "profit_factor": float(m_metrics["profit_factor"]),
            })
        df_mp = pd.DataFrame(mp_rows)
        con.register("df_mp_tmp", df_mp)
        con.execute("CREATE OR REPLACE TABLE monthly_performance AS SELECT * FROM df_mp_tmp")
        created_tables.append("monthly_performance")

    # 5. Table `equity_curve` & 6. Table `drawdown_events`
    timestamps = pd.to_datetime(ohlcv_df.index, utc=True)
    if len(timestamps) > 0:
        exits_by_time: dict[pd.Timestamp, float] = {}
        for t in all_trades:
            exit_t = pd.to_datetime(t.get("exit_time"), utc=True) if t.get("exit_time") else None
            pnl_v = float(t.get("pnl", t.get("realized_pnl", 0.0)))
            if exit_t is not None and pd.notna(exit_t):
                exits_by_time[exit_t] = exits_by_time.get(exit_t, 0.0) + pnl_v

        current_cash = init_cash
        peak_val = init_cash
        cur_dd_start = None
        cur_dd_trough_time = None
        cur_dd_peak_val = init_cash
        cur_dd_trough_val = init_cash
        in_dd = False
        dd_start_bar = 0

        eq_rows = []
        dd_rows = []
        dd_counter = 1

        for bar_idx, ts in enumerate(timestamps):
            if ts in exits_by_time:
                current_cash += exits_by_time[ts]

            if current_cash > peak_val:
                if in_dd:
                    dd_pct = (cur_dd_peak_val - cur_dd_trough_val) / cur_dd_peak_val * 100.0
                    if dd_pct >= 0.2:
                        dd_rows.append({
                            "drawdown_id": dd_counter,
                            "strategy_name": strategy_name,
                            "start_time": cur_dd_start,
                            "trough_time": cur_dd_trough_time,
                            "recovery_time": ts,
                            "peak_value": float(cur_dd_peak_val),
                            "trough_value": float(cur_dd_trough_val),
                            "drawdown_pct": float(dd_pct),
                            "duration_bars": int(bar_idx - dd_start_bar),
                            "recovery_bars": int(bar_idx - dd_start_bar),
                            "is_recovered": True,
                        })
                        dd_counter += 1
                    in_dd = False
                peak_val = current_cash
            elif current_cash < peak_val:
                if not in_dd:
                    in_dd = True
                    cur_dd_start = ts
                    cur_dd_peak_val = peak_val
                    cur_dd_trough_val = current_cash
                    cur_dd_trough_time = ts
                    dd_start_bar = bar_idx
                else:
                    if current_cash < cur_dd_trough_val:
                        cur_dd_trough_val = current_cash
                        cur_dd_trough_time = ts

            dd_pct = ((peak_val - current_cash) / peak_val * 100.0) if peak_val > 0 else 0.0
            ret_pct = ((current_cash - init_cash) / init_cash * 100.0)

            eq_rows.append({
                "timestamp": ts,
                "strategy_name": strategy_name,
                "equity_value": float(current_cash),
                "cash": float(current_cash),
                "drawdown_pct": float(dd_pct),
                "cumulative_return_pct": float(ret_pct),
            })

        if in_dd:
            dd_pct = (cur_dd_peak_val - cur_dd_trough_val) / cur_dd_peak_val * 100.0
            if dd_pct >= 0.2:
                dd_rows.append({
                    "drawdown_id": dd_counter,
                    "strategy_name": strategy_name,
                    "start_time": cur_dd_start,
                    "trough_time": cur_dd_trough_time,
                    "recovery_time": None,
                    "peak_value": float(cur_dd_peak_val),
                    "trough_value": float(cur_dd_trough_val),
                    "drawdown_pct": float(dd_pct),
                    "duration_bars": int(len(timestamps) - dd_start_bar),
                    "recovery_bars": None,
                    "is_recovered": False,
                })

        df_eq = pd.DataFrame(eq_rows)
        con.register("df_eq_tmp", df_eq)
        con.execute("CREATE OR REPLACE TABLE equity_curve AS SELECT * FROM df_eq_tmp")
        created_tables.append("equity_curve")

        if dd_rows:
            df_dd = pd.DataFrame(dd_rows)
            con.register("df_dd_tmp", df_dd)
            con.execute("CREATE OR REPLACE TABLE drawdown_events AS SELECT * FROM df_dd_tmp")
            created_tables.append("drawdown_events")

    # 7. Table `sl_risk_summary` (v6.1 Dynamic SL Adaptation breakdown)
    if all_trades and any("sl_mode" in t for t in all_trades):
        modes_seen = sorted(set(t.get("sl_mode") for t in all_trades if t.get("sl_mode")))
        sl_rows = []
        for sm in modes_seen:
            sm_trades = [t for t in all_trades if t.get("sl_mode") == sm]
            cnt = len(sm_trades)
            pnls = [float(t.get("pnl", t.get("realized_pnl", 0.0))) for t in sm_trades]
            wins_cnt = sum(1 for p in pnls if p > 0)
            wr = (wins_cnt / cnt * 100.0) if cnt > 0 else 0.0
            tot_pnl = sum(pnls)
            avg_pnl = tot_pnl / cnt if cnt > 0 else 0.0
            share = (cnt / len(all_trades)) * 100.0 if all_trades else 0.0

            breach_cnt = sum(1 for t in sm_trades if t.get("primary_sl_hit_timestamp") is not None)
            breach_pct = (breach_cnt / cnt * 100.0) if cnt > 0 else 0.0

            sl_rows.append({
                "strategy_name": strategy_name,
                "sl_mode": sm,
                "trade_count": int(cnt),
                "share_pct": float(share),
                "win_rate_pct": float(wr),
                "net_pnl": float(tot_pnl),
                "avg_trade_pnl": float(avg_pnl),
                "primary_breach_count": int(breach_cnt),
                "primary_breach_pct": float(breach_pct),
            })

        df_sl = pd.DataFrame(sl_rows)
        con.register("df_sl_tmp", df_sl)
        con.execute("CREATE OR REPLACE TABLE sl_risk_summary AS SELECT * FROM df_sl_tmp")
        created_tables.append("sl_risk_summary")

    con.close()
    return created_tables


# ---------------------------------------------------------------------------
# Post-Test Enrichment Runner
# ---------------------------------------------------------------------------

def run_post_test_enrichment(target_db: str, strategy_name: str) -> bool:
    """Execute post-test enrichment script if present in repository."""
    enricher_path = _REPO_ROOT / "Shared" / "strategies" / "_helpers" / "post-test-enrichment.py"
    if not enricher_path.exists():
        logger.warning("Enrichment script not found at %s. Skipping.", enricher_path)
        return False

    cmd = [
        sys.executable,
        str(enricher_path),
        "--target",
        str(target_db),
        "--strategy",
        strategy_name,
    ]
    logger.info("Executing post-test enrichment: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info("Post-enrichment completed successfully:\n%s", proc.stdout.strip())
        return True
    except subprocess.CalledProcessError as e:
        logger.warning("Post-enrichment exited with code %d:\n%s", e.returncode, e.stderr.strip())
        return False


# ---------------------------------------------------------------------------
# Terminal Rendering
# ---------------------------------------------------------------------------

def render_summary(
    strategy_name: str,
    meta: dict[str, Any],
    metrics: dict[str, Any],
    target_db: str,
    console: Console,
) -> None:
    """Render borderless summary tables using Rich."""
    pnl = metrics.get("net_pnl", 0.0)
    ret = metrics.get("total_return", 0.0) * 100.0
    ret_color = "green" if ret >= 0 else "red"
    pnl_color = "green" if pnl >= 0 else "red"

    table = Table(title="1Ybt-s2 Execution Summary", box=None, header_style="bold cyan")
    table.add_column("Property", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Strategy", strategy_name)
    table.add_row("Instrument / Timeframe", f"{meta.get('symbol')} / {meta.get('timeframe')}")
    table.add_row("Bar Count", f"{meta.get('bars', 0):,}")
    table.add_row("Date Range", f"{meta.get('start')} -> {meta.get('end')}")
    table.add_row("Total Executed Trades", f"{metrics.get('total_trades', 0)}")
    table.add_row("Winning / Losing Trades", f"{metrics.get('wins', 0)} / {metrics.get('losses', 0)}")
    table.add_row("Win Rate", f"{metrics.get('win_rate', 0.0) * 100.0:.2f}%")
    table.add_row("Net Realized PnL", f"[{pnl_color}]${pnl:+,.2f}[/{pnl_color}]")
    table.add_row("Total Return", f"[{ret_color}]{ret:+.2f}%[/{ret_color}]")
    table.add_row("Profit Factor", f"{metrics.get('profit_factor', 0.0):.2f}")
    table.add_row("Sharpe Ratio", f"{metrics.get('sharpe_ratio', 0.0):.2f}")
    table.add_row("Sortino Ratio", f"{metrics.get('sortino_ratio', 0.0):.2f}")
    table.add_row("Calmar Ratio", f"{metrics.get('calmar_ratio', 0.0):.2f}")
    table.add_row("Max Drawdown", f"{metrics.get('max_drawdown', 0.0) * 100.0:.2f}% (${metrics.get('max_drawdown_points', 0.0):,.2f})")
    table.add_row("Payoff Ratio (Avg Win / Avg Loss)", f"{metrics.get('payoff_ratio', 0.0):.2f}")
    table.add_row("Average Holding Bars", f"{metrics.get('avg_holding_bars', 0.0):.1f}")
    table.add_row("Target DuckDB", target_db)

    console.print("\n")
    console.print(table)
    console.print("\n")


# ---------------------------------------------------------------------------
# CLI & Main Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="1Ybt-s2: Single-Strategy Parquet-to-DuckDB Backtest Runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "pos_parquet",
        nargs="?",
        help="Path to input Parquet OHLCV file (.parquet)",
    )
    parser.add_argument(
        "pos_strategy",
        nargs="?",
        help="Path to strategy .py file or registered strategy name",
    )
    parser.add_argument(
        "--parquet",
        "-p",
        dest="opt_parquet",
        help="Path to input Parquet OHLCV file (.parquet)",
    )
    parser.add_argument(
        "--strategy",
        "-s",
        dest="opt_strategy",
        help="Path to strategy .py file or registered strategy name",
    )
    parser.add_argument(
        "--output-db",
        "--target-db",
        "-t",
        "-o",
        dest="target_db",
        help="Path to output DuckDB database file",
    )
    parser.add_argument(
        "--init-cash",
        type=float,
        default=10000.0,
        help="Initial capital balance in USD",
    )
    parser.add_argument(
        "--risk-per-trade",
        type=float,
        default=100.0,
        help="Fixed risk amount per trade in USD",
    )
    parser.add_argument(
        "--fees",
        type=float,
        default=0.0,
        help="Broker commission fee per leg",
    )
    parser.add_argument(
        "--post-enrich",
        choices=["on", "off"],
        default="on",
        help="Run post-test database enrichment pipeline ('on' or 'off')",
    )
    parser.add_argument(
        "--dump",
        nargs="?",
        const=True,
        default=None,
        help="Export high-level portfolio performance summary JSON",
    )

    args = parser.parse_args()
    console = Console()

    parquet_path = args.opt_parquet or args.pos_parquet
    strategy_path = args.opt_strategy or args.pos_strategy

    if not parquet_path:
        parser.error("A Parquet file path must be provided via argument or --parquet / -p.")
    if not strategy_path:
        parser.error("A strategy file path or registered strategy name must be provided via argument or --strategy / -s.")

    console.print("[bold cyan]▶ 1Ybt-s2: Single-Strategy Parquet-to-DuckDB Backtest Runner[/bold cyan]")

    # 1. Resolve Strategy
    strategy, strategy_name = resolve_strategy(strategy_path)
    console.print(f"  • Strategy    : [bold yellow]{strategy_name}[/bold yellow] ({strategy_path})")

    # 2. Ingest Parquet
    ohlcv_df, meta = load_ohlcv_from_parquet(parquet_path)
    symbol = meta["symbol"]
    timeframe = meta["timeframe"]
    console.print(f"  • Parquet     : [bold green]{meta['source']}[/bold green]")
    console.print(f"  • Instrument  : [bold]{symbol}[/bold] | Timeframe: [bold]{timeframe}[/bold]")
    console.print(f"  • Date Range  : {meta['start']} -> {meta['end']} ([bold]{meta['bars']:,}[/bold] bars)")

    # 3. Determine Output Database Path
    if args.target_db:
        target_db = args.target_db
    else:
        target_db = f"Shared/OUTs/duckdb/{strategy_name}_{symbol.lower()}_{timeframe}.duckdb"
    console.print(f"  • Target DB   : [bold magenta]{target_db}[/bold magenta]")

    # 4. Execute Strategy
    start_sim = time.time()
    console.print(f"\n[bold yellow]▶ Executing Strategy Simulation on {len(ohlcv_df):,} bars...[/bold yellow]")
    params = {
        "risk_per_trade": args.risk_per_trade,
        "fees": args.fees,
    }
    entries, exits = strategy.generate_signals(ohlcv_df, params=params)
    all_trades = getattr(strategy, "completed_trades", [])

    sim_duration = time.time() - start_sim
    console.print(f"  ✔ Simulation finished in [bold]{sim_duration:.2f}s[/bold]. Total completed trades: [bold]{len(all_trades)}[/bold]")

    # 5. Persist to DuckDB
    console.print(f"\n[bold yellow]▶ Persisting tables into DuckDB: {target_db}...[/bold yellow]")
    created_tables = persist_to_duckdb(
        target_db=target_db,
        ohlcv_df=ohlcv_df,
        all_trades=all_trades,
        strategy_name=strategy_name,
        symbol=symbol,
        timeframe=timeframe,
        init_cash=args.init_cash,
    )
    for tbl in created_tables:
        console.print(f"  ✔ Table created: [bold green]{tbl}[/bold green]")

    # 6. Post-test Enrichment
    if args.post_enrich == "on":
        console.print("\n[bold yellow]▶ Executing Post-Test Enrichment Pipeline...[/bold yellow]")
        enriched = run_post_test_enrichment(target_db=target_db, strategy_name=strategy_name)
        if enriched:
            console.print("  ✔ Post-enrichment completed.")

    # 7. Summary Rendering
    summary_metrics = compute_metrics_from_trades(all_trades, ohlcv_df["close"], args.init_cash)
    render_summary(
        strategy_name=strategy_name,
        meta=meta,
        metrics=summary_metrics,
        target_db=target_db,
        console=console,
    )

    # 8. Dump JSON Results (if requested)
    if args.dump:
        dump_target = args.dump if isinstance(args.dump, str) else f"Shared/OUTs/{strategy_name}_{symbol.lower()}_{timeframe}_portfolio.json"
        dump_path = Path(dump_target)
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        dump_data = {
            "report_type": "single_strategy_summary",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "strategy": strategy_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "market_dataset": {
                "start": meta["start"].isoformat() if isinstance(meta["start"], datetime) else str(meta["start"]),
                "end": meta["end"].isoformat() if isinstance(meta["end"], datetime) else str(meta["end"]),
                "total_bars": meta["bars"],
                "source_file": meta["source"],
            },
            "performance_metrics": summary_metrics,
        }
        with open(dump_path, "w", encoding="utf-8") as f:
            json.dump(dump_data, f, indent=2, default=str)
        console.print(f"  ✔ Portfolio summary dumped to: [bold]{dump_path}[/bold]")


if __name__ == "__main__":
    main()
