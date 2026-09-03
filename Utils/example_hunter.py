#!/usr/bin/env python3
"""Example Hunter CLI script with crisp, 100% opaque candlestick rendering.

Features:
- Solid, opaque candle bodies with zero wick leakage inside the body.
- Single-pattern mode: Displays 12 real market examples of 1 specified pattern.
- Multi-pattern mode: Displays 1 real market example for up to 12 DIFFERENT patterns in a single canvas.
- Custom market colors (Blue target candle, Ash context candles).

Usage:
    python Utils/example_hunter.py --pattern hammer
    python Utils/example_hunter.py --multi --family 1-candle
"""

import argparse
from pathlib import Path
import sys

import duckdb
import matplotlib

matplotlib.use("Agg")  # Headless rendering
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import ta_patterns as tap
import ta_patterns.chart_patterns as cp

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = BASE_DIR / "Shared" / "OUTs" / "ohlcv_5m.duckdb"
DEFAULT_OUT_DIR = BASE_DIR / "Shared" / "OUTs"
CATALOG_DB = BASE_DIR / "Shared" / "Data" / "memory.duckdb"


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

    if category == "chart_pattern" and "v" in varnames:
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


def load_ohlcv_data(db_path: Path):
    """Load OHLCV data from DuckDB database into pandas DataFrame."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at: {db_path}")

    conn = duckdb.connect(str(db_path))
    tables = [t[0] for t in conn.execute("SHOW TABLES;").fetchall()]
    table_name = (
        "ohlcv_5m" if "ohlcv_5m" in tables else (tables[0] if tables else None)
    )

    if not table_name:
        conn.close()
        raise ValueError(f"No tables found in database {db_path}")

    df = conn.execute(
        f"""
        SELECT open, high, low, close, volume, timestamp 
        FROM {table_name} 
        ORDER BY timestamp;
    """
    ).fetchdf()
    conn.close()

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df, table_name


def draw_candlestick_subsegment(
    ax, opens, highs, lows, closes, timestamps, target_idx, title
):
    """Draw crisp, 100% opaque candlestick plot with zero internal wick leakage."""
    n = len(closes)
    x = np.arange(n)

    ax.grid(False)

    for i in range(n):
        is_target = i == target_idx
        is_bullish = closes[i] >= opens[i]

        if is_target:
            color = "#1e88e5"  # Solid Bright Blue target candle body
            edge_color = "#1565c0"
            lw = 1.8
        else:
            if is_bullish:
                color = "#b0bec5"  # Solid Light Ash
                edge_color = "#78909c"
            else:
                color = "#37474f"  # Solid Dark Ash
                edge_color = "#263238"
            lw = 1.2

        body_bottom = min(opens[i], closes[i])
        body_top = max(opens[i], closes[i])
        body_height = max(abs(closes[i] - opens[i]), 0.00005)

        # 1. Draw top wick (body top -> high) and bottom wick (low -> body bottom)
        ax.plot(
            [x[i], x[i]],
            [body_top, highs[i]],
            color=edge_color,
            linewidth=lw,
            zorder=2,
        )
        ax.plot(
            [x[i], x[i]],
            [lows[i], body_bottom],
            color=edge_color,
            linewidth=lw,
            zorder=2,
        )

        # 2. Draw 100% opaque candle body (zorder=3) so no internal wicks are visible
        ax.bar(
            x[i],
            body_height,
            bottom=body_bottom,
            width=0.6,
            color=color,
            edgecolor=edge_color,
            linewidth=1.2 if is_target else 0.8,
            alpha=1.0,
            zorder=3,
        )

    ax.set_title(title, fontsize=9, fontweight="bold", color="#1a237e")
    ax.tick_params(axis="both", which="both", labelsize=7)
    ax.set_xlim(-0.8, n - 0.2)

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)


def fetch_patterns_by_family(family: str, direction: str = "BULLISH"):
    """Fetch pattern names from memory.duckdb pattern_catalog."""
    if not CATALOG_DB.exists():
        return []
    conn = duckdb.connect(str(CATALOG_DB))
    rows = conn.execute(
        """
        SELECT pattern_name 
        FROM pattern_catalog 
        WHERE family = ? AND direction_class = ?
        ORDER BY pattern_name;
    """,
        (family, direction),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def hunt_single_pattern(
    pattern_name: str,
    df,
    o,
    h,
    l,
    c,
    v,
    max_examples: int,
    context_bars: int,
    output_path: Path,
):
    """Scan and plot 12 examples of ONE single pattern."""
    fn, category = find_pattern_function(pattern_name)
    if fn is None:
        print(f"[-] Pattern '{pattern_name}' not found in library.")
        return

    signals = run_detector(fn, category, o, h, l, c, v)
    hit_indices = np.where(signals != 0)[0]
    valid_hits = [idx for idx in hit_indices if idx >= context_bars]
    total_found = len(valid_hits)

    print(
        f"[+] Found {total_found:,} occurrences of pattern '{pattern_name}'!"
    )
    if total_found == 0:
        return

    if total_found <= max_examples:
        selected_hits = valid_hits
    else:
        step = total_found / max_examples
        selected_hits = [
            valid_hits[int(i * step)] for i in range(max_examples)
        ]

    n_plots = len(selected_hits)
    cols = 4 if n_plots >= 4 else n_plots
    rows = int(np.ceil(n_plots / cols))

    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 3 * rows))
    axes = np.array(axes).flatten() if n_plots > 1 else [axes]

    for idx, hit_idx in enumerate(selected_hits):
        start_idx = hit_idx - context_bars
        end_idx = hit_idx + 1

        sub_o = o[start_idx:end_idx]
        sub_h = h[start_idx:end_idx]
        sub_l = l[start_idx:end_idx]
        sub_c = c[start_idx:end_idx]
        sub_ts = df["timestamp"].iloc[start_idx:end_idx].values

        target_ts_str = (
            df["timestamp"].iloc[hit_idx].strftime("%Y-%m-%d %H:%M")
        )
        sig_val = signals[hit_idx]
        dir_str = "Bullish (+1)" if sig_val > 0 else "Bearish (-1)"

        title = f"#{idx+1} {target_ts_str}\nClose: {sub_c[-1]:.5f} [{dir_str}]"
        draw_candlestick_subsegment(
            axes[idx],
            sub_o,
            sub_h,
            sub_l,
            sub_c,
            sub_ts,
            target_idx=context_bars,
            title=title,
        )

    for j in range(n_plots, len(axes)):
        axes[j].axis("off")

    plt.suptitle(
        f"Pattern Hunter — '{pattern_name}' in Real EUR/USD Data ({total_found:,} occurrences)",
        fontsize=14,
        fontweight="bold",
        y=0.99,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[+] Output canvas saved to: {output_path.resolve()}")


def hunt_multi_patterns(
    pattern_list: list, df, o, h, l, c, v, context_bars: int, output_path: Path
):
    """Scan and plot 1 real example for EACH of up to 12 DIFFERENT patterns."""
    found_examples = []

    for p_name in pattern_list:
        if len(found_examples) >= 12:
            break
        fn, category = find_pattern_function(p_name)
        if fn is None:
            continue

        signals = run_detector(fn, category, o, h, l, c, v)
        if signals is None:
            continue

        hit_indices = np.where(signals != 0)[0]
        valid_hits = [idx for idx in hit_indices if idx >= context_bars]

        if valid_hits:
            hit_idx = valid_hits[len(valid_hits) // 2]
            found_examples.append(
                {
                    "pattern_name": p_name,
                    "hit_idx": hit_idx,
                    "signal": signals[hit_idx],
                }
            )

    print(
        f"[+] Found real market occurrences for {len(found_examples)} distinct patterns!"
    )
    if not found_examples:
        print("[-] No occurrences found for the specified pattern list.")
        return

    n_plots = len(found_examples)
    cols = 4 if n_plots >= 4 else n_plots
    rows = int(np.ceil(n_plots / cols))

    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 3 * rows))
    axes = np.array(axes).flatten() if n_plots > 1 else [axes]

    for idx, item in enumerate(found_examples):
        p_name = item["pattern_name"]
        hit_idx = item["hit_idx"]

        start_idx = hit_idx - context_bars
        end_idx = hit_idx + 1

        sub_o = o[start_idx:end_idx]
        sub_h = h[start_idx:end_idx]
        sub_l = l[start_idx:end_idx]
        sub_c = c[start_idx:end_idx]
        sub_ts = df["timestamp"].iloc[start_idx:end_idx].values
        target_ts_str = (
            df["timestamp"].iloc[hit_idx].strftime("%Y-%m-%d %H:%M")
        )

        title = f"{idx+1}. {p_name}\n{target_ts_str} | {sub_c[-1]:.5f}"
        draw_candlestick_subsegment(
            axes[idx],
            sub_o,
            sub_h,
            sub_l,
            sub_c,
            sub_ts,
            target_idx=context_bars,
            title=title,
        )

    for j in range(n_plots, len(axes)):
        axes[j].axis("off")

    plt.suptitle(
        f"Pattern Hunter — 12 Distinct Real Market Patterns (EUR/USD 5m)",
        fontsize=14,
        fontweight="bold",
        y=0.99,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(
        f"[+] Output multi-pattern canvas saved to: {output_path.resolve()}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Hunt and plot real technical analysis patterns with opaque candle bodies."
    )
    parser.add_argument(
        "-p",
        "--pattern",
        type=str,
        default=None,
        help="Single pattern name to hunt 12 examples (e.g. hammer, engulfing_bullish)",
    )
    parser.add_argument(
        "--patterns",
        nargs="+",
        default=None,
        help="List of multiple distinct pattern names to hunt",
    )
    parser.add_argument(
        "--multi",
        action="store_true",
        help="Enable multi-pattern mode (1 occurrence for 12 different patterns)",
    )
    parser.add_argument(
        "-f",
        "--family",
        type=str,
        default="1-candle",
        help="Family tag to auto-select 12 patterns in multi mode (default: 1-candle)",
    )
    parser.add_argument(
        "-d",
        "--db",
        type=str,
        default=str(DEFAULT_DB),
        help="Path to DuckDB database (default: Shared/OUTs/ohlcv_5m.duckdb)",
    )
    parser.add_argument(
        "-n",
        "--max-examples",
        type=int,
        default=12,
        help="Maximum examples (default: 12)",
    )
    parser.add_argument(
        "-b",
        "--context-bars",
        type=int,
        default=14,
        help="Number of context bars before target pattern bar (default: 14)",
    )
    parser.add_argument(
        "-o",
        "--out",
        type=str,
        default=None,
        help="Output image path",
    )

    args = parser.parse_args()
    db_file = Path(args.db)

    df, table_name = load_ohlcv_data(db_file)
    print(f"[+] Loaded {len(df):,} bars from '{table_name}' in {db_file.name}")

    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    v = df["volume"].to_numpy() if "volume" in df.columns else None

    # Multi-pattern mode trigger
    if args.multi or args.patterns:
        if args.patterns:
            pattern_list = args.patterns
        else:
            pattern_list = fetch_patterns_by_family(args.family)

        out_file = (
            Path(args.out)
            if args.out
            else DEFAULT_OUT_DIR
            / f"pattern_hunter_opaque_{args.family.replace('+', 'plus')}.png"
        )
        hunt_multi_patterns(
            pattern_list, df, o, h, l, c, v, args.context_bars, out_file
        )

    else:
        pattern_name = args.pattern if args.pattern else "hammer"
        out_file = (
            Path(args.out)
            if args.out
            else DEFAULT_OUT_DIR / f"pattern_hunter_opaque_{pattern_name}.png"
        )
        hunt_single_pattern(
            pattern_name,
            df,
            o,
            h,
            l,
            c,
            v,
            args.max_examples,
            args.context_bars,
            out_file,
        )


if __name__ == "__main__":
    main()
