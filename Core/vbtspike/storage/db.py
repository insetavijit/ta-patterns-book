"""DuckDB connection management.

Single-writer contract (DL-V6-09): one writer at a time.
Read-only connections against comparative/coverage views are safe only when
no write is in flight.

NOTE: vbtspike never creates the DuckDB file. The file must exist before
running any command. Set ``duckdb_path`` in config/cnf.yaml to point at
your pre-existing database file.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

_SCHEMA_SQL = Path(__file__).parent / "schema.sql"
_VIEWS_SQL = Path(__file__).parent / "views.sql"


def get_connection(db_path: str | Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the user-provided DuckDB file and ensure the schema is initialised.

    The DuckDB file is **not** created automatically — it must already exist.
    Set ``duckdb_path`` in config/cnf.yaml to the path of your database file.

    Args:
        db_path: Path to an existing DuckDB file.
        read_only: Whether to open in read-only mode.

    Returns:
        An open DuckDB connection. The caller is responsible for closing it.

    Raises:
        SystemExit(1): If the file does not exist.
    """
    path = Path(db_path)

    if not path.exists():
        print(
            f"[vbtspike] DB ERROR: DuckDB file not found: {path}\n"
            "  vbtspike does not create the database file automatically.\n"
            "  Point 'duckdb_path' in config/cnf.yaml at your existing .duckdb file.",
            file=sys.stderr,
        )
        sys.exit(1)

    conn = duckdb.connect(str(path), read_only=read_only)
    if not read_only:
        _bootstrap(conn)
    logger.debug("DuckDB connection open: %s (read_only=%s)", path, read_only)
    return conn


def get_results_connection(
    strategy_name: str,
    results_dir: str | Path = "results",
) -> tuple[duckdb.DuckDBPyConnection, Path]:
    """Open or create a dedicated DuckDB file named after the strategy.

    Args:
        strategy_name: Name of the strategy (e.g. 'sma_cross').
        results_dir: Directory where strategy results .duckdb files are stored.

    Returns:
        (conn, results_path): An open DuckDB connection initialized with
        batches, test_runs, and analytical views, plus the file path.
    """
    results_path = Path(results_dir) / f"{strategy_name}.duckdb"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(results_path))
    _bootstrap(conn)
    logger.info("Results DuckDB open: %s", results_path)
    return conn, results_path


def _bootstrap(conn: duckdb.DuckDBPyConnection) -> None:
    """Idempotently ensure tables, types, and views exist in the provided DB."""
    tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
    if "test_runs" in tables:
        try:
            metrics_type = str(
                conn.execute("SELECT column_type FROM (DESCRIBE test_runs) WHERE column_name = 'metrics'").fetchone()[0]
            )
            if "benchmark_return" not in metrics_type:
                logger.info("Migrating test_runs table to test-schema.json format...")
                conn.execute("DROP VIEW IF EXISTS comparative")
                conn.execute("DROP VIEW IF EXISTS coverage")
                conn.execute("DROP VIEW IF EXISTS trades")
                conn.execute("DROP VIEW IF EXISTS trade_book")
                conn.execute("DROP VIEW IF EXISTS backtest_run")
                conn.execute("DROP VIEW IF EXISTS run_params")
                conn.execute("DROP TABLE test_runs")
        except Exception as exc:
            logger.debug("Migration check skipped: %s", exc)

    schema_sql = _SCHEMA_SQL.read_text(encoding="utf-8")
    views_sql = _VIEWS_SQL.read_text(encoding="utf-8")
    
    for stmt in schema_sql.split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            conn.execute(stmt)
        except duckdb.CatalogException as exc:
            # Ignore if type/table already exists
            if "already exists" not in str(exc).lower():
                raise

    conn.execute(views_sql)
    logger.debug("Schema bootstrap complete")
