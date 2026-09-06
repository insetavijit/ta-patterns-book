"""CLI entry point for vbtspike (spec §8, DL-V6-08).

Exit codes:
  0 — success
  1 — error (including config validation failure)
  2 — dedup-skip (fingerprint matched within trust window, --force not set)

All commands load and validate config/cnf.yaml as the very first step.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import click

logger = logging.getLogger(__name__)

# Version string — kept in sync with pyproject.toml
_VERSION = "0.6.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_duration(duration_str: str) -> timedelta:
    """Parse a simple duration string like '24h', '30m', '7d' into timedelta.

    Supported suffixes: h (hours), m (minutes), d (days).
    '0' or '0h' means no cache — always re-run.
    """
    s = duration_str.strip().lower()
    if s in ("0", ""):
        return timedelta(0)
    suffixes = {"h": "hours", "m": "minutes", "d": "days"}
    for suffix, kwarg in suffixes.items():
        if s.endswith(suffix):
            try:
                return timedelta(**{kwarg: int(s[:-1])})
            except ValueError:
                pass
    raise click.BadParameter(
        f"Cannot parse duration '{duration_str}'. Use e.g. '24h', '7d', '30m'."
    )


def _resolve_window(timeframe: str) -> tuple[datetime, datetime]:
    """Derive a sensible default backtest window for a given timeframe.

    Returns (window_start, window_end) in UTC.

    Heuristic:
      - 1m/5m/15m -> 7 days
      - 1h/4h     -> 90 days
      - 1d        -> 2 years
      - otherwise -> 90 days
    """
    now = datetime.now(tz=timezone.utc)
    days_map = {
        "1m": 7, "5m": 7, "15m": 7,
        "1h": 90, "4h": 90,
        "1d": 730,
    }
    days = days_map.get(timeframe, 90)
    return now - timedelta(days=days), now


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(version=_VERSION, prog_name="vbtspike")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """vbtSpike — backtest runner and DuckDB persistence layer."""
    ctx.ensure_object(dict)


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--strategy", required=True, help="Strategy name (e.g. sma_cross).")
@click.option("--symbol", required=True, help="Ticker symbol (e.g. BTCUSDT).")
@click.option("--timeframe", required=True, help="Timeframe (e.g. 1h, 4h, 1d).")
@click.option(
    "--fast-window", default=10, show_default=True,
    help="Fast SMA window (strategy param).",
)
@click.option(
    "--slow-window", default=50, show_default=True,
    help="Slow SMA window (strategy param).",
)
@click.option(
    "--start", "--start-date", default=None,
    help="Start date/time for backtest (e.g. '2025-01-01' or '2025-01-01 09:30').",
)
@click.option(
    "--end", "--end-date", default=None,
    help="End date/time for backtest (e.g. '2025-01-15').",
)
@click.option(
    "--force", is_flag=True, default=False,
    help="Re-run even if fingerprint exists in trust window.",
)
@click.option(
    "--max-cache-age", default=None,
    help="Override max cache age, e.g. '0' for full refresh.",
)
@click.option(
    "--db", "--duckdb-path", default=None,
    help="Path to DuckDB database file (overrides cnf.yaml).",
)
@click.option(
    "--config", default=None,
    help="Path to cnf.yaml (defaults to Shared/cnf.yaml or config/cnf.yaml).",
)
def run(
    strategy: str,
    symbol: str,
    timeframe: str,
    fast_window: int,
    slow_window: int,
    start: str | None,
    end: str | None,
    force: bool,
    max_cache_age: str | None,
    db: str | None,
    config: str | None,
) -> None:
    """Run a backtest for a strategy/symbol/timeframe combination."""
    # --- Step 1: Load and validate config (DL-V6-02) ---
    from .config.loader import load_config
    cfg = load_config(Path(config) if config else None)
    target_db = Path(db) if db else Path(cfg.duckdb_path)

    # --- Step 2: Resolve strategy ---
    try:
        from ..strategies import get_strategy
        strat = get_strategy(strategy)
    except (ImportError, KeyError, ValueError):
        try:
            from Core.strategies import get_strategy
            strat = get_strategy(strategy)
        except KeyError as exc:
            click.echo(f"ERROR: {exc}", err=True)
            sys.exit(1)

    # --- Step 3: Resolve backtest window & enforce 1-month maximum duration ---
    import pandas as pd
    if start and end:
        window_start = pd.to_datetime(start, utc=True).to_pydatetime()
        window_end = pd.to_datetime(end, utc=True).to_pydatetime()
        if window_end < window_start:
            click.echo(f"ERROR: --end ({end}) must be after --start ({start}).", err=True)
            sys.exit(1)
        duration_days = (window_end - window_start).total_seconds() / 86400
        if duration_days > 31.0:
            click.echo(
                f"ERROR: Backtest duration cannot exceed 1 month / 31 days (requested: {duration_days:.1f} days). "
                f"Please specify a window of 31 days or fewer.",
                err=True,
            )
            sys.exit(1)
    elif start:
        window_start = pd.to_datetime(start, utc=True).to_pydatetime()
        window_end = (pd.to_datetime(start, utc=True) + pd.Timedelta(days=28)).to_pydatetime()
    elif end:
        window_end = pd.to_datetime(end, utc=True).to_pydatetime()
        window_start = (pd.to_datetime(end, utc=True) - pd.Timedelta(days=28)).to_pydatetime()
    else:
        # Default to 28-day window (max 1 month)
        now = datetime.now(tz=timezone.utc)
        window_start = now - timedelta(days=28)
        window_end = now

    # --- Step 4: Build params and compute fingerprint ---
    from .simulation import get_vbt_version
    params: dict[str, Any] = {
        "strategy_name": strat.name,
        "strategy_version": strat.version,
        "symbol": symbol,
        "timeframe": timeframe,
        "fast_window": fast_window,
        "slow_window": slow_window,
        "start_date": window_start.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": window_end.strftime("%Y-%m-%d %H:%M:%S"),
        "trade_type": "EXIT_TRADE",
        "vectorbt_version": get_vbt_version(),
        "data_source": "duckdb_dump",
        "initial_cash": 10000.0,
        "currency": "USD",
        "fee_model": "PERCENTAGE",
        "fees_value": 0.001,
        "slippage_pct": 0.0,
    }

    from .integrity import compute_fingerprint
    fingerprint = compute_fingerprint(params)
    logger.info("Fingerprint: %s", fingerprint[:16])

    # --- Step 5: Open DuckDB database and create/reuse batch ---
    from .storage import (
        get_connection,
        create_or_reuse_batch,
        insert_in_progress,
        upsert_complete_run,
        mark_skipped,
    )
    conn = get_connection(target_db, read_only=False)
    batch_id = create_or_reuse_batch(conn)

    # --- Step 6: Dedup check ---
    if not force:
        existing = conn.execute(
            "SELECT status FROM test_runs WHERE fingerprint = ? AND status = 'complete'",
            [fingerprint],
        ).fetchone()
        if existing:
            mark_skipped(conn, fingerprint, batch_id)
            conn.close()
            click.echo(
                f"[vbtspike] SKIP: fingerprint {fingerprint[:16]}... already complete in {target_db}. "
                "Use --force to re-run."
            )
            sys.exit(2)

    # --- Step 7: Insert in_progress sentinel ---
    insert_in_progress(conn, fingerprint, params, window_start, window_end, batch_id)

    # --- Step 8: Load OHLCV data from DuckDB ---
    click.echo(
        f"[vbtspike] Running {strategy} on {symbol}/{timeframe} "
        f"({window_start.strftime('%Y-%m-%d')} -> {window_end.strftime('%Y-%m-%d')})"
    )

    tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
    table_to_use = None
    target_candidates = [
        f"ohlcv_{symbol.lower()}_{timeframe}_2025",
        f"ohlcv_{timeframe}_2025",
        "ohlcv",
        tables[0] if tables else None,
    ]
    for candidate in target_candidates:
        if candidate and candidate in tables:
            table_to_use = candidate
            break

    if not table_to_use:
        click.echo(f"ERROR: No OHLCV table found in database. Available tables: {tables}", err=True)
        conn.close()
        sys.exit(1)

    logger.info("Loading OHLCV data from table: %s", table_to_use)
    df_raw = conn.execute(f"SELECT * FROM {table_to_use}").df()

    ts_col = "timestamp" if "timestamp" in df_raw.columns else "ts"
    if ts_col not in df_raw.columns:
        click.echo(f"ERROR: Table {table_to_use} missing timestamp/ts column", err=True)
        conn.close()
        sys.exit(1)

    df_raw = df_raw.rename(columns={ts_col: "ts"}).set_index("ts")
    df_raw.index = pd.to_datetime(df_raw.index, utc=True)

    req_cols = ["open", "high", "low", "close", "volume"]
    for col in req_cols:
        if col not in df_raw.columns:
            click.echo(f"ERROR: Table {table_to_use} missing required column: {col}", err=True)
            conn.close()
            sys.exit(1)

    ohlcv = df_raw[req_cols].sort_index()

    # Filter to requested date window
    start_ts = pd.to_datetime(window_start, utc=True)
    end_ts = pd.to_datetime(window_end, utc=True)
    ohlcv = ohlcv[(ohlcv.index >= start_ts) & (ohlcv.index <= end_ts)]

    if ohlcv.empty:
        earliest = df_raw.index.min()
        latest = df_raw.index.max()
        click.echo(
            f"ERROR: No OHLCV data available in requested range ({start} to {end}).\n"
            f"  Available database range: {earliest} to {latest} ({len(df_raw)} bars total).",
            err=True,
        )
        conn.close()
        sys.exit(1)

    click.echo(
        f"[vbtspike] Loaded {len(ohlcv)} bars from '{table_to_use}' "
        f"({ohlcv.index.min().strftime('%Y-%m-%d %H:%M')} -> {ohlcv.index.max().strftime('%Y-%m-%d %H:%M')})"
    )

    # --- Step 9: Generate signals ---
    try:
        entries, exits = strat.generate_signals(ohlcv, params)
    except Exception as exc:
        logger.error("Signal generation failed: %s", exc)
        conn.close()
        sys.exit(1)

    # --- Step 10: Run simulation ---
    from .simulation import run_backtest
    try:
        metrics, trades = run_backtest(ohlcv, entries, exits, symbol=symbol, freq=None)
    except Exception as exc:
        logger.error("Simulation failed: %s", exc)
        conn.close()
        sys.exit(1)

    # --- Step 11: Persist complete result in DuckDB ---
    upsert_complete_run(
        conn, fingerprint, params, window_start, window_end,
        metrics, trades, batch_id,
    )
    conn.close()

    sharpe_val = metrics.get("sharpe_ratio")
    sharpe_str = f"{sharpe_val:.4f}" if sharpe_val is not None else "N/A"
    click.echo(
        f"[vbtspike] DONE: return={metrics['total_return']:.4f} "
        f"sharpe={sharpe_str} "
        f"drawdown={metrics['max_drawdown']:.4f} "
        f"win_rate={metrics.get('win_rate', 0):.2%} "
        f"trades={len(trades)}\n"
        f"[vbtspike] Results saved into: {target_db}"
    )
    sys.exit(0)


# ---------------------------------------------------------------------------
# backup command
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--db", "--duckdb-path", default=None,
    help="Path to DuckDB database file (overrides cnf.yaml).",
)
@click.option(
    "--config", default=None,
    help="Path to cnf.yaml (defaults to Shared/cnf.yaml or config/cnf.yaml).",
)
def backup(db: str | None, config: str | None) -> None:
    """Create an on-demand DuckDB snapshot (spec §6)."""
    from .config.loader import load_config
    cfg = load_config(Path(config) if config else None)
    if db:
        from dataclasses import replace
        cfg = replace(cfg, duckdb_path=db)

    from .storage.backup import run_backup
    try:
        snap = run_backup(cfg)
        click.echo(f"[vbtspike] Backup complete: {snap}")
    except FileNotFoundError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)
    except Exception as exc:
        logger.error("Backup failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    cli()
