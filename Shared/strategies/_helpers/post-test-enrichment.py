#!/usr/bin/env python3
"""Post-Test DuckDB Database Enrichment Pipeline.

Orchestrates post-backtest database enrichment across executed backtest databases:
1. Candlestick Pattern Engine:
   Computes all 62 candlestick patterns from the 'ohlcv' table using pandas-ta-classic
   and persists reference table 'candel_patters_{tf}' and canonical view 'candel_patters_tf'.
2. Metadata & Data Dictionary Engine:
   Generates and injects the comprehensive 'info' data dictionary table
   documenting all trade, excursion, pattern, and timestamp columns (clmn_name, brif, calcuation, remars).
   Supports classic_floor_mod_v6_1 (76 columns), classic_floor_mod_v6 (69 columns), and v5 schemas.
3. Database Integrity & Profiling:
   Validates schema integrity and displays a borderless Rich summary table
   of all tables, views, row counts, and column counts.

Usage:
    uv run python Shared/strategies/_helpers/post-test-enrichment.py --target Shared/OUTs/duckdb/classic_floor_mod_v6_1.duckdb
    uv run python Shared/strategies/_helpers/post-test-enrichment.py --dry-run
"""

from __future__ import annotations

import argparse
import glob
import sys
import time
from pathlib import Path
from typing import Any

import duckdb
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Resolve repository root: ta-patterns-book
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parents[2]  # Shared/strategies/_helpers -> parents[2] = ta-patterns-book
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_UTILS_DIR = _REPO_ROOT / "Utils"
if str(_UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(_UTILS_DIR))

try:
    from Utils.candel_patterns import generate_patterns_for_db
    from Utils.strategy_info import pack_info_table
except ImportError:
    from candel_patterns import generate_patterns_for_db
    from strategy_info import pack_info_table

console = Console()


def load_enrichment_scripts(repo_root: Path) -> list[str]:
    """Load worker scripts list from Shared/cnf.yaml."""
    cnf_file = repo_root / "Shared" / "cnf.yaml"
    if cnf_file.exists():
        try:
            with open(cnf_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            scripts = data.get("post_test_enrichment", {}).get("scripts", [])
            if isinstance(scripts, list) and scripts:
                return [str(s) for s in scripts]
        except Exception:
            pass
    return ["Shared/strategies/_helpers/candel_patterns.py"]


def resolve_default_target_db(repo_root: Path) -> Path | None:
    """Find the most sensible default target database from cnf.yaml or OUTs/duckdb."""
    cnf_file = repo_root / "Shared" / "cnf.yaml"
    outs_duckdb_dir = repo_root / "Shared" / "OUTs" / "duckdb"

    # 1. Check for newest generated .duckdb in Shared/OUTs/duckdb/
    if outs_duckdb_dir.exists():
        dbs = sorted(outs_duckdb_dir.glob("*.duckdb"), key=lambda p: p.stat().st_mtime, reverse=True)
        if dbs:
            return dbs[0]

    # 2. Check Shared/cnf.yaml backtest_db or active_db_path
    if cnf_file.exists():
        try:
            with open(cnf_file, "r", encoding="utf-8") as f:
                cdata = yaml.safe_load(f)
            backtest_db = cdata.get("paths", {}).get("shared", {}).get("data", {}).get("backtest_db")
            if backtest_db and (repo_root / backtest_db).exists():
                return repo_root / backtest_db
            active_db = cdata.get("paths", {}).get("shared", {}).get("strategies", {}).get("active_db_path")
            if active_db and (repo_root / active_db).exists():
                return repo_root / active_db
        except Exception:
            pass

    # 3. Fallback to Shared/Data/Ohlcv_2325Eurusd.duckdb
    fallback = repo_root / "Shared" / "Data" / "Ohlcv_2325Eurusd.duckdb"
    if fallback.exists():
        return fallback

    return None


def detect_strategy_from_db(target_db: Path) -> str:
    """Auto-detect strategy version from tables or column signatures in DuckDB."""
    try:
        con = duckdb.connect(str(target_db), read_only=True)
        tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        for t in tables:
            if "trade" in t.lower():
                cols = [c[0] for c in con.execute(f"DESCRIBE {t}").fetchall()]
                # Check for v6.1 specific signatures
                if "sl_mode" in cols or "primary_sl_hit_timestamp" in cols:
                    con.close()
                    return "classic_floor_mod_v6_1"
                # Check for strategy_name column value
                if "strategy_name" in cols:
                    strat = con.execute(f"SELECT strategy_name FROM {t} WHERE strategy_name IS NOT NULL LIMIT 1").fetchone()
                    if strat and strat[0]:
                        con.close()
                        return str(strat[0])
                # Check for v6 specific signatures
                if "pfib15_bsl" in cols or "safe_sl_hit" in cols:
                    con.close()
                    return "classic_floor_mod_v6"
        con.close()
    except Exception:
        pass

    # Fallback to checking filename
    fname = target_db.stem.lower()
    if "v6_1" in fname or "v6-1" in fname:
        return "classic_floor_mod_v6_1"
    elif "v6" in fname:
        return "classic_floor_mod_v6"
    elif "v5" in fname:
        return "classic_floor_mod_v5"
    return "classic_floor_mod_v6_1"


def run_post_test_enrichment(
    target_db: str | Path | None = None,
    strategy_name: str | None = None,
    ohlcv_table: str | None = None,
    timeframe: str | None = None,
    worker_scripts: list[str] | None = None,
    dry_run: bool = False,
    force: bool = False,
    with_info: bool = False,
) -> None:
    """Execute complete post-test database enrichment pipeline."""
    import subprocess
    start_time = time.perf_counter()

    # Resolve database path
    if target_db is None:
        resolved_path = resolve_default_target_db(_REPO_ROOT)
        if resolved_path is None:
            console.print("[bold red]Error: No target DuckDB specified and no default found.[/bold red]")
            sys.exit(1)
        target_path = resolved_path
    else:
        target_path = Path(target_db).resolve()

    if not target_path.exists():
        console.print(f"[bold red]Error: Target DuckDB database '{target_path}' does not exist.[/bold red]")
        sys.exit(1)

    # Strategy detection
    if not strategy_name:
        strategy_name = detect_strategy_from_db(target_path)

    # Worker scripts resolution
    if not worker_scripts:
        worker_scripts = load_enrichment_scripts(_REPO_ROOT)

    console.print(Panel(
        f"[bold cyan]POST-TEST DUCKDB ENRICHMENT PIPELINE[/bold cyan]\n"
        f"Database : [bold white]{target_path}[/bold white]\n"
        f"Strategy : [bold green]{strategy_name}[/bold green]\n"
        f"Workers  : [bold magenta]{', '.join(Path(s).name for s in worker_scripts)}[/bold magenta]\n"
        f"Dry Run  : [yellow]{dry_run}[/yellow]",
        border_style="cyan"
    ))

    # ------------------------------------------------------------------
    # Step 1: Execute Configured Worker Scripts (e.g. candel_patterns.py)
    # ------------------------------------------------------------------
    console.print(f"[bold yellow]▶ Step 1: Executing Registered Worker Scripts ({len(worker_scripts)} script(s))...[/bold yellow]")
    for s_idx, script_rel in enumerate(worker_scripts, 1):
        script_path = _REPO_ROOT / script_rel if not Path(script_rel).is_absolute() else Path(script_rel)
        if not script_path.exists():
            console.print(f"  [{s_idx}/{len(worker_scripts)}] [bold red]Worker script not found: {script_path}[/bold red]")
            continue

        console.print(f"  [{s_idx}/{len(worker_scripts)}] Running: [bold green]{script_path.name}[/bold green] ([dim]{script_rel}[/dim])")
        cmd = [
            sys.executable, str(script_path),
            "--target", str(target_path),
        ]
        if timeframe:
            cmd.extend(["--tf", str(timeframe)])
        if ohlcv_table:
            cmd.extend(["--ohlcv-table", str(ohlcv_table)])
        if dry_run:
            cmd.append("--dry-run")

        try:
            res = subprocess.run(cmd)
            if res.returncode != 0:
                console.print(f"  [bold red]Worker {script_path.name} exited with status code {res.returncode}[/bold red]\n")
            else:
                console.print(f"  [green]✓ Completed {script_path.name} successfully.[/green]\n")
        except Exception as err:
            console.print(f"  [bold red]Exception invoking {script_path.name}: {err}[/bold red]\n")

    # ------------------------------------------------------------------
    # Step 2: Strategy Information (Optional, user-provided by default)
    # ------------------------------------------------------------------
    if with_info:
        console.print("[bold yellow]▶ Step 2: Packing Metadata & Column Data Dictionary into 'info'...[/bold yellow]")
        try:
            n_info = pack_info_table(
                target_db=str(target_path),
                strategy_name=strategy_name,
                table_name="info",
                dry_run=dry_run,
            )
            console.print(f"[green]✓ Completed metadata packing ({n_info} columns documented in 'info').[/green]\n")
        except Exception as e:
            console.print(f"[bold red]Error during info table generation: {e}[/bold red]")
            raise e
    else:
        console.print("[dim]▶ Step 2: Skipped 'info' table packing (user-provided metadata mode).[/dim]\n")

    # ------------------------------------------------------------------
    # Step 3: Schema Verification & Table Profiling
    # ------------------------------------------------------------------
    console.print("[bold yellow]▶ Step 3: Verifying Database Integrity & Table Schema...[/bold yellow]")
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
    summary_table.add_column("Table / View Name", style="bold green", min_width=26)
    summary_table.add_column("Row Count", justify="right", style="bold yellow", min_width=12)
    summary_table.add_column("Columns", justify="right", style="cyan", min_width=10)
    summary_table.add_column("Purpose", style="dim white", min_width=32)

    for idx, tbl in enumerate(tables, 1):
        try:
            row_cnt = con.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
            col_cnt = len(con.execute(f"DESCRIBE {tbl}").fetchall())
        except Exception:
            row_cnt = -1
            col_cnt = -1

        purpose = "Database relation"
        if tbl == "ohlcv" or "ohlcv" in tbl:
            purpose = "Market OHLCV price history"
        elif "candel_patters" in tbl:
            purpose = "62-pattern TA reference table / view"
        elif tbl == "info":
            purpose = "Canonical data dictionary & column specifications"
        elif "portfolio_metrics" in tbl:
            purpose = "Overall portfolio summary & risk statistics"
        elif "monthly_performance" in tbl:
            purpose = "Month-by-month aggregated performance metrics"
        elif "equity_curve" in tbl:
            purpose = "Continuous bar-by-bar portfolio equity & drawdown series"
        elif "drawdown_events" in tbl:
            purpose = "Peak-to-trough drawdown and recovery cycles"
        elif "sl_risk_summary" in tbl:
            purpose = "Dynamic SL architecture risk distribution (v6.1)"
        elif "concurrent_false" in tbl:
            purpose = "Single active position trade simulations"
        elif "concurrent_true" in tbl:
            purpose = "Overlapping position trade simulations"
        elif "trade" in tbl:
            purpose = "Executed trade records & excursion telemetry"

        summary_table.add_row(
            str(idx),
            tbl,
            f"{row_cnt:,}" if row_cnt >= 0 else "—",
            str(col_cnt) if col_cnt >= 0 else "—",
            purpose,
        )

    con.close()
    console.print(summary_table)

    elapsed = time.perf_counter() - start_time
    console.print(f"\n[bold green]★ Post-test database enrichment pipeline finished in {elapsed:.2f}s![/bold green]\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Post-test DuckDB Database Enrichment Pipeline for VectorBT & Strategy Backtest Runs."
    )
    parser.add_argument(
        "--target",
        "-t",
        help="Path to the target DuckDB database file. If omitted, uses active backtest DB.",
    )
    parser.add_argument(
        "--strategy",
        "-s",
        help="Strategy name (defaults to auto-detection from database or cnf.yaml)",
    )
    parser.add_argument(
        "--ohlcv-table",
        help="Source OHLCV table name (defaults to 'ohlcv')",
    )
    parser.add_argument(
        "--tf",
        "--timeframe",
        help="Candle resolution timeframe (e.g. '5m', '1m'). Auto-detected if omitted.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate enrichment run without committing database mutations to disk",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force recomputation and overwrite of existing enrichment tables",
    )
    parser.add_argument(
        "--scripts",
        nargs="*",
        help="Worker script paths to execute (overrides cnf.yaml post_test_enrichment.scripts)",
    )
    parser.add_argument(
        "--with-info",
        action="store_true",
        help="Include automatic 'info' table generation (defaults to False; metadata is user-provided)",
    )

    args = parser.parse_args()
    run_post_test_enrichment(
        target_db=args.target,
        strategy_name=args.strategy,
        ohlcv_table=args.ohlcv_table,
        timeframe=args.tf,
        worker_scripts=args.scripts,
        dry_run=args.dry_run,
        force=args.force,
        with_info=args.with_info,
    )


if __name__ == "__main__":
    main()
