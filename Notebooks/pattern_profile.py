#!/usr/bin/env python3
"""pattern_profile.py: Profile setup patterns (entry_1) across:
1. entry_1 performance distribution
2. Candle duration distribution
3. Candlestick pattern classes (ecpatt_1..3 and epcpatt_1..3)
4. Dynamic segment grouping via --group (e.g. --group epcpatt)

Usage examples:
    uv run python Notebooks/pattern_profile.py --group epcpatt --primary
    uv run python Notebooks/pattern_profile.py --group epcpatt --pattern="DR-UG-UG" --primary
    uv run python Notebooks/pattern_profile.py --group ecpatt --primary
    uv run python Notebooks/pattern_profile.py --pattern="DR-UG-UG" --primary --dump
    uv run python Notebooks/pattern_profile.py --primary
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


def resolve_db_and_view(pattern: str = None, db_arg: str = None, primary: bool = False, secondary: bool = False, view_arg: str = None):
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
        view_name = view_arg or "classic_floor_mod_v4_trades"
        return db_path, view_name

    # Auto-detection: check primary first, then secondary
    primary_db = get_duckdb_path(target="primary")
    candidate_views = [view_arg] if view_arg else [
        "classic_floor_mod_v4_trades",
        "classic_floor_mod_v3e_trades",
        "classic_floor_mod_v3c_trades",
        "classic_floor_mod_v3b_trades",
        "classic_floor_mod_v3a_trades",
    ]
    
    con = get_db_connection(primary_db, read_only=True)
    for v in candidate_views:
        try:
            if pattern:
                cnt = con.execute(f'SELECT COUNT(*) FROM "{v}" WHERE entry_1 = ?;', [pattern]).fetchone()[0]
                if cnt > 0:
                    con.close()
                    return primary_db, v
            else:
                cnt = con.execute(f'SELECT COUNT(*) FROM "{v}";').fetchone()[0]
                if cnt > 0:
                    con.close()
                    return primary_db, v
        except Exception:
            continue
    con.close()

    # Fallback to secondary database (531 baseline trades)
    sec_db = get_duckdb_path(target="secondary")
    return sec_db, (view_arg or "trades")


CANDLESTICK_PATTERN_COLS = [
    ("ecpatt_1", "Entry Candle 1-Pattern (ecpatt_1)"),
    ("ecpatt_2", "Entry Candle 2-Pattern (ecpatt_2)"),
    ("ecpatt_3", "Entry Candle 3-Pattern (ecpatt_3)"),
    ("epcpatt_1", "Setup Pre-Entry 1-Pattern (epcpatt_1)"),
    ("epcpatt_2", "Setup Pre-Entry 2-Pattern (epcpatt_2)"),
    ("epcpatt_3", "Setup Pre-Entry 3-Pattern (epcpatt_3)"),
]


def main():
    parser = argparse.ArgumentParser(
        description="Profile setup patterns (entry_1) across duration and candlestick pattern classes, with segment grouping."
    )
    parser.add_argument(
        "--group", "-g",
        type=str,
        default="all",
        help="Target distribution group prefix (e.g. 'epcpatt', 'ecpatt', 'entry', 'duration', or 'all')",
    )
    parser.add_argument(
        "--pattern", "-p",
        type=str,
        default=None,
        help="Setup pattern to profile on entry_1 (e.g. DR-UG-UG, or omit for all entry_1 patterns)",
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
        help="Source view/table name (e.g. classic_floor_mod_v4_trades, trades)",
    )
    parser.add_argument(
        "--skip-candlestick-patterns",
        action="store_true",
        help="Skip the candlestick pattern breakdown tables in 'all' mode",
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
    pattern = args.pattern.strip().strip("'\"") if args.pattern else None
    if pattern and pattern.upper() in ["ALL", "*", "NONE"]:
        pattern = None

    group = args.group.strip().lower()

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
    filter_expr = f"entry_1 = '{pattern}'" if pattern else None

    group_suffix = f" (GROUP: {group})" if group != "all" else ""
    profile_title = f"PATTERN PROFILE: {pattern}{group_suffix}" if pattern else f"STRATEGY PATTERN PROFILE{group_suffix}"

    console.print(f"\n[bold cyan]═══ {profile_title} ═══[/bold cyan]")
    console.print(f"  • Database : [yellow]{db_path}[/yellow]")
    console.print(f"  • View     : [yellow]{view_name}[/yellow]\n")

    con = get_db_connection(db_path, read_only=True)
    cols_df = con.execute(f'SELECT * FROM "{view_name}" LIMIT 0;').df()
    cols = list(cols_df.columns)

    # Check trade count matching filter
    where_sql = f"WHERE {filter_expr}" if filter_expr else ""
    total_matching = con.execute(f'SELECT COUNT(*) FROM "{view_name}" {where_sql};').fetchone()[0]

    if total_matching == 0:
        filter_desc = f"pattern '{pattern}'" if pattern else "all trades"
        console.print(f"[red]No trades found for {filter_desc} in view '{view_name}'.[/red]")
        con.close()
        if tee:
            sys.stdout = orig_stdout
        return

    # Mode 1: Duration only
    if group == "duration":
        console.print(f"[bold cyan]─── HOLDING DURATION DISTRIBUTION ───[/bold cyan]")
        generate_duration_table(
            db_path=db_path,
            view_name=view_name,
            pattern_filter=filter_expr,
            output_fmt=args.output,
        )

    # Mode 2: Specific prefix group (e.g. 'epcpatt', 'ecpatt', 'entry', etc.)
    elif group != "all":
        # Match columns starting with "{group}_" or exactly equal to "{group}"
        matched_cols = [c for c in cols if c == group or c.startswith(f"{group}_")]
        # Sort naturally by index if ending in numbers
        matched_cols.sort(key=lambda x: [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', x)])

        if not matched_cols:
            console.print(f"[red]No columns found matching group prefix '{group}_' in view '{view_name}'.[/red]")
            avail = [c for c in cols if "_" in c]
            console.print(f"[yellow]Available prefixed columns: {', '.join(sorted(avail))}[/yellow]")
        else:
            console.print(f"[bold cyan]─── DISTRIBUTION TABLES FOR GROUP: '{group.upper()}' ({len(matched_cols)} COLUMNS) ───[/bold cyan]")
            for col_name in matched_cols:
                console.print(f"\n[bold green]► {col_name.upper()} DISTRIBUTION[/bold green]")
                generate_distribution_table(
                    db_path=db_path,
                    view_name=view_name,
                    pattern_col=col_name,
                    pattern_filter=filter_expr,
                    output_fmt=args.output,
                )

    # Mode 3: "all" mode (Section 1: entry_1, Section 2: duration, Section 3: 6 candlestick classes)
    else:
        # Section 1: entry_1 Performance Breakdown
        console.print(f"[bold cyan]─── SECTION 1: ENTRY_1 PERFORMANCE BREAKDOWN ───[/bold cyan]")
        generate_distribution_table(
            db_path=db_path,
            view_name=view_name,
            pattern_col="entry_1",
            pattern_filter=filter_expr,
            output_fmt=args.output,
        )

        # Section 2: Holding Duration Distribution
        console.print(f"\n[bold cyan]─── SECTION 2: HOLDING DURATION DISTRIBUTION ───[/bold cyan]")
        generate_duration_table(
            db_path=db_path,
            view_name=view_name,
            pattern_filter=filter_expr,
            output_fmt=args.output,
        )

        # Section 3: The 6 Candlestick Pattern Distribution Classes
        if not args.skip_candlestick_patterns:
            available_cdl_cols = [c for c in CANDLESTICK_PATTERN_COLS if c[0] in cols]
            if available_cdl_cols:
                console.print(f"\n[bold cyan]─── SECTION 3: CANDLESTICK PATTERN DISTRIBUTIONS ({len(available_cdl_cols)} CLASSES) ───[/bold cyan]")
                for col_name, col_desc in available_cdl_cols:
                    console.print(f"\n[bold green]► {col_desc.upper()}[/bold green]")
                    generate_distribution_table(
                        db_path=db_path,
                        view_name=view_name,
                        pattern_col=col_name,
                        pattern_filter=filter_expr,
                        output_fmt=args.output,
                    )

    con.close()

    # Handle Dump if requested
    if args.dump:
        sys.stdout = orig_stdout
        dump_fmt = get_default_dump_format()
        
        safe_v = view_name.replace('"', '')
        outs_dir = _REPO_ROOT / "Shared" / "OUTs"
        outs_dir.mkdir(parents=True, exist_ok=True)

        group_part = f"{group}_" if group != "all" else ""
        pattern_part = f"{pattern.replace('-', '_')}_" if pattern else ""

        dump_file = outs_dir / f"pattern_profile_{group_part}{pattern_part}{safe_v}.{dump_fmt}"

        clean_output = tee.get_clean_text()
        with open(dump_file, "w", encoding="utf-8") as f:
            f.write(clean_output)

        console.print(f"\n[bold green]✓ Dumped stdio tables to: {dump_file}[/bold green]\n")


if __name__ == "__main__":
    main()
