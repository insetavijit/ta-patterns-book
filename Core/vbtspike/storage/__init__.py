"""Storage package — owns the single DuckDB file.

Only the storage package is permitted to perform durable writes.
All other modules read results only through the comparative/coverage views.
"""

from .db import get_connection, get_results_connection
from .ingest import ingest_ohlcv
from .writer import (
    create_or_reuse_batch,
    insert_in_progress,
    upsert_complete_run,
    mark_skipped,
)
from .backup import run_backup

__all__ = [
    "get_connection",
    "get_results_connection",
    "ingest_ohlcv",
    "create_or_reuse_batch",
    "insert_in_progress",
    "upsert_complete_run",
    "mark_skipped",
    "run_backup",
]
