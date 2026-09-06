#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "duckdb>=1.0.0",
#   "pyyaml>=6.0",
#   "numpy>=1.24",
# ]
# ///
"""
ohlcv-inspector: a read-only CLI that inspects an OHLCV candle table in
DuckDB for data-quality problems (Tier: quality) and statistical
abnormalities (Tier: anomaly).

v2 changes vs v1 (see review notes):
  - identifiers (table/column names) are quoted, never f-string-spliced raw
  - scalar filter/threshold values are bound as real DuckDB parameters
  - the filtered base data is materialized ONCE per run into a temp table,
    instead of being re-scanned from a CTE by every check
  - detail-row truncation is signaled explicitly in the report, not silent
  - non-finite floats (NaN/Infinity) are sanitized before JSON serialization
  - --column-map rejects unknown logical keys instead of silently ignoring them
  - `config validate` checks threshold value ranges, not just types
  - --incremental/--full are honestly reported as not-yet-implemented rather
    than silently accepted as no-ops
  - --attach lets you attach extra DuckDB/SQLite/etc. files before running
  - dead imports removed; `version` reports all runtime dependency versions

See ohlcv-inspector-cli-tool-brief.md for the full command/flag reference,
exit-code contract, and JSON output schema this script implements.
"""

from __future__ import annotations

import argparse
import copy
import csv
import io
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

try:
    import numpy as _np
except ImportError:  # pragma: no cover
    _np = None

TOOL_VERSION = "0.2.0"
CHECK_REGISTRY_VERSION = "2026-09-06"

# --------------------------------------------------------------------------
# Exit codes (authoritative contract -- see brief section 4)
# --------------------------------------------------------------------------
EXIT_CLEAN = 0
EXIT_WARNINGS_OR_FLAGS = 1
EXIT_HARD_ERRORS = 2
EXIT_USAGE_OR_CONFIG_ERROR = 3
EXIT_RUNTIME_ERROR = 4

REQUIRED_COLUMN_KEYS = ("symbol", "timestamp", "open", "high", "low", "close", "volume")

DEFAULT_COLUMN_MAP = {k: k for k in REQUIRED_COLUMN_KEYS}

DEFAULT_THRESHOLDS = {
    "price_tolerance": 1e-6,
    "allow_zero_price": False,
    "expected_interval_seconds": 60,
    "gap_multiplier": 1.5,
    "staleness_multiplier": 3.0,
    "anomaly_window": 20,
    "anomaly_min_periods": 10,
    "return_zscore_threshold": 6.0,
    "volume_zscore_threshold": 6.0,
    "reversion_fraction": 0.5,
    "frozen_min_repeat": 4,
    "volume_price_divergence_zscore": 4.0,
    "volume_price_divergence_range_pct": 0.0005,
}

# (key, min_exclusive, max_inclusive_or_None) -- used by `config validate`
THRESHOLD_RANGES = {
    "price_tolerance": (0.0, None),
    "expected_interval_seconds": (0.0, None),
    "gap_multiplier": (0.0, None),
    "staleness_multiplier": (0.0, None),
    "anomaly_window": (1.0, None),
    "anomaly_min_periods": (1.0, None),
    "return_zscore_threshold": (0.0, None),
    "volume_zscore_threshold": (0.0, None),
    "reversion_fraction": (0.0, 1.0),
    "frozen_min_repeat": (1.0, None),
    "volume_price_divergence_zscore": (0.0, None),
    "volume_price_divergence_range_pct": (0.0, None),
}

DEFAULT_CONFIG = {
    "column_map": DEFAULT_COLUMN_MAP,
    "thresholds": DEFAULT_THRESHOLDS,
    "enabled_checks": None,  # None => all checks enabled
}


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class ToolError(Exception):
    """Structured error -> maps directly to the JSON error shape in the brief."""

    def __init__(self, exit_code: int, error_type: str, input_value: str, suggestion: str):
        super().__init__(f"{error_type}: {input_value}")
        self.exit_code = exit_code
        self.error_type = error_type
        self.input_value = input_value
        self.suggestion = suggestion

    def to_dict(self) -> dict:
        return {
            "error_type": self.error_type,
            "input": self.input_value,
            "suggestion": self.suggestion,
            "exit_code": self.exit_code,
        }


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(config_path: str | None, column_map_override: str | None) -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if config_path:
        if yaml is None:
            raise ToolError(
                EXIT_USAGE_OR_CONFIG_ERROR, "missing_dependency", "pyyaml",
                "install pyyaml, or omit --config to use built-in defaults",
            )
        p = Path(config_path)
        if not p.exists():
            raise ToolError(
                EXIT_USAGE_OR_CONFIG_ERROR, "config_not_found", config_path, "check the --config path",
            )
        try:
            user_cfg = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError as e:
            raise ToolError(EXIT_USAGE_OR_CONFIG_ERROR, "config_parse_error", str(e), "fix the YAML syntax")
        cfg = deep_merge(cfg, user_cfg)
        cfg["_config_source"] = str(p)
    else:
        cfg["_config_source"] = "built-in-defaults"

    if column_map_override:
        overrides = {}
        for pair in column_map_override.split(","):
            if "=" not in pair:
                raise ToolError(
                    EXIT_USAGE_OR_CONFIG_ERROR, "invalid_column_map", pair,
                    "use logical=actual, e.g. close=close_price",
                )
            k, v = pair.split("=", 1)
            overrides[k.strip()] = v.strip()
        cfg["column_map"] = deep_merge(cfg["column_map"], overrides)

    validate_column_map_keys(cfg["column_map"])
    return cfg


def validate_column_map_keys(column_map: dict) -> None:
    unknown = [k for k in column_map if k not in REQUIRED_COLUMN_KEYS]
    if unknown:
        raise ToolError(
            EXIT_USAGE_OR_CONFIG_ERROR, "unknown_column_map_key", ", ".join(unknown),
            f"valid keys are: {', '.join(REQUIRED_COLUMN_KEYS)}",
        )
    missing = [k for k in REQUIRED_COLUMN_KEYS if k not in column_map]
    if missing:
        raise ToolError(
            EXIT_USAGE_OR_CONFIG_ERROR, "incomplete_column_map", ", ".join(missing),
            f"column_map must define all of: {', '.join(REQUIRED_COLUMN_KEYS)}",
        )


def validate_thresholds(thresholds: dict) -> list[str]:
    problems = []
    for key, default_val in DEFAULT_THRESHOLDS.items():
        if key not in thresholds:
            continue
        val = thresholds[key]
        if key == "allow_zero_price":
            if not isinstance(val, bool):
                problems.append(f"threshold 'allow_zero_price' expected bool, got {type(val).__name__}")
            continue
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            problems.append(f"threshold '{key}' expected a number, got {type(val).__name__}")
            continue
        lo, hi = THRESHOLD_RANGES.get(key, (None, None))
        if lo is not None and not (val > lo):
            problems.append(f"threshold '{key}' must be > {lo}, got {val}")
        if hi is not None and not (val <= hi):
            problems.append(f"threshold '{key}' must be <= {hi}, got {val}")
    return problems


# --------------------------------------------------------------------------
# Check registry
# --------------------------------------------------------------------------
@dataclass
class CheckDef:
    name: str
    tier: str  # "quality" | "anomaly"
    default_severity: str  # "error" | "warning" | "flagged"
    description: str
    example: str


CHECK_REGISTRY: list[CheckDef] = [
    CheckDef("null_values", "quality", "error",
             "Flags rows with a NULL in symbol, timestamp, open, high, low, close, or volume.",
             "A row with close=NULL."),
    CheckDef("negative_or_zero_price", "quality", "error",
             "Flags rows where open/high/low/close <= 0 (unless allow_zero_price is set).",
             "open = -1.5"),
    CheckDef("negative_volume", "quality", "error",
             "Flags rows where volume < 0.",
             "volume = -100"),
    CheckDef("zero_volume", "quality", "warning",
             "Flags rows with volume == 0 (may be legitimate for illiquid periods).",
             "volume = 0"),
    CheckDef("high_ge_low", "quality", "error",
             "Flags rows where high < low (beyond price_tolerance).",
             "high=10.0, low=10.5"),
    CheckDef("high_ge_open_close", "quality", "error",
             "Flags rows where high < max(open, close).",
             "high=10.0, close=10.3"),
    CheckDef("low_le_open_close", "quality", "error",
             "Flags rows where low > min(open, close).",
             "low=10.5, open=10.2"),
    CheckDef("duplicate_timestamp", "quality", "error",
             "Flags (symbol, timestamp) pairs that appear more than once.",
             "Two rows for AAPL at 2026-01-02 09:31:00."),
    CheckDef("non_monotonic_timestamp", "quality", "error",
             "Flags rows whose timestamp is not strictly greater than the previous row for that symbol.",
             "Row at 09:32 followed by a row at 09:31 for the same symbol."),
    CheckDef("interval_gap", "quality", "warning",
             "Flags gaps between consecutive bars larger than expected_interval_seconds * gap_multiplier.",
             "1-minute bars with a 10-minute jump between two rows."),
    CheckDef("staleness", "quality", "warning",
             "Flags a symbol whose most recent bar is older than expected_interval_seconds * staleness_multiplier relative to now. Wall-clock dependent -- not reproducible across runs.",
             "Latest bar is 3 hours old on a table expected to update every minute."),
    CheckDef("frozen_bar", "anomaly", "flagged",
             "Flags runs of consecutive bars with identical OHLC, suggesting a stale/frozen feed.",
             "4+ consecutive bars with identical open/high/low/close."),
    CheckDef("return_outlier", "anomaly", "flagged",
             "Robust (median/MAD) z-score on bar-over-bar close return, computed on a trailing rolling window.",
             "A single bar with an 18% return vs. a typical 0.3% for that symbol."),
    CheckDef("price_spike_reversion", "anomaly", "flagged",
             "A return_outlier bar where the next bar's return reverses a large fraction of the move -- a classic bad-tick signature.",
             "Bar spikes +15%, next bar returns -14%."),
    CheckDef("volume_zscore_spike", "anomaly", "flagged",
             "Robust (median/MAD) z-score on volume, computed on a trailing rolling window.",
             "Volume 12x the rolling median with no corresponding price move."),
    CheckDef("volume_price_divergence", "anomaly", "flagged",
             "Flags bars with an extreme volume z-score but a near-zero price range, an unusual combination.",
             "Volume z-score 9.0 but (high-low)/close under 0.05%."),
]

CHECK_BY_NAME = {c.name: c for c in CHECK_REGISTRY}
QUALITY_CHECK_NAMES = [c.name for c in CHECK_REGISTRY if c.tier == "quality"]
ANOMALY_CHECK_NAMES = [c.name for c in CHECK_REGISTRY if c.tier == "anomaly"]


# --------------------------------------------------------------------------
# Identifier quoting (never trust raw f-string identifiers -- see review)
# --------------------------------------------------------------------------
def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def quote_qualified(name: str) -> str:
    """Quote a possibly schema-qualified identifier, e.g. main.ohlcv_1m."""
    return ".".join(quote_ident(part) for part in name.split("."))


# --------------------------------------------------------------------------
# Base table materialization (once per run, not once per check)
# --------------------------------------------------------------------------
def materialize_base_table(con, table_or_query: str, is_query: bool, cmap: dict,
                            symbols: list[str] | None, start: str | None, end: str | None) -> str:
    source = f"({table_or_query})" if is_query else quote_qualified(table_or_query)
    select_cols = ", ".join(
        f"{quote_ident(cmap[logical])} AS {logical if logical != 'timestamp' else 'ts'}"
        for logical in REQUIRED_COLUMN_KEYS
    )
    where_clauses = []
    params: dict = {}
    if symbols:
        where_clauses.append(f"{quote_ident(cmap['symbol'])} IN (SELECT UNNEST($symbols))")
        params["symbols"] = symbols
    if start:
        where_clauses.append(f"{quote_ident(cmap['timestamp'])} >= $start_ts")
        params["start_ts"] = start
    if end:
        where_clauses.append(f"{quote_ident(cmap['timestamp'])} <= $end_ts")
        params["end_ts"] = end
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    table_name = "base_table"
    sql = f'CREATE OR REPLACE TEMP TABLE {table_name} AS SELECT {select_cols} FROM {source} {where_sql}'
    con.execute(sql, params)
    return table_name


def dry_run_sql(table_or_query: str, is_query: bool, cmap: dict,
                 symbols: list[str] | None, start: str | None, end: str | None) -> str:
    """Same shape as materialize_base_table but returns text instead of executing (params inlined for readability only)."""
    source = f"({table_or_query})" if is_query else quote_qualified(table_or_query)
    select_cols = ", ".join(
        f"{quote_ident(cmap[logical])} AS {logical if logical != 'timestamp' else 'ts'}"
        for logical in REQUIRED_COLUMN_KEYS
    )
    where_clauses = []
    if symbols:
        where_clauses.append(f"{quote_ident(cmap['symbol'])} IN ({', '.join(repr(s) for s in symbols)})")
    if start:
        where_clauses.append(f"{quote_ident(cmap['timestamp'])} >= '{start}'")
    if end:
        where_clauses.append(f"{quote_ident(cmap['timestamp'])} <= '{end}'")
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    return f"CREATE OR REPLACE TEMP TABLE base_table AS SELECT {select_cols} FROM {source} {where_sql}"


# --------------------------------------------------------------------------
# Quality tier checks (SQL against the materialized base_table; thresholds
# passed as bound parameters, never spliced into the SQL text)
# --------------------------------------------------------------------------
def quality_check_sql(name: str, base_table: str, thresholds: dict) -> tuple[str, dict]:
    p: dict = {}
    if name == "null_values":
        sql = f"""
        SELECT symbol, ts, open, high, low, close, volume, 'null in required column' AS message
        FROM {base_table}
        WHERE symbol IS NULL OR ts IS NULL OR open IS NULL OR high IS NULL
           OR low IS NULL OR close IS NULL OR volume IS NULL
        """
        return sql, p

    if name == "negative_or_zero_price":
        op = "<" if thresholds["allow_zero_price"] else "<="
        sql = f"""
        SELECT symbol, ts, open, high, low, close, volume, 'non-positive price' AS message
        FROM {base_table}
        WHERE open {op} 0 OR high {op} 0 OR low {op} 0 OR close {op} 0
        """
        return sql, p

    if name == "negative_volume":
        return (f"""
        SELECT symbol, ts, open, high, low, close, volume, 'negative volume' AS message
        FROM {base_table} WHERE volume < 0
        """, p)

    if name == "zero_volume":
        return (f"""
        SELECT symbol, ts, open, high, low, close, volume, 'zero volume' AS message
        FROM {base_table} WHERE volume = 0
        """, p)

    if name == "high_ge_low":
        p["tol"] = thresholds["price_tolerance"]
        return (f"""
        SELECT symbol, ts, open, high, low, close, volume, 'high < low' AS message
        FROM {base_table} WHERE high < low - $tol
        """, p)

    if name == "high_ge_open_close":
        p["tol"] = thresholds["price_tolerance"]
        return (f"""
        SELECT symbol, ts, open, high, low, close, volume, 'high < max(open, close)' AS message
        FROM {base_table} WHERE high < greatest(open, close) - $tol
        """, p)

    if name == "low_le_open_close":
        p["tol"] = thresholds["price_tolerance"]
        return (f"""
        SELECT symbol, ts, open, high, low, close, volume, 'low > min(open, close)' AS message
        FROM {base_table} WHERE low > least(open, close) + $tol
        """, p)

    if name == "duplicate_timestamp":
        return (f"""
        WITH dupes AS (
            SELECT symbol, ts, count(*) AS n FROM {base_table} GROUP BY symbol, ts HAVING count(*) > 1
        )
        SELECT b.symbol, b.ts, b.open, b.high, b.low, b.close, b.volume,
               'duplicate (symbol, timestamp)' AS message
        FROM {base_table} b JOIN dupes d USING (symbol, ts)
        """, p)

    if name == "non_monotonic_timestamp":
        return (f"""
        WITH ordered AS (
            SELECT *, lag(ts) OVER (PARTITION BY symbol ORDER BY ts) AS prev_ts FROM {base_table}
        )
        SELECT symbol, ts, open, high, low, close, volume,
               'timestamp not strictly increasing vs previous row' AS message
        FROM ordered WHERE prev_ts IS NOT NULL AND ts <= prev_ts
        """, p)

    if name == "interval_gap":
        p["interval_s"] = float(thresholds["expected_interval_seconds"])
        p["gap_mult"] = float(thresholds["gap_multiplier"])
        return (f"""
        WITH ordered AS (
            SELECT *, lag(ts) OVER (PARTITION BY symbol ORDER BY ts) AS prev_ts FROM {base_table}
        )
        SELECT symbol, ts, open, high, low, close, volume,
               'gap of ' || date_diff('second', prev_ts, ts) || 's exceeds expected interval' AS message
        FROM ordered
        WHERE prev_ts IS NOT NULL AND date_diff('second', prev_ts, ts) > $interval_s * $gap_mult
        """, p)

    if name == "staleness":
        p["interval_s"] = float(thresholds["expected_interval_seconds"])
        p["stale_mult"] = float(thresholds["staleness_multiplier"])
        return (f"""
        WITH latest AS (SELECT symbol, max(ts) AS last_ts FROM {base_table} GROUP BY symbol)
        SELECT symbol, last_ts AS ts, NULL AS open, NULL AS high, NULL AS low, NULL AS close, NULL AS volume,
               'latest bar is ' || date_diff('second', last_ts, now()) || 's old' AS message
        FROM latest WHERE date_diff('second', last_ts, now()) > $interval_s * $stale_mult
        """, p)

    raise KeyError(name)


def anomaly_features_sql(base_table: str, thresholds: dict) -> tuple[str, dict]:
    # anomaly_window is used as a ROWS BETWEEN frame bound, which DuckDB
    # requires as a literal, not a bind parameter -- validated as a
    # positive int by validate_thresholds() before it ever reaches here.
    window = int(thresholds["anomaly_window"])
    sql = f"""
    WITH ordered AS (
        SELECT *,
               lag(close) OVER w AS prev_close, lag(open) OVER w AS prev_open,
               lag(high) OVER w AS prev_high, lag(low) OVER w AS prev_low
        FROM {base_table}
        WINDOW w AS (PARTITION BY symbol ORDER BY ts)
    ),
    ret AS (
        SELECT *,
               CASE WHEN prev_close IS NOT NULL AND prev_close != 0
                    THEN close / prev_close - 1 ELSE NULL END AS ret,
               (open = prev_open AND high = prev_high AND low = prev_low AND close = prev_close) AS same_as_prev
        FROM ordered
    ),
    with_lead AS (
        SELECT *, lead(ret) OVER (PARTITION BY symbol ORDER BY ts) AS next_ret FROM ret
    ),
    roll AS (
        SELECT *,
            median(ret) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN {window} PRECEDING AND 1 PRECEDING) AS roll_median_ret,
            median(volume) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN {window} PRECEDING AND 1 PRECEDING) AS roll_median_vol,
            count(ret) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN {window} PRECEDING AND 1 PRECEDING) AS n_hist
        FROM with_lead
    ),
    mad AS (
        SELECT *,
            median(abs(ret - roll_median_ret)) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN {window} PRECEDING AND 1 PRECEDING) AS roll_mad_ret,
            median(abs(volume - roll_median_vol)) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN {window} PRECEDING AND 1 PRECEDING) AS roll_mad_vol
        FROM roll
    ),
    grp AS (
        SELECT *, sum(CASE WHEN same_as_prev THEN 0 ELSE 1 END) OVER (PARTITION BY symbol ORDER BY ts) AS run_group
        FROM mad
    ),
    scored AS (
        SELECT *,
            count(*) OVER (PARTITION BY symbol, run_group) AS run_length,
            CASE WHEN roll_mad_ret > 0 THEN 0.6745 * (ret - roll_median_ret) / roll_mad_ret END AS ret_zscore,
            CASE WHEN roll_mad_vol > 0 THEN 0.6745 * (volume - roll_median_vol) / roll_mad_vol END AS vol_zscore,
            CASE WHEN close != 0 THEN (high - low) / close ELSE NULL END AS range_pct
        FROM grp
    )
    SELECT symbol, ts, open, high, low, close, volume,
           ret, next_ret, ret_zscore, vol_zscore, range_pct, same_as_prev, run_length, n_hist
    FROM scored
    """
    return sql, {}


# --------------------------------------------------------------------------
# DB helpers
# --------------------------------------------------------------------------
def connect_db(db_path: str, attach: list[str] | None = None):
    if db_path != ":memory:" and not Path(db_path).exists():
        raise ToolError(EXIT_RUNTIME_ERROR, "db_not_found", db_path, "check the --db path")
    try:
        con = duckdb.connect(db_path, read_only=(db_path != ":memory:"))
    except duckdb.Error as e:
        raise ToolError(EXIT_RUNTIME_ERROR, "db_connection_failed", db_path, str(e))
    for spec in (attach or []):
        path, _, alias = spec.partition(":")
        alias = alias or Path(path).stem
        try:
            con.execute(f"ATTACH {quote_ident(path)!s} AS {quote_ident(alias)} (READ_ONLY)"
                        .replace(quote_ident(path) + "!s", f"'{path}'"))
        except duckdb.Error as e:
            raise ToolError(EXIT_RUNTIME_ERROR, "attach_failed", spec, str(e))
    return con


def get_columns(con, table: str) -> list[str]:
    try:
        rows = con.execute(f"DESCRIBE {quote_qualified(table)}").fetchall()
    except duckdb.Error as e:
        raise ToolError(EXIT_RUNTIME_ERROR, "table_not_found", table, str(e))
    return [r[0] for r in rows]


def schema_check(db: str, table: str, cmap: dict, attach: list[str] | None = None) -> dict:
    con = connect_db(db, attach)
    actual_cols = get_columns(con, table)
    missing = [(logical, physical) for logical, physical in cmap.items() if physical not in actual_cols]
    return {
        "ok": not missing,
        "table": table,
        "available_columns": actual_cols,
        "column_map": cmap,
        "missing": [{"logical": l, "expected_column": p} for l, p in missing],
    }


def rows_to_dicts(con, sql: str, params: dict) -> list[dict]:
    rel = con.execute(sql, params)
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, row)) for row in rel.fetchall()]


def sanitize(v):
    """Make a value JSON-safe: no NaN/Infinity, datetimes -> isoformat, numpy scalars -> python."""
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(v, datetime):
        return v.isoformat()
    if _np is not None:
        if isinstance(v, _np.floating):
            f = float(v)
            return None if (math.isnan(f) or math.isinf(f)) else f
        if isinstance(v, _np.integer):
            return int(v)
    return v


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------
def run_inspection(args, cfg: dict) -> dict:
    cmap = cfg["column_map"]
    thresholds = cfg["thresholds"]
    enabled = cfg.get("enabled_checks")

    is_query = bool(args.query)
    table_or_query = args.query if is_query else args.table
    symbols = [s.strip() for s in args.symbol.split(",")] if args.symbol else None
    attach = args.attach or []

    requested = set(n.strip() for n in args.checks.split(",")) if args.checks else None
    excluded = set(n.strip() for n in args.exclude_checks.split(",")) if args.exclude_checks else set()

    def check_active(name: str, tier: str) -> bool:
        if args.tier != "all" and args.tier != tier:
            return False
        if enabled is not None and name not in enabled:
            return False
        if requested is not None and name not in requested:
            return False
        if name in excluded:
            return False
        return True

    notices = []
    if args.incremental:
        notices.append("--incremental is not yet implemented in this version; running a full scan instead of "
                        "resuming from a checkpoint. Do not rely on this flag for incremental behavior.")
    if args.full:
        notices.append("--full has no effect: this version always performs a full scan.")

    if args.dry_run:
        sql_blocks = {"base_table (materialized once)": dry_run_sql(table_or_query, is_query, cmap, symbols, args.start, args.end)}
        for name in QUALITY_CHECK_NAMES:
            if check_active(name, "quality"):
                sql, _ = quality_check_sql(name, "base_table", thresholds)
                sql_blocks[name] = sql.strip()
        if any(check_active(n, "anomaly") for n in ANOMALY_CHECK_NAMES):
            sql, _ = anomaly_features_sql("base_table", thresholds)
            sql_blocks["anomaly_features"] = sql.strip()
        return {"dry_run": True, "sql": sql_blocks, "notices": notices}

    con = connect_db(args.db, attach)
    if not is_query:
        get_columns(con, args.table)  # raises table_not_found if missing

    base_table = materialize_base_table(con, table_or_query, is_query, cmap, symbols, args.start, args.end)
    total_rows = con.execute(f"SELECT count(*) FROM {base_table}").fetchone()[0]

    summary = []
    details = []

    for name in QUALITY_CHECK_NAMES:
        if not check_active(name, "quality"):
            continue
        sql, params = quality_check_sql(name, base_table, thresholds)
        rows = rows_to_dicts(con, sql, params)
        severity = CHECK_BY_NAME[name].default_severity
        if rows:
            truncated = len(rows) > args.limit
            summary.append({
                "check": name, "tier": "quality", "severity": severity,
                "violations": len(rows),
                "pct_rows": round(len(rows) / total_rows, 6) if total_rows else None,
                "truncated": truncated,
            })
            for r in rows[: args.limit]:
                details.append({
                    "check": name, "tier": "quality", "severity": severity,
                    "symbol": r.get("symbol"), "timestamp": sanitize(r.get("ts")),
                    "values": {k: sanitize(v) for k, v in r.items() if k not in ("symbol", "ts", "message")},
                    "message": r.get("message"), "score": None,
                })

    if any(check_active(n, "anomaly") for n in ANOMALY_CHECK_NAMES):
        feat_sql, feat_params = anomaly_features_sql(base_table, thresholds)
        feat_rows = rows_to_dicts(con, feat_sql, feat_params)
        t = thresholds

        def add(name, rows_iter, message_fn, score_fn):
            rows = list(rows_iter)
            if rows:
                truncated = len(rows) > args.limit
                summary.append({
                    "check": name, "tier": "anomaly", "severity": "flagged",
                    "violations": len(rows),
                    "pct_rows": round(len(rows) / total_rows, 6) if total_rows else None,
                    "truncated": truncated,
                })
                for r in rows[: args.limit]:
                    details.append({
                        "check": name, "tier": "anomaly", "severity": "flagged",
                        "symbol": r.get("symbol"), "timestamp": sanitize(r.get("ts")),
                        "values": {k: sanitize(v) for k, v in r.items()
                                   if k in ("open", "high", "low", "close", "volume", "ret", "range_pct")},
                        "message": message_fn(r), "score": sanitize(score_fn(r)),
                    })

        if check_active("frozen_bar", "anomaly"):
            add("frozen_bar",
                (r for r in feat_rows if r["same_as_prev"] and r["run_length"] >= t["frozen_min_repeat"]),
                lambda r: f"{r['run_length']} consecutive bars with identical OHLC",
                lambda r: float(r["run_length"]))

        if check_active("return_outlier", "anomaly"):
            add("return_outlier",
                (r for r in feat_rows
                 if r["ret_zscore"] is not None and r["n_hist"] >= t["anomaly_min_periods"]
                 and abs(r["ret_zscore"]) >= t["return_zscore_threshold"]),
                lambda r: f"return {r['ret']:.4%} is a robust z-score of {r['ret_zscore']:.2f} vs rolling window",
                lambda r: round(abs(r["ret_zscore"]), 3))

        if check_active("price_spike_reversion", "anomaly"):
            def is_reversion(r):
                if r["ret_zscore"] is None or r["next_ret"] is None or r["n_hist"] < t["anomaly_min_periods"]:
                    return False
                if abs(r["ret_zscore"]) < t["return_zscore_threshold"]:
                    return False
                opp = (r["ret"] > 0 and r["next_ret"] < 0) or (r["ret"] < 0 and r["next_ret"] > 0)
                return opp and abs(r["next_ret"]) >= t["reversion_fraction"] * abs(r["ret"])
            add("price_spike_reversion",
                (r for r in feat_rows if is_reversion(r)),
                lambda r: f"return {r['ret']:.4%} reversed by {r['next_ret']:.4%} on the following bar",
                lambda r: round(abs(r["ret_zscore"]), 3))

        if check_active("volume_zscore_spike", "anomaly"):
            add("volume_zscore_spike",
                (r for r in feat_rows
                 if r["vol_zscore"] is not None and r["n_hist"] >= t["anomaly_min_periods"]
                 and abs(r["vol_zscore"]) >= t["volume_zscore_threshold"]),
                lambda r: f"volume z-score {r['vol_zscore']:.2f} vs rolling window",
                lambda r: round(abs(r["vol_zscore"]), 3))

        if check_active("volume_price_divergence", "anomaly"):
            def is_divergence(r):
                if r["vol_zscore"] is None or r["range_pct"] is None or r["n_hist"] < t["anomaly_min_periods"]:
                    return False
                return (r["vol_zscore"] >= t["volume_price_divergence_zscore"]
                        and r["range_pct"] <= t["volume_price_divergence_range_pct"])
            add("volume_price_divergence",
                (r for r in feat_rows if is_divergence(r)),
                lambda r: f"volume z-score {r['vol_zscore']:.2f} but range only {r['range_pct']:.4%} of close",
                lambda r: round(r["vol_zscore"], 3))

    exit_code = EXIT_CLEAN
    if any(s["severity"] == "error" for s in summary):
        exit_code = EXIT_HARD_ERRORS
    elif summary:
        exit_code = EXIT_WARNINGS_OR_FLAGS

    return {
        "meta": {
            "tool_version": TOOL_VERSION,
            "check_registry_version": CHECK_REGISTRY_VERSION,
            "config_source": cfg.get("_config_source"),
            "db": args.db,
            "table": args.table or "<query>",
            "symbols": symbols or "all",
            "start": args.start, "end": args.end,
            "total_rows_inspected": total_rows,
            "run_at": datetime.now(timezone.utc).isoformat(),
            "notices": notices,
        },
        "summary": summary,
        "details": details,
        "exit_code": exit_code,
    }


# --------------------------------------------------------------------------
# Output formatting
# --------------------------------------------------------------------------
def print_text_report(report: dict, verbose: bool):
    for notice in report.get("notices", []):
        print(f"NOTICE: {notice}")
    if report.get("dry_run"):
        for name, sql in report["sql"].items():
            print(f"--- {name} ---")
            print(sql.strip())
            print()
        return
    m = report["meta"]
    print(f"ohlcv-inspector v{TOOL_VERSION}  (checks {CHECK_REGISTRY_VERSION})")
    print(f"db={m['db']} table={m['table']} rows_inspected={m['total_rows_inspected']}")
    print(f"symbols={m['symbols']} start={m['start']} end={m['end']}")
    print()
    if not report["summary"]:
        print("CLEAN -- no quality errors/warnings or anomaly flags.")
    else:
        print(f"{'CHECK':30} {'TIER':10} {'SEVERITY':9} {'COUNT':>8} {'%ROWS':>8}  TRUNCATED")
        for s in report["summary"]:
            pct = f"{s['pct_rows']*100:.3f}%" if s["pct_rows"] is not None else "n/a"
            print(f"{s['check']:30} {s['tier']:10} {s['severity']:9} {s['violations']:>8} {pct:>8}  {s['truncated']}")
        if verbose:
            print()
            print("Details:")
            for d in report["details"]:
                print(f"  [{d['severity']}] {d['check']} symbol={d['symbol']} ts={d['timestamp']} :: {d['message']}")
    print()
    print(f"exit_code={report['exit_code']}")


def write_csv_report(report: dict, out) -> None:
    writer = csv.writer(out)
    writer.writerow(["check", "tier", "severity", "symbol", "timestamp", "message", "score"])
    for d in report.get("details", []):
        writer.writerow([d["check"], d["tier"], d["severity"], d["symbol"], d["timestamp"], d["message"], d["score"]])


def emit(report: dict, fmt: str, output: str | None, verbose: bool):
    if fmt == "json":
        text = json.dumps(report, indent=2, default=str, allow_nan=False)
    elif fmt == "csv":
        buf = io.StringIO()
        write_csv_report(report, buf)
        text = buf.getvalue()
    else:
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            print_text_report(report, verbose)
        finally:
            sys.stdout = old_stdout
        text = buf.getvalue()

    if output:
        Path(output).write_text(text)
    else:
        print(text)


def emit_error(err: ToolError, fmt: str):
    if fmt == "json":
        print(json.dumps(err.to_dict(), indent=2))
    else:
        print(f"ERROR [{err.error_type}]: {err.input_value}", file=sys.stderr)
        print(f"  suggestion: {err.suggestion}", file=sys.stderr)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def add_common_db_args(p):
    p.add_argument("--db", required=True, help="Path to DuckDB file, or :memory:")
    p.add_argument("--attach", action="append",
                    help="Attach an extra database before running, as path[:alias]. Repeatable.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ohlcv-inspector",
        description="Inspect an OHLCV candle table in DuckDB for quality problems and statistical abnormalities.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run the inspection and produce a report.")
    add_common_db_args(p_run)
    src = p_run.add_mutually_exclusive_group(required=True)
    src.add_argument("--table", help="Table name to inspect.")
    src.add_argument("--query", help="Arbitrary SQL source instead of --table.")
    p_run.add_argument("--symbol", help="Comma-separated symbol(s) to restrict to.")
    p_run.add_argument("--start", help="Start date/timestamp (inclusive).")
    p_run.add_argument("--end", help="End date/timestamp (inclusive).")
    p_run.add_argument("--tier", choices=["quality", "anomaly", "all"], default="all")
    p_run.add_argument("--checks", help="Comma-separated check names to run (default: all enabled).")
    p_run.add_argument("--exclude-checks", help="Comma-separated check names to skip.")
    p_run.add_argument("--config", help="Path to YAML config file.")
    p_run.add_argument("--column-map", help="Inline column mapping, e.g. close=close_price,volume=vol")
    p_run.add_argument("--incremental", action="store_true",
                        help="NOT YET IMPLEMENTED -- accepted for forward compatibility, emits a notice, runs a full scan.")
    p_run.add_argument("--full", action="store_true", help="No effect in this version (always full scan).")
    p_run.add_argument("--dry-run", action="store_true", help="Print SQL that would run; do not execute.")
    p_run.add_argument("--format", choices=["text", "json", "csv"], default="text")
    p_run.add_argument("--output", help="Write report to file instead of stdout.")
    p_run.add_argument("--limit", type=int, default=500, help="Max detail rows per check (default 500).")
    p_run.add_argument("--verbose", action="store_true")
    p_run.add_argument("--quiet", action="store_true")

    p_schema = sub.add_parser("schema", help="Schema-related commands.")
    schema_sub = p_schema.add_subparsers(dest="schema_command", required=True)
    p_schema_check = schema_sub.add_parser("check", help="Validate table columns against the column map.")
    add_common_db_args(p_schema_check)
    p_schema_check.add_argument("--table", required=True)
    p_schema_check.add_argument("--column-map")
    p_schema_check.add_argument("--config")
    p_schema_check.add_argument("--format", choices=["text", "json"], default="text")

    p_checks = sub.add_parser("checks", help="Inspect the check registry.")
    checks_sub = p_checks.add_subparsers(dest="checks_command", required=True)
    p_checks_list = checks_sub.add_parser("list", help="List available checks.")
    p_checks_list.add_argument("--tier", choices=["quality", "anomaly", "all"], default="all")
    p_checks_list.add_argument("--format", choices=["text", "json"], default="text")
    p_checks_describe = checks_sub.add_parser("describe", help="Describe a specific check.")
    p_checks_describe.add_argument("name")
    p_checks_describe.add_argument("--format", choices=["text", "json"], default="text")

    p_config = sub.add_parser("config", help="Config-related commands.")
    config_sub = p_config.add_subparsers(dest="config_command", required=True)
    p_config_validate = config_sub.add_parser("validate", help="Validate a config file without running anything.")
    p_config_validate.add_argument("--config", required=True)
    p_config_validate.add_argument("--format", choices=["text", "json"], default="text")

    sub.add_parser("version", help="Print version info.")

    return parser


def cmd_run(args) -> int:
    fmt = args.format
    try:
        cfg = load_config(args.config, args.column_map)
        report = run_inspection(args, cfg)
    except ToolError as e:
        emit_error(e, fmt if fmt != "csv" else "text")
        return e.exit_code
    except duckdb.Error as e:
        emit_error(ToolError(EXIT_RUNTIME_ERROR, "duckdb_error", str(e), "check the table/query and try again"),
                    fmt if fmt != "csv" else "text")
        return EXIT_RUNTIME_ERROR

    emit(report, fmt, args.output, args.verbose and not args.quiet)
    return EXIT_CLEAN if report.get("dry_run") else report.get("exit_code", EXIT_CLEAN)


def cmd_schema_check(args) -> int:
    try:
        cfg = load_config(args.config, args.column_map)
        result = schema_check(args.db, args.table, cfg["column_map"], args.attach)
    except ToolError as e:
        emit_error(e, args.format)
        return e.exit_code

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"table: {result['table']}")
        print(f"available columns: {', '.join(result['available_columns'])}")
        if result["ok"]:
            print("schema OK -- all mapped columns found.")
        else:
            print("schema MISMATCH:")
            for m in result["missing"]:
                print(f"  logical '{m['logical']}' -> expected column '{m['expected_column']}' NOT FOUND")
    return EXIT_CLEAN if result["ok"] else EXIT_USAGE_OR_CONFIG_ERROR


def cmd_checks_list(args) -> int:
    checks = [c for c in CHECK_REGISTRY if args.tier == "all" or c.tier == args.tier]
    if args.format == "json":
        print(json.dumps([{"name": c.name, "tier": c.tier, "severity": c.default_severity,
                            "description": c.description} for c in checks], indent=2))
    else:
        for c in checks:
            print(f"[{c.tier:8}] {c.name:28} (default severity: {c.default_severity})")
            print(f"    {c.description}")
    return EXIT_CLEAN


def cmd_checks_describe(args) -> int:
    c = CHECK_BY_NAME.get(args.name)
    if not c:
        err = ToolError(EXIT_USAGE_OR_CONFIG_ERROR, "unknown_check", args.name,
                         "run 'ohlcv-inspector checks list' to see available check names")
        emit_error(err, args.format)
        return err.exit_code
    if args.format == "json":
        print(json.dumps({"name": c.name, "tier": c.tier, "severity": c.default_severity,
                           "description": c.description, "example": c.example}, indent=2))
    else:
        print(f"{c.name}  [{c.tier}, default severity: {c.default_severity}]")
        print(f"  {c.description}")
        print(f"  Example trigger: {c.example}")
    return EXIT_CLEAN


def cmd_config_validate(args) -> int:
    try:
        cfg = load_config(args.config, None)
    except ToolError as e:
        emit_error(e, args.format)
        return e.exit_code

    problems = validate_thresholds(cfg["thresholds"])
    ok = not problems
    if args.format == "json":
        print(json.dumps({"ok": ok, "problems": problems, "config_source": cfg["_config_source"]}, indent=2))
    else:
        print(f"config: {cfg['_config_source']}")
        print("OK" if ok else "INVALID:")
        for p in problems:
            print(f"  - {p}")
    return EXIT_CLEAN if ok else EXIT_USAGE_OR_CONFIG_ERROR


def cmd_version(args) -> int:
    print(f"ohlcv-inspector {TOOL_VERSION}")
    print(f"check_registry_version {CHECK_REGISTRY_VERSION}")
    print(f"duckdb {duckdb.__version__}")
    print(f"pyyaml {yaml.__version__ if yaml else 'not installed'}")
    if _np is not None:
        print(f"numpy {_np.__version__}")
    else:
        print("numpy not installed")
    print(f"python {sys.version.split()[0]}")
    return EXIT_CLEAN


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return cmd_run(args)
        if args.command == "schema" and args.schema_command == "check":
            return cmd_schema_check(args)
        if args.command == "checks" and args.checks_command == "list":
            return cmd_checks_list(args)
        if args.command == "checks" and args.checks_command == "describe":
            return cmd_checks_describe(args)
        if args.command == "config" and args.config_command == "validate":
            return cmd_config_validate(args)
        if args.command == "version":
            return cmd_version(args)
    except ToolError as e:
        emit_error(e, getattr(args, "format", "text"))
        return e.exit_code
    parser.print_help()
    return EXIT_USAGE_OR_CONFIG_ERROR


if __name__ == "__main__":
    sys.exit(main())
