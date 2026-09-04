#!/usr/bin/env python3
"""
duckdb_explorer.py — A single-file, dependency-light CLI for researching and
inspecting DuckDB database files.

WHY THIS EXISTS
----------------
DuckDB ships an excellent official CLI, but it is a separate binary, its
output is tuned for humans (boxed tables, prompts), and there is no
single-file, pip-installable, agent-friendly wrapper that emits stable JSON
for every operation. This script fills that gap: one file, stdlib +
`duckdb` only, safe-by-default (read-only), and every command returns a
predictable, versioned JSON envelope so a coding agent can parse it without
scraping text.

DESIGN PRINCIPLES (read this before adding commands)
------------------------------------------------------
1. Read-only by default. Destructive SQL requires --write. DuckDB's own
   read_only connection mode is the *authoritative* enforcement; the
   tool-level keyword pre-check only exists to fail fast with a clearer
   message, so it is intentionally narrow rather than exhaustive — see
   `looks_like_write()`.
2. Every response is a JSON envelope: {schema_version, command, success,
   data, meta, error}. Same shape on success or failure.
3. No prompts, no interactive state required to get useful output.
4. Distinct process exit codes so an agent can branch without parsing text:
       0  success
       1  SQL / execution error
       2  file not found or invalid database
       3  argument / validation error
       4  read-only violation (write attempted without --write)
       5  query timed out (--timeout exceeded)
5. Global --limit caps rows returned anywhere, protecting agent context
   windows from accidental huge dumps. --offset pairs with it on the
   commands where paging through a large table is a realistic need.
6. Prefer DuckDB's own built-ins (SUMMARIZE, information_schema,
   duckdb_extensions(), duckdb_indexes(), duckdb_tables(), COPY ... FORMAT
   JSON) over hand-rolled SQL or Python-side reimplementations, since they
   are maintained upstream, stream instead of buffering in Python, and are
   more correct/efficient.
7. `query` is the escape hatch. Dedicated subcommands exist only where they
   save an agent a full SQL round-trip (schema, sample, summarize, search,
   diff) — everything else is reachable through `query`. Because of this,
   niceties like --offset are added to dedicated commands, not retrofitted
   onto `query` by rewriting arbitrary user SQL.
8. The tool describes itself. `describe` emits the full command/flag
   surface as JSON, so an agent can introspect capabilities once and cache
   them instead of scraping --help text meant for humans.
9. Never build SQL by interpolating untrusted *values* (file paths, search
   terms) directly into a query string. Identifiers go through
   quote_ident(); string literal values that must be inlined (COPY targets,
   file paths — DuckDB does not accept those as bound parameters) go
   through quote_literal(). Everything else uses `?` placeholders.

INTENTIONALLY OMITTED (and why)
---------------------------------
- Interactive REPL: agents call this tool non-interactively, per-invocation,
  with explicit flags. A REPL doesn't serve that pattern.
- Persistent config file / session history: agents pass explicit flags on
  every call, so there is no cross-call state worth persisting here. Adding
  it would introduce hidden state that makes agent behavior less
  predictable, not more.
- Row-level `diff-data` and `dependencies` graph: high implementation cost,
  narrow payoff versus just using `query` with the metadata this tool
  already exposes (schema-all + diff-schema cover the common cases).
- Cross-schema JOINs / query rewriting for --schema: the --schema flag
  scopes catalog introspection (which schema information_schema/table
  lookups target); it does not rewrite arbitrary SQL passed to `query`.
  Schema-qualify identifiers yourself in `query` when you need to cross
  schemas in one statement.

CHANGELOG
---------
v2.0.0
- Fixed: file paths (export --out, import file) are no longer interpolated
  unescaped into SQL strings — added quote_literal() and used it
  everywhere a path must be inlined.
- Fixed: WRITE_KEYWORDS no longer blocks PRAGMA/SET/LOAD/INSTALL/CALL in
  read-only mode — these don't mutate the database file (LOAD httpfs is a
  common prerequisite for read-only remote-parquet queries). Added
  MERGE/REPLACE to the list of statements that *do* require --write.
- Added: --schema flag (default 'main') threaded through every catalog
  command, plus a new `list-schemas` command. Previously every command was
  hardcoded to the 'main' schema.
- Added: `export`'s JSON/NDJSON-to-file path now goes through DuckDB's
  native `COPY ... (FORMAT JSON)` instead of buffering the full result set
  in Python — constant memory instead of O(rows).
- Added: `describe` command — emits the tool's full command/flag surface
  as JSON for agent self-discovery.
- Added: --timeout (seconds) aborts a running query via conn.interrupt()
  and returns exit code 5 instead of hanging the process indefinitely.
- Added: --offset on `sample` and `export --table` for paging through
  large tables without hand-writing SQL.
- Added: --estimate-counts uses DuckDB's catalog-level row estimates
  (duckdb_tables().estimated_size) instead of a full SELECT count(*) scan
  per table, for list-tables/stats/profile on large databases.
- Changed: `version`/`describe` no longer require opening a database
  connection — `db` is now effectively optional for those two commands.
- Fixed: --quiet is now implemented (previously a no-op) — suppresses
  best-effort warnings written to stderr (e.g. a table that failed to
  count, an estimate falling back to exact).
- Fixed: SQL preview truncation length was inconsistent (200 vs 500 chars
  in different error paths) — unified to SQL_PREVIEW_LEN.
- Documented: checksum's bit_xor(hash(...)) is order-independent but can
  miss an even number of duplicate-row changes cancelling out in XOR —
  noted explicitly in the command's own docstring and --help text.
- Fixed (final review pass): `export --query --offset` used to silently
  ignore --offset (it only ever applied to --table); now raises a clear
  validation error instead of a silent no-op.
- Added (final review pass): a one-time, best-effort startup warning to
  stderr (suppressible with --quiet) if the installed duckdb library is
  older than MIN_DUCKDB_VERSION, since a few commands depend on catalog
  functions/columns only present in newer releases.

USAGE EXAMPLES
---------------
    # Full context-priming dump for an agent starting cold on a file
    python duckdb_explorer.py mydata.duckdb schema-all

    # One-shot profile of a single table (schema + stats + sample rows)
    python duckdb_explorer.py mydata.duckdb profile orders

    # Arbitrary SQL, JSON out
    python duckdb_explorer.py mydata.duckdb query "SELECT * FROM orders LIMIT 5"

    # Explicit write, since the tool is read-only by default
    python duckdb_explorer.py mydata.duckdb query "DELETE FROM orders WHERE id=1" --write

    # Export a table to parquet
    python duckdb_explorer.py mydata.duckdb export --table orders --format parquet --out orders.parquet

    # Page through a large table 5000 rows at a time
    python duckdb_explorer.py mydata.duckdb sample orders -n 5000 --offset 10000

    # Query a non-default schema
    python duckdb_explorer.py mydata.duckdb list-tables --schema staging

    # Bound a runaway query to 30 seconds
    python duckdb_explorer.py mydata.duckdb query "SELECT * FROM huge_table" --timeout 30

    # Let an agent learn the tool's full surface without parsing --help
    python duckdb_explorer.py mydata.duckdb describe

Run `python duckdb_explorer.py --help` or `python duckdb_explorer.py <command> --help`
for full flag documentation on every subcommand.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from typing import Any, Optional

try:
    import duckdb
except ImportError:  # pragma: no cover - guidance for the agent/user
    sys.stderr.write(
        "duckdb package is not installed. Install it with:\n"
        "  pip install duckdb --break-system-packages\n"
    )
    sys.exit(2)


TOOL_NAME = "duckdb_explorer"
TOOL_VERSION = "2.0.0"
SCHEMA_VERSION = "1.0"  # bump if the JSON envelope shape changes
MIN_DUCKDB_VERSION = (0, 10, 0)  # SUMMARIZE, duckdb_tables().estimated_size, etc. need this or newer

# Exit codes — documented in the module docstring above; keep in sync.
EXIT_OK = 0
EXIT_SQL_ERROR = 1
EXIT_FILE_ERROR = 2
EXIT_VALIDATION_ERROR = 3
EXIT_READONLY_VIOLATION = 4
EXIT_TIMEOUT = 5

DEFAULT_LIMIT = 1000
DEFAULT_SCHEMA = "main"
SQL_PREVIEW_LEN = 500  # chars of SQL echoed back in error details; unified across all error paths

# Statements that mutate data or schema. Used to enforce --write safety
# with a fast, tool-level error before ever opening (or using) a write
# connection. This is NOT the authoritative enforcement — DuckDB's own
# read_only connection flag blocks writes at the file-handle level
# regardless of what this list catches or misses. Kept deliberately narrow:
# PRAGMA/SET/LOAD/INSTALL/CALL are excluded because they configure the
# session or extensions rather than mutate the database file (e.g. `LOAD
# httpfs` is a normal prerequisite for read-only queries against S3/HTTP
# parquet, and blocking it here would break that read-only workflow for no
# safety benefit).
WRITE_KEYWORDS = (
    "insert", "update", "delete", "drop", "create", "alter",
    "truncate", "copy", "attach", "detach", "vacuum", "checkpoint",
    "merge", "replace",
)


# --------------------------------------------------------------------------
# Envelope / output helpers
# --------------------------------------------------------------------------

class ToolError(Exception):
    """Raised for any expected failure; carries the process exit code to use."""

    def __init__(self, message: str, exit_code: int, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.details = details or {}


def make_envelope(command: str, success: bool, data: Any = None,
                   meta: Optional[dict] = None, error: Optional[dict] = None) -> dict:
    """Build the standard, versioned response envelope every command returns.

    Keeping this shape identical across every command (success or failure)
    means an agent can write one parser instead of one per command.
    """
    return {
        "tool": TOOL_NAME,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "success": success,
        "data": data,
        "meta": meta or {},
        "error": error,
    }


def rows_to_dicts(cursor: "duckdb.DuckDBPyConnection") -> list[dict]:
    """Convert the pending result of a cursor into a list of plain dicts."""
    columns = [d[0] for d in cursor.description] if cursor.description else []
    rows = cursor.fetchall()
    return [dict(zip(columns, row)) for row in rows]


def _json_default(obj: Any) -> Any:
    """Fallback JSON serializer for types DuckDB commonly returns.

    Handles Decimal, datetime/date/time, bytes, and anything else with a
    sane string form, so `json.dumps` never blows up on a normal result set.
    """
    try:
        import datetime
        import decimal
        if isinstance(obj, (datetime.date, datetime.datetime, datetime.time)):
            return obj.isoformat()
        if isinstance(obj, decimal.Decimal):
            return float(obj)
    except Exception:
        pass
    if isinstance(obj, (bytes, bytearray)):
        return {"$base64": True, "encoded": obj.hex()}
    return str(obj)


def emit(envelope: dict, output_format: str, arrays: bool = False, nl: bool = False,
          pretty: bool = False) -> None:
    """Print the final envelope to stdout in the requested format.

    output_format:
        json      - single JSON object (default; safest for agents)
        ndjson    - if data is a list, one JSON object per line (no envelope
                    wrapper per line — just the records), otherwise falls
                    back to a single JSON line of the envelope
        table     - human-readable padded columns (for people, not agents)
        markdown  - GitHub-flavored markdown table (for people/docs)
    arrays/nl only apply when output_format == 'json' and data is a list of
    dicts, mirroring sqlite-utils' --arrays/--nl conventions.
    """
    data = envelope.get("data")

    if output_format == "ndjson":
        if isinstance(data, list):
            for row in data:
                sys.stdout.write(json.dumps(row, default=_json_default) + "\n")
        else:
            sys.stdout.write(json.dumps(envelope, default=_json_default) + "\n")
        return

    if output_format in ("table", "markdown") and isinstance(data, list) and data and isinstance(data[0], dict):
        _print_tabular(data, markdown=(output_format == "markdown"))
        if not envelope["success"]:
            sys.stderr.write(json.dumps(envelope.get("error"), default=_json_default) + "\n")
        return

    # default: json
    if arrays and isinstance(data, list) and data and isinstance(data[0], dict):
        keys = list(data[0].keys())
        envelope = dict(envelope)
        envelope["data"] = [[row.get(k) for k in keys] for row in data]
        envelope["meta"] = dict(envelope.get("meta") or {})
        envelope["meta"]["columns"] = keys

    if nl and isinstance(envelope.get("data"), list):
        for row in envelope["data"]:
            sys.stdout.write(json.dumps(row, default=_json_default) + "\n")
        return

    indent = 2 if pretty else None
    sys.stdout.write(json.dumps(envelope, default=_json_default, indent=indent) + "\n")


def _print_tabular(rows: list[dict], markdown: bool = False) -> None:
    """Minimal dependency-free tabular printer for --output table/markdown."""
    if not rows:
        print("(no rows)")
        return
    headers = list(rows[0].keys())
    str_rows = [[("" if r.get(h) is None else str(r.get(h))) for h in headers] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in str_rows)) for i, h in enumerate(headers)]

    def fmt_row(cells: list[str]) -> str:
        return " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells))

    if markdown:
        print("| " + " | ".join(headers) + " |")
        print("|" + "|".join("---" for _ in headers) + "|")
        for r in str_rows:
            print("| " + " | ".join(r) + " |")
    else:
        print(fmt_row(headers))
        print("-+-".join("-" * w for w in widths))
        for r in str_rows:
            print(fmt_row(r))


def _parse_version(version_str: str) -> tuple:
    """Best-effort parse of a 'X.Y.Z[-suffix]' version string into a comparable int tuple."""
    parts = []
    for chunk in version_str.split(".")[:3]:
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def check_duckdb_version(args: Any) -> None:
    """Warn (not fail) if the installed duckdb library is older than MIN_DUCKDB_VERSION.

    Several commands rely on catalog functions/columns that only exist in
    newer DuckDB releases (duckdb_tables().estimated_size, etc.) — this
    gives an agent a clear signal in stderr for *why* those might be
    silently falling back or erroring, rather than a bare DuckDB error.
    """
    try:
        if _parse_version(duckdb.__version__) < MIN_DUCKDB_VERSION:
            warn(
                args,
                f"installed duckdb {duckdb.__version__} is older than the "
                f"{'.'.join(str(p) for p in MIN_DUCKDB_VERSION)} this tool targets; "
                "some commands (e.g. --estimate-counts) may fall back or error.",
            )
    except Exception:
        pass  # never let a version-string parsing quirk break the actual command


def warn(args: Any, message: str) -> None:
    """Write a best-effort warning to stderr, unless --quiet was passed.

    Used for non-fatal situations an agent might still want visibility
    into (a table that failed to count, an estimate falling back to an
    exact scan) without them polluting stdout or breaking the envelope.
    """
    if not getattr(args, "quiet", False):
        sys.stderr.write(f"warning: {message}\n")


# --------------------------------------------------------------------------
# Connection helpers
# --------------------------------------------------------------------------

def connect(db_path: str, read_only: bool) -> "duckdb.DuckDBPyConnection":
    """Open a DuckDB connection, validating the file first.

    Raises ToolError(EXIT_FILE_ERROR) if the path doesn't look like a usable
    DuckDB database (missing, and not an explicit request to create one).
    """
    if db_path != ":memory:":
        path = Path(db_path)
        if read_only and not path.exists():
            raise ToolError(
                f"Database file not found: {db_path}",
                EXIT_FILE_ERROR,
                {"path": db_path},
            )
    try:
        return duckdb.connect(database=db_path, read_only=read_only)
    except duckdb.Error as exc:
        raise ToolError(str(exc), EXIT_FILE_ERROR, {"path": db_path}) from exc


def looks_like_write(sql: str) -> bool:
    """Heuristic check: does this (first) statement start with a mutating keyword?

    This is a fast, cheap pre-check used to fail early with a clear error
    before even opening a write-mode connection. DuckDB's own read_only
    connection flag is the authoritative enforcement; this just gives a
    nicer, tool-level error message and exit code. It is intentionally
    narrow (see WRITE_KEYWORDS) — it does not try to catch every possible
    way of sneaking a mutation past a keyword scan (leading comments,
    multi-statement strings, CTEs wrapping a DML statement). Treat it as a
    courtesy, not a security boundary; the read_only connection is the
    security boundary.
    """
    first_word = sql.strip().split(None, 1)[0].lower().strip("(;") if sql.strip() else ""
    return first_word in WRITE_KEYWORDS


def quote_ident(name: str) -> str:
    """Double-quote a SQL identifier, escaping embedded double quotes."""
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    """Single-quote a SQL string literal, escaping embedded single quotes.

    DuckDB's COPY statement (and a handful of other DDL-adjacent
    statements) take file paths as inline string literals rather than
    bound parameters — `?` placeholders aren't accepted there. Any time a
    path or other string has to be inlined into SQL text, it MUST go
    through this function rather than a bare f-string interpolation, or a
    value containing a single quote can break out of the literal.
    """
    return "'" + value.replace("'", "''") + "'"


class QueryTimeout(Exception):
    """Raised when a query is interrupted by the --timeout watchdog."""


def execute_with_timeout(conn: "duckdb.DuckDBPyConnection", sql: str,
                          params: Optional[list] = None,
                          timeout: Optional[float] = None) -> "duckdb.DuckDBPyConnection":
    """Run conn.execute(sql, params), aborting via conn.interrupt() after `timeout` seconds.

    DuckDB doesn't expose a native per-query timeout, but connections can
    be interrupted from another thread. This starts a timer that calls
    conn.interrupt() if the query is still running when it fires, then
    translates DuckDB's resulting InterruptException into QueryTimeout so
    callers can map it to EXIT_TIMEOUT with a clear message instead of a
    raw DuckDB error or an indefinite hang.
    """
    if not timeout:
        return conn.execute(sql, params) if params is not None else conn.execute(sql)

    timer = threading.Timer(timeout, conn.interrupt)
    timer.daemon = True
    timer.start()
    try:
        return conn.execute(sql, params) if params is not None else conn.execute(sql)
    except duckdb.Error as exc:
        if "interrupt" in str(exc).lower():
            raise QueryTimeout(f"Query exceeded timeout of {timeout}s and was interrupted.") from exc
        raise
    finally:
        timer.cancel()


def run_sql(conn: "duckdb.DuckDBPyConnection", sql: str, limit: Optional[int],
            offset: Optional[int] = None, timeout: Optional[float] = None) -> tuple[list[dict], Optional[int]]:
    """Execute one SQL statement, returning (rows, rows_affected).

    If the statement produced a result set, rows are returned (optionally
    capped at `limit`, skipping `offset` rows first) and rows_affected is
    None. If it was a write with no result set, rows is [] and
    rows_affected carries the affected row count when DuckDB exposes it.
    """
    cursor = execute_with_timeout(conn, sql, timeout=timeout)
    if cursor.description:
        rows = rows_to_dicts_capped(cursor, limit, offset)
        return rows, None
    # No result set (e.g. DDL/DML) — DuckDB's Python API doesn't always
    # expose rowcount consistently across statement types, so report what
    # we can and let 'success: true' carry the rest of the signal.
    rowcount = getattr(cursor, "rowcount", -1)
    return [], (rowcount if rowcount is not None and rowcount >= 0 else None)


def rows_to_dicts_capped(cursor: "duckdb.DuckDBPyConnection", limit: Optional[int],
                          offset: Optional[int] = None) -> list[dict]:
    columns = [d[0] for d in cursor.description] if cursor.description else []
    if offset:
        cursor.fetchmany(offset)  # discard; DuckDB's cursor has no seek/skip primitive
    rows = cursor.fetchmany(limit) if limit else cursor.fetchall()
    return [dict(zip(columns, row)) for row in rows]


def estimated_row_count(conn: "duckdb.DuckDBPyConnection", table: str, schema: str) -> Optional[int]:
    """Fast, catalog-level row estimate via duckdb_tables(), no table scan.

    Falls back to None (caller decides whether to fall back to an exact
    count) if the catalog function or column isn't available on this
    DuckDB version.
    """
    try:
        row = conn.execute(
            "SELECT estimated_size FROM duckdb_tables() WHERE table_name = ? AND schema_name = ?",
            [table, schema],
        ).fetchone()
        return row[0] if row else None
    except duckdb.Error:
        return None


def _require_table_exists(conn, table: str, schema: str) -> None:
    exists = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
        [schema, table],
    ).fetchone()
    if not exists:
        raise ToolError(
            f"Table not found: {schema}.{table}",
            EXIT_VALIDATION_ERROR,
            {"table": table, "schema": schema},
        )


def _schema(args) -> str:
    """The catalog schema a command should target: --schema, or 'main'."""
    return getattr(args, "schema", None) or DEFAULT_SCHEMA


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_list_schemas(conn, args) -> dict:
    """List all schemas present in the database (catalog 'main' database)."""
    rows = rows_to_dicts(conn.execute(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE catalog_name = current_database() ORDER BY schema_name"
    ))
    return make_envelope("list-schemas", True, rows, {"count": len(rows)})


def cmd_list_tables(conn, args) -> dict:
    """List all tables and views with row counts and type, in one schema."""
    schema = _schema(args)
    sql = """
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = ?
        ORDER BY table_name
    """
    rows = rows_to_dicts(conn.execute(sql, [schema]))
    for r in rows:
        count = None
        if args.estimate_counts:
            count = estimated_row_count(conn, r["table_name"], schema)
        if count is None:
            try:
                count = conn.execute(
                    f"SELECT count(*) FROM {quote_ident(schema)}.{quote_ident(r['table_name'])}"
                ).fetchone()[0]
            except duckdb.Error:
                warn(args, f"could not count rows in {schema}.{r['table_name']}")
                count = None
        r["row_count"] = count
        r["row_count_is_estimate"] = bool(args.estimate_counts)
        r["table_type"] = "view" if r["table_type"] == "VIEW" else "table"
    return make_envelope("list-tables", True, rows, {"schema": schema, "count": len(rows)})


def cmd_schema(conn, args) -> dict:
    """Column names, types, nullability, and defaults for one table."""
    schema = _schema(args)
    _require_table_exists(conn, args.table, schema)
    sql = """
        SELECT column_name, data_type, is_nullable, column_default, ordinal_position
        FROM information_schema.columns
        WHERE table_schema = ? AND table_name = ?
        ORDER BY ordinal_position
    """
    rows = rows_to_dicts(conn.execute(sql, [schema, args.table]))
    return make_envelope("schema", True, rows, {"schema": schema, "table": args.table, "column_count": len(rows)})


def cmd_schema_all(conn, args) -> dict:
    """Full schema for every table/view in one schema — for agent context priming."""
    schema = _schema(args)
    tables = rows_to_dicts(conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = ? ORDER BY table_name",
        [schema],
    ))
    result = {}
    for t in tables:
        name = t["table_name"]
        cols = rows_to_dicts(conn.execute(
            """SELECT column_name, data_type, is_nullable, column_default
               FROM information_schema.columns
               WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position""",
            [schema, name],
        ))
        result[name] = cols
    return make_envelope("schema-all", True, result, {"schema": schema, "table_count": len(result)})


def cmd_summarize(conn, args) -> dict:
    """Wraps DuckDB's native SUMMARIZE for per-column statistics in one scan."""
    schema = _schema(args)
    _require_table_exists(conn, args.table, schema)
    rows = rows_to_dicts(conn.execute(f"SUMMARIZE {quote_ident(schema)}.{quote_ident(args.table)}"))
    return make_envelope("summarize", True, rows, {"schema": schema, "table": args.table})


def cmd_sample(conn, args) -> dict:
    """Preview N rows from a table, optionally skipping --offset rows first."""
    schema = _schema(args)
    _require_table_exists(conn, args.table, schema)
    n = min(args.n, args.limit) if args.limit else args.n
    sql = f"SELECT * FROM {quote_ident(schema)}.{quote_ident(args.table)} LIMIT ? OFFSET ?"
    rows = rows_to_dicts(conn.execute(sql, [n, args.offset or 0]))
    return make_envelope(
        "sample", True, rows,
        {"schema": schema, "table": args.table, "requested": n, "offset": args.offset or 0},
    )


def cmd_row_count(conn, args) -> dict:
    """Row count for a table — exact by default, or a fast catalog estimate with --estimate-counts."""
    schema = _schema(args)
    _require_table_exists(conn, args.table, schema)
    if args.estimate_counts:
        count = estimated_row_count(conn, args.table, schema)
        if count is not None:
            return make_envelope(
                "row-count", True,
                {"schema": schema, "table": args.table, "row_count": count, "is_estimate": True},
            )
        warn(args, f"no catalog estimate available for {schema}.{args.table}, falling back to exact count")
    count = conn.execute(f"SELECT count(*) FROM {quote_ident(schema)}.{quote_ident(args.table)}").fetchone()[0]
    return make_envelope(
        "row-count", True,
        {"schema": schema, "table": args.table, "row_count": count, "is_estimate": False},
    )


def cmd_query(conn, args) -> dict:
    """Run arbitrary SQL text (from --sql or a --file) and return results."""
    sql = args.sql
    if args.file:
        sql = Path(args.file).read_text()
    if not sql or not sql.strip():
        raise ToolError("No SQL provided (use positional SQL or --file).", EXIT_VALIDATION_ERROR)

    if not args.write and looks_like_write(sql):
        raise ToolError(
            "Statement looks like a write operation but --write was not passed. "
            "Re-run with --write to allow this, or use --dry-run to preview it.",
            EXIT_READONLY_VIOLATION,
            {"sql": sql.strip()[:SQL_PREVIEW_LEN]},
        )

    if args.dry_run:
        return make_envelope("query", True, None, {"dry_run": True, "sql": sql.strip()})

    try:
        rows, rows_affected = run_sql(conn, sql, args.limit, timeout=args.timeout)
    except QueryTimeout as exc:
        raise ToolError(str(exc), EXIT_TIMEOUT, {"sql": sql.strip()[:SQL_PREVIEW_LEN], "timeout": args.timeout}) from exc
    except duckdb.Error as exc:
        raise ToolError(str(exc), EXIT_SQL_ERROR, {"sql": sql.strip()[:SQL_PREVIEW_LEN]}) from exc

    meta = {"row_count": len(rows), "limited": bool(args.limit and len(rows) == args.limit)}
    if rows_affected is not None:
        meta["rows_affected"] = rows_affected
    return make_envelope("query", True, rows, meta)


def cmd_explain(conn, args) -> dict:
    """Return the query plan for a SQL statement (optionally with EXPLAIN ANALYZE)."""
    prefix = "EXPLAIN ANALYZE " if args.analyze else "EXPLAIN "
    try:
        rows = rows_to_dicts(execute_with_timeout(conn, prefix + args.sql, timeout=args.timeout))
    except QueryTimeout as exc:
        raise ToolError(str(exc), EXIT_TIMEOUT, {"sql": args.sql[:SQL_PREVIEW_LEN]}) from exc
    except duckdb.Error as exc:
        raise ToolError(str(exc), EXIT_SQL_ERROR, {"sql": args.sql[:SQL_PREVIEW_LEN]}) from exc
    return make_envelope("explain", True, rows, {"analyze": args.analyze})


def cmd_validate_sql(conn, args) -> dict:
    """Check that SQL is syntactically/semantically valid without executing it.

    Implemented via EXPLAIN, which parses and binds the statement against
    the catalog without running it — this catches typos, unknown tables/
    columns, and syntax errors.
    """
    try:
        conn.execute("EXPLAIN " + args.sql)
        valid = True
        error_message = None
    except duckdb.Error as exc:
        valid = False
        error_message = str(exc)
    return make_envelope("validate-sql", True, {"valid": valid, "error": error_message}, {"sql": args.sql})


def cmd_search_columns(conn, args) -> dict:
    """Find tables/columns whose name matches a keyword (case-insensitive substring)."""
    schema = _schema(args)
    sql = """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = ? AND column_name ILIKE ?
        ORDER BY table_name, ordinal_position
    """
    rows = rows_to_dicts(conn.execute(sql, [schema, f"%{args.term}%"]))
    return make_envelope("search-columns", True, rows, {"schema": schema, "term": args.term, "match_count": len(rows)})


def cmd_search_values(conn, args) -> dict:
    """Search for a value across all (or one table's) column contents in one schema.

    Builds one UNION ALL query per table across candidate columns so it
    runs as a single scan-per-table rather than one query per column.
    Column names are inlined as string literals (via quote_literal) since
    they're used as VARCHAR labels, not identifiers, in the SELECT list.
    """
    schema = _schema(args)
    tables = [args.table] if args.table else [
        r["table_name"] for r in rows_to_dicts(
            conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = ?", [schema])
        )
    ]
    matches = []
    for table in tables:
        cols = rows_to_dicts(conn.execute(
            """SELECT column_name, data_type FROM information_schema.columns
               WHERE table_schema = ? AND table_name = ?""",
            [schema, table],
        ))
        if not cols:
            continue
        parts = []
        for c in cols:
            col_ident = quote_ident(c["column_name"])
            col_label = quote_literal(c["column_name"])
            parts.append(
                f"SELECT {col_ident}::VARCHAR AS value, {col_label} AS column_name "
                f"FROM {quote_ident(schema)}.{quote_ident(table)} WHERE {col_ident}::VARCHAR ILIKE ?"
            )
        union_sql = " UNION ALL ".join(parts) + " LIMIT ?"
        params = [f"%{args.term}%"] * len(cols) + [args.limit or DEFAULT_LIMIT]
        try:
            rows = rows_to_dicts(conn.execute(union_sql, params))
        except duckdb.Error:
            warn(args, f"skipped {schema}.{table}: not all columns support text search")
            continue
        for r in rows:
            r["table_name"] = table
            matches.append(r)
    return make_envelope("search-values", True, matches, {"schema": schema, "term": args.term, "match_count": len(matches)})


def cmd_diff_schema(conn, args) -> dict:
    """Compare table/column structure between the primary DB and --other (same schema name in both)."""
    schema = _schema(args)
    other_conn = connect(args.other, read_only=True)
    try:
        def snapshot(c):
            tables = rows_to_dicts(c.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = ?", [schema]
            ))
            out = {}
            for t in tables:
                name = t["table_name"]
                cols = rows_to_dicts(c.execute(
                    """SELECT column_name, data_type FROM information_schema.columns
                       WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position""",
                    [schema, name],
                ))
                out[name] = {c2["column_name"]: c2["data_type"] for c2 in cols}
            return out

        left = snapshot(conn)
        right = snapshot(other_conn)
        tables_only_in_left = sorted(set(left) - set(right))
        tables_only_in_right = sorted(set(right) - set(left))
        common = sorted(set(left) & set(right))
        column_diffs = {}
        for t in common:
            l_cols, r_cols = left[t], right[t]
            only_left = sorted(set(l_cols) - set(r_cols))
            only_right = sorted(set(r_cols) - set(l_cols))
            type_mismatches = sorted(
                col for col in (set(l_cols) & set(r_cols)) if l_cols[col] != r_cols[col]
            )
            if only_left or only_right or type_mismatches:
                column_diffs[t] = {
                    "columns_only_in_primary": only_left,
                    "columns_only_in_other": only_right,
                    "type_mismatches": [
                        {"column": c, "primary_type": l_cols[c], "other_type": r_cols[c]}
                        for c in type_mismatches
                    ],
                }
        data = {
            "schema": schema,
            "tables_only_in_primary": tables_only_in_left,
            "tables_only_in_other": tables_only_in_right,
            "common_tables": common,
            "column_diffs": column_diffs,
            "identical": not (tables_only_in_left or tables_only_in_right or column_diffs),
        }
        return make_envelope("diff-schema", True, data, {"primary": args.db, "other": args.other})
    finally:
        other_conn.close()


def cmd_export(conn, args) -> dict:
    """Export a table (optionally with --offset) or a --query result to CSV / JSON / NDJSON / Parquet.

    File paths are inlined into SQL via quote_literal() rather than an
    unescaped f-string, since DuckDB's COPY statement takes the target
    path as a string literal (bound parameters aren't accepted there).
    JSON/NDJSON exports to a file go through DuckDB's native
    `COPY ... (FORMAT JSON)` — streaming, constant memory — rather than
    buffering the full result set in Python; the Python path is only used
    for the no --out / print-to-envelope case, which is already bounded by
    --limit.
    """
    if args.table:
        schema = _schema(args)
        _require_table_exists(conn, args.table, schema)
        source_sql = f"SELECT * FROM {quote_ident(schema)}.{quote_ident(args.table)}"
        if args.offset:
            source_sql += f" OFFSET {int(args.offset)}"
    elif args.query:
        if args.offset:
            raise ToolError(
                "--offset is only supported with --table, not --query. "
                "Add OFFSET directly to your --query SQL instead.",
                EXIT_VALIDATION_ERROR,
            )
        source_sql = args.query
    else:
        raise ToolError("Provide either --table or --query to export.", EXIT_VALIDATION_ERROR)

    out_path = args.out
    fmt = args.format

    try:
        if fmt == "parquet":
            if not out_path:
                raise ToolError("--out is required for parquet export.", EXIT_VALIDATION_ERROR)
            conn.execute(f"COPY ({source_sql}) TO {quote_literal(out_path)} (FORMAT PARQUET)")
        elif fmt == "csv":
            if not out_path:
                raise ToolError("--out is required for csv export.", EXIT_VALIDATION_ERROR)
            conn.execute(f"COPY ({source_sql}) TO {quote_literal(out_path)} (FORMAT CSV, HEADER)")
        elif out_path:
            # json/ndjson to a file: stream via native COPY instead of buffering in Python.
            array_opt = ", ARRAY true" if fmt == "json" else ""
            conn.execute(f"COPY ({source_sql}) TO {quote_literal(out_path)} (FORMAT JSON{array_opt})")
        else:
            # No --out: return rows inline in the envelope (already bounded by --limit
            # upstream commands apply; here we cap defensively at args.limit too).
            rows, _ = run_sql(conn, source_sql, args.limit, timeout=args.timeout)
            return make_envelope("export", True, rows, {"format": fmt, "row_count": len(rows)})
    except QueryTimeout as exc:
        raise ToolError(str(exc), EXIT_TIMEOUT, {"sql": source_sql[:SQL_PREVIEW_LEN]}) from exc
    except duckdb.Error as exc:
        raise ToolError(str(exc), EXIT_SQL_ERROR, {"sql": source_sql[:SQL_PREVIEW_LEN]}) from exc

    return make_envelope("export", True, {"path": out_path, "format": fmt}, None)


def cmd_import(conn, args) -> dict:
    """Load a CSV / Parquet / JSON file into a new (or replaced) table. Requires --write.

    The file path is passed through quote_literal() rather than an
    unescaped f-string interpolation.
    """
    if not args.write:
        raise ToolError(
            "import creates a table, which is a write operation — re-run with --write.",
            EXIT_READONLY_VIOLATION,
        )
    src = Path(args.file)
    if not src.exists():
        raise ToolError(f"Source file not found: {args.file}", EXIT_FILE_ERROR, {"path": args.file})

    ext = src.suffix.lower()
    path_lit = quote_literal(args.file)
    if ext == ".csv":
        opts = []
        if args.delimiter:
            opts.append(f"delim={quote_literal(args.delimiter)}")
        if args.no_header:
            opts.append("header=false")
        opt_str = f", {', '.join(opts)}" if opts else ""
        reader = f"read_csv_auto({path_lit}{opt_str})"
    elif ext == ".parquet":
        reader = f"read_parquet({path_lit})"
    elif ext in (".json", ".ndjson"):
        reader = f"read_json_auto({path_lit})"
    else:
        raise ToolError(f"Unsupported file extension: {ext}", EXIT_VALIDATION_ERROR)

    schema = _schema(args)
    verb = "CREATE OR REPLACE TABLE" if args.replace else "CREATE TABLE"
    qualified_table = f"{quote_ident(schema)}.{quote_ident(args.table)}"
    try:
        conn.execute(f"{verb} {qualified_table} AS SELECT * FROM {reader}")
        count = conn.execute(f"SELECT count(*) FROM {qualified_table}").fetchone()[0]
    except duckdb.Error as exc:
        raise ToolError(str(exc), EXIT_SQL_ERROR, {"file": args.file}) from exc
    return make_envelope("import", True, {"schema": schema, "table": args.table, "row_count": count}, None)


def cmd_stats(conn, args) -> dict:
    """High-level file/database stats: size on disk, table count, total rows (one schema)."""
    schema = _schema(args)
    tables = rows_to_dicts(conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = ?", [schema]
    ))
    total_rows = 0
    any_exact_failed = False
    for t in tables:
        count = None
        if args.estimate_counts:
            count = estimated_row_count(conn, t["table_name"], schema)
        if count is None:
            try:
                count = conn.execute(
                    f"SELECT count(*) FROM {quote_ident(schema)}.{quote_ident(t['table_name'])}"
                ).fetchone()[0]
            except duckdb.Error:
                warn(args, f"could not count rows in {schema}.{t['table_name']}")
                any_exact_failed = True
                count = 0
        total_rows += count
    file_size = None
    if args.db != ":memory:" and Path(args.db).exists():
        file_size = Path(args.db).stat().st_size
    data = {
        "database_file": args.db,
        "schema": schema,
        "file_size_bytes": file_size,
        "table_count": len(tables),
        "total_row_count": total_rows,
        "total_row_count_is_estimate": bool(args.estimate_counts),
        "total_row_count_partial": any_exact_failed,
        "duckdb_version": duckdb.__version__,
    }
    return make_envelope("stats", True, data, None)


def cmd_checksum(conn, args) -> dict:
    """Order-independent content hash of a table, for detecting data changes across runs.

    Computes bit_xor(hash(col1, col2, ...)) over all columns — XOR makes the
    result independent of row order, so re-running gives the same checksum
    regardless of physical row layout.

    KNOWN LIMITATION: because XOR is its own inverse, an even number of
    identical duplicate rows being added or removed can leave the checksum
    unchanged even though the data changed (e.g. inserting the same row
    twice, or removing two copies of a row, XORs out to no change). Treat
    this as a cheap "did anything obviously change" smoke test, not a
    cryptographic or fully collision-resistant diff — for that, compare
    actual row sets via `query`.
    """
    schema = _schema(args)
    _require_table_exists(conn, args.table, schema)
    cols = rows_to_dicts(conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = ? AND table_name = ?",
        [schema, args.table],
    ))
    if not cols:
        raise ToolError(f"Table has no columns: {schema}.{args.table}", EXIT_VALIDATION_ERROR)
    col_list = ", ".join(quote_ident(c["column_name"]) for c in cols)
    sql = (
        f"SELECT bit_xor(hash({col_list})) AS checksum, count(*) AS row_count "
        f"FROM {quote_ident(schema)}.{quote_ident(args.table)}"
    )
    result = conn.execute(sql).fetchone()
    return make_envelope(
        "checksum", True,
        {
            "schema": schema, "table": args.table,
            "checksum": str(result[0]), "row_count": result[1],
            "note": "order-independent XOR checksum; can miss even-count duplicate-row changes, see --help",
        },
        None,
    )


def cmd_indexes(conn, args) -> dict:
    """List indexes and constraints defined on a table."""
    schema = _schema(args)
    _require_table_exists(conn, args.table, schema)
    try:
        idx_rows = rows_to_dicts(conn.execute(
            "SELECT * FROM duckdb_indexes() WHERE table_name = ? AND schema_name = ?", [args.table, schema]
        ))
    except duckdb.Error:
        idx_rows = []
    try:
        constraint_rows = rows_to_dicts(conn.execute(
            "SELECT * FROM duckdb_constraints() WHERE table_name = ? AND schema_name = ?", [args.table, schema]
        ))
    except duckdb.Error:
        constraint_rows = []
    return make_envelope(
        "indexes", True,
        {"indexes": idx_rows, "constraints": constraint_rows},
        {"schema": schema, "table": args.table},
    )


def cmd_list_extensions(conn, args) -> dict:
    """List loaded/available DuckDB extensions."""
    rows = rows_to_dicts(conn.execute("SELECT * FROM duckdb_extensions()"))
    return make_envelope("list-extensions", True, rows, {"count": len(rows)})


def cmd_profile(conn, args) -> dict:
    """One-shot combined schema + summarize + sample for a table.

    This is the single most useful command for an agent seeing a table for
    the first time — it front-loads everything schema/summarize/sample
    would return separately, in one call.
    """
    schema = _schema(args)
    _require_table_exists(conn, args.table, schema)
    qualified = f"{quote_ident(schema)}.{quote_ident(args.table)}"
    schema_rows = rows_to_dicts(conn.execute(
        """SELECT column_name, data_type, is_nullable, column_default
           FROM information_schema.columns
           WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position""",
        [schema, args.table],
    ))
    summary = rows_to_dicts(conn.execute(f"SUMMARIZE {qualified}"))
    sample_n = min(args.n, args.limit) if args.limit else args.n
    sample = rows_to_dicts(conn.execute(f"SELECT * FROM {qualified} LIMIT ?", [sample_n]))
    row_count = None
    is_estimate = False
    if args.estimate_counts:
        row_count = estimated_row_count(conn, args.table, schema)
        is_estimate = row_count is not None
    if row_count is None:
        row_count = conn.execute(f"SELECT count(*) FROM {qualified}").fetchone()[0]
    data = {
        "schema": schema,
        "table": args.table,
        "row_count": row_count,
        "row_count_is_estimate": is_estimate,
        "schema_columns": schema_rows,
        "summary": summary,
        "sample": sample,
    }
    return make_envelope("profile", True, data, None)


def cmd_pandas(conn, args) -> dict:
    """Execute a Pandas expression on a table or query result DataFrame."""
    try:
        import pandas as pd
        import numpy as np
    except ImportError:
        raise ToolError("pandas/numpy packages are required for the pandas subcommand.", EXIT_FILE_ERROR)

    if getattr(args, "query", None):
        sql = args.query
    elif getattr(args, "table", None):
        schema = quote_ident(getattr(args, "schema", None) or "main")
        tbl = quote_ident(args.table)
        sql = f"SELECT * FROM {schema}.{tbl}"
    else:
        raise ToolError("Either <table> positional argument or --query must be provided.", EXIT_VALIDATION_ERROR)

    try:
        df = conn.execute(sql).fetchdf()
    except duckdb.Error as exc:
        raise ToolError(str(exc), EXIT_SQL_ERROR, {"sql": sql}) from exc

    expr = getattr(args, "expr", None) or getattr(args, "pandas", None) or getattr(args, "df_expr", None)
    if not expr or not expr.strip():
        expr = "df.head()"

    try:
        if "df.info" in expr:
            import io
            buf = io.StringIO()
            df.info(buf=buf)
            res = buf.getvalue()
        else:
            res = eval(expr, {"df": df, "pd": pd, "np": np, "pandas": pd, "numpy": np})
    except Exception as exc:
        raise ToolError(f"Error evaluating Pandas expression '{expr}': {exc}", EXIT_VALIDATION_ERROR) from exc

    if isinstance(res, pd.DataFrame):
        if args.limit and len(res) > args.limit:
            res = res.head(args.limit)
        records = res.to_dict(orient="records")
        records = json.loads(json.dumps(records, default=str))
        result_data = {
            "expression": expr,
            "result_type": "DataFrame",
            "shape": list(res.shape),
            "columns": list(res.columns),
            "data": records,
        }
    elif isinstance(res, pd.Series):
        if args.limit and len(res) > args.limit:
            res = res.head(args.limit)
        res_dict = res.to_dict()
        res_dict = json.loads(json.dumps(res_dict, default=str))
        result_data = {
            "expression": expr,
            "result_type": "Series",
            "name": str(res.name) if res.name else "Series",
            "length": len(res),
            "data": res_dict,
        }
    else:
        result_data = {
            "expression": expr,
            "result_type": type(res).__name__,
            "value": json.loads(json.dumps(res, default=str)),
        }

    return make_envelope("pandas", True, result_data, None)


def cmd_health_check(conn, args) -> dict:
    """Verify the file opens as a valid, queryable DuckDB database."""
    try:
        conn.execute("SELECT 1").fetchone()
        ok = True
        message = "Database opened and responded to a test query successfully."
    except duckdb.Error as exc:
        ok = False
        message = str(exc)
    return make_envelope("health-check", ok, {"healthy": ok, "message": message}, None)


def cmd_version(conn, args) -> dict:
    """Report tool and DuckDB library versions. Does not require --db to point at a real file."""
    duckdb_version = duckdb.__version__
    data = {
        "tool_version": TOOL_VERSION,
        "schema_version": SCHEMA_VERSION,
        "duckdb_version": duckdb_version,
        "min_supported_duckdb_version": ".".join(str(p) for p in MIN_DUCKDB_VERSION),
    }
    return make_envelope("version", True, data, None)


def cmd_describe(conn, args) -> dict:
    """Emit the tool's full command/flag surface as JSON, for agent self-discovery.

    Lets an agent introspect capabilities once (and cache the result)
    instead of parsing --help text that argparse formats for humans. Does
    not require --db to point at a real file.
    """
    parser = build_parser()
    global_flags = _describe_actions(a for a in parser._actions if not isinstance(a, argparse._SubParsersAction))

    sub_action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    commands = {}
    for name, subp in sub_action.choices.items():
        commands[name] = {
            "help": sub_action.choices[name].description or "",
            "args": _describe_actions(subp._actions),
        }

    data = {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "schema_version": SCHEMA_VERSION,
        "exit_codes": {
            "0": "success", "1": "sql_or_execution_error", "2": "file_not_found_or_invalid_database",
            "3": "argument_or_validation_error", "4": "readonly_violation", "5": "query_timeout",
        },
        "global_flags": global_flags,
        "commands": commands,
    }
    return make_envelope("describe", True, data, {"command_count": len(commands)})


def _describe_actions(actions) -> list[dict]:
    out = []
    for act in actions:
        if act.dest in ("help",):
            continue
        out.append({
            "name": act.dest,
            "flags": act.option_strings or [act.dest],
            "required": bool(getattr(act, "required", False)),
            "help": act.help,
            "choices": list(act.choices) if act.choices else None,
            "default": act.default if act.default is not argparse.SUPPRESS else None,
        })
    return out


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------

def _add_schema_flag(p: argparse.ArgumentParser) -> None:
    p.add_argument("--schema", default=None,
                    help=f"Catalog schema to target (default: '{DEFAULT_SCHEMA}').")


def _add_estimate_flag(p: argparse.ArgumentParser) -> None:
    p.add_argument("--estimate-counts", action="store_true",
                    help="Use DuckDB's fast catalog-level row estimate (duckdb_tables().estimated_size) "
                         "instead of a full SELECT count(*) scan. Falls back to an exact count per-table "
                         "if no estimate is available.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="duckdb_explorer.py",
        description=(
            "Single-file, agent-friendly CLI for inspecting and researching DuckDB "
            "database files. Read-only by default; every command returns a versioned "
            "JSON envelope. See the module docstring for design details. "
            "Run with a bare --version anywhere in the arguments to print the tool "
            "version without needing a database path."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("db",
                         help="Path to the .duckdb file (or ':memory:'). Still a required "
                              "positional for parser consistency, but its value is never opened "
                              "or validated for the 'version'/'describe' commands — pass ':memory:' "
                              "as a placeholder for those if convenient. For a bare version check "
                              "with no other arguments at all, use --version anywhere on the "
                              "command line instead (bypasses argument parsing entirely).")
    parser.add_argument(
        "--write", action="store_true",
        help="Allow write operations (INSERT/UPDATE/DELETE/CREATE/DROP/etc). Off by default for safety.",
    )
    parser.add_argument(
        "--output", choices=["json", "ndjson", "table", "markdown"], default="json",
        help="Output format. 'json' is recommended for agent consumption.",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                         help="Cap on rows returned by any command. 0 disables the cap.")
    parser.add_argument("--timeout", type=float, default=None,
                         help="Abort a running query after this many seconds (exit code 5). "
                              "Applies to query/explain/export. No timeout by default.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output (indent=2).")
    parser.add_argument("--arrays", action="store_true",
                         help="With --output json, return row data as arrays instead of objects (sqlite-utils style).")
    parser.add_argument("--nl", action="store_true",
                         help="With --output json, emit newline-delimited JSON rows instead of one JSON object.")
    parser.add_argument("--quiet", action="store_true",
                         help="Suppress best-effort warnings written to stderr (e.g. a table that failed "
                              "to count, an estimate falling back to an exact scan).")
    parser.add_argument("--no-color", action="store_true", help="Reserved for future colored output; currently a no-op.")

    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser("list-schemas", help="List all schemas in the database.")
    p.set_defaults(func=cmd_list_schemas)

    p = sub.add_parser("list-tables", help="List all tables/views with row counts.")
    _add_schema_flag(p)
    _add_estimate_flag(p)
    p.set_defaults(func=cmd_list_tables)

    p = sub.add_parser("schema", help="Show column schema for one table.")
    p.add_argument("table")
    _add_schema_flag(p)
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("schema-all", help="Show schema for every table in one call.")
    _add_schema_flag(p)
    p.set_defaults(func=cmd_schema_all)

    p = sub.add_parser("summarize", help="Per-column statistics via DuckDB's native SUMMARIZE.")
    p.add_argument("table")
    _add_schema_flag(p)
    p.set_defaults(func=cmd_summarize)

    p = sub.add_parser("sample", help="Preview N rows from a table.")
    p.add_argument("table")
    p.add_argument("-n", type=int, default=10, help="Number of rows to preview.")
    p.add_argument("--offset", type=int, default=0, help="Skip this many rows before previewing (for paging).")
    _add_schema_flag(p)
    p.set_defaults(func=cmd_sample)

    p = sub.add_parser("row-count", help="Row count for a table.")
    p.add_argument("table")
    _add_schema_flag(p)
    _add_estimate_flag(p)
    p.set_defaults(func=cmd_row_count)

    p = sub.add_parser("query", help="Run arbitrary SQL.")
    p.add_argument("sql", nargs="?", help="SQL text. Omit if using --file.")
    p.add_argument("--file", help="Read SQL from this file instead of the positional argument.")
    p.add_argument("--dry-run", action="store_true", help="Print what would run without executing it.")
    p.set_defaults(func=cmd_query)

    p = sub.add_parser("explain", help="Show the query plan for a SQL statement.")
    p.add_argument("sql")
    p.add_argument("--analyze", action="store_true", help="Use EXPLAIN ANALYZE to include real execution stats.")
    p.set_defaults(func=cmd_explain)

    p = sub.add_parser("validate-sql", help="Check SQL validity without executing it.")
    p.add_argument("sql")
    p.set_defaults(func=cmd_validate_sql)

    p = sub.add_parser("search-columns", help="Find tables/columns whose name matches a keyword.")
    p.add_argument("term")
    _add_schema_flag(p)
    p.set_defaults(func=cmd_search_columns)

    p = sub.add_parser("search-values", help="Search for a value across column contents.")
    p.add_argument("term")
    p.add_argument("--table", help="Restrict search to one table (default: all tables in the schema).")
    _add_schema_flag(p)
    p.set_defaults(func=cmd_search_values)

    p = sub.add_parser("diff-schema", help="Compare table/column structure against another DuckDB file.")
    p.add_argument("--other", required=True, help="Path to the DuckDB file to compare against.")
    _add_schema_flag(p)
    p.set_defaults(func=cmd_diff_schema)

    p = sub.add_parser("export", help="Export a table or query result to CSV/JSON/NDJSON/Parquet.")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--table", help="Table to export in full (or from --offset onward).")
    group.add_argument("--query", help="Arbitrary SELECT query to export.")
    p.add_argument("--format", choices=["csv", "json", "ndjson", "parquet"], default="json")
    p.add_argument("--out", help="Output file path. If omitted (json/ndjson only), prints to stdout via the envelope.")
    p.add_argument("--offset", type=int, default=0,
                   help="Skip this many rows before exporting (only with --table, for paging).")
    _add_schema_flag(p)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("import", help="Load a CSV/Parquet/JSON file into a new table. Requires --write.")
    p.add_argument("file", help="Path to the source CSV/Parquet/JSON file.")
    p.add_argument("--table", required=True, help="Name of the table to create.")
    p.add_argument("--replace", action="store_true", help="Replace the table if it already exists.")
    p.add_argument("--delimiter", help="CSV field delimiter override (default: auto-detected).")
    p.add_argument("--no-header", action="store_true", help="CSV file has no header row (default: auto-detected).")
    _add_schema_flag(p)
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("stats", help="High-level database stats (size, table count, total rows).")
    _add_schema_flag(p)
    _add_estimate_flag(p)
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("checksum", help="Order-independent content hash of a table.")
    p.add_argument("table")
    _add_schema_flag(p)
    p.set_defaults(func=cmd_checksum)

    p = sub.add_parser("indexes", help="List indexes and constraints on a table.")
    p.add_argument("table")
    _add_schema_flag(p)
    p.set_defaults(func=cmd_indexes)

    p = sub.add_parser("list-extensions", help="List loaded/available DuckDB extensions.")
    p.set_defaults(func=cmd_list_extensions)

    p = sub.add_parser("profile", help="Combined schema + summarize + sample for one table.")
    p.add_argument("table")
    p.add_argument("-n", type=int, default=5, help="Number of sample rows to include.")
    _add_schema_flag(p)
    _add_estimate_flag(p)
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("pandas", help="Execute Pandas operations/expressions directly on a table or query DataFrame.")
    p.add_argument("table", nargs="?", help="Table to load into DataFrame (e.g. ohlcv_5m).")
    p.add_argument("expr", nargs="?", help="Pandas expression to evaluate on 'df' (e.g. \"df.groupby('status')['pnl'].sum()\")")
    p.add_argument("--expr", help="Optional --expr flag alias for the Pandas expression.")
    p.add_argument("--query", help="Custom SQL query to produce the input DataFrame instead of a table.")
    _add_schema_flag(p)
    p.set_defaults(func=cmd_pandas)

    p = sub.add_parser("health-check", help="Verify the file is a valid, queryable DuckDB database.")
    p.set_defaults(func=cmd_health_check)

    p = sub.add_parser("version", help="Print tool and DuckDB library versions. Does not require a database path.")
    p.set_defaults(func=cmd_version)

    p = sub.add_parser("describe", help="Emit the tool's full command/flag surface as JSON, for agent self-discovery. "
                                         "Does not require a database path.")
    p.set_defaults(func=cmd_describe)

    return parser


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

NO_DB_REQUIRED_COMMANDS = ("version", "describe")


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    # Fast path: `--version`/`-V` anywhere bypasses the normal required
    # positionals entirely, matching standard CLI convention (git, docker,
    # etc.) where --version needs no other arguments.
    if "--version" in argv or "-V" in argv:
        envelope = cmd_version(None, None)
        emit(envelope, "json", pretty=False)
        return EXIT_OK

    parser = build_parser()
    args = parser.parse_args(argv)
    limit = args.limit if args.limit and args.limit > 0 else None
    args.limit = limit  # normalize 0 -> None ("no cap") for downstream commands

    command_name = args.command
    check_duckdb_version(args)
    conn = None
    try:
        if command_name not in NO_DB_REQUIRED_COMMANDS:
            # 'health-check' still needs a connection to be useful; every other
            # data-bearing command needs one, so open it uniformly here.
            conn = connect(args.db, read_only=not args.write)
        envelope = args.func(conn, args)
    except ToolError as exc:
        envelope = make_envelope(
            command_name, False, None, None,
            {"message": exc.message, "exit_code": exc.exit_code, "details": exc.details},
        )
        emit(envelope, args.output, args.arrays, args.nl, args.pretty)
        return exc.exit_code
    except duckdb.Error as exc:
        envelope = make_envelope(
            command_name, False, None, None,
            {"message": str(exc), "exit_code": EXIT_SQL_ERROR, "details": {}},
        )
        emit(envelope, args.output, args.arrays, args.nl, args.pretty)
        return EXIT_SQL_ERROR
    finally:
        if conn is not None:
            conn.close()

    emit(envelope, args.output, args.arrays, args.nl, args.pretty)
    return EXIT_OK if envelope.get("success", True) else EXIT_SQL_ERROR


if __name__ == "__main__":
    sys.exit(main())
