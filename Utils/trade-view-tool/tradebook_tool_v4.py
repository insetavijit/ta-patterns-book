#!/usr/bin/env python3
"""
tradebook_tool v4 — Trade Book + Smart Grid, combined CLI
==========================================================
Designed to be driven by a coding agent (Claude Code / editor tooling) as
much as by a human. Three subcommands:

    tradebook_tool.py tradebook --json ...   # generate trade playbook PNGs
    tradebook_tool.py smartgrid --json ...   # run the chart-packing layout engine
    tradebook_tool.py describe --pretty      # machine-readable self-description

What changed in v4.1 (fixes from a follow-up code review of v4)
------------------------------------------------------------------
Bug fixes:
  - Argparse-level failures (invalid --strategy choice, missing required
    --ohlcv-table, violating the --sql/--sql-file mutually-exclusive group,
    unrecognized flags, etc.) used to bypass the documented error_envelope
    contract entirely: argparse calls ArgumentParser.error() -> exit()
    *before* main()'s try/except is even entered, so --json was ignored and
    plain argparse usage text went to stderr instead of the
    {"status": "error", "code": "bad_input", ...} JSON envelope. Both the
    top-level parser and every subparser now use a small
    `_JsonAwareArgumentParser` subclass that emits the same JSON envelope
    on argparse-level errors when --json is present anywhere in argv, so
    "every bad-input failure gets the JSON envelope when --json is passed"
    is now actually true, not just true for post-parse validation errors.

Robustness / input validation:
  - `smartgrid`'s --max-charts, --min-candles, and --px-per-candle are now
    range-checked in validate_input() the same way tradebook's equivalent
    flags already were, instead of being passed straight to paginate()/
    fill_row() with unspecified behavior on bad values. (Previously
    documented as a known gap in the manual; now closed in code, so that
    section of the manual is gone.)

Code quality:
  - smartgrid's argparse --default values are now sourced directly from
    LayoutConfig's own field defaults (a single `LayoutConfig()` instance
    built once at parser-construction time) instead of being retyped as
    separate literals in add_argument(...), removing a place the two could
    silently drift apart.
  - Numeric/pattern constraints (minimum/maximum/pattern/choices semantics
    beyond what argparse's `choices=` already expresses) are now attached
    directly to the relevant argparse Action objects at definition time and
    surfaced through `describe`, so `describe --pretty` is now the complete
    canonical source for flags/defaults/help/choices *and* constraints --
    the manual no longer carries a separate, hand-maintained copy that could
    drift from the code.

(v1 -> v4 changelog is unchanged and omitted here for brevity; see below.)

What changed in v4 (fixes from a code review of v3)
------------------------------------------------------
Bug fixes:
  - `smartgrid --candles ... --dry-run` used to silently DISCARD the given
    --candles and substitute the built-in dummy dataset. Fixed: --dry-run
    now validates/lays out whatever --candles you actually passed (it only
    skips the file write), matching how `tradebook --dry-run` behaves.
  - `--candles` used to silently drop unparseable tokens (a typo like
    `15o` just vanished with no warning). It now raises a clear
    bad-input error listing the offending token(s) instead of quietly
    changing your dataset.
  - A bad/nonexistent `--ohlcv-table` used to surface deep inside DuckDB as
    an uncaught CatalogException, misclassified as EXIT_UNEXPECTED. A fast
    upfront existence check now reports it as EXIT_BAD_INPUT with an
    actionable message.

Robustness / input validation:
  - `--pad`, `--exit-lookahead`, `--row-capacity`, `--max-charts` are now
    range-checked upfront (clear error) instead of failing later inside
    DuckDB (e.g. a negative LIMIT) or deep inside the layout engine.
  - `--hline-cols` values that turn out non-numeric are now logged at
    debug level instead of being swallowed silently.
  - Ctrl-C now exits with a dedicated EXIT_INTERRUPTED (130) instead of an
    uncaught-exception traceback.
  - New `--debug` flag (or TRADEBOOK_DEBUG=1) prints a full traceback to
    stderr on unexpected errors — important for a tool an *agent* is meant
    to self-correct against.

Performance:
  - The SL/TP-scan + window-fetch that used to cost up to 4 DuckDB round
    trips per trade is now at most 2 (`resolve_exit_and_window`), with
    identical semantics — see that function's docstring.
  - Heavy rendering dependencies (mplfinance, matplotlib, Pillow) are now
    deferred a second time: `--dry-run` only imports duckdb + pandas, never
    matplotlib/mplfinance/Pillow, since it never renders anything.

Code quality:
  - Lazy tradebook dependencies are no longer pushed into module `global`s;
    they're returned from `_load_tradebook_deps()` as an explicit
    `_TradebookDeps` object and threaded through function calls, so static
    analysis and tests can reason about them normally.
  - `dummy_data` is now an immutable tuple (`_DEFAULT_DUMMY_CANDLES`)
    instead of a shared mutable module-level list.
  - Removed an unused `datetime.timedelta` import and a stray, unattached
    triple-quoted "section banner" string that did nothing at runtime.
  - Single version scheme: `__version__` now tracks this file's own
    generation number (this is v4) instead of an unrelated semver.

New: agent-ergonomics
  - `describe` subcommand: emits this tool's flags, exit codes, and the
    TRADE COLUMN CONTRACT as JSON, so an agent can introspect the contract
    once instead of re-reading this whole docstring every session.
  - `--log-json`: emit stderr progress/log lines as JSON instead of plain
    text, to match the existing `--json` stdout result envelope.

(v2 -> v3 changelog — generic --sql contract, vectorized SL/TP scan,
identifier whitelisting, the PIL-import fix — is unchanged and omitted
here for brevity; see the TRADE COLUMN CONTRACT below, which still applies
as-is. Run `tradebook_tool.py describe` for the full current contract.)

TRADE COLUMN CONTRACT (what your --sql result must/can contain)
-----------------------------------------------------------------
Required (case-insensitive column names; alias with AS as needed):
    entry_time    timestamp the trade was entered
    entry_price   float entry price

Recognized optional columns:
    trade_id      shown in the chart title (default: row position)
    sl_price      stop-loss price -> red horizontal line
    tp_price      take-profit price -> green horizontal line
    exit_time     explicit exit timestamp (skips the SL/TP scan)
    exit_price    explicit exit price (used with exit_time)
    exit_reason   free text shown in the chart title
    pnl           float; drives WIN/LOSS color coding in the title

Any other column can be drawn as a horizontal reference line via
--hline-cols, e.g. --hline-cols s1,r1,vwap

If neither exit_time/exit_price nor sl_price/tp_price is supplied, the
chart is centered on entry_time alone with no computed exit.

Agent-facing conventions
----------------------------------------------
  - stdout is reserved for machine-readable results (JSON when --json is
    passed). All progress/status/log messages go to stderr via `logging`
    (plain text by default, or JSON lines with --log-json).
  - Exit codes are semantic (see EXIT_* constants below).
  - `tradebook --dry-run` validates inputs/SQL and reports how many
    trades would be plotted, without touching matplotlib or writing files.
  - Heavy dependencies (duckdb, matplotlib, mplfinance, pandas, PIL) are
    imported lazily and in two stages: duckdb+pandas whenever `tradebook`
    runs, and matplotlib/mplfinance/PIL only when it will actually render
    (i.e. not on `--dry-run`). `smartgrid` and `describe` (pure Python, no
    I/O) start and return instantly.
  - Run `tradebook_tool.py describe --pretty` for a full machine-readable
    dump of flags, exit codes, and the trade column contract.
  - `--debug` (or TRADEBOOK_DEBUG=1) prints full tracebacks to stderr on
    unexpected errors instead of a one-line summary.

============================================================================
SECTION 1: Smart Grid Layout Engine (no I/O, no SQL, nothing here is
hardcoded)
============================================================================
Candlestick Chart Grid Layout System
-------------------------------------
  Stage A (packing)   -> group charts into rows
  Stage B (fill)      -> resolve leftover space per row via BOUNDED
                          proportional extension of displayed candles
  Pagination          -> split rows across canvases by max charts/canvas

Three packing strategies are provided for Stage A:
  - "wordwrap" : greedy, order-preserving (baseline / safest default)
  - "bestfit"  : reorders charts (Best-Fit-Decreasing bin packing)
  - "optimal"  : order-preserving DP that minimizes TOTAL leftover^3
                 across all rows at once -- recommended default.

No external dependencies for this section. Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import traceback
from dataclasses import dataclass

__version__ = "4.1.0"  # tracks this file's own generation number (v4, revision 1)

# --------------------------------------------------------------------------
# Semantic exit codes (agent-facing contract — do not renumber casually;
# treat this as a versioned interface once anything depends on it).
# --------------------------------------------------------------------------

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_BAD_INPUT = 2
EXIT_DB_NOT_FOUND = 3
EXIT_INTERRUPTED = 130  # conventional SIGINT exit code

# --------------------------------------------------------------------------
# argparse-level errors (bad --strategy choice, missing required flag,
# violated mutually-exclusive group, unrecognized argument, ...) call
# ArgumentParser.error() -> exit() *before* parse_args() returns, i.e.
# before main()'s try/except around post-parse validation is ever entered.
# Left alone, these print plain argparse usage text to stderr and exit 2,
# silently skipping the documented JSON error_envelope contract even when
# --json was requested. This subclass closes that gap by emitting the same
# envelope shape from error() itself. --json/args.json don't exist yet at
# this point (parsing hasn't finished), so we sniff sys.argv directly --
# harmless even for `describe`, which has no --json flag of its own.
# --------------------------------------------------------------------------

class _JsonAwareArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that emits the tool's standard JSON error envelope on
    argparse-level failures when --json is present in argv, instead of
    falling back to plain usage text. Set once on the top-level parser;
    add_subparsers() propagates the same class to every subparser
    automatically (argparse defaults parser_class to type(self))."""

    def error(self, message: str) -> None:
        if "--json" in sys.argv:
            envelope = {"status": "error", "code": "bad_input", "message": message}
            print(json.dumps(envelope), file=sys.stderr)
        else:
            print(f"{self.prog}: error: {message}", file=sys.stderr)
        self.exit(EXIT_BAD_INPUT)


# --------------------------------------------------------------------------
# Logging: everything progress/status related goes to stderr. stdout is
# reserved for the command's actual result (JSON or human summary).
# --------------------------------------------------------------------------

logger = logging.getLogger("tradebook_tool")


class _JsonLogFormatter(logging.Formatter):
    """Optional structured-log formatter (--log-json) so an agent can parse
    progress lines the same way it parses the --json result envelope,
    instead of regex-ing plain text."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {"level": record.levelname.lower(), "message": record.getMessage()}
        return json.dumps(payload)


def _configure_logging(quiet: bool = False, json_logs: bool = False) -> None:
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(_JsonLogFormatter() if json_logs else logging.Formatter("%(message)s"))
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING if quiet else logging.INFO)
    logger.propagate = False


# --------------------------------------------------------------------------
# Dummy Data (default baseline dataset for smartgrid testing & dry-runs).
# Immutable: earlier versions used a shared mutable module-level list;
# a tuple can't be accidentally mutated by one caller and corrupt every
# later dry-run in the same process. Copy to a list only where a list is
# actually required (e.g. LayoutConfig consumers that may want to extend it).
# --------------------------------------------------------------------------

_DEFAULT_DUMMY_CANDLES: tuple[int, ...] = (200, 150, 350, 25, 45, 500, 80, 120, 300, 60, 90, 200, 40, 70)


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

@dataclass
class LayoutConfig:
    row_capacity_candles: int = 500       # canvas width, in candle units
    px_per_candle: float = 3.0            # fixed zoom level, never changes
    gap_candles: int = 2                  # spacing between charts in a row
    max_charts_per_canvas: int = 12       # pagination limit
    max_extension_ratio: float = 1.3      # cap on how much a chart can be
                                           # stretched via extra candles
    min_candles: int = 15                 # floor so no chart gets too narrow
    packing_strategy: str = "optimal"     # "wordwrap" | "bestfit" | "optimal"


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def validate_input(candle_counts: list[int], config: LayoutConfig) -> None:
    if not candle_counts:
        raise ValueError("candle_counts must not be empty")
    if any((not isinstance(c, int)) or c <= 0 for c in candle_counts):
        raise ValueError("candle_counts must all be positive integers")
    if config.row_capacity_candles <= 0:
        raise ValueError("row_capacity_candles must be positive")
    if config.gap_candles < 0:
        raise ValueError("gap_candles must be >= 0")
    if config.max_extension_ratio < 1.0:
        raise ValueError("max_extension_ratio must be >= 1.0")
    if config.packing_strategy not in ("wordwrap", "bestfit", "optimal"):
        raise ValueError(f"unknown packing_strategy: {config.packing_strategy}")
    if config.max_charts_per_canvas < 1:
        raise ValueError("max_charts_per_canvas must be >= 1")
    if config.min_candles < 0:
        raise ValueError("min_candles must be >= 0")
    if config.px_per_candle <= 0:
        raise ValueError("px_per_candle must be > 0")


# --------------------------------------------------------------------------
# Stage A: packing strategies -> list of rows, each row = list of original indices
# --------------------------------------------------------------------------

def pack_wordwrap(candle_counts: list[int], capacity: int, gap: int) -> list[list[int]]:
    rows: list[list[int]] = []
    current: list[int] = []
    current_total = 0
    for i, c in enumerate(candle_counts):
        if c > capacity:
            if current:
                rows.append(current)
                current, current_total = [], 0
            rows.append([i])  # overflow row, alone
            continue
        needed = c + (gap if current else 0)
        if current and current_total + needed > capacity:
            rows.append(current)
            current, current_total = [], 0
            needed = c
        current.append(i)
        current_total += needed
    if current:
        rows.append(current)
    return rows


def pack_bestfit(candle_counts: list[int], capacity: int, gap: int) -> list[list[int]]:
    order = sorted(range(len(candle_counts)), key=lambda i: candle_counts[i], reverse=True)
    rows: list[dict] = []  # {"indices": [...], "total": int, "overflow": bool}
    for i in order:
        c = candle_counts[i]
        if c > capacity:
            rows.append({"indices": [i], "total": c, "overflow": True})
            continue
        best_r, best_leftover = None, None
        for r_idx, row in enumerate(rows):
            if row["overflow"]:
                continue
            addl = c if not row["indices"] else gap + c
            new_total = row["total"] + addl
            if new_total <= capacity:
                leftover = capacity - new_total
                if best_leftover is None or leftover < best_leftover:
                    best_leftover, best_r = leftover, r_idx
        if best_r is not None:
            row = rows[best_r]
            addl = c if not row["indices"] else gap + c
            row["total"] += addl
            row["indices"].append(i)
        else:
            rows.append({"indices": [i], "total": c, "overflow": False})
    for row in rows:
        row["indices"].sort()
    rows.sort(key=lambda r: min(r["indices"]))
    return [r["indices"] for r in rows]


def pack_optimal(candle_counts: list[int], capacity: int, gap: int) -> list[list[int]]:
    """
    Order-preserving DP (Knuth-Plass style): choose row breakpoints that
    minimize the SUM of leftover^3 across ALL rows at once, instead of
    greedily minimizing each row in isolation. O(n^2) -- fine for typical
    per-canvas batch sizes (tens to a few hundred charts).
    """
    n = len(candle_counts)
    INF = float("inf")
    dp = [INF] * (n + 1)
    dp[0] = 0.0
    back = [-1] * (n + 1)

    for i in range(1, n + 1):
        running_total = 0
        for j in range(i - 1, -1, -1):
            c = candle_counts[j]
            if j == i - 1:
                running_total = c
            else:
                running_total += gap + c
            if running_total > capacity:
                if j == i - 1:
                    if dp[j] + 0.0 < dp[i]:
                        dp[i] = dp[j] + 0.0
                        back[i] = j
                break
            leftover = capacity - running_total
            badness = leftover ** 3
            if dp[j] + badness < dp[i]:
                dp[i] = dp[j] + badness
                back[i] = j

    rows = []
    i = n
    while i > 0:
        j = back[i]
        rows.append(list(range(j, i)))
        i = j
    rows.reverse()
    return rows


PACKERS = {
    "wordwrap": pack_wordwrap,
    "bestfit": pack_bestfit,
    "optimal": pack_optimal,
}


# --------------------------------------------------------------------------
# Stage B: bounded proportional fill
# --------------------------------------------------------------------------

def fill_row(indices: list[int], candle_counts: list[int], config: LayoutConfig) -> list[dict]:
    capacity = config.row_capacity_candles
    gap = config.gap_candles
    n = len(indices)
    is_overflow = n == 1 and candle_counts[indices[0]] > capacity

    if is_overflow:
        c = candle_counts[indices[0]]
        return [{
            "index": indices[0], "original_candles": c, "displayed_candles": c,
            "extra_candles_added": 0, "capped": False, "overflow": True,
        }]

    gap_total = gap * max(0, n - 1)
    available = capacity - gap_total
    natural_total = sum(candle_counts[i] for i in indices)
    scale = available / natural_total if natural_total > 0 else 1.0
    scale_capped = min(scale, config.max_extension_ratio)
    capped = scale > config.max_extension_ratio

    results = []
    for i in indices:
        c = candle_counts[i]
        displayed = max(config.min_candles, round(c * scale_capped))
        results.append({
            "index": i, "original_candles": c, "displayed_candles": displayed,
            "extra_candles_added": displayed - c, "capped": capped, "overflow": False,
        })

    if not capped:
        residual = available - sum(r["displayed_candles"] for r in results)
        results[-1]["displayed_candles"] += residual
        results[-1]["extra_candles_added"] += residual

    return results


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------

def paginate(rows_filled: list[list[dict]], max_charts_per_canvas: int) -> list[list[list[dict]]]:
    canvases = []
    current_canvas_rows = []
    current_chart_count = 0

    for row in rows_filled:
        row_size = len(row)
        if current_canvas_rows and current_chart_count + row_size > max_charts_per_canvas:
            canvases.append(current_canvas_rows)
            current_canvas_rows, current_chart_count = [], 0
        current_canvas_rows.append(row)
        current_chart_count += row_size

    if current_canvas_rows:
        canvases.append(current_canvas_rows)
    return canvases


# --------------------------------------------------------------------------
# Public API Function
# --------------------------------------------------------------------------

def compute_layout(candle_counts: list[int] = None, config: LayoutConfig = None) -> dict:
    if candle_counts is None:
        candle_counts = list(_DEFAULT_DUMMY_CANDLES)
    config = config or LayoutConfig()
    validate_input(candle_counts, config)

    packer = PACKERS[config.packing_strategy]
    row_indices = packer(candle_counts, config.row_capacity_candles, config.gap_candles)

    rows_filled = [fill_row(row, candle_counts, config) for row in row_indices]
    canvases_rows = paginate(rows_filled, config.max_charts_per_canvas)

    canvases_out = []
    for canvas_idx, canvas_rows in enumerate(canvases_rows):
        rows_out = []
        for row_idx, row in enumerate(canvas_rows):
            x_candles = 0
            charts_out = []
            for item in row:
                x_px = round(x_candles * config.px_per_candle, 1)
                width_px = round(item["displayed_candles"] * config.px_per_candle, 1)
                charts_out.append({
                    "index": item["index"],
                    "original_candles": item["original_candles"],
                    "displayed_candles": item["displayed_candles"],
                    "extra_candles_added": item["extra_candles_added"],
                    "x_px": x_px,
                    "width_px": width_px,
                    "capped": item["capped"],
                    "overflow": item["overflow"],
                })
                x_candles += item["displayed_candles"] + config.gap_candles
            rows_out.append({"row": row_idx, "charts": charts_out})
        canvases_out.append({"canvas_index": canvas_idx, "rows": rows_out})

    return {
        "config": {
            "row_capacity_candles": config.row_capacity_candles,
            "px_per_candle": config.px_per_candle,
            "gap_candles": config.gap_candles,
            "max_charts_per_canvas": config.max_charts_per_canvas,
            "max_extension_ratio": config.max_extension_ratio,
            "min_candles": config.min_candles,
            "packing_strategy": config.packing_strategy,
        },
        "canvas_width_px": round(config.row_capacity_candles * config.px_per_candle, 1),
        "total_charts": len(candle_counts),
        "canvases": canvases_out,
    }


# --------------------------------------------------------------------------
# Class API
# --------------------------------------------------------------------------

class SmartGridEngine:
    """Object-Oriented Class API for the Candlestick Chart Grid Layout System."""

    def __init__(self, candle_counts: list[int] = None, config: LayoutConfig = None):
        self.candle_counts = candle_counts if candle_counts is not None else list(_DEFAULT_DUMMY_CANDLES)
        self.config = config or LayoutConfig()

    def run(self) -> dict:
        """Computes and returns the layout solution dictionary."""
        return compute_layout(self.candle_counts, self.config)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.run(), indent=indent)

    def save_json(self, filepath: str) -> str:
        res = self.run()
        filepath = os.path.normpath(filepath)
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(res, f, indent=2)
        return filepath

    @classmethod
    def dry_run(cls, config: LayoutConfig = None) -> dict:
        engine = cls(candle_counts=list(_DEFAULT_DUMMY_CANDLES), config=config)
        return engine.run()


# ============================================================================
# SECTION 2: Trade Book Generator
# ============================================================================
# Generates SmartGrid-packed candlestick "trade playbook" PNGs from a DuckDB
# database, using the SmartGridEngine defined above for layout. Nothing about
# the trade query, the OHLCV table name, or its column names is hardcoded —
# see the TRADE COLUMN CONTRACT and --ohlcv-*-col flags documented at the top
# of this file (or run `tradebook_tool.py describe`).
#
# Heavy dependencies are imported lazily and in two stages via
# `_load_tradebook_deps()` / `_TradebookDeps.load_render_deps()`, so
# `--dry-run` never pays the cost of importing matplotlib/mplfinance/PIL,
# and `smartgrid`/`describe` never pay the cost of importing anything here.
# ============================================================================

# A plain SQL identifier: letters/digits/underscore, not starting with a
# digit. Used to validate table/column names before they're interpolated
# into a FROM/SELECT clause, since those positions can't be parameterized
# with `?` placeholders the way values can.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Columns your --sql result MUST provide (case-insensitive, via `AS`).
TRADE_REQUIRED_COLUMNS = ("entry_time", "entry_price")

# Colors cycled through for --hline-cols reference lines beyond SL/TP.
_HLINE_COLOR_CYCLE = ["darkorange", "purple", "teal", "brown", "magenta", "slategray"]


class TradebookInputError(ValueError):
    """Raised for invalid CLI/user input -> maps to EXIT_BAD_INPUT."""


class _TradebookDeps:
    """Explicit container for the heavy, lazily-imported dependencies used
    by the tradebook subcommand. Passed explicitly through function calls
    instead of being pushed into module `global`s (as earlier versions did),
    so static analysis tools (mypy/pyright) and unit tests can reason about
    them normally, and so the two import stages stay cleanly separated."""

    __slots__ = ("duckdb", "pd", "mpf", "mdates", "gridspec", "plt", "Image")

    def __init__(self, duckdb_mod, pd_mod):
        self.duckdb = duckdb_mod
        self.pd = pd_mod
        self.mpf = None
        self.mdates = None
        self.gridspec = None
        self.plt = None
        self.Image = None

    def load_render_deps(self) -> None:
        """Second-stage import: only needed when actually rendering PNGs
        (never on --dry-run)."""
        if self.mpf is not None:
            return
        import mplfinance as mpf
        import matplotlib.dates as mdates
        import matplotlib.gridspec as gridspec
        import matplotlib.pyplot as plt
        from PIL import Image  # mplfinance renders -> Pillow handles the PNG save/optimize

        self.mpf, self.mdates, self.gridspec, self.plt, self.Image = mpf, mdates, gridspec, plt, Image


def _load_tradebook_deps() -> _TradebookDeps:
    """First-stage import: duckdb + pandas only. Needed by every tradebook
    invocation (including --dry-run); matplotlib/mplfinance/PIL are loaded
    separately, only when a render actually happens."""
    import duckdb
    import pandas as pd
    return _TradebookDeps(duckdb, pd)


def _validate_identifier(name: str, flag_name: str) -> str:
    if not name or not _IDENTIFIER_RE.match(name):
        raise TradebookInputError(
            f"{flag_name} must be a plain SQL identifier (letters, digits, "
            f"underscore, not starting with a digit); got: {name!r}"
        )
    return name


def _validate_select_sql(sql: str) -> str:
    """Defense-in-depth guard: --sql must be a read query. The DuckDB
    connection is also opened read_only=True as the primary guard against
    writes; this just fails fast with a clearer error before hitting the DB.
    Note: --sql is assumed to be author-trusted (written by you or your
    agent), not adversarial end-user input — this guard catches accidental
    writes/typos, it is not a sandbox against a hostile query string."""
    if not sql or not sql.strip():
        raise TradebookInputError("--sql (or --sql-file) must not be empty")
    m = re.match(r"^\s*(?:--[^\n]*\n\s*)*(\w+)", sql)
    first_word = m.group(1).lower() if m else ""
    if first_word not in ("select", "with"):
        raise TradebookInputError(
            "--sql must be a read-only SELECT (or WITH ... SELECT) query, "
            f"got a query starting with: {first_word!r}"
        )
    return sql


def build_ohlcv_column_map(
    time_col: str, open_col: str, high_col: str, low_col: str, close_col: str,
    volume_col: str | None,
) -> dict:
    """Validates and returns the {role: actual_column_name} map used to
    build every OHLCV query. This is the ONLY place OHLCV column names are
    resolved — change your --ohlcv-*-col flags, not this code, to point at
    a differently-named table."""
    mapping = {"time": time_col, "open": open_col, "high": high_col, "low": low_col, "close": close_col}
    if volume_col:
        mapping["volume"] = volume_col
    for role, col in mapping.items():
        _validate_identifier(col, f"--ohlcv-{role}-col")
    return mapping


def _ohlcv_select_clause(ohlcv_cols: dict) -> str:
    """Builds 'src_col AS "Open"' etc. so mplfinance gets the column names
    it expects (Open/High/Low/Close[/Volume]) regardless of what your table
    actually calls them."""
    display_names = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
    parts = [f'"{ohlcv_cols["time"]}" AS "Time"']
    for role, disp in display_names.items():
        if role in ohlcv_cols:
            parts.append(f'"{ohlcv_cols[role]}" AS "{disp}"')
    return ", ".join(parts)


def _check_table_exists(deps: _TradebookDeps, con, table: str) -> None:
    """Fails fast with EXIT_BAD_INPUT (instead of letting a raw
    duckdb.CatalogException surface later as EXIT_UNEXPECTED) when
    --ohlcv-table doesn't exist / isn't queryable in this database."""
    try:
        con.execute(f'SELECT 1 FROM "{table}" LIMIT 0')
    except deps.duckdb.Error as e:
        raise TradebookInputError(
            f"--ohlcv-table {table!r} could not be queried -- does it exist "
            f"in this database (as a table or view)? Underlying error: {e}"
        )


def normalize_trade_columns(df):
    """Lowercases --sql result columns and enforces TRADE_REQUIRED_COLUMNS."""
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in TRADE_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise TradebookInputError(
            f"--sql result is missing required column(s): {missing}. "
            "Alias your columns to satisfy the contract, e.g. "
            "'SELECT ts AS entry_time, px AS entry_price, ... FROM ...'. "
            f"Columns returned: {list(df.columns)}"
        )
    return df


def _to_naive_ts(pd, value):
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts


def _concat_window(deps: _TradebookDeps, before, main, after):
    """Assembles the final chart window from up to three fetched pieces,
    deduping on Time and indexing by it (what mplfinance expects)."""
    pd = deps.pd
    parts = [d for d in (before, main, after) if d is not None and not d.empty]
    if not parts:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close"])
    df = pd.concat(parts, ignore_index=True).drop_duplicates(subset="Time").sort_values("Time")
    df["Time"] = pd.to_datetime(df["Time"])
    df = df.set_index("Time")
    return df


def fetch_trade_window(deps: _TradebookDeps, con, ohlcv_table: str, ohlcv_cols: dict,
                        entry_dt, exit_dt, pad_candles: int):
    """Builds the candle window for one chart when the exit is already known
    (the explicit exit_time/exit_price path): up to `pad_candles` before
    entry, everything between entry and exit, up to `pad_candles` after
    exit. Count-based (not time-based), so it works for any bar size
    without needing to know the timeframe. Three queries — used only for
    the explicit-exit path; see resolve_exit_and_window() for the more
    common SL/TP-scan path, which does the equivalent in two queries."""
    pd = deps.pd
    select_clause = _ohlcv_select_clause(ohlcv_cols)
    time_col = ohlcv_cols["time"]

    q_before = (
        f'SELECT {select_clause} FROM "{ohlcv_table}" '
        f'WHERE "{time_col}" < ? ORDER BY "{time_col}" DESC LIMIT ?'
    )
    before = con.execute(q_before, [entry_dt, pad_candles]).df().iloc[::-1]

    q_main = (
        f'SELECT {select_clause} FROM "{ohlcv_table}" '
        f'WHERE "{time_col}" >= ? AND "{time_col}" <= ? ORDER BY "{time_col}" ASC'
    )
    main = con.execute(q_main, [entry_dt, exit_dt]).df()

    q_after = (
        f'SELECT {select_clause} FROM "{ohlcv_table}" '
        f'WHERE "{time_col}" > ? ORDER BY "{time_col}" ASC LIMIT ?'
    )
    after = con.execute(q_after, [exit_dt, pad_candles]).df()

    return _concat_window(deps, before, main, after)


def resolve_exit_and_window(deps: _TradebookDeps, con, ohlcv_table: str, ohlcv_cols: dict,
                             entry_dt, entry_p: float, sl_p: float | None, tp_p: float | None,
                             pad_candles: int, exit_lookahead: int):
    """
    Combines the SL/TP scan and the chart-window fetch — two separate
    round-trip groups in earlier versions (up to 1 + 3 = 4 queries per
    trade) — into two queries total:

      1. `before`  - up to `pad_candles` candles strictly before entry_time.
      2. `forward` - up to `exit_lookahead + pad_candles + 1` candles at/after
                     entry_time, ASC. An exact-entry-time row, if present, is
                     excluded from SL/TP hit-testing (mirrors the original
                     "scan starts strictly after entry" semantics) but is
                     still included in the rendered window. Everything the
                     window needs after entry (the "main" and "after-exit"
                     slices) is sliced from this same in-memory frame instead
                     of issued as separate queries.

    Returns (exit_dt, exit_p, exit_reason, df_window). Timeframe-agnostic:
    works off candle COUNT, never assumes bar duration.
    """
    pd = deps.pd
    select_clause = _ohlcv_select_clause(ohlcv_cols)
    time_col = ohlcv_cols["time"]

    q_before = (
        f'SELECT {select_clause} FROM "{ohlcv_table}" '
        f'WHERE "{time_col}" < ? ORDER BY "{time_col}" DESC LIMIT ?'
    )
    before = con.execute(q_before, [entry_dt, pad_candles]).df().iloc[::-1]

    forward_limit = exit_lookahead + pad_candles + 1
    q_forward = (
        f'SELECT {select_clause} FROM "{ohlcv_table}" '
        f'WHERE "{time_col}" >= ? ORDER BY "{time_col}" ASC LIMIT ?'
    )
    forward = con.execute(q_forward, [entry_dt, forward_limit]).df()

    if forward.empty:
        # No future data available at all -- don't guess a duration, just
        # report the trade as closing at entry.
        return entry_dt, entry_p, "NO_DATA", _concat_window(deps, before, pd.DataFrame(), pd.DataFrame())

    forward["Time"] = pd.to_datetime(forward["Time"])

    # Exclude an exact-entry-time row from the SL/TP scan (matches the
    # earlier ">" semantics for the scan) while keeping it in `forward`
    # for window assembly below.
    if forward.iloc[0]["Time"] == entry_dt:
        scan = forward.iloc[1:1 + exit_lookahead]
    else:
        scan = forward.iloc[0:exit_lookahead]

    if scan.empty:
        main = forward[forward["Time"] <= entry_dt]
        after = forward[forward["Time"] > entry_dt].iloc[:pad_candles]
        return entry_dt, entry_p, "NO_DATA", _concat_window(deps, before, main, after)

    if sl_p is None and tp_p is None:
        main = forward[forward["Time"] <= entry_dt]
        after = forward[forward["Time"] > entry_dt].iloc[:pad_candles]
        return entry_dt, entry_p, "N/A", _concat_window(deps, before, main, after)

    is_long = True
    if sl_p is not None and tp_p is not None:
        is_long = tp_p > sl_p
    elif sl_p is not None:
        is_long = entry_p > sl_p

    if is_long:
        sl_hit = scan["Low"].le(sl_p) if sl_p is not None else None
        tp_hit = scan["High"].ge(tp_p) if tp_p is not None else None
    else:
        sl_hit = scan["High"].ge(sl_p) if sl_p is not None else None
        tp_hit = scan["Low"].le(tp_p) if tp_p is not None else None

    sl_idx = sl_hit.idxmax() if sl_hit is not None and sl_hit.any() else None
    tp_idx = tp_hit.idxmax() if tp_hit is not None and tp_hit.any() else None

    if sl_idx is not None and (tp_idx is None or sl_idx <= tp_idx):
        row = scan.loc[sl_idx]
        exit_dt, exit_p, exit_reason = _to_naive_ts(pd, row["Time"]), sl_p, "SL"
    elif tp_idx is not None:
        row = scan.loc[tp_idx]
        exit_dt, exit_p, exit_reason = _to_naive_ts(pd, row["Time"]), tp_p, "TP"
    else:
        row = scan.iloc[-1]
        exit_dt, exit_p, exit_reason = _to_naive_ts(pd, row["Time"]), float(row["Close"]), "TIME"

    exit_time_val = row["Time"]
    main = forward[forward["Time"] <= exit_time_val]
    after = forward[forward["Time"] > exit_time_val].iloc[:pad_candles]
    return exit_dt, exit_p, exit_reason, _concat_window(deps, before, main, after)


def generate_trade_book(
    deps: _TradebookDeps,
    db_path: str, sql: str, sql_params: list, ohlcv_table: str, ohlcv_cols: dict,
    output_file: str, pad_candles: int = 15, exit_lookahead: int = 288,
    hline_cols: list[str] | None = None, row_capacity: int = 350,
    strategy: str = "optimal", max_charts: int = 18, run_name: str = "tradebook",
    dry_run: bool = False,
) -> dict:
    """Returns a result envelope dict:
        {"status": "ok", "trades_found": int, "canvases_generated": int,
         "output_files": [str, ...], "run_name": str, "dry_run": bool}
    Raises FileNotFoundError if db_path doesn't exist, TradebookInputError
    for bad --sql / --ohlcv-* input.
    """
    pd = deps.pd
    sql = _validate_select_sql(sql)
    _validate_identifier(ohlcv_table, "--ohlcv-table")
    hline_cols = [c.strip().lower() for c in (hline_cols or []) if c.strip()]

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DuckDB database file not found at '{db_path}'")

    with deps.duckdb.connect(db_path, read_only=True) as con:
        _check_table_exists(deps, con, ohlcv_table)

        df_trades = con.execute(sql, sql_params or []).df()

        if df_trades.empty:
            logger.info("No trades returned by --sql")
            return {"status": "ok", "trades_found": 0, "canvases_generated": 0,
                    "output_files": [], "run_name": run_name, "dry_run": dry_run}

        df_trades = normalize_trade_columns(df_trades)

        if dry_run:
            logger.info(f"[dry-run] {len(df_trades)} trade(s) would be plotted")
            return {"status": "ok", "trades_found": int(len(df_trades)), "canvases_generated": 0,
                    "output_files": [], "run_name": run_name, "dry_run": True}

        trade_windows = []
        candle_counts = []

        for i, row in enumerate(df_trades.to_dict("records")):
            t_id = row.get("trade_id", i + 1)
            entry_dt = _to_naive_ts(pd, row["entry_time"])
            entry_p = float(row["entry_price"])
            sl_p = row.get("sl_price")
            sl_p = float(sl_p) if sl_p is not None and pd.notna(sl_p) else None
            tp_p = row.get("tp_price")
            tp_p = float(tp_p) if tp_p is not None and pd.notna(tp_p) else None

            exit_time_given = row.get("exit_time")
            has_exit_time = exit_time_given is not None and pd.notna(exit_time_given)

            if has_exit_time:
                exit_dt = _to_naive_ts(pd, exit_time_given)
                exit_price_given = row.get("exit_price")
                exit_p = (float(exit_price_given)
                          if exit_price_given is not None and pd.notna(exit_price_given)
                          else entry_p)
                exit_reason = row.get("exit_reason") or "PROVIDED"
                df_window = fetch_trade_window(deps, con, ohlcv_table, ohlcv_cols, entry_dt, exit_dt, pad_candles)
            else:
                exit_dt, exit_p, exit_reason, df_window = resolve_exit_and_window(
                    deps, con, ohlcv_table, ohlcv_cols, entry_dt, entry_p, sl_p, tp_p,
                    pad_candles, exit_lookahead,
                )

            c_cnt = len(df_window) if not df_window.empty else max(pad_candles, 1)

            pnl = row.get("pnl")
            pnl = float(pnl) if pnl is not None and pd.notna(pnl) else None

            hline_values = {}
            for col in hline_cols:
                v = row.get(col)
                if v is not None and pd.notna(v):
                    try:
                        hline_values[col] = float(v)
                    except (TypeError, ValueError):
                        logger.debug(
                            f"--hline-cols: column '{col}' value {v!r} on trade "
                            f"#{t_id} is not numeric, skipping"
                        )

            candle_counts.append(c_cnt)
            trade_windows.append({
                "t_id": t_id, "entry_dt": entry_dt, "entry_p": entry_p, "sl_p": sl_p, "tp_p": tp_p,
                "pnl": pnl, "exit_dt": exit_dt, "exit_p": exit_p, "exit_reason": exit_reason,
                "df_window": df_window, "hline_values": hline_values,
            })

    # DuckDB connection is closed (context manager) before the CPU-bound
    # layout/render work below, which needs no DB access.

    config = LayoutConfig(
        row_capacity_candles=row_capacity,
        packing_strategy=strategy,
        max_charts_per_canvas=max_charts,
    )
    layout_data = SmartGridEngine(candle_counts=candle_counts, config=config).run()
    canvases = layout_data["canvases"]
    total_canvases = len(canvases)

    # Only import matplotlib/mplfinance/PIL now that we know we're actually
    # rendering (dry_run already returned above).
    deps.load_render_deps()
    mpf, mdates, gridspec, plt, Image = deps.mpf, deps.mdates, deps.gridspec, deps.plt, deps.Image

    custom_style = mpf.make_mpf_style(
        base_mpf_style="charles",
        rc={"font.size": 6, "axes.labelsize": 6, "xtick.labelsize": 5.5,
            "ytick.labelsize": 5.5, "figure.facecolor": "#fafafa"},
    )

    generated_pngs = []

    for canvas_idx, canvas in enumerate(canvases):
        rows = canvas["rows"]
        num_rows = len(rows)

        fig = plt.figure(figsize=(16, 3.8 * num_rows), dpi=150)
        outer_gs = gridspec.GridSpec(num_rows, 1, figure=fig, hspace=0.35)

        for r_idx, row in enumerate(rows):
            charts_in_row = row["charts"]
            row_widths = [c["displayed_candles"] for c in charts_in_row]
            inner_gs = gridspec.GridSpecFromSubplotSpec(
                1, len(charts_in_row), subplot_spec=outer_gs[r_idx], width_ratios=row_widths, wspace=0.20,
            )

            for c_idx, chart_info in enumerate(charts_in_row):
                tw = trade_windows[chart_info["index"]]
                df_w = tw["df_window"]
                ax = fig.add_subplot(inner_gs[0, c_idx])

                if df_w.empty:
                    ax.text(0.5, 0.5, f"No Data\nTrade #{tw['t_id']}", ha="center", va="center")
                    continue

                mpf.plot(df_w, type="candle", ax=ax, style=custom_style)

                x_dates = df_w.index
                entry_dt = tw["entry_dt"]
                entry_idx_arr = x_dates.get_indexer([entry_dt])
                if entry_idx_arr[0] != -1:
                    entry_idx = entry_idx_arr[0]
                    ax.axvline(x=entry_idx, color="blue", linestyle="--", linewidth=1.2, alpha=0.8)
                    ax.axhline(y=tw["entry_p"], color="blue", linestyle=":", linewidth=1.0, alpha=0.7)

                if tw["sl_p"] is not None:
                    ax.axhline(y=tw["sl_p"], color="red", linestyle="-", linewidth=0.9, alpha=0.75, label="SL")
                if tw["tp_p"] is not None:
                    ax.axhline(y=tw["tp_p"], color="green", linestyle="-", linewidth=0.9, alpha=0.75, label="TP")
                for h_idx, (col_name, val) in enumerate(tw["hline_values"].items()):
                    color = _HLINE_COLOR_CYCLE[h_idx % len(_HLINE_COLOR_CYCLE)]
                    ax.axhline(y=val, color=color, linestyle="-.", linewidth=0.7, alpha=0.6, label=col_name)

                pnl_val = tw["pnl"]
                if pnl_val is None:
                    win_loss, color_edge = "N/A", "#555555"
                else:
                    win_loss = "WIN" if pnl_val >= 0 else "LOSS"
                    color_edge = "#2e7d32" if pnl_val >= 0 else "#c62828"

                title_str = f"Trade #{tw['t_id']} | {win_loss} | Exit: {tw['exit_reason']}"
                ax.set_title(title_str, fontsize=6.5, fontweight="bold", color=color_edge, pad=3)
                ax.tick_params(axis="both", which="major", labelsize=5.5)
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))

        page_str = f" (Page {canvas_idx + 1}/{total_canvases})" if total_canvases > 1 else ""
        plt.suptitle(
            f"Trade Playbook — {run_name}{page_str} — {len(df_trades)} Trades | SmartGrid {strategy.upper()}",
            fontsize=12, fontweight="bold", y=0.995,
        )
        fig.subplots_adjust(top=0.94, bottom=0.04, left=0.04, right=0.96)

        base_dir, file_name = os.path.split(output_file)
        name_no_ext, ext = os.path.splitext(file_name)
        sub_dir = os.path.join(base_dir, name_no_ext)
        os.makedirs(sub_dir, exist_ok=True)

        page_output = (
            os.path.join(sub_dir, f"p{canvas_idx + 1}{ext}")
            if total_canvases > 1 else
            os.path.join(sub_dir, f"{name_no_ext}{ext}")
        )

        # mplfinance/matplotlib render into a buffer; Pillow handles the
        # actual PNG save + optimization.
        import io
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        with Image.open(buf) as img:
            img.save(page_output, format="PNG", optimize=True)

        file_size_kb = os.path.getsize(page_output) / 1024
        logger.info(f"SmartGrid PNG generated: {page_output} ({file_size_kb:.1f} KB)")
        generated_pngs.append(page_output)

    return {
        "status": "ok",
        "trades_found": int(len(df_trades)),
        "canvases_generated": total_canvases,
        "output_files": generated_pngs,
        "run_name": run_name,
        "dry_run": False,
    }


# --------------------------------------------------------------------------
# CLI: tradebook subcommand
# --------------------------------------------------------------------------

def _build_tradebook_parser(subparsers):
    parser = subparsers.add_parser(
        "tradebook",
        description=(
            "Generate SmartGrid trade playbook PNG(s) from an arbitrary --sql query "
            "against a DuckDB database, using mplfinance for rendering and Pillow for "
            "PNG save/optimize. See the TRADE COLUMN CONTRACT in this file's module "
            "docstring (or run `tradebook_tool.py describe`) for what your --sql "
            "result must/can contain."
        ),
        epilog=(
            "Examples:\n"
            "  %(prog)s --db trades.duckdb "
            "--sql \"SELECT trade_id, entry_time, entry_price, sl_price, tp_price, pnl "
            "FROM v_all_trades WHERE pnl < 0 ORDER BY entry_time LIMIT 12\" "
            "--ohlcv-table ohlcv_5m --json\n"
            "  %(prog)s --db trades.duckdb --sql-file query.sql --ohlcv-table ohlcv_1m "
            "--ohlcv-time-col ts --hline-cols s1,r1,vwap\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", type=str, default=None,
                         help="Path to DuckDB database file (or set TRADEBOOK_DB env var)")

    sql_group = parser.add_mutually_exclusive_group(required=True)
    sql_group.add_argument("--sql", type=str, default=None,
                            help="Trade-selection SQL query (must satisfy the TRADE COLUMN CONTRACT)")
    sql_group.add_argument("--sql-file", type=str, default=None,
                            help="Path to a file containing the trade-selection SQL query")
    parser.add_argument("--sql-params", type=str, default=None,
                         help="JSON array of values bound to `?` placeholders in --sql, e.g. '[\"2025-01-01\"]'")

    _ident_constraint = {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"}

    a = parser.add_argument("--ohlcv-table", type=str, required=True,
                             help="Table/view name containing OHLCV candle data")
    a.constraint = _ident_constraint

    a = parser.add_argument("--ohlcv-time-col", type=str, default="timestamp")
    a.constraint = _ident_constraint
    a = parser.add_argument("--ohlcv-open-col", type=str, default="open")
    a.constraint = _ident_constraint
    a = parser.add_argument("--ohlcv-high-col", type=str, default="high")
    a.constraint = _ident_constraint
    a = parser.add_argument("--ohlcv-low-col", type=str, default="low")
    a.constraint = _ident_constraint
    a = parser.add_argument("--ohlcv-close-col", type=str, default="close")
    a.constraint = _ident_constraint
    a = parser.add_argument("--ohlcv-volume-col", type=str, default="volume",
                             help="Set to '' to indicate no volume column is available")
    a.constraint = {"type": "string", "pattern": "^($|[A-Za-z_][A-Za-z0-9_]*$)",
                     "note": "empty string explicitly means 'no volume column'"}

    a = parser.add_argument("--pad", "-p", type=int, default=15,
                             help="Context candles before entry / after exit (default: 15, must be >= 0)")
    a.constraint = {"type": "integer", "minimum": 0}

    a = parser.add_argument("--exit-lookahead", type=int, default=288,
                             help="Max candles scanned forward for SL/TP hits (default: 288, must be >= 1)")
    a.constraint = {"type": "integer", "minimum": 1}

    parser.add_argument("--hline-cols", type=str, default=None,
                         help="Comma-separated extra --sql columns to draw as reference lines, e.g. s1,r1,vwap")

    a = parser.add_argument("--row-capacity", "-r", type=int, default=350,
                             help="Target candle capacity per row (default: 350, must be > 0)")
    a.constraint = {"type": "integer", "exclusiveMinimum": 0}

    a = parser.add_argument("--max-charts", "-m", type=int, default=18,
                             help="Max charts per canvas page (default: 18, must be >= 1)")
    a.constraint = {"type": "integer", "minimum": 1}

    a = parser.add_argument("--strategy", type=str, choices=["optimal", "wordwrap", "bestfit"], default="optimal",
                             help="SmartGrid packing strategy (default: optimal)")
    a.constraint = {"type": "string", "enum": ["optimal", "wordwrap", "bestfit"]}

    parser.add_argument("--run-name", type=str, default="tradebook",
                         help="Label used in chart titles and default output filename (default: tradebook)")
    parser.add_argument("--output", type=str, default=None, help="Output PNG path")
    parser.add_argument("--output-dir", type=str, default="./outs",
                         help="Directory for the default output path when --output is not given (default: ./outs)")
    parser.add_argument("--dry-run", action="store_true",
                         help="Validate inputs/SQL and report trade count without rendering or writing files "
                              "(never imports matplotlib/mplfinance/PIL)")
    parser.add_argument("--json", action="store_true", help="Emit a single-line JSON result envelope on stdout")
    parser.add_argument("--quiet", action="store_true", help="Suppress info-level progress logs on stderr")
    return parser


def _run_tradebook(args) -> int:
    deps = _load_tradebook_deps()

    db_path = args.db or os.environ.get("TRADEBOOK_DB")
    if not db_path:
        raise TradebookInputError("--db is required (or set the TRADEBOOK_DB environment variable)")

    if args.sql_file:
        try:
            with open(args.sql_file, "r") as f:
                sql = f.read()
        except OSError as e:
            raise TradebookInputError(f"could not read --sql-file '{args.sql_file}': {e}")
    else:
        sql = args.sql
    sql = _validate_select_sql(sql)

    if args.sql_params:
        try:
            sql_params = json.loads(args.sql_params)
        except json.JSONDecodeError as e:
            raise TradebookInputError(f"--sql-params must be a JSON array: {e}")
        if not isinstance(sql_params, list):
            raise TradebookInputError("--sql-params must be a JSON array, e.g. '[\"2025-01-01\"]'")
    else:
        sql_params = []

    ohlcv_cols = build_ohlcv_column_map(
        args.ohlcv_time_col, args.ohlcv_open_col, args.ohlcv_high_col,
        args.ohlcv_low_col, args.ohlcv_close_col, args.ohlcv_volume_col or None,
    )
    _validate_identifier(args.ohlcv_table, "--ohlcv-table")

    hline_cols = [c for c in (args.hline_cols.split(",") if args.hline_cols else [])]

    # Fail fast, with a clear message tied to the flag name, instead of a
    # confusing DuckDB/layout-engine error later.
    if args.pad < 0:
        raise TradebookInputError(f"--pad must be >= 0, got {args.pad}")
    if args.exit_lookahead < 1:
        raise TradebookInputError(f"--exit-lookahead must be >= 1, got {args.exit_lookahead}")
    if args.row_capacity <= 0:
        raise TradebookInputError(f"--row-capacity must be > 0, got {args.row_capacity}")
    if args.max_charts < 1:
        raise TradebookInputError(f"--max-charts must be >= 1, got {args.max_charts}")

    os.makedirs(args.output_dir, exist_ok=True)
    out_png = args.output if args.output else os.path.join(args.output_dir, f"{args.run_name}.png")

    result = generate_trade_book(
        deps,
        db_path=db_path, sql=sql, sql_params=sql_params,
        ohlcv_table=args.ohlcv_table, ohlcv_cols=ohlcv_cols, output_file=out_png,
        pad_candles=args.pad, exit_lookahead=args.exit_lookahead, hline_cols=hline_cols,
        row_capacity=args.row_capacity, strategy=args.strategy, max_charts=args.max_charts,
        run_name=args.run_name, dry_run=args.dry_run,
    )

    if args.json:
        print(json.dumps(result))
    else:
        if result["dry_run"]:
            logger.info(f"[dry-run] {result['trades_found']} trade(s) would be plotted")
        else:
            logger.info(f"{result['trades_found']} trade(s), {len(result['output_files'])} PNG(s) written")
        print(
            f"Done: {result['trades_found']} trade(s), "
            f"{result['canvases_generated']} canvas(es), "
            f"{len(result['output_files'])} PNG(s) written."
        )

    return EXIT_OK


# --------------------------------------------------------------------------
# CLI: smartgrid subcommand (pure Python, nothing hardcoded)
# --------------------------------------------------------------------------

def _parse_candles_arg(raw_args: list[str]) -> list[int]:
    """Parses --candles tokens (allowing loose formats like '[200, 150]' or
    '200,150' in addition to plain space-separated ints, since agents often
    paste JSON-ish lists). Any token that isn't a positive integer raises a
    clear error instead of being silently dropped, so a typo doesn't quietly
    change the dataset being laid out."""
    values: list[int] = []
    invalid: list[str] = []
    for item in raw_args:
        cleaned = str(item).strip().strip("[]{}")
        for part in re.split(r"[,\s]+", cleaned):
            part = part.strip()
            if not part:
                continue
            if part.isdigit() and int(part) > 0:
                values.append(int(part))
            else:
                invalid.append(part)
    if invalid:
        raise TradebookInputError(
            f"--candles contains invalid token(s) (must all be positive integers): {invalid}"
        )
    if not values:
        raise TradebookInputError(f"--candles produced no valid positive integers from input: {raw_args}")
    return values


def _build_smartgrid_parser(subparsers):
    parser = subparsers.add_parser(
        "smartgrid",
        description="Candlestick Chart Grid Layout System (Stage A Packing, Stage B Fill, Pagination).",
        epilog=(
            "Examples:\n"
            "  %(prog)s --dry-run --json\n"
            "  %(prog)s --candles 200 150 350 25 --row-capacity 400\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Defaults are read from LayoutConfig itself (single instance, built
    # once) instead of being retyped as separate literals here, so the
    # dataclass stays the one source of truth and the two can't drift apart.
    _cfg_defaults = LayoutConfig()

    a = parser.add_argument("--candles", "--candels", "-c", nargs="+",
                             help="Candle counts for charts e.g. 200 150 350 25 45 500 80 120 300")
    a.constraint = {"type": "array", "items": {"type": "integer", "minimum": 1}, "minItems": 1}

    a = parser.add_argument("--row-capacity", "-r", type=int, default=_cfg_defaults.row_capacity_candles,
                             help=f"Row capacity in candles (default: {_cfg_defaults.row_capacity_candles})")
    a.constraint = {"type": "integer", "exclusiveMinimum": 0}

    a = parser.add_argument("--px-per-candle", type=float, default=_cfg_defaults.px_per_candle,
                             help=f"Fixed zoom level in px/candle (default: {_cfg_defaults.px_per_candle})")
    a.constraint = {"type": "number", "exclusiveMinimum": 0}

    a = parser.add_argument("--gap", type=int, default=_cfg_defaults.gap_candles,
                             help=f"Gap between charts in candles (default: {_cfg_defaults.gap_candles})")
    a.constraint = {"type": "integer", "minimum": 0}

    a = parser.add_argument("--max-charts", type=int, default=_cfg_defaults.max_charts_per_canvas,
                             help=f"Max charts per canvas (default: {_cfg_defaults.max_charts_per_canvas})")
    a.constraint = {"type": "integer", "minimum": 1}

    a = parser.add_argument("--max-extension", type=float, default=_cfg_defaults.max_extension_ratio,
                             help=f"Max extension ratio (default: {_cfg_defaults.max_extension_ratio})")
    a.constraint = {"type": "number", "minimum": 1.0}

    a = parser.add_argument("--min-candles", type=int, default=_cfg_defaults.min_candles,
                             help=f"Min candles floor per chart (default: {_cfg_defaults.min_candles})")
    a.constraint = {"type": "integer", "minimum": 0}

    a = parser.add_argument("--strategy", type=str, choices=["optimal", "wordwrap", "bestfit"],
                             default=_cfg_defaults.packing_strategy,
                             help=f"Packing strategy (default: {_cfg_defaults.packing_strategy})")
    a.constraint = {"type": "string", "enum": ["optimal", "wordwrap", "bestfit"]}
    parser.add_argument("--dry-run", action="store_true",
                         help="Compute layout using --candles if given (else default dummy data); skip file write "
                              "-- --candles is honored on dry-run too (fixed in v4: it used to be ignored)")
    parser.add_argument("--output", type=str, default="./outs/layout_output.json", help="Output JSON path")
    parser.add_argument("--json", action="store_true", help="Emit a compact JSON result envelope on stdout instead of the full pretty layout")
    parser.add_argument("--quiet", action="store_true", help="Suppress info-level progress logs on stderr")
    return parser


def _run_smartgrid(args) -> int:
    if args.candles:
        candle_counts = _parse_candles_arg(args.candles)
    else:
        candle_counts = list(_DEFAULT_DUMMY_CANDLES)

    config = LayoutConfig(
        row_capacity_candles=args.row_capacity,
        px_per_candle=args.px_per_candle,
        gap_candles=args.gap,
        max_charts_per_canvas=args.max_charts,
        max_extension_ratio=args.max_extension,
        min_candles=args.min_candles,
        packing_strategy=args.strategy,
    )

    engine = SmartGridEngine(candle_counts=candle_counts, config=config)
    result = engine.run()

    out_file = None
    if not args.dry_run:
        out_file = engine.save_json(filepath=args.output)
        logger.info(f"Layout output written to: {out_file}")
    else:
        logger.info("[dry-run] Layout computed, no file written")

    if args.json:
        envelope = {
            "status": "ok",
            "dry_run": args.dry_run,
            "total_charts": result["total_charts"],
            "canvases_generated": len(result["canvases"]),
            "output_file": out_file,
            "layout": result,
        }
        print(json.dumps(envelope))
    else:
        print(json.dumps(result, indent=2))

    return EXIT_OK


# --------------------------------------------------------------------------
# CLI: describe subcommand (new in v4 — agent-facing self-description)
# --------------------------------------------------------------------------

def _build_describe_parser(subparsers):
    parser = subparsers.add_parser(
        "describe",
        description=(
            "Emit a machine-readable JSON description of this tool: subcommands "
            "and their flags, exit codes, and the TRADE COLUMN CONTRACT. Intended "
            "for a coding agent to introspect the contract once instead of "
            "re-parsing this file's module docstring every session."
        ),
    )
    parser.add_argument("--pretty", action="store_true",
                         help="Pretty-print with indentation (default: compact single line)")
    return parser


def _describe_subparser(sub_action, name: str) -> dict | None:
    """Best-effort introspection of an argparse subparser's flags. Uses
    argparse's internal `_actions` list (no public API exists for this);
    wrapped so a future argparse internals change degrades gracefully to a
    shorter description instead of crashing `describe`."""
    parser = sub_action.choices.get(name)
    if parser is None:
        return None
    info = {"description": parser.description, "flags": []}
    try:
        for a in parser._actions:  # noqa: SLF001 -- deliberate, defensive best-effort introspection
            if not a.option_strings or a.dest == "help":
                continue
            default = a.default
            if not isinstance(default, (str, int, float, bool, type(None))):
                default = str(default)
            info["flags"].append({
                "flags": a.option_strings,
                "dest": a.dest,
                "help": a.help,
                "required": bool(getattr(a, "required", False)),
                "default": default,
                "choices": list(a.choices) if a.choices else None,
                # JSON-Schema-style bound, only present where it adds
                # something argparse's own choices/type can't already
                # express (numeric bounds, identifier patterns, array
                # shape). None when no extra constraint was attached.
                "constraint": getattr(a, "constraint", None),
            })
    except AttributeError:
        info["flags"] = None  # introspection unavailable; description is still useful
    return info


def _run_describe(args) -> int:
    top_parser = build_parser()
    sub_action = next(
        (a for a in top_parser._actions if isinstance(a, argparse._SubParsersAction)),  # noqa: SLF001
        None,
    )

    payload = {
        "tool": "tradebook_tool",
        "version": __version__,
        "exit_codes": {
            "EXIT_OK": EXIT_OK,
            "EXIT_UNEXPECTED": EXIT_UNEXPECTED,
            "EXIT_BAD_INPUT": EXIT_BAD_INPUT,
            "EXIT_DB_NOT_FOUND": EXIT_DB_NOT_FOUND,
            "EXIT_INTERRUPTED": EXIT_INTERRUPTED,
        },
        "subcommands": {
            "tradebook": _describe_subparser(sub_action, "tradebook") if sub_action else None,
            "smartgrid": _describe_subparser(sub_action, "smartgrid") if sub_action else None,
        },
        "trade_column_contract": {
            "required_columns": list(TRADE_REQUIRED_COLUMNS),
            "optional_columns": {
                "trade_id": "shown in the chart title (default: row position)",
                "sl_price": "float; stop-loss price -> red horizontal line",
                "tp_price": "float; take-profit price -> green horizontal line",
                "exit_time": "explicit exit timestamp (skips the SL/TP scan)",
                "exit_price": "explicit exit price (used with exit_time)",
                "exit_reason": "free text shown in the chart title",
                "pnl": "float; drives WIN/LOSS color coding in the title",
            },
            "reference_lines": (
                "any other --sql column can be drawn as a horizontal reference "
                "line via --hline-cols, e.g. --hline-cols s1,r1,vwap"
            ),
        },
        "global_flags": {
            "--debug": "print a full traceback to stderr on unexpected errors (or set TRADEBOOK_DEBUG=1); "
                       "must appear before the subcommand",
            "--log-json": "emit stderr log lines as JSON instead of plain text; must appear before the subcommand",
        },
    }
    text = json.dumps(payload, indent=2 if args.pretty else None)
    print(text)
    return EXIT_OK


# --------------------------------------------------------------------------
# Top-level CLI entry point
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    # _JsonAwareArgumentParser (not plain ArgumentParser) so that argparse-
    # level failures -- bad choices, missing required flags, mutually-
    # exclusive violations -- also emit the JSON error envelope when --json
    # is present. add_subparsers() below inherits this class automatically.
    parser = _JsonAwareArgumentParser(
        prog="tradebook_tool",
        description="Trade Book + Smart Grid — combined CLI, designed for both human and agent use.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--debug", action="store_true",
                         help="Print a full traceback to stderr on unexpected errors (or set TRADEBOOK_DEBUG=1). "
                              "Must appear before the subcommand, e.g. `%(prog)s --debug tradebook ...`")
    parser.add_argument("--log-json", action="store_true",
                         help="Emit stderr progress/log lines as JSON instead of plain text. "
                              "Must appear before the subcommand.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _build_tradebook_parser(subparsers)
    _build_smartgrid_parser(subparsers)
    _build_describe_parser(subparsers)
    return parser


def main(argv: list[str] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    debug = getattr(args, "debug", False) or os.environ.get("TRADEBOOK_DEBUG") == "1"
    _configure_logging(quiet=getattr(args, "quiet", False), json_logs=getattr(args, "log_json", False))

    try:
        if args.command == "tradebook":
            return _run_tradebook(args)
        elif args.command == "smartgrid":
            return _run_smartgrid(args)
        elif args.command == "describe":
            return _run_describe(args)
        else:
            parser.error(f"unknown command: {args.command}")
            return EXIT_BAD_INPUT  # unreachable, parser.error() exits itself
    except KeyboardInterrupt:
        logger.warning("Interrupted.")
        return EXIT_INTERRUPTED
    except FileNotFoundError as e:
        error = {"status": "error", "code": "db_not_found", "message": str(e)}
        if getattr(args, "json", False):
            print(json.dumps(error), file=sys.stderr)
        else:
            logger.error(str(e))
        return EXIT_DB_NOT_FOUND
    except (TradebookInputError, ValueError) as e:
        error = {"status": "error", "code": "bad_input", "message": str(e)}
        if getattr(args, "json", False):
            print(json.dumps(error), file=sys.stderr)
        else:
            logger.error(str(e))
        return EXIT_BAD_INPUT
    except Exception as e:
        if debug:
            traceback.print_exc(file=sys.stderr)
        error = {"status": "error", "code": "unexpected", "message": f"{type(e).__name__}: {e}"}
        if getattr(args, "json", False):
            print(json.dumps(error), file=sys.stderr)
        else:
            logger.error(f"Unexpected error: {type(e).__name__}: {e}")
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    sys.exit(main())
