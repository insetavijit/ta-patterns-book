#!/usr/bin/env python3
"""patter_profile.py: Profile a 3-candle setup pattern (entry_1) by entry_2 and duration groups.

Usage examples:
    uv run python tmp/patter_profile.py --pattern="DR-DR-DR" --dump
    uv run python tmp/patter_profile.py --pattern="DR-UG-UG" --primary --view classic_floor_mod_v3c_trades --dump
    uv run python tmp/patter_profile.py --pattern="DR-DR-UG" --secondary --dump custom_dump.txt
"""

import argparse
import io
import os
import re
import sys
from pathlib import Path

# Add project root and Core to path
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "Core") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "Core"))

import duckdb
from rich.console import Console
from ta_patterns_book.loss_profile.db import get_duckdb_path, get_db_connection, load_config
from ta_patterns_book.loss_profile.reporters import (
    generate_distribution_table,
    generate_duration_table,
)
from ta_patterns_book.loss_profile.sql import (
    build_distribution_query,
)


class TeeStream:
    """Simultaneously writes to terminal stdout and an in-memory buffer."""
    def __init__(self, original_stream):
        self.original_stream = original_stream
        self.buffer = io.StringIO()

    def write(self, data):
        self.original_stream.write(data)
        self.buffer.write(data)

    def flush(self):
        self.original_stream.flush()

    def get_clean_text(self) -> str:
        """Return captured text with ANSI escape codes stripped."""
        raw = self.buffer.getvalue()
        return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", raw)


def get_default_dump_format() -> str:
    """Read default dump format from Shared/cnf.yaml (default: 'txt')."""
    config = load_config()
    return config.get("display", {}).get("default_dump", "txt")


def resolve_db_and_view(pattern: str, db_arg: str = None, primary: bool = False, secondary: bool = False, view_arg: str = None):
    """Intelligently resolve DuckDB database and trade view."""
    if db_arg:
        db_path = db_arg if Path(db_arg).is_absolute() else str(_REPO_ROOT / db_arg)
        view_name = view_arg or "trades"
        return db_path, view_name

    if secondary:
        db_path = get_duckdb_path(target="secondary")
        view_name = view_arg or "trades"
        return db_path, view_name

    if primary:
        db_path = get_duckdb_path(target="primary")
        view_name = view_arg or "classic_floor_mod_v3c_trades"
        return db_path, view_name

    # Auto-detection: check primary first, then secondary
    primary_db = get_duckdb_path(target="primary")
    candidate_views = [view_arg] if view_arg else ["classic_floor_mod_v3c_trades", "classic_floor_mod_v3b_trades", "classic_floor_mod_v3a_trades"]
    
    con = get_db_connection(primary_db, read_only=True)
    for v in candidate_views:
        try:
            cnt = con.execute(f'SELECT COUNT(*) FROM "{v}" WHERE entry_1 = ?;', [pattern]).fetchone()[0]
            if cnt > 0:
                con.close()
                return primary_db, v
        except Exception:
            continue
    con.close()

    # Fallback to secondary database (531 baseline trades)
    sec_db = get_duckdb_path(target="secondary")
    return sec_db, (view_arg or "trades")


def main():
    parser = argparse.ArgumentParser(
        description="Profile a 3-candle setup pattern (entry_1) by entry_2 and all duration groups."
    )
    parser.add_argument(
        "--pattern", "-p",
        type=str,
        default="DR-DR-DR",
        help="Setup pattern to profile (default: DR-DR-DR)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Explicit path to DuckDB database file",
    )
    parser.add_argument(
        "--primary",
        action="store_true",
        help="Use primary database (Shared/INPs/Ohlcv_2325Eurusd.duckdb)",
    )
    parser.add_argument(
        "--secondary",
        action="store_true",
        help="Use secondary baseline database (Shared/Data/eur_usd_trades_5m.duckdb)",
    )
    parser.add_argument(
        "--view", "-v",
        type=str,
        default=None,
        help="Source view/table name (e.g. trades, classic_floor_mod_v3c_trades)",
    )
    parser.add_argument(
        "--output", "-o",
        choices=["text", "markdown", "md"],
        default="text",
        help="Output format: 'text' (default) or 'markdown'",
    )
    parser.add_argument(
        "--dump",
        nargs="?",
        const="default",
        type=str,
        default=None,
        help="Dump stdio tables into a file (default format from cnf.yaml: 'txt')",
    )

    args = parser.parse_args()
    pattern = args.pattern.strip().strip("'\"")

    db_path, view_name = resolve_db_and_view(
        pattern=pattern,
        db_arg=args.db,
        primary=args.primary,
        secondary=args.secondary,
        view_arg=args.view,
    )

    # If --dump is active, tee stdout to memory buffer
    tee = None
    orig_stdout = sys.stdout
    if args.dump:
        tee = TeeStream(orig_stdout)
        sys.stdout = tee

    console = Console()
    console.print(f"\n[bold cyan]═══ PATTERN PROFILE: {pattern} ═══[/bold cyan]")
    console.print(f"  • Database : [yellow]{db_path}[/yellow]")
    console.print(f"  • View     : [yellow]{view_name}[/yellow]\n")

    # Step 1: entry_2 performance distribution for entry_1 = pattern
    con = get_db_connection(db_path, read_only=True)
    cols_df = con.execute(f'SELECT * FROM "{view_name}" LIMIT 0;').df()
    has_pattern_col = "entry_2" in cols_df.columns

    filter_expr = f"entry_1 = '{pattern}'"
    query = build_distribution_query(
        view_name=view_name,
        pattern_col="entry_2",
        pattern_filter=filter_expr,
        has_pattern_col=has_pattern_col,
    )
    df_dist = con.execute(query).df()

    if df_dist.empty:
        console.print(f"[red]No trades found for pattern '{pattern}' in view '{view_name}'.[/red]")
        con.close()
        if tee:
            sys.stdout = orig_stdout
        return

    # Print Step 1: entry_2 breakdown table
    generate_distribution_table(
        db_path=db_path,
        view_name=view_name,
        pattern_col="entry_2",
        pattern_filter=filter_expr,
        output_fmt=args.output,
    )

    # Step 2: Extract distinct entry_2 groups
    entry_2_groups = df_dist["pattern"].tolist()

    console.print(f"\n[bold magenta]─── DURATION BREAKDOWNS FOR ALL {len(entry_2_groups)} ENTRY_2 GROUPS ───[/bold magenta]")

    # Step 3: For each entry_2 group, display duration breakdown
    for e2 in entry_2_groups:
        nested_filter = f"entry_1 = '{pattern}' AND entry_2 = '{e2}'"
        generate_duration_table(
            db_path=db_path,
            view_name=view_name,
            pattern_filter=nested_filter,
            output_fmt=args.output,
        )

    con.close()

    # Handle Dump if requested
    if args.dump:
        sys.stdout = orig_stdout
        dump_fmt = get_default_dump_format()
        
        if args.dump == "default":
            safe_p = pattern.replace("-", "_")
            safe_v = view_name.replace('"', '')
            outs_dir = _REPO_ROOT / "Shared" / "OUTs"
            outs_dir.mkdir(parents=True, exist_ok=True)
            dump_file = outs_dir / f"pattern_profile_{safe_p}_{safe_v}.{dump_fmt}"
        else:
            custom_path = Path(args.dump)
            if not custom_path.suffix:
                custom_path = custom_path.with_suffix(f".{dump_fmt}")
            dump_file = custom_path if custom_path.is_absolute() else _REPO_ROOT / custom_path
            dump_file.parent.mkdir(parents=True, exist_ok=True)

        clean_output = tee.get_clean_text()
        with open(dump_file, "w", encoding="utf-8") as f:
            f.write(clean_output)

        console.print(f"\n[bold green]✓ Dumped stdio tables to: {dump_file}[/bold green]\n")


if __name__ == "__main__":
    main()
