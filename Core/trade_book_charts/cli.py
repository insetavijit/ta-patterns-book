"""CLI Interface & Subcommand Handlers for TradeView."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import traceback

from .db import (
    _load_tradebook_deps,
    _validate_identifier,
    _validate_select_sql,
    build_ohlcv_column_map,
)
from .engine import LayoutConfig, SmartGridEngine
from .models import (
    EXIT_BAD_INPUT,
    EXIT_DB_NOT_FOUND,
    EXIT_INTERRUPTED,
    EXIT_OK,
    EXIT_UNEXPECTED,
    TRADE_REQUIRED_COLUMNS,
    TradebookInputError,
    _DEFAULT_DUMMY_CANDLES,
    __version__,
)
from .renderer import generate_trade_book

logger = logging.getLogger("tradebook_tool")


class _JsonAwareArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that emits JSON error envelopes when --json is present."""

    def error(self, message: str) -> None:
        if "--json" in sys.argv:
            envelope = {"status": "error", "code": "bad_input", "message": message}
            print(json.dumps(envelope), file=sys.stderr)
        else:
            print(f"{self.prog}: error: {message}", file=sys.stderr)
        self.exit(EXIT_BAD_INPUT)


class _JsonLogFormatter(logging.Formatter):
    """Optional structured-log formatter (--log-json)."""

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


def _build_tradebook_parser(subparsers):
    parser = subparsers.add_parser(
        "tradebook",
        description=(
            "Generate SmartGrid trade playbook PNG(s) from an arbitrary --sql query "
            "against a DuckDB database."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db", type=str, default=None, help="Path to DuckDB database file (or set TRADEBOOK_DB env var)"
    )

    sql_group = parser.add_mutually_exclusive_group(required=True)
    sql_group.add_argument(
        "--sql", type=str, default=None, help="Trade-selection SQL query"
    )
    sql_group.add_argument(
        "--sql-file", type=str, default=None, help="Path to a file containing the trade-selection SQL query"
    )
    parser.add_argument(
        "--sql-params", type=str, default=None, help="JSON array of values bound to `?` placeholders in --sql"
    )

    _ident_constraint = {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"}

    a = parser.add_argument(
        "--ohlcv-table", type=str, required=True, help="Table/view name containing OHLCV candle data"
    )
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
    a = parser.add_argument(
        "--ohlcv-volume-col",
        type=str,
        default="volume",
        help="Set to '' to indicate no volume column is available",
    )
    a.constraint = {
        "type": "string",
        "pattern": "^($|[A-Za-z_][A-Za-z0-9_]*$)",
        "note": "empty string explicitly means 'no volume column'",
    }

    a = parser.add_argument(
        "--pad",
        "-p",
        type=int,
        default=15,
        help="Context candles before entry / after exit (default: 15, must be >= 0)",
    )
    a.constraint = {"type": "integer", "minimum": 0}

    a = parser.add_argument(
        "--exit-lookahead",
        type=int,
        default=288,
        help="Max candles scanned forward for SL/TP hits (default: 288, must be >= 1)",
    )
    a.constraint = {"type": "integer", "minimum": 1}

    parser.add_argument(
        "--hline-cols",
        type=str,
        default=None,
        help="Comma-separated extra --sql columns to draw as reference lines",
    )

    a = parser.add_argument(
        "--row-capacity",
        "-r",
        type=int,
        default=350,
        help="Target candle capacity per row (default: 350, must be > 0)",
    )
    a.constraint = {"type": "integer", "exclusiveMinimum": 0}

    a = parser.add_argument(
        "--max-charts",
        "--limit",
        "-m",
        "-l",
        type=int,
        default=18,
        help="Max charts per canvas page / limit per page (default: 18, must be >= 1)",
    )
    a.constraint = {"type": "integer", "minimum": 1}

    a = parser.add_argument(
        "--strategy",
        type=str,
        choices=["optimal", "wordwrap", "bestfit"],
        default="optimal",
        help="SmartGrid packing strategy (default: optimal)",
    )
    a.constraint = {"type": "string", "enum": ["optimal", "wordwrap", "bestfit"]}

    parser.add_argument(
        "--run-name",
        type=str,
        default="tradebook",
        help="Label used in chart titles and default output filename",
    )
    parser.add_argument("--output", type=str, default=None, help="Output PNG path")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./outs",
        help="Directory for default output path when --output is omitted",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate inputs/SQL without rendering PNGs"
    )
    parser.add_argument("--json", action="store_true", help="Emit single-line JSON result envelope on stdout")
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
        args.ohlcv_time_col,
        args.ohlcv_open_col,
        args.ohlcv_high_col,
        args.ohlcv_low_col,
        args.ohlcv_close_col,
        args.ohlcv_volume_col or None,
    )
    _validate_identifier(args.ohlcv_table, "--ohlcv-table")

    hline_cols = [c for c in (args.hline_cols.split(",") if args.hline_cols else [])]

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
        db_path=db_path,
        sql=sql,
        sql_params=sql_params,
        ohlcv_table=args.ohlcv_table,
        ohlcv_cols=ohlcv_cols,
        output_file=out_png,
        pad_candles=args.pad,
        exit_lookahead=args.exit_lookahead,
        hline_cols=hline_cols,
        row_capacity=args.row_capacity,
        strategy=args.strategy,
        max_charts=args.max_charts,
        run_name=args.run_name,
        dry_run=args.dry_run,
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


def _parse_candles_arg(raw_args: list[str]) -> list[int]:
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
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _cfg_defaults = LayoutConfig()

    a = parser.add_argument(
        "--candles", "--candels", "-c", nargs="+", help="Candle counts for charts e.g. 200 150 350 25"
    )
    a.constraint = {"type": "array", "items": {"type": "integer", "minimum": 1}, "minItems": 1}

    a = parser.add_argument(
        "--row-capacity",
        "-r",
        type=int,
        default=_cfg_defaults.row_capacity_candles,
        help=f"Row capacity in candles (default: {_cfg_defaults.row_capacity_candles})",
    )
    a.constraint = {"type": "integer", "exclusiveMinimum": 0}

    a = parser.add_argument(
        "--px-per-candle",
        type=float,
        default=_cfg_defaults.px_per_candle,
        help=f"Fixed zoom level in px/candle (default: {_cfg_defaults.px_per_candle})",
    )
    a.constraint = {"type": "number", "exclusiveMinimum": 0}

    a = parser.add_argument(
        "--gap",
        type=int,
        default=_cfg_defaults.gap_candles,
        help=f"Gap between charts in candles (default: {_cfg_defaults.gap_candles})",
    )
    a.constraint = {"type": "integer", "minimum": 0}

    a = parser.add_argument(
        "--max-charts",
        type=int,
        default=_cfg_defaults.max_charts_per_canvas,
        help=f"Max charts per canvas (default: {_cfg_defaults.max_charts_per_canvas})",
    )
    a.constraint = {"type": "integer", "minimum": 1}

    a = parser.add_argument(
        "--max-extension",
        type=float,
        default=_cfg_defaults.max_extension_ratio,
        help=f"Max extension ratio (default: {_cfg_defaults.max_extension_ratio})",
    )
    a.constraint = {"type": "number", "minimum": 1.0}

    a = parser.add_argument(
        "--min-candles",
        type=int,
        default=_cfg_defaults.min_candles,
        help=f"Min candles floor per chart (default: {_cfg_defaults.min_candles})",
    )
    a.constraint = {"type": "integer", "minimum": 0}

    a = parser.add_argument(
        "--strategy",
        type=str,
        choices=["optimal", "wordwrap", "bestfit"],
        default=_cfg_defaults.packing_strategy,
        help=f"Packing strategy (default: {_cfg_defaults.packing_strategy})",
    )
    a.constraint = {"type": "string", "enum": ["optimal", "wordwrap", "bestfit"]}
    parser.add_argument("--dry-run", action="store_true", help="Compute layout without writing output file")
    parser.add_argument("--output", type=str, default="./outs/layout_output.json", help="Output JSON path")
    parser.add_argument(
        "--json", action="store_true", help="Emit compact JSON result envelope on stdout"
    )
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


def _build_describe_parser(subparsers):
    parser = subparsers.add_parser(
        "describe",
        description="Emit a machine-readable JSON description of this tool's contract.",
    )
    parser.add_argument(
        "--pretty", action="store_true", help="Pretty-print with indentation (default: compact)"
    )
    return parser


def _describe_subparser(sub_action, name: str) -> dict | None:
    parser = sub_action.choices.get(name)
    if parser is None:
        return None
    info = {"description": parser.description, "flags": []}
    try:
        for a in parser._actions:
            if not a.option_strings or a.dest == "help":
                continue
            default = a.default
            if not isinstance(default, (str, int, float, bool, type(None))):
                default = str(default)
            info["flags"].append(
                {
                    "flags": a.option_strings,
                    "dest": a.dest,
                    "help": a.help,
                    "required": bool(getattr(a, "required", False)),
                    "default": default,
                    "choices": list(a.choices) if a.choices else None,
                    "constraint": getattr(a, "constraint", None),
                }
            )
    except AttributeError:
        info["flags"] = None
    return info


def _run_describe(args) -> int:
    top_parser = build_parser()
    sub_action = next(
        (a for a in top_parser._actions if isinstance(a, argparse._SubParsersAction)),
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
            "reference_lines": "any other --sql column can be drawn as a horizontal reference line via --hline-cols",
        },
        "global_flags": {
            "--debug": "print a full traceback to stderr on unexpected errors",
            "--log-json": "emit stderr log lines as JSON instead of plain text",
        },
    }
    text = json.dumps(payload, indent=2 if args.pretty else None)
    print(text)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = _JsonAwareArgumentParser(
        prog="tradebook_tool",
        description="Trade Book + Smart Grid — combined CLI, designed for both human and agent use.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--debug", action="store_true", help="Print a full traceback to stderr on unexpected errors"
    )
    parser.add_argument(
        "--log-json", action="store_true", help="Emit stderr progress/log lines as JSON"
    )
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
            return EXIT_BAD_INPUT
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
