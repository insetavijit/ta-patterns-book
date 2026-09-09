"""CLI for Post-Trade Excursion Analysis."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
from rich.console import Console
from rich.table import Table

from post_trade_analysis.constants import DEFAULT_HORIZONS
from post_trade_analysis.engine import run_post_trade_analysis


def print_summary_report(
    db_path: str,
    strategy_name: str,
    horizons: tuple[int, ...],
) -> None:
    """Render a borderless rich summary table of post-trade Fibonacci excursions."""
    console = Console()
    con = duckdb.connect(db_path, read_only=True)
    safe_strat = strategy_name.replace("-", "_").replace(".", "_")
    view_name = f"{safe_strat}_trades_pfib"

    console.print(f"\n[bold green]Post-Trade Excursion Summary for '{strategy_name}'[/bold green]")
    console.print(f"[dim]Database: {db_path} | View: {view_name}[/dim]\n")

    table = Table(
        box=None,
        show_header=True,
        header_style="bold cyan",
        pad_edge=False,
    )
    table.add_column("Horizon", justify="center")
    table.add_column("TP Trades", justify="right")
    table.add_column("P(>=1.272)", justify="right")
    table.add_column("P(>=1.618)", justify="right")
    table.add_column("P(>=2.000)", justify="right")
    table.add_column("SL Hit %", justify="right")
    table.add_column("BE Hit %", justify="right")
    table.add_column("Med Offset", justify="right")

    for h in sorted(horizons):
        query = f"""
            SELECT 
                COUNT(*) AS total_tp,
                COUNT(CASE WHEN pfib{h}_bsl >= 1.272 THEN 1 END) AS c_1272,
                COUNT(CASE WHEN pfib{h}_bsl >= 1.618 THEN 1 END) AS c_1618,
                COUNT(CASE WHEN pfib{h}_bsl >= 2.000 THEN 1 END) AS c_2000,
                COUNT(CASE WHEN pfib{h}_sl_hit THEN 1 END) AS c_sl,
                COUNT(CASE WHEN pfib{h}_be_hit THEN 1 END) AS c_be,
                MEDIAN(pfib{h}_candles) AS med_offset
            FROM "{view_name}"
            WHERE LOWER(exit_reason) = 'tp' 
              AND pfib{h}_window_complete = TRUE
              AND pfib{h}_gap_crossed = FALSE;
        """
        try:
            row = con.execute(query).fetchone()
            if row and row[0] > 0:
                tot, c1272, c1618, c2000, c_sl, c_be, med_off = row
                p1272 = (c1272 / tot) * 100.0
                p1618 = (c1618 / tot) * 100.0
                p2000 = (c2000 / tot) * 100.0
                psl = (c_sl / tot) * 100.0
                pbe = (c_be / tot) * 100.0
                med_str = f"{med_off:.1f}" if med_off is not None else "-"

                table.add_row(
                    f"{h} candles",
                    str(tot),
                    f"{p1272:.1f}%",
                    f"{p1618:.1f}%",
                    f"{p2000:.1f}%",
                    f"{psl:.1f}%",
                    f"{pbe:.1f}%",
                    med_str,
                )
        except Exception as err:
            table.add_row(f"{h} candles", "Error", str(err), "", "", "", "", "")

    con.close()
    console.print(table)
    console.print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-Horizon Post-Exit Fibonacci Excursion Analyzer"
    )
    parser.add_argument(
        "--db",
        default="Shared/INPs/Ohlcv_2325Eurusd.duckdb",
        help="Path to DuckDB database",
    )
    parser.add_argument(
        "--strategy",
        "-s",
        default="classic_floor_mod_v4c",
        help="Strategy name (default: classic_floor_mod_v4c)",
    )
    parser.add_argument(
        "--ohlcv-table",
        default=None,
        help="OHLCV table name (auto-detected if omitted)",
    )
    parser.add_argument(
        "--horizons",
        default="15,30,60",
        help="Comma-separated forward horizons in candles (default: '15,30,60')",
    )

    args = parser.parse_args()

    horizons_tuple = tuple(int(x.strip()) for x in args.horizons.split(",") if x.strip())
    if not horizons_tuple:
        horizons_tuple = DEFAULT_HORIZONS

    count = run_post_trade_analysis(
        db_path=args.db,
        strategy_name=args.strategy,
        ohlcv_table=args.ohlcv_table,
        horizons=horizons_tuple,
    )

    print(f"✓ Analyzed {count} trades for strategy '{args.strategy}' with horizons={horizons_tuple}")
    print_summary_report(args.db, args.strategy, horizons_tuple)


if __name__ == "__main__":
    main()
