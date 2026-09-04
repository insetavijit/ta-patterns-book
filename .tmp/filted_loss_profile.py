#!/usr/bin/env python3
"""Filtered Loss Profile Script (.tmp/filted_loss_profile.py)

Supports analyzing performance using --v1 or --v2 filter definitions, and allows
filtering by `--filtered-true` (trades where filters matched) or `--filtered-false` (trades where filters did not match).

Usage Examples:
  uv run python .tmp/filted_loss_profile.py --v1 --filtered-false
  uv run python .tmp/filted_loss_profile.py --v2 --filtered-true
  uv run python .tmp/filted_loss_profile.py --v1 --filtered-true
  uv run python .tmp/filted_loss_profile.py --v2 --filtered-false
"""

import argparse
from pathlib import Path
import sys

import duckdb
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "Shared" / "Data" / "eur_usd_trades_5m.duckdb"

# Import duration table generator from loss_profile.py
sys.path.insert(0, str(BASE_DIR / "Notebooks"))
from loss_profile import generate_duration_table


def run_filtered_loss_profile(v1: bool, v2: bool, filtered_true: bool, filtered_false: bool, duration_till: int = None):
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at: {DB_PATH}")

    conn = duckdb.connect(str(DB_PATH), read_only=False)

    # Determine filter set version
    if v2:
        version_label = "v2 (Excludes Entry Candle)"
        f_3red = "3_red_candels_v2"
        f_rgr = "red_green_red_v2"
    else:
        version_label = "v1 (Includes Entry Candle)"
        f_3red = "3_red_candels"
        f_rgr = "red_green_red"

    # Determine filter condition
    if filtered_true:
        cond_label = f"FILTER MATCHED = TRUE ({f_3red} = True OR {f_rgr} = True)"
        where_clause = f'"{f_3red}" = True OR "{f_rgr}" = True'
    elif filtered_false:
        cond_label = f"FILTER CLEAN = FALSE ({f_3red} = False AND {f_rgr} = False)"
        where_clause = f'"{f_3red}" = False AND "{f_rgr}" = False'
    else:
        cond_label = "ALL TRADES (UNFILTERED)"
        where_clause = "1=1"

    temp_view_name = "tmp_filtered_loss_profile_view"

    # Create temporary view for duration group generator
    conn.execute(f"CREATE OR REPLACE VIEW {temp_view_name} AS SELECT * FROM filtered_trades WHERE {where_clause};")
    conn.close()

    print("\n" + "=" * 85)
    print(f" FILTERED LOSS PROFILE | Version: {version_label}")
    print(f" Condition: {cond_label}")
    print("=" * 85)

    generate_duration_table(str(DB_PATH), view_name=temp_view_name, duration_till=duration_till)

    # Cleanup temp view
    conn = duckdb.connect(str(DB_PATH), read_only=False)
    conn.execute(f"DROP VIEW IF EXISTS {temp_view_name};")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Filtered Loss Profile CLI tool.")
    
    # Version group
    version_group = parser.add_mutually_exclusive_group()
    version_group.add_argument("--v1", action="store_true", help="Use v1 filters (includes entry candle). Default.")
    version_group.add_argument("--v2", action="store_true", help="Use v2 filters (excludes entry candle).")

    # Filter state group
    state_group = parser.add_mutually_exclusive_group()
    state_group.add_argument("--filtered-true", action="store_true", help="Include trades matching either pattern filter (True).")
    state_group.add_argument("--filtered-false", action="store_true", help="Include clean trades excluding pattern filters (False).")

    parser.add_argument("--duration-till", type=int, default=None, help="Limit duration table output up to specified candle duration (e.g. 5)")

    args = parser.parse_args()

    run_filtered_loss_profile(
        v1=args.v1 or not args.v2,
        v2=args.v2,
        filtered_true=args.filtered_true,
        filtered_false=args.filtered_false,
        duration_till=args.duration_till
    )


if __name__ == "__main__":
    main()
