"""OHLCV ingestion into the DuckDB ohlcv table.

Inserts are idempotent on the (symbol, timeframe, ts) primary key — duplicate
candlesticks are silently ignored via INSERT OR IGNORE.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger(__name__)


def ingest_ohlcv(
    conn: "duckdb.DuckDBPyConnection",
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    batch_id: str,
) -> int:
    """Insert OHLCV rows for a given symbol/timeframe into the ohlcv table.

    Args:
        conn: Open DuckDB connection.
        df: DataFrame with columns [open, high, low, close, volume],
            indexed by timestamp (DatetimeIndex).
        symbol: Ticker symbol, e.g. 'BTCUSDT'.
        timeframe: Timeframe string, e.g. '1h', '4h', '1d'.
        batch_id: Foreign key to the batches table.

    Returns:
        Number of rows inserted (duplicates are silently skipped).
    """
    required_cols = {"open", "high", "low", "close", "volume"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"OHLCV DataFrame missing columns: {sorted(missing)}")

    records = df.reset_index().rename(columns={df.index.name or "index": "ts"})
    records["symbol"] = symbol
    records["timeframe"] = timeframe
    records["batch_id"] = batch_id

    rows = records[["symbol", "timeframe", "ts", "open", "high", "low", "close", "volume", "batch_id"]]

    before = conn.execute("SELECT COUNT(*) FROM ohlcv").fetchone()[0]
    # Register as a temporary relation and insert
    conn.register("_ingest_tmp", rows)
    conn.execute("""
        INSERT OR IGNORE INTO ohlcv
            (symbol, timeframe, ts, open, high, low, close, volume, batch_id)
        SELECT symbol, timeframe, ts, open, high, low, close, volume, batch_id
        FROM _ingest_tmp
    """)
    conn.unregister("_ingest_tmp")
    after = conn.execute("SELECT COUNT(*) FROM ohlcv").fetchone()[0]

    inserted = after - before
    logger.info(
        "Ingested %d rows for %s/%s (batch=%s)",
        inserted, symbol, timeframe, batch_id,
    )
    return inserted
