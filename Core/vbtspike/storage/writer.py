"""Write operations for batches and test_runs tables.

This module is the sole place that writes to test_runs. All writes go through
named functions — no ad-hoc SQL outside this file.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

import uuid

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

def create_or_reuse_batch(
    conn: "duckdb.DuckDBPyConnection",
    batch_id: str | None = None,
    note: str | None = None,
) -> str:
    """Create a new batches row, or reuse an existing one.

    Args:
        conn: Open DuckDB connection.
        batch_id: Explicit batch ID. If None, a new UUID4 is generated.
        note: Optional human-readable label for this batch.

    Returns:
        The batch_id that was created or reused.
    """
    bid = batch_id or str(uuid.uuid4())

    existing = conn.execute(
        "SELECT batch_id FROM batches WHERE batch_id = ?", [bid]
    ).fetchone()

    if existing is None:
        conn.execute(
            "INSERT INTO batches (batch_id, note) VALUES (?, ?)",
            [bid, note],
        )
        try:
            conn.commit()
        except Exception:
            pass
        logger.info("Created batch: %s", bid)
    else:
        logger.debug("Reusing existing batch: %s", bid)

    return bid


# ---------------------------------------------------------------------------
# test_runs
# ---------------------------------------------------------------------------

def insert_in_progress(
    conn: "duckdb.DuckDBPyConnection",
    fingerprint: str,
    params: dict[str, Any],
    window_start: datetime,
    window_end: datetime,
    batch_id: str,
) -> None:
    """Insert an in_progress sentinel row before the simulation starts.

    This satisfies NFR-AUD-001 — there is always a row recording that a run
    was attempted, even if it crashes mid-flight.

    Args:
        conn: Open DuckDB connection.
        fingerprint: SHA-256 hex fingerprint.
        params: Run parameters dict.
        window_start: Backtest window start timestamp.
        window_end: Backtest window end timestamp.
        batch_id: Foreign key to batches.batch_id.
    """
    conn.execute(
        """
        INSERT OR IGNORE INTO test_runs
            (fingerprint, params, window_start, window_end, status, batch_id)
        VALUES (?, ?, ?, ?, 'in_progress', ?)
        """,
        [
            fingerprint,
            json.dumps(params),
            window_start,
            window_end,
            batch_id,
        ],
    )
    logger.info("Inserted in_progress sentinel: %s", fingerprint[:16])


def upsert_complete_run(
    conn: "duckdb.DuckDBPyConnection",
    fingerprint: str,
    params: dict[str, Any],
    window_start: datetime,
    window_end: datetime,
    metrics: dict[str, float],
    trades: list[dict[str, Any]],
    batch_id: str,
) -> None:
    """Update the in_progress row to complete with metrics and trades.

    Args:
        conn: Open DuckDB connection.
        fingerprint: SHA-256 hex fingerprint (must match existing row).
        params: Run parameters dict.
        window_start: Backtest window start timestamp.
        window_end: Backtest window end timestamp.
        metrics: Dict with keys: total_return, sharpe, max_drawdown.
        trades: List of trade dicts with keys: ts, side, price, size.
        batch_id: Foreign key to batches.batch_id.
    """
    metrics_struct = {
        "total_return": metrics.get("total_return"),
        "benchmark_return": metrics.get("benchmark_return"),
        "sharpe_ratio": metrics.get("sharpe_ratio"),
        "sortino_ratio": metrics.get("sortino_ratio"),
        "max_drawdown": metrics.get("max_drawdown"),
        "win_rate": metrics.get("win_rate"),
        "profit_factor": metrics.get("profit_factor"),
        "total_trades": metrics.get("total_trades"),
    }

    conn.execute(
        "DELETE FROM test_runs WHERE fingerprint = ?",
        [fingerprint],
    )
    conn.execute(
        """
        INSERT INTO test_runs
            (fingerprint, params, window_start, window_end, metrics, trades, status, batch_id)
        VALUES (?, ?, ?, ?, ?, ?, 'complete', ?)
        """,
        [
            fingerprint,
            json.dumps(params),
            window_start,
            window_end,
            metrics_struct,
            trades,
            batch_id,
        ],
    )
    try:
        conn.commit()
    except Exception:
        pass

    logger.info(
        "Marked complete: %s (return=%.4f, sharpe=%.4f)",
        fingerprint[:16],
        metrics.get("total_return", 0),
        metrics.get("sharpe", 0),
    )


def mark_skipped(
    conn: "duckdb.DuckDBPyConnection",
    fingerprint: str,
    batch_id: str,
) -> None:
    """Record a skipped run — fingerprint matched within the trust window.

    Args:
        conn: Open DuckDB connection.
        fingerprint: The matched fingerprint.
        batch_id: The current batch ID (link the skip to this run's batch).
    """
    conn.execute(
        """
        INSERT OR IGNORE INTO test_runs
            (fingerprint, params, status, batch_id)
        VALUES (?, '{}', 'skipped', ?)
        """,
        [fingerprint, batch_id],
    )
    logger.info("Skipped (dedup): %s", fingerprint[:16])
