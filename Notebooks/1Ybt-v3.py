#!/usr/bin/env python3
"""1Ybt-v3.py — Direct Parquet & Dual-Mode Backtest Runner.

Enhanced version of 1Ybt-v2 supporting:
1. Direct Parquet Ingestion (--ohlcv "path/to/data.parquet" or directory):
   - Bypasses DB/table requirements when Parquet data is provided.
   - Auto-infers symbol, timeframe, and date span from parquet data & filename.
   - Slices automatically (single window for short datasets, monthly for multi-month spans).
2. Direct Strategy File Loading:
   - Accepts registered strategy names (e.g. `classic_floor_mod_v6_1`) OR direct file paths
     (e.g. `Shared/strategies/classic_floor_mod_v6/classic_floor_mod_v6_1.py`).
3. Dual-Mode Execution:
   - Executes both `allow_concurrent_trades = False` and `allow_concurrent_trades = True`.
4. Target DuckDB Persistence & Comparative Diagnostics:
   - Writes `ohlcv`, `trades_concurrent_false`, `trades_concurrent_true`,
     `monthly_performance`, `equity_curve`, `drawdown_events`, `comparative_summary`.
   - Renders borderless Rich tables.
"""

from __future__ import annotations

import argparse
import calendar
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import re
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
logger = logging.getLogger("1Ybt-v3")


# ---------------------------------------------------------------------------
# Dynamic Strategy Loader
# ---------------------------------------------------------------------------

class StrategyAdapter:
    """Wrapper to normalize strategies returning 3-tuples (entries, exits, trades_df)."""

    def __init__(self, inner: Any, name: str, version: str = "1.0.0") -> None:
        self._inner = inner
        self.name = name
        self.version = version
        self.last_trades_df: pd.DataFrame | None = None
        self.completed_trades: list[dict[str, Any]] = []

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict[str, Any] | None = None,
    ) -> tuple[pd.Series, pd.Series]:
        res = self._inner.generate_signals(ohlcv, params=params)
        if isinstance(res, tuple) and len(res) == 3:
            entries, exits, trades_df = res
            self.last_trades_df = trades_df
            self.completed_trades = getattr(self._inner, "completed_trades", [])
            return entries, exits
        elif isinstance(res, tuple) and len(res) == 2:
            entries, exits = res
            self.last_trades_df = getattr(self._inner, "last_trades_df", None)
            self.completed_trades = getattr(self._inner, "completed_trades", [])
            return entries, exits
        else:
            raise ValueError(f"Unexpected return from generate_signals: {type(res)}")


def resolve_strategy(strategy_input: str) -> tuple[Any, str]:
    """Resolve strategy from file path or registered strategy name."""
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

    # Fallback: check if file exists in Shared/strategies or Core/strategies
    candidates = [
        _REPO_ROOT / "Shared" / "strategies" / "classic_floor_mod_v6" / f"{strategy_input}.py",
        _REPO_ROOT / "Core" / "strategies" / f"{strategy_input}.py",
    ]
    for cand in candidates:
        if cand.exists():
            return resolve_strategy(str(cand))

    # Fallback: look up in registry
    return get_strategy(strategy_input), strategy_input


# ---------------------------------------------------------------------------
# Parquet / CSV OHLCV Loader & Metadata Inference
# ---------------------------------------------------------------------------

def load_ohlcv_from_parquet(path_str: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load OHLCV DataFrame from parquet or CSV file or directory, and infer metadata."""
    p = Path(path_str)
    if not p.exists():
        raise FileNotFoundError(f"OHLCV path not found: {path_str}")

    if p.is_file():
        if p.suffix.lower() in (".csv", ".txt"):
            df = pd.read_csv(p)
        else:
            df = pd.read_parquet(p)
        source_name = p.stem
    elif p.is_dir():
        files = sorted(list(p.rglob("*.parquet")) + list(p.rglob("*.perque")) + list(p.rglob("*.csv")))
        if not files:
            raise FileNotFoundError(f"No parquet or CSV files found in directory: {path_str}")
        dfs = [pd.read_csv(f) if f.suffix.lower() in (".csv", ".txt") else pd.read_parquet(f) for f in files]
        df = pd.concat(dfs, ignore_index=True)
        source_name = p.name
    else:
        raise ValueError(f"Invalid path: {path_str}")

    # Normalize column names to lowercase
    df.columns = [str(c).lower() for c in df.columns]

    # Timestamp column handling
    if "timestamp" in df.columns:
        df["ts"] = pd.to_datetime(df["timestamp"], utc=True)
    elif "date" in df.columns:
        df["ts"] = pd.to_datetime(df["date"], utc=True)
    elif "time" in df.columns:
        df["ts"] = pd.to_datetime(df["time"], utc=True)
    elif isinstance(df.index, pd.DatetimeIndex):
        df["ts"] = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
    else:
        first_col = df.columns[0]
        df["ts"] = pd.to_datetime(df[first_col], utc=True)

    ohlcv = df.set_index("ts").sort_index()
    ohlcv = ohlcv[~ohlcv.index.duplicated(keep="first")]

    # Required OHLCV columns
    for col in ["open", "high", "low", "close"]:
        if col not in ohlcv.columns:
            raise ValueError(f"Missing required candle column '{col}' in {path_str}")
        ohlcv[col] = ohlcv[col].astype(float)

    if "volume" not in ohlcv.columns:
        ohlcv["volume"] = 0.0
    else:
        ohlcv["volume"] = ohlcv["volume"].astype(float)

    # Infer timeframe from median time delta
    inferred_tf = "5m"
    if len(ohlcv) > 1:
        time_diff = ohlcv.index.to_series().diff().median()
        if pd.notna(time_diff):
            seconds = int(time_diff.total_seconds())
            if seconds == 60:
                inferred_tf = "1m"
            elif seconds == 300:
                inferred_tf = "5m"
            elif seconds == 600:
                inferred_tf = "10m"
            elif seconds == 900:
                inferred_tf = "15m"
            elif seconds == 1800:
                inferred_tf = "30m"
            elif seconds == 3600:
                inferred_tf = "1h"
            elif seconds == 14400:
                inferred_tf = "4h"
            elif seconds == 86400:
                inferred_tf = "1d"
            else:
                inferred_tf = f"{max(1, seconds // 60)}m"

    # Infer symbol from filename if matching {SYMBOL}-{DATE}... pattern
    m = re.match(r"^([A-Za-z0-9]+)-", source_name)
    inferred_symbol = m.group(1).upper() if m else "EURUSD"

    meta = {
        "source": str(p),
        "source_name": source_name,
        "symbol": inferred_symbol,
        "timeframe": inferred_tf,
        "start": ohlcv.index.min(),
        "end": ohlcv.index.max(),
        "bars": len(ohlcv),
    }
    return ohlcv, meta


# ---------------------------------------------------------------------------
# Slicing & Window Construction
# ---------------------------------------------------------------------------

def build_windows_from_ohlcv(
    ohlcv: pd.DataFrame,
) -> list[tuple[str, datetime, datetime]]:
    """Build simulation windows from loaded OHLCV index."""
    start_dt = ohlcv.index.min().to_pydatetime()
    end_dt = ohlcv.index.max().to_pydatetime()
    span_days = (end_dt - start_dt).days

    if span_days <= 32:
        # Single window for datasets under ~1 month
        lbl = f"{start_dt.strftime('%Y%m%d')}_{end_dt.strftime('%Y%m%d')}"
        return [(lbl, start_dt, end_dt)]

    # Multi-month span: split into calendar months
    windows: list[tuple[str, datetime, datetime]] = []
    curr = datetime(start_dt.year, start_dt.month, 1, tzinfo=timezone.utc)
    while curr <= end_dt:
        y, m = curr.year, curr.month
        _, last_day = calendar.monthrange(y, m)
        m_start = max(start_dt, datetime(y, m, 1, 0, 0, 0, tzinfo=timezone.utc))
        m_end = min(end_dt, datetime(y, m, last_day, 23, 59, 59, tzinfo=timezone.utc))
        if m_start < m_end:
            windows.append((f"{y}-{m:02d}", m_start, m_end))
        # Advance to next month
        curr = datetime(y, m, last_day, 0, 0, 0, tzinfo=timezone.utc) + timedelta(days=1)

    return windows


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
    return str(_REPO_ROOT / "Shared" / "Data" / "Ohlcv_2325Eurusd.duckdb")


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


def should_run_post_enrich(cli_choice: str | None, repo_root: Path) -> tuple[bool, str, bool]:
    """Determine if post-test enrichment should run."""
    cnf_file = repo_root / "Shared" / "cnf.yaml"
    cfg_status = "off"
    runner_script = "Shared/strategies/_helpers/post-test-enrichment.py"
    with_info = False
    if cnf_file.exists():
        try:
            with open(cnf_file, "r", encoding="utf-8") as f:
                cdata = yaml.safe_load(f)
            enrich_block = cdata.get("post_test_enrichment", {})
            cfg_status = str(enrich_block.get("status", "off")).strip().lower()
            if "enabled" in enrich_block and not enrich_block.get("enabled"):
                cfg_status = "off"
            if "runner" in enrich_block and isinstance(enrich_block["runner"], str):
                runner_script = enrich_block["runner"]
            with_info = bool(enrich_block.get("with_info", False))
        except Exception:
            pass

    final_choice = cli_choice.strip().lower() if cli_choice is not None else cfg_status
    return (final_choice in ("on", "true", "yes", "1"), runner_script, with_info)


# ---------------------------------------------------------------------------
# Metrics & Simulation Engine
# ---------------------------------------------------------------------------

def compute_metrics_from_trades(
    trades: list[dict[str, Any]],
    close_series: pd.Series,
    init_cash: float = 10000.0,
) -> dict[str, Any]:
    """Compute standard backtest summary metrics."""
    total_trades = len(trades)
    if total_trades > 0:
        win_trades = [t for t in trades if t.get("is_win") in (True, 1)]
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


def execute_slice(
    ohlcv_slice: pd.DataFrame,
    strategy_input: str,
    window_label: str,
    symbol: str,
    timeframe: str,
    allow_concurrent_trades: bool = False,
    init_cash: float = 10000.0,
    fees: float = 0.0,
) -> dict[str, Any]:
    """Execute strategy on an in-memory OHLCV slice."""
    if ohlcv_slice.empty:
        return {
            "month": window_label,
            "window_start": None,
            "window_end": None,
            "status": "NO_DATA",
            "bars": 0,
            "metrics": {},
            "trades": [],
        }

    w_start = ohlcv_slice.index.min().to_pydatetime()
    w_end = ohlcv_slice.index.max().to_pydatetime()

    strategy, strategy_name = resolve_strategy(strategy_input)
    version = getattr(strategy, "version", "1.0.0")

    strategy_params = {"allow_concurrent_trades": allow_concurrent_trades}
    entries, exits = strategy.generate_signals(ohlcv_slice, params=strategy_params)

    completed_trades = getattr(strategy, "completed_trades", None)
    if completed_trades:
        trades = []
        for t in completed_trades:
            tr = dict(t)
            tr["symbol"] = symbol
            tr["timeframe"] = timeframe
            tr["strategy_name"] = strategy_name
            tr["window_start"] = w_start
            tr["window_end"] = w_end
            tr["allow_concurrent_trades"] = allow_concurrent_trades
            trades.append(tr)
        metrics = compute_metrics_from_trades(trades, ohlcv_slice["close"], init_cash)
    else:
        # Fallback single position simulation
        trades = []
        pos = 0
        entry_p, entry_t, entry_i = 0.0, None, 0
        for i, (ts, row) in enumerate(ohlcv_slice.iterrows()):
            is_en = bool(entries.iloc[i]) if i < len(entries) else False
            is_ex = bool(exits.iloc[i]) if i < len(exits) else False
            curr = float(row["close"])
            if is_en and pos == 0:
                pos = 1
                entry_p = float(row.get("open", curr))
                entry_t = ts
                entry_i = i
            elif is_ex and pos == 1:
                net_pnl = (curr - entry_p) / entry_p * init_cash - (init_cash * fees * 2.0)
                trades.append({
                    "trade_id": len(trades) + 1,
                    "entry_time": entry_t,
                    "exit_time": ts,
                    "entry_price": entry_p,
                    "exit_price": curr,
                    "pnl": net_pnl,
                    "return_pct": (curr - entry_p) / entry_p * 100.0,
                    "is_win": net_pnl > 0,
                    "holding_bars": i - entry_i,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "strategy_name": strategy_name,
                    "allow_concurrent_trades": allow_concurrent_trades,
                })
                pos = 0
        metrics = compute_metrics_from_trades(trades, ohlcv_slice["close"], init_cash)

    return {
        "month": window_label,
        "window_start": w_start,
        "window_end": w_end,
        "status": "SUCCESS",
        "bars": len(ohlcv_slice),
        "metrics": metrics,
        "trades": trades,
    }


# ---------------------------------------------------------------------------
# Database Persistence
# ---------------------------------------------------------------------------

def persist_to_duckdb(
    target_db: str,
    ohlcv_df: pd.DataFrame,
    trades_false: list[dict[str, Any]],
    trades_true: list[dict[str, Any]],
    results_false: list[dict[str, Any]],
    results_true: list[dict[str, Any]],
    strategy_name: str,
    init_cash: float = 10000.0,
) -> list[str]:
    """Persist all simulation tables into target DuckDB."""
    target_path = Path(target_db)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(target_path), read_only=False)

    created_tables: list[str] = []

    # 1. ohlcv table
    ohlcv_clean = ohlcv_df.reset_index()
    if "ts" in ohlcv_clean.columns and "timestamp" not in ohlcv_clean.columns:
        ohlcv_clean = ohlcv_clean.rename(columns={"ts": "timestamp"})
    if "index" in ohlcv_clean.columns and "timestamp" not in ohlcv_clean.columns:
        ohlcv_clean = ohlcv_clean.rename(columns={"index": "timestamp"})

    keep_cols = [c for c in ["timestamp", "open", "high", "low", "close", "volume"] if c in ohlcv_clean.columns]
    con.register("df_ohlcv_tmp", ohlcv_clean[keep_cols])
    con.execute("CREATE OR REPLACE TABLE ohlcv AS SELECT * FROM df_ohlcv_tmp")
    created_tables.append("ohlcv")

    # 2. trades_concurrent_false & trades_concurrent_true
    for tbl_name, t_list in [
        ("trades_concurrent_false", trades_false),
        ("trades_concurrent_true", trades_true),
    ]:
        if t_list:
            df_tr = pd.DataFrame(t_list)
            # Add uid index
            if "uid" not in df_tr.columns:
                df_tr.insert(0, "uid", range(1, len(df_tr) + 1))
            con.register(f"df_{tbl_name}_tmp", df_tr)
            con.execute(f"CREATE OR REPLACE TABLE {tbl_name} AS SELECT * FROM df_{tbl_name}_tmp")
            created_tables.append(tbl_name)

    # 3. monthly_performance
    mp_rows = []
    for mode_name, res_list in [("concurrent_false", results_false), ("concurrent_true", results_true)]:
        for r in res_list:
            if r["status"] == "SUCCESS":
                m = r["metrics"]
                t_cnt = m.get("total_trades", 0)
                wr = m.get("win_rate", 0.0) * 100.0
                mp_rows.append({
                    "window": r["month"],
                    "mode": mode_name,
                    "strategy_name": strategy_name,
                    "trades": t_cnt,
                    "win_rate_pct": wr,
                    "return_pct": m.get("total_return", 0.0) * 100.0,
                    "max_drawdown_pct": m.get("max_drawdown", 0.0) * 100.0,
                    "profit_factor": m.get("profit_factor", 0.0),
                    "sharpe_ratio": m.get("sharpe_ratio", 0.0),
                })
    if mp_rows:
        df_mp = pd.DataFrame(mp_rows)
        con.register("df_mp_tmp", df_mp)
        con.execute("CREATE OR REPLACE TABLE monthly_performance AS SELECT * FROM df_mp_tmp")
        created_tables.append("monthly_performance")

    # 4. comparative_summary or portfolio_summary
    if trades_false and trades_true:
        def _summary(t_list: list[dict[str, Any]], res_list: list[dict[str, Any]]) -> dict[str, Any]:
            cnt = len(t_list)
            wins = sum(1 for t in t_list if t.get("is_win") in (True, 1, "1"))
            wr = (wins / cnt * 100.0) if cnt > 0 else 0.0
            pnl = sum(float(t.get("pnl", 0.0)) for t in t_list)
            comp_ret = 1.0
            for r in res_list:
                comp_ret *= (1.0 + r["metrics"].get("total_return", 0.0))
            return {"trades": cnt, "win_rate": wr, "pnl": pnl, "ret": (comp_ret - 1.0) * 100.0}

        s_false = _summary(trades_false, results_false)
        s_true = _summary(trades_true, results_true)

        comp_rows = [
            {"metric": "Total Trades", "concurrent_false": str(s_false["trades"]), "concurrent_true": str(s_true["trades"]), "delta": f"{s_true['trades'] - s_false['trades']:+d}"},
            {"metric": "Win Rate %", "concurrent_false": f"{s_false['win_rate']:.1f}%", "concurrent_true": f"{s_true['win_rate']:.1f}%", "delta": f"{s_true['win_rate'] - s_false['win_rate']:+.1f}%"},
            {"metric": "Realized PnL ($)", "concurrent_false": f"${s_false['pnl']:+,.2f}", "concurrent_true": f"${s_true['pnl']:+,.2f}", "delta": f"${s_true['pnl'] - s_false['pnl']:+,.2f}"},
            {"metric": "Compound Return %", "concurrent_false": f"{s_false['ret']:+.2f}%", "concurrent_true": f"{s_true['ret']:+.2f}%", "delta": f"{s_true['ret'] - s_false['ret']:+.2f}%"},
        ]
        con.register("df_comp_tmp", pd.DataFrame(comp_rows))
        con.execute("CREATE OR REPLACE TABLE comparative_summary AS SELECT * FROM df_comp_tmp")
        created_tables.append("comparative_summary")
    elif trades_false or trades_true:
        active_t = trades_false or trades_true
        cnt = len(active_t)
        wins = sum(1 for t in active_t if t.get("is_win") in (True, 1, "1"))
        wr = (wins / cnt * 100.0) if cnt > 0 else 0.0
        pnl = sum(float(t.get("pnl", 0.0)) for t in active_t)
        summary_rows = [
            {"metric": "Total Trades", "value": str(cnt)},
            {"metric": "Win Rate %", "value": f"{wr:.1f}%"},
            {"metric": "Realized PnL ($)", "value": f"${pnl:+,.2f}"},
        ]
        con.register("df_summary_tmp", pd.DataFrame(summary_rows))
        con.execute("CREATE OR REPLACE TABLE portfolio_summary AS SELECT * FROM df_summary_tmp")
        created_tables.append("portfolio_summary")

    con.close()
    return created_tables


# ---------------------------------------------------------------------------
# Terminal Rendering
# ---------------------------------------------------------------------------

def render_results(
    title: str,
    results: list[dict[str, Any]],
    console: Console,
) -> None:
    """Render Rich borderless summary table."""
    table = Table(title=title, box=None, header_style="bold cyan")
    table.add_column("Window / Month", style="bold")
    table.add_column("Start", justify="center")
    table.add_column("End", justify="center")
    table.add_column("Bars", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("Return %", justify="right")
    table.add_column("Max DD %", justify="right")
    table.add_column("Profit Factor", justify="right")

    for r in results:
        if r["status"] != "SUCCESS":
            table.add_row(r["month"], "-", "-", "0", "0", "-", "-", "-", "-")
            continue
        m = r["metrics"]
        ret = m.get("total_return", 0.0) * 100.0
        ret_style = "green" if ret >= 0 else "red"
        table.add_row(
            r["month"],
            r["window_start"].strftime("%Y-%m-%d"),
            r["window_end"].strftime("%Y-%m-%d"),
            f"{r['bars']:,}",
            str(m.get("total_trades", 0)),
            f"{m.get('win_rate', 0.0) * 100.0:.1f}%",
            f"[{ret_style}]{ret:+.2f}%[/{ret_style}]",
            f"{m.get('max_drawdown', 0.0) * 100.0:.2f}%",
            f"{m.get('profit_factor', 0.0):.2f}",
        )
    console.print(table)


def render_comparison(
    trades_false: list[dict[str, Any]],
    trades_true: list[dict[str, Any]],
    results_false: list[dict[str, Any]],
    results_true: list[dict[str, Any]],
    console: Console,
) -> None:
    """Render side-by-side diagnostic comparison."""
    table = Table(title="Comparative Execution Diagnostics", box=None, header_style="bold magenta")
    table.add_column("Performance Metric", style="bold")
    table.add_column("Concurrent: FALSE", justify="right")
    table.add_column("Concurrent: TRUE", justify="right")
    table.add_column("Delta (True - False)", justify="right")

    cnt_f, cnt_t = len(trades_false), len(trades_true)
    table.add_row("Total Executed Trades", str(cnt_f), str(cnt_t), f"{cnt_t - cnt_f:+d}")

    wr_f = (sum(1 for t in trades_false if t.get("is_win") in (True, 1)) / cnt_f * 100) if cnt_f else 0.0
    wr_t = (sum(1 for t in trades_true if t.get("is_win") in (True, 1)) / cnt_t * 100) if cnt_t else 0.0
    table.add_row("Win Rate", f"{wr_f:.1f}%", f"{wr_t:.1f}%", f"{wr_t - wr_f:+.1f}%")

    pnl_f = sum(float(t.get("pnl", 0.0)) for t in trades_false)
    pnl_t = sum(float(t.get("pnl", 0.0)) for t in trades_true)
    table.add_row("Realized Net PnL", f"${pnl_f:+,.2f}", f"${pnl_t:+,.2f}", f"${pnl_t - pnl_f:+,.2f}")

    console.print("\n")
    console.print(table)


# ---------------------------------------------------------------------------
# Portfolio JSON Results Exporter
# ---------------------------------------------------------------------------

def dump_portfolio_results(
    dump_target: str | bool,
    strategy_name: str,
    symbol: str,
    timeframe: str,
    ohlcv_df: pd.DataFrame,
    trades_false: list[dict[str, Any]],
    trades_true: list[dict[str, Any]],
    results_false: list[dict[str, Any]],
    results_true: list[dict[str, Any]],
    meta: dict[str, Any] | None = None,
    init_cash: float = 10000.0,
) -> Path:
    """Dump high-level portfolio performance summary (excluding individual trade logs) as JSON."""
    if isinstance(dump_target, str) and dump_target.strip():
        out_path = Path(dump_target)
    else:
        out_path = Path(f"Shared/OUTs/{strategy_name}_{symbol.lower()}_{timeframe}_portfolio.json")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    def _calc_mode_portfolio(t_list: list[dict[str, Any]], res_list: list[dict[str, Any]]) -> dict[str, Any]:
        cnt = len(t_list)
        if cnt == 0:
            return {
                "total_trades": 0,
                "win_rate_pct": 0.0,
                "net_pnl": 0.0,
                "total_return_pct": 0.0,
                "profit_factor": 0.0,
                "max_drawdown_pct": 0.0,
            }

        wins = [t for t in t_list if t.get("is_win") in (True, 1, "1")]
        losses = [t for t in t_list if t.get("is_win") in (False, 0, -1, "0")]
        pnls = [float(t.get("pnl", 0.0)) for t in t_list]
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        net_pnl = sum(pnls)
        win_rate = len(wins) / cnt * 100.0
        pf = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

        compound_ret = 1.0
        max_dd = 0.0
        monthly_sharpes = []
        for r in res_list:
            if r.get("status") == "SUCCESS":
                m = r.get("metrics", {})
                compound_ret *= (1.0 + m.get("total_return", 0.0))
                max_dd = max(max_dd, m.get("max_drawdown", 0.0))
                sh = m.get("sharpe_ratio")
                if sh is not None and not np.isnan(sh):
                    monthly_sharpes.append(sh)

        holding_bars = [int(t.get("holding_bars", 0)) for t in t_list if t.get("holding_bars") is not None]
        avg_bars = float(np.mean(holding_bars)) if holding_bars else 0.0

        avg_win = (gross_profit / len(wins)) if wins else 0.0
        avg_loss = (gross_loss / len(losses)) if losses else 0.0
        payoff = (avg_win / avg_loss) if avg_loss > 0 else 0.0

        bench_ret = 0.0
        if len(ohlcv_df) > 1:
            c0, c1 = float(ohlcv_df["close"].iloc[0]), float(ohlcv_df["close"].iloc[-1])
            bench_ret = (c1 - c0) / c0 * 100.0

        return {
            "total_trades": cnt,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate_pct": round(win_rate, 2),
            "net_pnl_usd": round(net_pnl, 2),
            "gross_profit_usd": round(gross_profit, 2),
            "gross_loss_usd": round(gross_loss, 2),
            "profit_factor": round(pf, 2),
            "expectancy_usd": round(net_pnl / cnt, 2),
            "avg_win_usd": round(avg_win, 2),
            "avg_loss_usd": round(avg_loss, 2),
            "payoff_ratio": round(payoff, 2),
            "compound_return_pct": round((compound_ret - 1.0) * 100.0, 2),
            "benchmark_return_pct": round(bench_ret, 2),
            "max_drawdown_pct": round(max_dd * 100.0, 2),
            "sharpe_ratio": round(float(np.mean(monthly_sharpes)), 2) if monthly_sharpes else None,
            "avg_holding_bars": round(avg_bars, 1),
        }

    stats_false = _calc_mode_portfolio(trades_false, results_false)
    stats_true = _calc_mode_portfolio(trades_true, results_true)

    start_ts = ohlcv_df.index.min().isoformat() if not ohlcv_df.empty else None
    end_ts = ohlcv_df.index.max().isoformat() if not ohlcv_df.empty else None

    dump_payload = {
        "report_type": "portfolio_summary",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": strategy_name,
        "symbol": symbol,
        "timeframe": timeframe,
        "market_dataset": {
            "start": start_ts,
            "end": end_ts,
            "total_bars": len(ohlcv_df),
            "source_file": meta.get("source") if meta else "duckdb",
        },
        "portfolio_results": {
            "concurrent_false": stats_false,
            "concurrent_true": stats_true,
            "comparison_delta": {
                "trades_delta": stats_true["total_trades"] - stats_false["total_trades"],
                "win_rate_delta_pct": round(stats_true["win_rate_pct"] - stats_false["win_rate_pct"], 2),
                "net_pnl_delta_usd": round(stats_true["net_pnl_usd"] - stats_false["net_pnl_usd"], 2),
                "compound_return_delta_pct": round(stats_true["compound_return_pct"] - stats_false["compound_return_pct"], 2),
                "profit_factor_delta": round(stats_true["profit_factor"] - stats_false["profit_factor"], 2),
            },
        },
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dump_payload, f, indent=2, default=str)

    return out_path


# ---------------------------------------------------------------------------
# CLI & Main Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="1Ybt-v3: Direct Parquet & Dual-Mode Backtest Runner"
    )
    parser.add_argument(
        "--ohlcv",
        dest="ohlcv",
        help="Direct path to Parquet file (.parquet) or directory. Bypasses DuckDB table requirement.",
    )
    parser.add_argument(
        "--strategy",
        "-s",
        default="classic_floor_mod_v6_1",
        help="Registered strategy name OR path to strategy .py file (default: classic_floor_mod_v6_1)",
    )
    parser.add_argument(
        "--year",
        "-y",
        type=int,
        default=2025,
        help="Calendar year to backtest when using DB mode (default: 2025)",
    )
    parser.add_argument(
        "--db",
        default=get_default_backtest_db(),
        help="Source DuckDB database path (used when --ohlcv is not provided)",
    )
    parser.add_argument(
        "--table",
        default=get_default_backtest_table(),
        help="Source OHLCV table name in DuckDB (used when --ohlcv is not provided)",
    )
    parser.add_argument(
        "--output-db",
        dest="output_db",
        help="Target DuckDB database path (default: Shared/OUTs/duckdb/<strategy>_<symbol>_<tf>.duckdb)",
    )
    parser.add_argument(
        "--symbol",
        help="Symbol ticker (e.g. EURUSD). Auto-inferred if using --ohlcv.",
    )
    parser.add_argument(
        "--timeframe",
        "--tf",
        dest="timeframe",
        help="Candle timeframe (e.g. 5m). Auto-inferred if using --ohlcv.",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=4,
        help="Process pool workers for multi-slice execution (default: 4)",
    )
    parser.add_argument(
        "--fees",
        type=float,
        default=0.0,
        help="Broker commission fee rate per leg (default: 0.0)",
    )
    parser.add_argument(
        "--post-enrich",
        choices=["on", "off"],
        default=None,
        help="Run post-test database enrichment pipeline ('on' or 'off')",
    )
    parser.add_argument(
        "--dump",
        nargs="?",
        const=True,
        default=None,
        help="Dump high-level portfolio performance summary (excluding individual trade logs) as JSON",
    )

    args = parser.parse_args()
    console = Console()

    console.print("[bold cyan]1Ybt-v3: Direct Parquet & Dual-Mode Backtest Runner[/bold cyan]")

    # Resolve strategy
    _, strategy_name = resolve_strategy(args.strategy)
    console.print(f"  • Strategy    : [bold yellow]{strategy_name}[/bold yellow] ({args.strategy})")

    # Mode 1: Direct Parquet Ingestion
    if args.ohlcv:
        console.print(f"  • Mode        : [bold green]Direct Parquet File/Directory[/bold green]")
        ohlcv_df, meta = load_ohlcv_from_parquet(args.ohlcv)
        symbol = args.symbol or meta["symbol"]
        timeframe = args.timeframe or meta["timeframe"]
        console.print(f"  • Source      : {meta['source']}")
        console.print(f"  • Symbol/TF   : [bold]{symbol}[/bold] / [bold]{timeframe}[/bold] (inferred from data)")
        console.print(f"  • Date Range  : {meta['start']} -> {meta['end']} ([bold]{meta['bars']:,}[/bold] bars)")

        windows = build_windows_from_ohlcv(ohlcv_df)
        console.print(f"  • Windows     : Discovered [bold]{len(windows)} simulation window(s)[/bold]")

        default_out = f"Shared/OUTs/duckdb/{strategy_name}_{symbol.lower()}_{timeframe}.duckdb"
        target_db = args.output_db or default_out
    else:
        # Mode 2: DuckDB Table Mode (compatible with 1Ybt-v2)
        console.print(f"  • Mode        : [bold blue]DuckDB Table Query[/bold blue]")
        symbol = args.symbol or "EURUSD"
        timeframe = args.timeframe or "5m"
        target_db = args.output_db or f"Shared/OUTs/duckdb/{strategy_name}.duckdb"

        con = duckdb.connect(args.db, read_only=True)
        query = f"SELECT timestamp AS ts, open, high, low, close, volume FROM {args.table} WHERE EXTRACT(year FROM timestamp) = {args.year} ORDER BY timestamp ASC"
        df_raw = con.execute(query).df()
        con.close()
        df_raw["ts"] = pd.to_datetime(df_raw["ts"], utc=True)
        ohlcv_df = df_raw.set_index("ts").sort_index()
        if timeframe and timeframe != "1m":
            ohlcv_df = resample_ohlcv(ohlcv_df, target_timeframe=timeframe)
        windows = build_windows_from_ohlcv(ohlcv_df)

    is_explicit_blocking = strategy_name.upper().endswith("B") or "BLOCKING" in strategy_name.upper()
    is_explicit_concurrent = strategy_name.upper().endswith("C") or "CONCURRENT" in strategy_name.upper()

    run_phase_false = not is_explicit_concurrent
    run_phase_true = not is_explicit_blocking

    # Run Phase 1: allow_concurrent_trades = False
    results_false: list[dict[str, Any]] = []
    trades_false: list[dict[str, Any]] = []
    if run_phase_false:
        console.print(f"\n[bold]Phase 1: Concurrent = FALSE[/bold]")
        for w_lbl, w_start, w_end in windows:
            sub = ohlcv_df.loc[w_start:w_end]
            res = execute_slice(
                ohlcv_slice=sub,
                strategy_input=args.strategy,
                window_label=w_lbl,
                symbol=symbol,
                timeframe=timeframe,
                allow_concurrent_trades=False,
                fees=args.fees,
            )
            results_false.append(res)
            trades_false.extend(res["trades"])

        render_results(
            title=f"Summary (CONCURRENT: FALSE) — {strategy_name.upper()}",
            results=results_false,
            console=console,
        )

    # Run Phase 2: allow_concurrent_trades = True
    results_true: list[dict[str, Any]] = []
    trades_true: list[dict[str, Any]] = []
    if run_phase_true:
        console.print(f"\n[bold]Phase 2: Concurrent = TRUE[/bold]")
        for w_lbl, w_start, w_end in windows:
            sub = ohlcv_df.loc[w_start:w_end]
            res = execute_slice(
                ohlcv_slice=sub,
                strategy_input=args.strategy,
                window_label=w_lbl,
                symbol=symbol,
                timeframe=timeframe,
                allow_concurrent_trades=True,
                fees=args.fees,
            )
            results_true.append(res)
            trades_true.extend(res["trades"])

        render_results(
            title=f"Summary (CONCURRENT: TRUE) — {strategy_name.upper()}",
            results=results_true,
            console=console,
        )

    # Comparative Diagnostics (only if both phases were run)
    if run_phase_false and run_phase_true:
        render_comparison(
            trades_false=trades_false,
            trades_true=trades_true,
            results_false=results_false,
            results_true=results_true,
            console=console,
        )

    # Persist to DuckDB
    console.print(f"\n[bold cyan]▶ Persisting results to DuckDB: {target_db}...[/bold cyan]")
    created_tables = persist_to_duckdb(
        target_db=target_db,
        ohlcv_df=ohlcv_df,
        trades_false=trades_false,
        trades_true=trades_true,
        results_false=results_false,
        results_true=results_true,
        strategy_name=strategy_name,
    )
    for tbl in created_tables:
        console.print(f"  • Created table: [bold green]{tbl}[/bold green]")

    # Dump portfolio results if requested
    if args.dump:
        dump_meta = meta if args.ohlcv else {"source": f"{args.db}:{args.table}"}
        dump_file = dump_portfolio_results(
            dump_target=args.dump,
            strategy_name=strategy_name,
            symbol=symbol,
            timeframe=timeframe,
            ohlcv_df=ohlcv_df,
            trades_false=trades_false,
            trades_true=trades_true,
            results_false=results_false,
            results_true=results_true,
            meta=dump_meta,
        )
        console.print(f"\n[bold green]✓ Portfolio summary JSON dumped to:[/] [cyan]{dump_file}[/cyan]")

    # Post-Test Database Enrichment Pipeline
    run_enrich, runner_rel, with_info_flag = should_run_post_enrich(args.post_enrich, _REPO_ROOT)
    if run_enrich:
        console.print(f"\n[bold cyan]▶ Launching Post-Test Database Enrichment Pipeline...[/bold cyan]")
        import subprocess
        runner_path = _REPO_ROOT / runner_rel if not Path(runner_rel).is_absolute() else Path(runner_rel)
        if runner_path.exists():
            cmd = [
                "uv", "run", "python", str(runner_path),
                "--target", str(target_db),
                "--strategy", str(strategy_name),
                "--tf", str(timeframe),
            ]
            if with_info_flag:
                cmd.append("--with-info")
            subprocess.run(cmd)

    console.print(f"\n[bold green]✓ Backtest and persistence completed successfully![/bold green]\n")


if __name__ == "__main__":
    main()
