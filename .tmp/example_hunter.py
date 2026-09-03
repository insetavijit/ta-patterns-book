#!/usr/bin/env python3
"""Example Hunter CLI script with multi-page support for Chart Patterns and Candlesticks.

Supports:
- Category filtering ('candlestick', 'chart_pattern')
- Direction filtering ('BULLISH', 'BEARISH', 'BEARISH_NEUTRAL')
- Automatic pagination into subdirectories (e.g. Shared/OUTs/png/chart-patterns-bullish/page_N.png)
- 20 charts per page (4 rows x 5 cols)
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
import seaborn as sns
import ta_patterns as tap
import ta_patterns.chart_patterns as cp

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = BASE_DIR / "Shared" / "OUTs" / "ohlcv_5m.duckdb"
DEFAULT_OUT_DIR = BASE_DIR / "Shared" / "OUTs" / "png"
CATALOG_DB = BASE_DIR / "Shared" / "Data" / "memory.duckdb"


def get_pattern_candle_count(pattern_name: str, family: str = None) -> int:
    """Determine how many candles belong to the pattern."""
    if family == "1-candle":
        return 1
    elif family == "2-candle":
        return 2
    elif family == "3-candle":
        return 3
    elif family == "4+ candle":
        if pattern_name in [
            "rising_three_methods",
            "falling_three_methods",
            "mat_hold",
            "breakaway_bullish",
            "breakaway_bearish",
            "ladder_bottom",
        ]:
            return 5
        return 4

    # Default for chart patterns: highlight the last 5 key formation bars
    return 5


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
    ax, opens, highs, lows, closes, timestamps, target_indices, title
):
    """Draw candlestick subsegment highlighting pattern formation bars in Blue."""
    n = len(closes)
    x = np.arange(n)

    ax.grid(False)

    for i in range(n):
        is_target = i in target_indices
        is_bullish = closes[i] >= opens[i]

        if is_target:
            color = "#1e88e5"  # Solid Bright Blue pattern candle body
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

        # Top & bottom wicks
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

        # 100% opaque candle body
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

    ax.set_title(title, fontsize=8, fontweight="bold", color="#1a237e")
    ax.tick_params(axis="both", which="both", labelsize=6)
    ax.set_xlim(-0.8, n - 0.2)

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)


def fetch_patterns_from_catalog(category: str = "chart_pattern", direction: str = "BULLISH"):
    """Fetch pattern names from memory.duckdb pattern_catalog."""
    if not CATALOG_DB.exists():
        return []
    conn = duckdb.connect(str(CATALOG_DB))
    if direction == "BEARISH_NEUTRAL":
        rows = conn.execute(
            """
            SELECT pattern_name 
            FROM pattern_catalog 
            WHERE category = ? 
              AND direction_class IN ('BEARISH', 'NON_DIRECTIONAL')
            ORDER BY pattern_name;
        """,
            (category,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT pattern_name 
            FROM pattern_catalog 
            WHERE category = ? 
              AND direction_class = ?
            ORDER BY pattern_name;
        """,
            (category, direction),
        ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def render_paged_canvas(
    pattern_items: list,
    page_num: int,
    total_pages: int,
    category_title: str,
    df,
    o,
    h,
    l,
    c,
    prior_bars: int,
    post_bars: int,
    output_path: Path,
):
    """Render one 4x5 canvas page containing up to 20 chart pattern examples."""
    n_plots = len(pattern_items)
    cols = 5
    rows = 4

    sns.set_theme(style="white")
    fig, axes = plt.subplots(rows, cols, figsize=(18, 12))
    axes = np.array(axes).flatten()

    for idx, item in enumerate(pattern_items):
        p_name = item["pattern_name"]
        hit_idx = item["hit_idx"]
        c_count = item["candle_count"]

        start_idx = max(0, hit_idx - prior_bars - (c_count - 1))
        end_idx = min(len(df), hit_idx + post_bars + 1)

        sub_o = o[start_idx:end_idx]
        sub_h = h[start_idx:end_idx]
        sub_l = l[start_idx:end_idx]
        sub_c = c[start_idx:end_idx]
        sub_ts = df["timestamp"].iloc[start_idx:end_idx].values
        target_ts_str = df["timestamp"].iloc[hit_idx].strftime("%Y-%m-%d %H:%M")

        target_center_idx = hit_idx - start_idx
        target_indices = set(
            range(max(0, target_center_idx - (c_count - 1)), target_center_idx + 1)
        )

        title = f"{idx+1}. {p_name}\n{target_ts_str} | Close: {c[hit_idx]:.5f}"
        draw_candlestick_subsegment(
            axes[idx],
            sub_o,
            sub_h,
            sub_l,
            sub_c,
            sub_ts,
            target_indices=target_indices,
            title=title,
        )

    for j in range(n_plots, len(axes)):
        axes[j].axis("off")

    plt.suptitle(
        f"{category_title} — Page {page_num} of {total_pages} ({n_plots} Patterns, Real EUR/USD 5m)",
        fontsize=14,
        fontweight="bold",
        y=0.99,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[+] Saved canvas page to: {output_path.resolve()}")


def hunt_all_paged_patterns(
    pattern_list: list,
    category_title: str,
    output_dir: Path,
    file_prefix: str,
    df,
    o,
    h,
    l,
    c,
    v,
    prior_bars: int = 20,
    post_bars: int = 5,
    page_size: int = 20,
):
    """Scan real data for all patterns and output chunked 20-chart pages."""
    found_examples = []
    total_len = len(df)

    print(f"[+] Scanning market data for {len(pattern_list)} patterns...")

    for p_name in pattern_list:
        fn, category = find_pattern_function(p_name)
        if fn is None:
            continue

        c_count = get_pattern_candle_count(p_name)
        signals = run_detector(fn, category, o, h, l, c, v)
        if signals is None:
            continue

        hit_indices = np.where(signals != 0)[0]
        valid_hits = [
            idx
            for idx in hit_indices
            if idx >= (prior_bars + c_count - 1) and idx + post_bars < total_len
        ]

        if valid_hits:
            hit_idx = valid_hits[len(valid_hits) // 2]
            found_examples.append(
                {
                    "pattern_name": p_name,
                    "hit_idx": hit_idx,
                    "signal": signals[hit_idx],
                    "candle_count": c_count,
                }
            )

    total_found = len(found_examples)
    print(
        f"[+] Found real market occurrences for {total_found} of {len(pattern_list)} patterns!"
    )

    if not found_examples:
        print("[-] No occurrences found.")
        return

    total_pages = int(np.ceil(total_found / page_size))

    for p_idx in range(total_pages):
        start_idx = p_idx * page_size
        end_idx = min(total_found, (p_idx + 1) * page_size)
        page_items = found_examples[start_idx:end_idx]

        out_path = output_dir / f"{file_prefix}_page_{p_idx+1}.png"
        render_paged_canvas(
            page_items,
            p_idx + 1,
            total_pages,
            category_title,
            df,
            o,
            h,
            l,
            c,
            prior_bars,
            post_bars,
            out_path,
        )


def main():
    parser = argparse.ArgumentParser(
        description="Hunt and plot real technical analysis patterns with 20 charts per page."
    )
    parser.add_argument(
        "--category",
        type=str,
        default="chart_pattern",
        choices=["candlestick", "chart_pattern"],
        help="Category: candlestick or chart_pattern (default: chart_pattern)",
    )
    parser.add_argument(
        "--direction",
        type=str,
        default="BULLISH",
        help="Direction filter: BULLISH, BEARISH, or BEARISH_NEUTRAL (default: BULLISH)",
    )
    parser.add_argument(
        "-d",
        "--db",
        type=str,
        default=str(DEFAULT_DB),
        help="Path to DuckDB database (default: Shared/OUTs/ohlcv_5m.duckdb)",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="Target output subdirectory",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=20,
        help="Number of charts per canvas page (default: 20)",
    )
    parser.add_argument(
        "--prior-bars",
        type=int,
        default=20,
        help="Context bars before pattern (default: 20)",
    )
    parser.add_argument(
        "--post-bars",
        type=int,
        default=5,
        help="Outcome bars after pattern (default: 5)",
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

    # Determine subdirectory and title
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        folder_name = f"{args.category.replace('_', '-')}-{args.direction.lower()}"
        out_dir = DEFAULT_OUT_DIR / folder_name

    pattern_list = fetch_patterns_from_catalog(args.category, args.direction)
    category_title = f"{args.category.replace('_', ' ').title()} ({args.direction})"
    file_prefix = f"{args.direction.lower()}_{args.category}"

    hunt_all_paged_patterns(
        pattern_list,
        category_title,
        out_dir,
        file_prefix,
        df,
        o,
        h,
        l,
        c,
        v,
        args.prior_bars,
        args.post_bars,
        args.page_size,
    )


if __name__ == "__main__":
    main()
