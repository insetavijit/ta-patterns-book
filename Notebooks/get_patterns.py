#!/usr/bin/env python3
"""Get Patterns Script for OHLCV Candle Ranges.

Scans a specified candle index/timestamp range against all 300 technical analysis
pattern detectors and outputs a table of detected patterns in that range.

Usage:
    uv run python Notebooks/get_patterns.py --start 100 --end 150
    uv run python Notebooks/get_patterns.py --trade-id 1 --context 10
    uv run python Notebooks/get_patterns.py --start "2025-01-02 08:00" --end "2025-01-02 10:00"
"""

import argparse
from pathlib import Path
import sys

import duckdb
import numpy as np
import pandas as pd
import ta_patterns as tap
import ta_patterns.chart_patterns as cp

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = BASE_DIR / "Shared" / "Data" / "eur_usd_trades_5m.duckdb"
CATALOG_DB = BASE_DIR / "Shared" / "Data" / "memory.duckdb"


def load_catalog_metadata():
    """Load metadata for patterns from memory.duckdb pattern_catalog."""
    if not CATALOG_DB.exists():
        return {}
    conn = duckdb.connect(str(CATALOG_DB), read_only=True)
    rows = conn.execute(
        """
        SELECT pattern_name, category, family, direction_class, is_volume_dependent
        FROM pattern_catalog;
    """
    ).fetchall()
    conn.close()

    return {
        r[0]: {
            "category": r[1],
            "family": r[2],
            "direction": r[3],
            "volume_dep": bool(r[4]),
        }
        for r in rows
    }


def find_pattern_function(pattern_name: str):
    """Find pattern detector function in tap (candlesticks) or cp (chart patterns)."""
    if hasattr(tap, pattern_name):
        return getattr(tap, pattern_name), "candlestick"
    elif hasattr(cp, pattern_name):
        return getattr(cp, pattern_name), "chart_pattern"
    else:
        return None, None


def run_detector(fn, category, o, h, l, c, v):
    """Execute pattern detector handling signature variations safely."""
    varnames = (
        fn.__code__.co_varnames[:5] if hasattr(fn, "__code__") else ()
    )

    if category == "chart_pattern" and "v" in varnames and v is not None:
        try:
            return fn(o, h, l, c, v=v)
        except Exception:
            pass

    try:
        return fn(o, h, l, c)
    except TypeError:
        try:
            return fn(o, c)
        except TypeError:
            return fn(c)


def scan_patterns_in_range(
    df, start_idx: int, end_idx: int, catalog_meta: dict
):
    """Slice subsegment (with 30 bars context) and scan pattern detectors fast."""
    sub_start = max(0, start_idx - 30)
    sub_end = min(len(df), end_idx + 1)
    sub_df = df.iloc[sub_start:sub_end].copy()

    o = sub_df["open"].to_numpy()
    h = sub_df["high"].to_numpy()
    l = sub_df["low"].to_numpy()
    c = sub_df["close"].to_numpy()
    v = sub_df["volume"].to_numpy() if "volume" in sub_df.columns else None

    results = []

    all_patterns = set(catalog_meta.keys())
    for name in getattr(tap, "PATTERNS", set()):
        all_patterns.add(name)
    for name in getattr(cp, "CHART_PATTERNS", set()):
        all_patterns.add(name)

    for p_name in sorted(all_patterns):
        fn, category = find_pattern_function(p_name)
        if fn is None:
            continue

        try:
            signals = run_detector(fn, category, o, h, l, c, v)
        except Exception:
            continue

        if signals is None:
            continue

        sub_hit_indices = np.where(signals != 0)[0]
        # Map sub_hit_indices back to global indices
        global_hits = [
            sub_start + sub_idx
            for sub_idx in sub_hit_indices
            if start_idx <= (sub_start + sub_idx) <= end_idx
        ]

        if global_hits:
            meta = catalog_meta.get(
                p_name,
                {
                    "category": category,
                    "family": "candlestick"
                    if category == "candlestick"
                    else "chart_pattern",
                    "direction": "UNKNOWN",
                },
            )

            hit_details = []
            for g_idx in global_hits:
                sub_i = g_idx - sub_start
                sig_val = signals[sub_i]
                ts_str = df["timestamp"].iloc[g_idx].strftime("%Y-%m-%d %H:%M")
                dir_label = "+1 (Bullish)" if sig_val > 0 else "-1 (Bearish)"
                hit_details.append(f"Bar {g_idx} [{ts_str}]: {dir_label}")

            results.append(
                {
                    "pattern_name": p_name,
                    "category": meta["category"],
                    "family": meta["family"],
                    "direction": meta["direction"],
                    "count": len(global_hits),
                    "hit_indices": global_hits,
                    "details": ", ".join(hit_details),
                }
            )

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Scan and report all pattern occurrences within a specific candle range."
    )
    parser.add_argument(
        "--db",
        type=str,
        default=str(DEFAULT_DB),
        help="Path to DuckDB database (default: Shared/Data/eur_usd_trades_5m.duckdb)",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Start bar index or timestamp (e.g. 100 or '2025-01-02 08:00')",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="End bar index or timestamp (e.g. 120 or '2025-01-02 10:00')",
    )
    parser.add_argument(
        "--trade-id",
        type=int,
        default=None,
        help="Scan candle range around a specific trade_id",
    )
    parser.add_argument(
        "--context",
        type=int,
        default=10,
        help="Context bars before/after trade entry when using --trade-id (default: 10)",
    )

    args = parser.parse_args()
    db_file = Path(args.db)

    if not db_file.exists():
        print(f"[-] Database not found at {db_file}")
        sys.exit(1)

    conn = duckdb.connect(str(db_file), read_only=True)

    # Load OHLCV table
    tables = [t[0] for t in conn.execute("SHOW TABLES;").fetchall()]
    ohlcv_table = (
        "ohlcv" if "ohlcv" in tables else ("ohlcv_5m" if "ohlcv_5m" in tables else tables[0])
    )

    df = conn.execute(
        f"SELECT open, high, low, close, volume, timestamp FROM {ohlcv_table} ORDER BY timestamp;"
    ).fetchdf()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    total_bars = len(df)

    start_idx = 0
    end_idx = total_bars - 1

    if args.trade_id is not None:
        trade_table = "trades" if "trades" in tables else "trade_duration_5m"
        t_df = conn.execute(
            f"SELECT entry_time FROM {trade_table} WHERE trade_id = {args.trade_id} LIMIT 1;"
        ).fetchdf()
        if not t_df.empty:
            entry_ts = pd.to_datetime(t_df.iloc[0]["entry_time"])
            if entry_ts.tzinfo is not None:
                entry_ts = entry_ts.tz_localize(None)
                df_ts = df["timestamp"].dt.tz_localize(None)
            else:
                df_ts = df["timestamp"]

            hit_indices = np.where(df_ts == entry_ts)[0]
            if len(hit_indices) > 0:
                e_idx = hit_indices[0]
                start_idx = max(0, e_idx - args.context)
                end_idx = min(total_bars - 1, e_idx + args.context)
                print(
                    f"[+] Trade #{args.trade_id} Entry at Bar {e_idx} ({df['timestamp'].iloc[e_idx]}). Scanning range: Bars {start_idx}..{end_idx}"
                )

    conn.close()

    # Parse numeric or timestamp --start / --end if provided
    if args.start is not None:
        try:
            start_idx = int(args.start)
        except ValueError:
            s_ts = pd.to_datetime(args.start)
            df_ts = df["timestamp"].dt.tz_localize(None) if s_ts.tzinfo is None and df["timestamp"].dt.tz is not None else df["timestamp"]
            diffs = (df_ts - (s_ts.tz_localize(None) if s_ts.tzinfo else s_ts)).abs()
            start_idx = diffs.idxmin()

    if args.end is not None:
        try:
            end_idx = int(args.end)
        except ValueError:
            e_ts = pd.to_datetime(args.end)
            df_ts = df["timestamp"].dt.tz_localize(None) if e_ts.tzinfo is None and df["timestamp"].dt.tz is not None else df["timestamp"]
            diffs = (df_ts - (e_ts.tz_localize(None) if e_ts.tzinfo else e_ts)).abs()
            end_idx = diffs.idxmin()

    print(
        f"[+] Scanning candle range: Bars {start_idx} to {end_idx} ({df['timestamp'].iloc[start_idx]} to {df['timestamp'].iloc[end_idx]}, Total {end_idx - start_idx + 1} candles)..."
    )

    catalog_meta = load_catalog_metadata()
    results = scan_patterns_in_range(df, start_idx, end_idx, catalog_meta)

    print(
        f"\n### 📊 Pattern Detection Report (Range: Bars {start_idx}..{end_idx})\n"
    )
    print(f"**Total Patterns Fired**: {len(results)}\n")

    if not results:
        print("No technical analysis patterns fired in this candle range.")
        return

    # Print clean Markdown Table
    print(
        "| # | Pattern Name | Category | Family | Direction | Count | Detailed Firings |"
    )
    print(
        "| :-: | :--- | :---: | :---: | :---: | :-: | :--- |"
    )

    for idx, r in enumerate(results):
        print(
            f"| {idx+1} | `{r['pattern_name']}` | {r['category']} | {r['family']} | {r['direction']} | **{r['count']}** | {r['details']} |"
        )


if __name__ == "__main__":
    main()
