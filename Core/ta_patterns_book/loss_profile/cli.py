"""CLI entry point for loss_profile package."""

import argparse
from .db import get_duckdb_path
from .reporters import (
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
    parser.add_argument("--db", type=str, default=None, help="Path to DuckDB database file")
    parser.add_argument("--view", type=str, default="trades", help="Source view/table (default: trades)")
    parser.add_argument("--monthly", "--month", "--mnth", nargs="?", const="all", type=str, default=None, help="Display monthly performance breakdown")
    parser.add_argument("--weekly", "--wk", action="store_true", help="Display weekly performance breakdown table")
    parser.add_argument("--duration-group", "--dur-group", action="store_true", help="Display duration bracket performance breakdown table")
    parser.add_argument("--duration-till", type=int, default=None, help="Limit duration table output up to specified candle duration (e.g. 5)")
    parser.add_argument("--loss-group", "--loss-grp", action="store_true", help="Display loss amount bracket performance breakdown table")
    parser.add_argument("--projected-rr", "--projected_rr", "-prr", action="store_true", help="Display projected R:R bracket performance breakdown table")
    parser.add_argument("--distribution", "--dist", nargs="?", const="entry_1", type=str, default=None, help="Display pattern performance distribution for specified column (default: entry_1)")
    parser.add_argument("--head", "--trades", nargs="?", const=10, type=int, default=None, help="Display matching trade rows head (default limit: 10)")
    parser.add_argument("--duration", "--dur", type=int, default=None, help="Exact candle duration filter (e.g. 1)")
    parser.add_argument("--pattern-filter", "--filter", type=str, default=None, help="Filter trades by pattern expression (e.g. entry_1=DR-DR-DR)")
    parser.add_argument("--losses-only", action="store_true", help="Filter breakdown to show losses only (pnl <= 0)")
    parser.add_argument("--loss", nargs="?", const=12, type=int, default=None, help="Show head of losing trades table & render Trade Playbook (default limit: 12)")
    parser.add_argument("--output", "--fmt", "-o", choices=["text", "markdown", "md"], default="text", help="Output format: 'text' (default) or 'markdown'/'md'")

    args = parser.parse_args()
    db_path = args.db if args.db else get_duckdb_path()
    output_fmt = "markdown" if args.output in ["markdown", "md"] else "text"

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
        generate_distribution_table(
            db_path,
            view_name=args.view,
            pattern_col=args.distribution,
            losses_only=args.losses_only,
            pattern_filter=args.pattern_filter,
            output_fmt=output_fmt,
        )
    elif args.projected_rr:
        generate_projected_rr_table(
            db_path,
            view_name=args.view,
            losses_only=args.losses_only,
            pattern_filter=args.pattern_filter,
            output_fmt=output_fmt,
        )
    elif args.loss_group:
        generate_loss_group_table(
            db_path,
            view_name=args.view,
            pattern_filter=args.pattern_filter,
            output_fmt=output_fmt,
        )
    elif args.duration_group or args.duration_till is not None or args.duration is not None:
        generate_duration_table(
            db_path,
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


if __name__ == "__main__":
    main()
