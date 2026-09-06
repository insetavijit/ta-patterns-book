"""Backtest runner — sole module that imports vectorbt.

Takes entry/exit signals from a strategy and OHLCV data, runs a vectorbt
Portfolio simulation, and returns structured metrics and trade records.

No DuckDB, no config, no fingerprinting here — those are the caller's concern.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd
import vectorbt as vbt

logger = logging.getLogger(__name__)


def get_vbt_version() -> str:
    """Return the installed vectorbt version string."""
    return str(vbt.__version__)


def run_backtest(
    ohlcv: pd.DataFrame,
    entries: pd.Series,
    exits: pd.Series,
    symbol: str,
    freq: str | None = None,
    init_cash: float = 10_000.0,
    fees: float = 0.001,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Run a vectorbt Portfolio simulation and return metrics + trade log.

    Args:
        ohlcv: OHLCV DataFrame indexed by timestamp. Must have a 'close' column.
        entries: Boolean Series aligned to ohlcv.index. True = entry signal.
        exits: Boolean Series aligned to ohlcv.index. True = exit signal.
        symbol: Ticker symbol, used for logging.
        freq: Frequency string (e.g. '1m', '1h', '1d') to bypass slow inference.
        init_cash: Initial portfolio cash (default 10,000).
        fees: Round-trip fee fraction (default 0.1%).

    Returns:
        (metrics, trades) where:
        - metrics: dict with keys total_return, sharpe, max_drawdown.
        - trades: list of dicts with keys ts, side, price, size.
    """
    logger.info(
        "Running backtest for %s (%d bars, %d entries)",
        symbol, len(ohlcv), entries.sum(),
    )

    pf = vbt.Portfolio.from_signals(
        close=ohlcv["close"],
        entries=entries,
        exits=exits,
        freq=freq,
        init_cash=init_cash,
        fees=fees,
    )

    metrics = _extract_metrics(pf, ohlcv)
    trades = _extract_trades(pf)

    logger.info(
        "Backtest complete: return=%.4f sharpe=%s drawdown=%.4f trades=%d",
        metrics["total_return"],
        metrics.get("sharpe_ratio"),
        metrics["max_drawdown"],
        len(trades),
    )

    return metrics, trades


def _extract_metrics(pf: vbt.Portfolio, ohlcv: pd.DataFrame) -> dict[str, Any]:
    """Extract comprehensive metrics matching Shared/test-schema.json."""
    try:
        sharpe = float(pf.sharpe_ratio())
        if pd.isna(sharpe):
            sharpe = None
    except Exception:
        sharpe = None

    try:
        sortino = float(pf.sortino_ratio())
        if pd.isna(sortino):
            sortino = None
    except Exception:
        sortino = None

    try:
        win_rate = float(pf.trades.win_rate())
        if pd.isna(win_rate):
            win_rate = 0.0
    except Exception:
        win_rate = 0.0

    try:
        profit_factor = float(pf.trades.profit_factor())
        if pd.isna(profit_factor):
            profit_factor = 0.0
    except Exception:
        profit_factor = 0.0

    try:
        bench_ret = float((ohlcv["close"].iloc[-1] - ohlcv["close"].iloc[0]) / ohlcv["close"].iloc[0])
    except Exception:
        bench_ret = 0.0

    return {
        "total_return": float(pf.total_return()),
        "benchmark_return": bench_ret,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "max_drawdown": float(pf.max_drawdown()),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_trades": int(pf.trades.count()),
    }


def _extract_trades(pf: vbt.Portfolio) -> list[dict[str, Any]]:
    """Extract complete trade book matching Shared/test-schema.json."""
    trades_df = pf.trades.records_readable
    if trades_df.empty:
        return []

    raw_records = pf.trades.records
    results: list[dict[str, Any]] = []

    for i, row in enumerate(trades_df.to_dict("records")):
        # Raw indices
        entry_idx = int(raw_records["entry_idx"][i]) if i < len(raw_records) else None
        exit_idx = int(raw_records["exit_idx"][i]) if (i < len(raw_records) and raw_records["exit_idx"][i] >= 0) else None

        # Timestamps
        entry_ts_raw = row.get("Entry Timestamp") if "Entry Timestamp" in row else row.get("Entry Index")
        exit_ts_raw = row.get("Exit Timestamp") if "Exit Timestamp" in row else row.get("Exit Index")

        entry_time = _to_datetime(entry_ts_raw)
        exit_time = _to_datetime(exit_ts_raw) if exit_ts_raw is not None and pd.notna(exit_ts_raw) else None

        # Prices & sizes
        entry_price = float(row.get("Avg Entry Price", 0.0))
        exit_price = float(row.get("Avg Exit Price", 0.0)) if pd.notna(row.get("Avg Exit Price")) else None
        size = float(row.get("Size", 0.0))
        entry_fees = float(row.get("Entry Fees", 0.0)) if pd.notna(row.get("Entry Fees")) else 0.0
        exit_fees = float(row.get("Exit Fees", 0.0)) if pd.notna(row.get("Exit Fees")) else 0.0
        pnl = float(row.get("PnL", 0.0)) if pd.notna(row.get("PnL")) else 0.0
        return_pct = float(row.get("Return", 0.0)) if pd.notna(row.get("Return")) else 0.0

        # Holding duration
        holding_bars = (exit_idx - entry_idx) if (exit_idx is not None and entry_idx is not None) else None
        holding_seconds = int((exit_time - entry_time).total_seconds()) if (exit_time and entry_time) else None

        results.append({
            "vbt_trade_id": int(row.get("Exit Trade Id", row.get("Trade Id", i))),
            "parent_id": int(row.get("Parent Id")) if (row.get("Parent Id") is not None and pd.notna(row.get("Parent Id"))) else None,
            "vbt_column": str(row.get("Column", 0)),
            "direction": str(row.get("Direction", "Long")),
            "status": str(row.get("Status", "Closed")),
            "entry_idx": entry_idx,
            "exit_idx": exit_idx,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "size": size,
            "entry_fees": entry_fees,
            "exit_fees": exit_fees,
            "pnl": pnl,
            "return_pct": return_pct,
            "holding_bars": holding_bars,
            "holding_seconds": holding_seconds,
            "is_win": bool(pnl > 0),
            "notes": None,
        })

    return results


def _to_datetime(value: Any) -> datetime | None:
    """Safely convert a pandas Timestamp or index label to a Python datetime."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return pd.Timestamp(value).to_pydatetime()
    except Exception:
        return None
