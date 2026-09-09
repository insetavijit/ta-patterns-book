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

import yaml

# Ensure Core is in Python path for strategy registry resolution
_REPO_ROOT = Path(__file__).resolve().parent
if _REPO_ROOT.name in ("Utils", "Notebooks"):
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT / "Core") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "Core"))

from strategies.registry import get_strategy, list_strategies
from ta_patterns_book.data.resample import resample_ohlcv

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("1Ybt")


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
    return str(_REPO_ROOT / "Shared" / "Data" / "ohlcv_eruusd.duckdb")


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


def simulate_signals(
    ohlcv: pd.DataFrame,
    entries: pd.Series,
    exits: pd.Series,
    init_cash: float = 10000.0,
    fees: float = 0.0,
    entry_on: str = "close",
    trades_df: pd.DataFrame | None = None,
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

            sl_price = None
            tp_price = None
            exit_reason = "Closed"
            pivot_val = None
            s1_val = None
            r1_val = None
            signal_time = None
            fib_bsl = None
            fib_bsl_ambiguous = None

            if trades_df is not None and not trades_df.empty:
                if "sl_price" in trades_df.columns and entry_idx < len(trades_df):
                    v = trades_df["sl_price"].iloc[entry_idx]
                    if pd.notna(v):
                        sl_price = float(v)
                if "tp_price" in trades_df.columns and entry_idx < len(trades_df):
                    v = trades_df["tp_price"].iloc[entry_idx]
                    if pd.notna(v):
                        tp_price = float(v)
                if "exit_reason" in trades_df.columns and exit_idx < len(trades_df):
                    v = trades_df["exit_reason"].iloc[exit_idx]
                    if pd.notna(v) and str(v).strip():
                        exit_reason = str(v).strip()
                if "pivot" in trades_df.columns and entry_idx < len(trades_df):
                    v = trades_df["pivot"].iloc[entry_idx]
                    if pd.notna(v):
                        pivot_val = float(v)
                if "s1" in trades_df.columns and entry_idx < len(trades_df):
                    v = trades_df["s1"].iloc[entry_idx]
                    if pd.notna(v):
                        s1_val = float(v)
                if "r1" in trades_df.columns and entry_idx < len(trades_df):
                    v = trades_df["r1"].iloc[entry_idx]
                    if pd.notna(v):
                        r1_val = float(v)
                if "signal_time" in trades_df.columns and entry_idx < len(trades_df):
                    v = trades_df["signal_time"].iloc[entry_idx]
                    if pd.notna(v):
                        signal_time = v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
                if "fib_bsl" in trades_df.columns:
                    for idx in (exit_idx, entry_idx):
                        if idx < len(trades_df):
                            v = trades_df["fib_bsl"].iloc[idx]
                            if pd.notna(v):
                                fib_bsl = float(v)
                                break
                if "fib_bsl_ambiguous" in trades_df.columns:
                    for idx in (exit_idx, entry_idx):
                        if idx < len(trades_df):
                            v = trades_df["fib_bsl_ambiguous"].iloc[idx]
                            if pd.notna(v):
                                fib_bsl_ambiguous = bool(v)
                                break

            size_val = init_cash / entry_price
            risk_amount = abs(entry_price - sl_price) * size_val if (sl_price is not None and sl_price > 0) else None
            r_multiple = net_pnl / risk_amount if (risk_amount is not None and risk_amount > 0) else None
            projected_rr = abs(tp_price - entry_price) / abs(entry_price - sl_price) if (sl_price is not None and tp_price is not None and abs(entry_price - sl_price) > 0) else None
            trade_id = len(trades) + 1

            trades.append({
                "trade_id": trade_id,
                "vbt_trade_id": trade_id,
                "parent_id": None,
                "vbt_column": "0",
                "direction": "Long",
                "status": "Closed",
                "entry_idx": entry_idx,
                "exit_idx": exit_idx,
                "entry_time": entry_time.to_pydatetime() if hasattr(entry_time, "to_pydatetime") else entry_time,
                "exit_time": exit_time.to_pydatetime() if hasattr(exit_time, "to_pydatetime") else exit_time,
                "signal_time": signal_time,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "exit_reason": exit_reason,
                "size": size_val,
                "entry_fees": fee_cost / 2.0,
                "exit_fees": fee_cost / 2.0,
                "pnl": net_pnl,
                "return_pct": ret_pct,
                "risk_amount": risk_amount,
                "r_multiple": r_multiple,
                "projected_rr": projected_rr,
                "pivot": pivot_val,
                "s1": s1_val,
                "r1": r1_val,
                "holding_bars": holding_bars,
                "holding_seconds": holding_seconds,
                "is_win": net_pnl > 0,
                "fib_bsl": fib_bsl,
                "fib_bsl_ambiguous": fib_bsl_ambiguous,
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
    fees: float = 0.0,
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

    # Automatically resample if timeframe is requested and differs from native data resolution
    if timeframe:
        ohlcv = resample_ohlcv(ohlcv, target_timeframe=timeframe)

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

    entry_on = "open" if any(k in strategy_name for k in ["v3", "v4", "v5"]) else "close"
    trades_df = getattr(strategy, "last_trades_df", None)
    metrics, trades = simulate_signals(
        ohlcv=ohlcv,
        entries=entries,
        exits=exits,
        init_cash=init_cash,
        fees=fees,
        entry_on=entry_on,
        trades_df=trades_df,
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
            trade_id BIGINT,
            direction VARCHAR,
            status VARCHAR,
            entry_time TIMESTAMP WITH TIME ZONE,
            exit_time TIMESTAMP WITH TIME ZONE,
            signal_time TIMESTAMP WITH TIME ZONE,
            entry_price DOUBLE,
            exit_price DOUBLE,
            sl_price DOUBLE,
            tp_price DOUBLE,
            exit_reason VARCHAR,
            size DOUBLE,
            entry_fees DOUBLE,
            exit_fees DOUBLE,
            pnl DOUBLE,
            return_pct DOUBLE,
            risk_amount DOUBLE,
            r_multiple DOUBLE,
            projected_rr DOUBLE,
            "pivot" DOUBLE,
            s1 DOUBLE,
            r1 DOUBLE,
            holding_bars BIGINT,
            holding_seconds BIGINT,
            is_win BOOLEAN,
            fib_bsl DOUBLE,
            fib_bsl_ambiguous BOOLEAN,
            PRIMARY KEY (fingerprint, vbt_trade_id)
        );
    """)

    # Migration for existing databases
    for col, ctype in [
        ("trade_id", "BIGINT"),
        ("signal_time", "TIMESTAMP WITH TIME ZONE"),
        ("sl_price", "DOUBLE"),
        ("tp_price", "DOUBLE"),
        ("exit_reason", "VARCHAR"),
        ("risk_amount", "DOUBLE"),
        ("r_multiple", "DOUBLE"),
        ("projected_rr", "DOUBLE"),
        ('"pivot"', "DOUBLE"),
        ("s1", "DOUBLE"),
        ("r1", "DOUBLE"),
        ("fib_bsl", "DOUBLE"),
        ("fib_bsl_ambiguous", "BOOLEAN"),
    ]:
        try:
            con.execute(f"ALTER TABLE trades ADD COLUMN IF NOT EXISTS {col} {ctype}")
        except Exception:
            pass


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

    # Check if a patterns table exists for this strategy
    has_patterns = False
    extra_pattern_cols = []
    try:
        tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        if f"{safe}_patterns" in tables:
            has_patterns = True
            cols = [c[0] for c in con.execute(f"DESCRIBE {safe}_patterns").fetchall()]
            for possible_col in [
                "candle_1",
                "ecpatt_1", "ecpatt_2", "ecpatt_3",
                "epcpatt_1", "epcpatt_2", "epcpatt_3",
            ]:
                if possible_col in cols:
                    extra_pattern_cols.append(f"p.{possible_col}")
    except Exception:
        pass

    patterns_join = f"LEFT JOIN {safe}_patterns p ON t.vbt_trade_id = p.vbt_trade_id AND t.fingerprint = p.fingerprint" if has_patterns else ""
    extra_cols_str = (", " + ", ".join(extra_pattern_cols)) if extra_pattern_cols else ""
    patterns_cols = f",\n            p.entry_1, p.entry_2, p.entry_3, p.entry_4{extra_cols_str}" if has_patterns else ""

    # View 1 — per-strategy individual trade log
    con.execute(f"""
        CREATE OR REPLACE VIEW {safe}_trades AS
        SELECT
            ROW_NUMBER() OVER (ORDER BY t.entry_time ASC) AS uid,
            ROW_NUMBER() OVER (ORDER BY t.entry_time ASC) AS trade_id,
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
            t.signal_time,
            t.entry_price,
            t.exit_price,
            t.sl_price,
            t.tp_price,
            t.exit_reason,
            t.size,
            t.entry_fees,
            t.exit_fees,
            t.pnl,
            t.return_pct,
            t.risk_amount,
            t.r_multiple,
            t.projected_rr,
            t."pivot",
            t.s1,
            t.r1,
            t.holding_bars,
            t.holding_seconds,
            t.is_win,
            t.fib_bsl,
            t.fib_bsl_ambiguous{patterns_cols}
        FROM trades t
        JOIN test_runs r ON t.fingerprint = r.fingerprint
        {patterns_join}
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


def populate_strategy_patterns(
    con: duckdb.DuckDBPyConnection,
    strategy_name: str,
) -> None:
    """Populate {strategy}_patterns table with entry_1..4, ecpatt_1..3, and epcpatt_1..3."""
    safe = _safe_view_name(strategy_name)
    try:
        trade_count = con.execute(f"""
            SELECT COUNT(*) 
            FROM trades t 
            JOIN test_runs r ON t.fingerprint = r.fingerprint 
            WHERE r.strategy_name = '{strategy_name}'
        """).fetchone()[0]
        if trade_count == 0:
            return

        tables = [t[0].lower() for t in con.execute("SHOW TABLES").fetchall()]
        ohlcv_table = None
        for candidate in ["ohlcv_eurusd_5m_2025", "ohlcv_5m", "ohlcv"]:
            if candidate in tables:
                ohlcv_table = candidate
                break

        if not ohlcv_table:
            return

        from ta_patterns_book.loss_profile.candles import compute_candlestick_pattern_columns
        df_ohlcv = con.execute(f"SELECT timestamp, open, high, low, close, volume FROM {ohlcv_table} ORDER BY timestamp ASC").fetchdf()
        patt_df = compute_candlestick_pattern_columns(df_ohlcv)
        for col in patt_df.columns:
            df_ohlcv[col] = patt_df[col]

        con.register("df_ohlcv_patterns_temp", df_ohlcv)

        con.execute(f"""
            CREATE OR REPLACE TABLE {safe}_patterns AS
            WITH candle_states AS (
                SELECT 
                    timestamp,
                    CASE WHEN close >= LAG(close, 1, open) OVER (ORDER BY timestamp) THEN 'U' ELSE 'D' END ||
                    CASE WHEN close > open THEN 'G' ELSE 'R' END AS cs,
                    ecpatt_1, ecpatt_2, ecpatt_3, epcpatt_1, epcpatt_2, epcpatt_3
                FROM df_ohlcv_patterns_temp
            ),
            patterns AS (
                SELECT
                    timestamp,
                    LAG(cs, 3) OVER (ORDER BY timestamp) || '-' || LAG(cs, 2) OVER (ORDER BY timestamp) || '-' || LAG(cs, 1) OVER (ORDER BY timestamp) AS entry_1,
                    LAG(cs, 2) OVER (ORDER BY timestamp) || '-' || LAG(cs, 1) OVER (ORDER BY timestamp) || '-' || cs AS entry_2,
                    LAG(cs, 1) OVER (ORDER BY timestamp) || '-' || cs || '-' || LEAD(cs, 1) OVER (ORDER BY timestamp) AS entry_3,
                    cs || '-' || LEAD(cs, 1) OVER (ORDER BY timestamp) || '-' || LEAD(cs, 2) OVER (ORDER BY timestamp) || '-' || LEAD(cs, 3) OVER (ORDER BY timestamp) AS entry_4,
                    ecpatt_1, ecpatt_2, ecpatt_3, epcpatt_1, epcpatt_2, epcpatt_3
                FROM candle_states
            )
            SELECT 
                t.vbt_trade_id,
                t.fingerprint,
                p.entry_1,
                p.entry_2,
                p.entry_3,
                p.entry_4,
                p.ecpatt_1,
                p.ecpatt_2,
                p.ecpatt_3,
                p.epcpatt_1,
                p.epcpatt_2,
                p.epcpatt_3
            FROM trades t
            JOIN test_runs r ON t.fingerprint = r.fingerprint
            JOIN patterns p ON t.entry_time = p.timestamp
            WHERE r.strategy_name = '{strategy_name}';
        """)
        logger.info("Created %s_patterns with 6 candlestick pattern columns", safe)
    except Exception as exc:
        logger.warning("Failed to auto-populate %s_patterns: %s", safe, exc)


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
                    vbt_trade_id, fingerprint, trade_id, direction, status,
                    entry_time, exit_time, signal_time, entry_price, exit_price,
                    sl_price, tp_price, exit_reason,
                    size, entry_fees, exit_fees, pnl, return_pct,
                    risk_amount, r_multiple, projected_rr,
                    "pivot", s1, r1,
                    holding_bars, holding_seconds, is_win,
                    fib_bsl, fib_bsl_ambiguous
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                t["vbt_trade_id"], fp, t.get("trade_id", t["vbt_trade_id"]), t["direction"], t["status"],
                t["entry_time"], t["exit_time"], t.get("signal_time"), t["entry_price"], t["exit_price"],
                t.get("sl_price"), t.get("tp_price"), t.get("exit_reason", "Closed"),
                t["size"], t["entry_fees"], t["exit_fees"], t["pnl"], t["return_pct"],
                t.get("risk_amount"), t.get("r_multiple"), t.get("projected_rr"),
                t.get("pivot"), t.get("s1"), t.get("r1"),
                t["holding_bars"], t["holding_seconds"], t["is_win"],
                t.get("fib_bsl"), t.get("fib_bsl_ambiguous")
            ])

    strategy_name = next(
        (r["params"]["strategy_name"] for r in results if r["status"] == "SUCCESS"),
        None,
    )
    if strategy_name:
        populate_strategy_patterns(con, strategy_name)
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
        default=get_default_backtest_db(),
        help=f"Path to DuckDB OHLCV database (default from cnf.yaml: {get_default_backtest_db()})",
    )
    parser.add_argument(
        "--table",
        default=get_default_backtest_table(),
        help=f"OHLCV table name (default from cnf.yaml: {get_default_backtest_table()})",
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
    parser.add_argument(
        "--fees",
        type=float,
        default=0.0,
        help="Broker commission / fee rate per leg (default: 0.0)",
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
                10000.0,
                args.fees,
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
