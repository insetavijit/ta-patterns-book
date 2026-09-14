#!/usr/bin/env python3
"""Post-Test DuckDB Database Enhancer.

Orchestrates post-backtest database enrichment after 1Ybt-v2.py execution:
1. Computes all 62 candlestick patterns from the 'ohlcv' table using pandas-ta-classic
   and persists the reference table 'candel_patters_{tf}' and view 'candel_patters_tf'.
2. Generates the comprehensive 'info' data dictionary table documenting all trade,
   excursion, and pattern columns (clmn_name, brif, calcuation, remars).
3. Validates database integrity and displays a rich summary of all tables and row counts.

Usage:
    uv run python post-tst-enhansments.py --target Shared/Data/classic_floor_mod-v5-1.duckdb
    uv run python Utils/post_tst_enhancements.py --target Shared/Data/classic_floor_mod-v5-1.duckdb
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Add repository root to Python path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_UTILS = _ROOT / "Utils"
if str(_UTILS) not in sys.path:
    sys.path.insert(0, str(_UTILS))

try:
    from Utils.candel_patterns import generate_patterns_for_db
    from Utils.strategy_info import pack_info_table
except ImportError:
    from candel_patterns import generate_patterns_for_db
    from strategy_info import pack_info_table

console = Console()


def detect_strategy_from_db(target_db: Path) -> str:
    """Detect strategy name from tables in DuckDB if possible."""
    try:
        con = duckdb.connect(str(target_db), read_only=True)
        tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        for t in tables:
            if "trade" in t.lower():
                # Check strategy_name column if exists
                cols = [c[0] for c in con.execute(f"DESCRIBE {t}").fetchall()]
                if "strategy_name" in cols:
                    strat = con.execute(f"SELECT strategy_name FROM {t} WHERE strategy_name IS NOT NULL LIMIT 1").fetchone()
                    if strat and strat[0]:
                        con.close()
                        return str(strat[0])
        con.close()
    except Exception:
        pass
    # Fallback to checking filename
    fname = target_db.stem.lower()
    if "v6" in fname:
        return "classic_floor_mod_v6"
    elif "v5" in fname:
        return "classic_floor_mod_v5"
    return "classic_floor_mod_v6"


def run_post_test_enhancements(
    target_db: str,
    strategy_name: str | None = None,
    ohlcv_table: str | None = None,
    timeframe: str | None = None,
    dry_run: bool = False,
) -> None:
    """Execute complete post-test database enrichment pipeline."""
    target_path = Path(target_db).resolve()
    if not target_path.exists():
        console.print(f"[bold red]Error: Target DuckDB database '{target_path}' does not exist.[/bold red]")
        sys.exit(1)

    start_time = time.perf_counter()

    console.print(Panel(
        f"[bold cyan]POST-TEST ENHANCEMENT PIPELINE[/bold cyan]\n"
        f"Database: [bold white]{target_path}[/bold white]",
        border_style="cyan"
    ))

    # Auto-detect strategy if not specified
    if not strategy_name:
        strategy_name = detect_strategy_from_db(target_path)
    console.print(f"Target Strategy: [bold green]{strategy_name}[/bold green]\n")

    # ------------------------------------------------------------------
    # Step 1: Candlestick Patterns Generation (candel_patters_tf)
    # ------------------------------------------------------------------
    console.print("[bold yellow]▶ Step 1: Generating Candlestick Patterns Reference...[/bold yellow]")
    try:
        patt_table = generate_patterns_for_db(
            target_db=str(target_path),
            ohlcv_table=ohlcv_table,
            timeframe=timeframe,
            dry_run=dry_run,
        )
        console.print(f"[green]✓ Completed candlestick patterns generation ('{patt_table}' and 'candel_patters_tf').[/green]\n")
    except Exception as e:
        console.print(f"[bold red]Failed to generate candlestick patterns: {e}[/bold red]")
        raise e

    # ------------------------------------------------------------------
    # Step 2: Strategy Information & Data Dictionary (info table)
    # ------------------------------------------------------------------
    console.print("[bold yellow]▶ Step 2: Packing Metadata & Column Dictionary into 'info'...[/bold yellow]")
    try:
        n_info = pack_info_table(
            target_db=str(target_path),
            strategy_name=strategy_name,
            table_name="info",
            dry_run=dry_run,
        )
        console.print(f"[green]✓ Completed metadata packing ({n_info} columns documented in 'info').[/green]\n")
    except Exception as e:
        console.print(f"[bold red]Failed to pack info table: {e}[/bold red]")
        raise e

    # ------------------------------------------------------------------
    # Step 3: Final Verification & Table Profiling
    # ------------------------------------------------------------------
    console.print("[bold yellow]▶ Step 3: Verifying Database Tables & Row Counts...[/bold yellow]")
    con = duckdb.connect(str(target_path), read_only=True)
    tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]

    summary_table = Table(
        title=f"Enriched Database Schema ({target_path.name})",
        box=None,
        show_header=True,
        header_style="bold cyan",
        show_edge=False,
        pad_edge=False,
    )
    summary_table.add_column("#", justify="right", style="dim", width=4)
    summary_table.add_column("Table / View Name", style="bold green", min_width=24)
    summary_table.add_column("Row Count", justify="right", style="bold yellow", min_width=12)
    summary_table.add_column("Columns", justify="right", style="cyan", min_width=10)
    summary_table.add_column("Purpose", style="dim white", min_width=30)

    for i, t in enumerate(tables, 1):
        try:
            cnt = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            col_cnt = len(con.execute(f"DESCRIBE {t}").fetchall())
        except Exception:
            cnt = -1
            col_cnt = -1

        purpose = "Unknown"
        if t == "ohlcv":
            purpose = "Raw / preprocessed candle bar history"
        elif "candel_patters" in t:
            purpose = "62-pattern TA reference table / view"
        elif t == "info":
            purpose = "Data dictionary & column specifications"
        elif "concurrent_false" in t:
            purpose = "Single active position trade simulations"
        elif "concurrent_true" in t:
            purpose = "Overlapping position trade simulations"
        elif "trade" in t:
            purpose = "Executed trade lifecycle records"

        summary_table.add_row(
            str(i),
            t,
            f"{cnt:,}" if cnt >= 0 else "—",
            str(col_cnt) if col_cnt >= 0 else "—",
            purpose,
        )

    con.close()
    console.print(summary_table)

    elapsed = time.perf_counter() - start_time
    console.print(f"\n[bold green]★ All post-test enhancements completed successfully in {elapsed:.2f}s![/bold green]\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Post-test DuckDB enhancer: enriches database with 'candel_patters_tf' and 'info' tables."
    )
    parser.add_argument(
        "--target",
        "-t",
        required=True,
        help="Path to the target DuckDB database (e.g. Shared/Data/classic_floor_mod-v5-1.duckdb)",
    )
    parser.add_argument(
        "--strategy",
        "-s",
        help="Strategy name (defaults to auto-detection from database)",
    )
    parser.add_argument(
        "--ohlcv-table",
        help="Source OHLCV table name (defaults to 'ohlcv')",
    )
    parser.add_argument(
        "--tf",
        "--timeframe",
        help="Candle resolution timeframe (e.g. '5m'). Auto-detected if omitted.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate run without writing modifications to DuckDB",
    )

    args = parser.parse_args()
    run_post_test_enhancements(
        target_db=args.target,
        strategy_name=args.strategy,
        ohlcv_table=args.ohlcv_table,
        timeframe=args.tf,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
