"""CLI entry point for loss_profile package."""

import argparse
import sys
from .db import get_duckdb_path
from .reporters import (
    generate_distribution,
    generate_distribution_table,
    generate_duration_table,
    generate_head_table,
    generate_loss_group_table,
    generate_loss_profile,
    generate_monthly_table,
    generate_projected_rr_table,
    generate_weekly_table,
)


def main():
    parser = argparse.ArgumentParser(description="Strategy Loss Profiler, Monthly, Weekly & Duration Performance Reporter")
    parser.add_argument("--db", type=str, default=None, help="Explicit path to DuckDB database file")
    parser.add_argument("--primary", action="store_true", help="Use primary database defined in Shared/cnf.yaml")
    parser.add_argument("--secondary", "--secoundary", action="store_true", help="Use secondary database defined in Shared/cnf.yaml")
    parser.add_argument("--view", type=str, default=None, required=True, help="Source view/table name (Required)")
    parser.add_argument("--monthly", "--month", "--mnth", nargs="?", const="all", type=str, default=None, help="Display monthly performance breakdown (Deprecated: use --dist monthly)")
    parser.add_argument("--weekly", "--wk", action="store_true", help="Display weekly performance breakdown table (Deprecated: use --dist weekly)")
    parser.add_argument("--duration-group", "--dur-group", action="store_true", help="Display duration bracket performance breakdown table (Deprecated: use --dist duration)")
    parser.add_argument("--duration-till", type=int, default=None, help="Limit duration table output up to specified candle duration (e.g. 5)")
    parser.add_argument("--loss-group", "--loss-grp", action="store_true", help="Display loss amount bracket performance breakdown table (Deprecated: use --dist loss)")
    parser.add_argument("--projected-rr", "--projected_rr", "-prr", action="store_true", help="Display projected R:R bracket performance breakdown table (Deprecated: use --dist prr)")
    parser.add_argument("--distribution", "--dist", nargs="?", const="entry_1", type=str, default=None, help="Display performance distribution for specified axis (e.g. entry_1, prr, duration, loss, monthly, weekly)")
    parser.add_argument("--head", "--trades", nargs="?", const=10, type=int, default=None, help="Display matching trade rows head (default limit: 10)")
    parser.add_argument("--duration", "--dur", type=int, default=None, help="Exact candle duration filter (e.g. 1)")
    parser.add_argument("--pattern-filter", "--filter", type=str, default=None, help="Filter trades by pattern expression (e.g. entry_1=DR-DR-DR)")
    parser.add_argument("--losses-only", action="store_true", help="Filter breakdown to show losses only (pnl <= 0)")
    parser.add_argument("--wins-only", action="store_true", help="Filter breakdown to show wins only (pnl > 0)")
    parser.add_argument("--min-trades", type=int, default=None, help="Hide distribution rows with fewer than N trades")
    parser.add_argument("--sort", choices=["win%", "trades", "pnl"], default=None, help="Sort distribution table by specified column")
    parser.add_argument("--top", type=int, default=None, help="Show top N distribution rows after sorting")
    parser.add_argument("--bottom", type=int, default=None, help="Show bottom N distribution rows after sorting")
    parser.add_argument("--compare", type=str, default=None, help="Cross-axis side-by-side pivot comparison axis (e.g. --dist prr --compare entry_1)")
    parser.add_argument("--loss", nargs="?", const=12, type=int, default=None, help="Show head of losing trades table & render Trade Playbook (default limit: 12)")
    parser.add_argument("--output", "--fmt", "-o", choices=["text", "markdown", "md"], default="text", help="Output format: 'text' (default) or 'markdown'/'md'")
    parser.add_argument("--dump", nargs="?", const="default", type=str, default=None, help="Dump stdio tables into a text file in Shared/OUTs/ (default: Shared/OUTs/loss_profile_<view>_<axis>.txt)")

    args = parser.parse_args()

    # 1. Validate explicit database specification
    has_db_flag = bool(args.primary or args.secondary or args.db)
    if not has_db_flag:
        parser.error("Database location must be explicitly specified via --primary, --secondary (or --secoundary), or --db <path>.")

    if args.primary and args.secondary:
        parser.error("Cannot specify both --primary and --secondary simultaneously.")

    # 2. Validate view specification
    if not args.view:
        parser.error("A view/table name must be explicitly specified via --view <view_name>.")

    target = "secondary" if args.secondary else "primary"
    db_path = get_duckdb_path(target=target, custom_path=args.db)

    # 3. Validate that the specified view exists in the database
    import duckdb
    try:
        check_con = duckdb.connect(db_path, read_only=True)
        available_views = [r[0] for r in check_con.execute("SHOW TABLES").fetchall()]
        check_con.close()
        if args.view not in available_views:
            avail_str = ", ".join(sorted(available_views)) if available_views else "none"
            parser.error(f"View/table '{args.view}' does not exist in database '{db_path}'. Available: {avail_str}")
    except Exception as exc:
        if "does not exist in database" in str(exc):
            raise
        pass

    # Normalize distribution and dump inputs (stripping curly braces if passed like {entry_1,entry_2})
    if args.distribution:
        args.distribution = args.distribution.strip("{} \t\r\n")
    if args.dump:
        args.dump = args.dump.strip("{} \t\r\n")

    # If --dump was passed with 'all' or comma-separated axes:
    if args.dump and args.dump != "default":
        dump_val = args.dump.strip()
        if dump_val.lower() == "all":
            if args.distribution is None:
                args.distribution = "all"
        elif not any(dump_val.lower().endswith(ext) for ext in [".txt", ".md", ".json", ".csv", ".log"]):
            # User passed an axis or list of axes to --dump (e.g. --dump entry_1,entry_2)
            if args.distribution is None:
                args.distribution = dump_val

    output_fmt = "markdown" if args.output in ["markdown", "md"] else "text"

    tee = None
    orig_stdout = sys.stdout
    if args.dump:
        from .reporters import TeeStream
        tee = TeeStream(orig_stdout)
        sys.stdout = tee

    try:
        if args.head is not None:
            generate_head_table(
                db_path,
                view_name=args.view,
                limit=args.head,
                pattern_filter=args.pattern_filter,
                duration=args.duration,
                duration_till=args.duration_till,
                losses_only=args.losses_only,
                output_fmt=output_fmt,
            )
        elif args.distribution is not None:
            raw_axis = args.distribution.strip()
            if "," in raw_axis:
                axis_list = [a.strip() for a in raw_axis.split(",") if a.strip()]
                for ax in axis_list:
                    generate_distribution(
                        db_path,
                        axis=ax,
                        view_name=args.view,
                        losses_only=args.losses_only,
                        wins_only=args.wins_only,
                        pattern_filter=args.pattern_filter,
                        duration_till=args.duration_till,
                        min_trades=args.min_trades,
                        sort=args.sort,
                        top=args.top,
                        bottom=args.bottom,
                        compare=args.compare,
                        output_fmt=output_fmt,
                    )
            else:
                generate_distribution(
                    db_path,
                    axis=raw_axis,
                    view_name=args.view,
                    losses_only=args.losses_only,
                    wins_only=args.wins_only,
                    pattern_filter=args.pattern_filter,
                    duration_till=args.duration_till,
                    min_trades=args.min_trades,
                    sort=args.sort,
                    top=args.top,
                    bottom=args.bottom,
                    compare=args.compare,
                    output_fmt=output_fmt,
                )
        elif args.projected_rr:
            generate_distribution(
                db_path,
                axis="prr",
                view_name=args.view,
                losses_only=args.losses_only,
                pattern_filter=args.pattern_filter,
                output_fmt=output_fmt,
            )
        elif args.loss_group:
            generate_distribution(
                db_path,
                axis="loss",
                view_name=args.view,
                pattern_filter=args.pattern_filter,
                output_fmt=output_fmt,
            )
        elif args.duration_group or args.duration_till is not None or args.duration is not None:
            generate_distribution(
                db_path,
                axis="duration",
                view_name=args.view,
                duration_till=args.duration_till,
                losses_only=args.losses_only,
                pattern_filter=args.pattern_filter,
                output_fmt=output_fmt,
            )
        elif args.weekly:
            generate_weekly_table(db_path, view_name=args.view, output_fmt=output_fmt)
        elif args.monthly is not None or args.loss is not None:
            generate_monthly_table(db_path, view_name=args.view, month_filter=args.monthly, show_loss_head=args.loss, output_fmt=output_fmt)
        else:
            generate_loss_profile(db_path, view_name=args.view)
    finally:
        if args.dump and tee is not None:
            sys.stdout = orig_stdout
            from .reporters import save_dump_file
            from rich.console import Console

            dump_val = args.dump.strip()
            if dump_val.lower() == "all":
                axis_name = "all"
                custom_file = None
            elif any(dump_val.lower().endswith(ext) for ext in [".txt", ".md", ".json", ".csv", ".log"]):
                axis_name = "dump"
                custom_file = dump_val
            elif dump_val != "default":
                axis_name = dump_val.replace(",", "_").replace(" ", "")
                custom_file = None
            else:
                axis_name = (
                    (args.distribution.replace(",", "_").replace(" ", "") if args.distribution else None)
                    or ("monthly" if args.monthly is not None else None)
                    or ("weekly" if args.weekly else None)
                    or ("duration" if (args.duration_group or args.duration_till is not None or args.duration is not None) else None)
                    or ("prr" if args.projected_rr else None)
                    or ("loss" if args.loss_group else None)
                    or ("head" if args.head is not None else None)
                    or "profile"
                )
                custom_file = None

            clean_text = tee.get_clean_text()
            dump_path = save_dump_file(
                content=clean_text,
                view_name=args.view,
                axis_name=axis_name,
                custom_name=custom_file,
                output_fmt=output_fmt,
            )
            Console().print(f"\n[bold green]✓ Dumped stdio tables to: {dump_path}[/bold green]\n")


if __name__ == "__main__":
    main()

