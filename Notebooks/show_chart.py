#!/usr/bin/env python3
"""Show Trade Pattern Canvas Script (3 + 3 + 2 Grid = 8 Pattern Subplots).

Scans the 15-candle lookback prior to trade entry to detect all fired candlestick patterns,
and renders an 8-subplot canvas (arranged as 3 + 3 + 2 charts) highlighting the pattern
candles in Bright Blue, with Signal/Entry vertical lines and SL/TP price levels.

Usage:
    uv run python Notebooks/show_chart.py 1 jan_2025
"""

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
DB_PATH = BASE_DIR / "Shared" / "Data" / "eur_usd_trades_5m.duckdb"
CATALOG_DB = BASE_DIR / "Shared" / "Data" / "memory.duckdb"
OUT_DIR = BASE_DIR / "Shared" / "OUTs" / "png"
OUT_FILE = OUT_DIR / "trade_1_chart.png"


def load_catalog_metadata():
    """Load metadata for patterns from memory.duckdb pattern_catalog."""
    if not CATALOG_DB.exists():
        return {}
    conn = duckdb.connect(str(CATALOG_DB), read_only=True)
    rows = conn.execute(
        """
        SELECT pattern_name, category, family, direction_class
        FROM pattern_catalog;
    """
    ).fetchall()
    conn.close()

    return {
        r[0]: {"category": r[1], "family": r[2], "direction": r[3]}
        for r in rows
    }


def get_pattern_candle_count(pattern_name: str, family: str = None) -> int:
    """Determine how many candles belong to the pattern."""
    if family == "1-candle":
        return 1
    elif family == "2-candle":
        return 2
    elif family == "3-candle":
        return 3
    elif family == "4+ candle":
        return 4

    if CATALOG_DB.exists():
        conn = duckdb.connect(str(CATALOG_DB), read_only=True)
        res = conn.execute(
            "SELECT family FROM pattern_catalog WHERE pattern_name = ?",
            (pattern_name,),
        ).fetchone()
        conn.close()
        if res:
            fam = res[0]
            if fam == "1-candle":
                return 1
            elif fam == "2-candle":
                return 2
            elif fam == "3-candle":
                return 3
            elif fam == "4+ candle":
                return 4
    return 1


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


def detect_patterns_for_trade(
    df, entry_idx: int, lookback_bars: int = 15, max_patterns: int = 8
):
    """Detect candlestick patterns fired within the lookback window prior to trade entry."""
    start_idx = max(0, entry_idx - lookback_bars)
    end_idx = entry_idx

    sub_start = max(0, start_idx - 30)
    sub_end = min(len(df), end_idx + 5)
    sub_df = df.iloc[sub_start:sub_end].copy()

    o = sub_df["open"].to_numpy()
    h = sub_df["high"].to_numpy()
    l = sub_df["low"].to_numpy()
    c = sub_df["close"].to_numpy()
    v = sub_df["volume"].to_numpy() if "volume" in sub_df.columns else None

    catalog_meta = load_catalog_metadata()
    fired_patterns = []

    # Search candlestick patterns specifically
    candlestick_patterns = [
        name for name in getattr(tap, "PATTERNS", set())
    ]
    for p_name in sorted(candlestick_patterns):
        fn, category = find_pattern_function(p_name)
        if fn is None:
            continue

        try:
            signals = run_detector(fn, category, o, h, l, c, v)
        except Exception:
            continue

        if signals is None:
            continue

        sub_hits = np.where(signals != 0)[0]
        global_hits = [
            sub_start + sub_i
            for sub_i in sub_hits
            if start_idx <= (sub_start + sub_i) <= end_idx
        ]

        if global_hits:
            hit_global_idx = global_hits[-1]  # Most recent firing
            c_count = get_pattern_candle_count(
                p_name, catalog_meta.get(p_name, {}).get("family")
            )
            fired_patterns.append(
                {
                    "pattern_name": p_name,
                    "hit_idx": hit_global_idx,
                    "signal": signals[hit_global_idx - sub_start],
                    "candle_count": c_count,
                    "family": catalog_meta.get(p_name, {}).get(
                        "family", "candlestick"
                    ),
                    "direction": catalog_meta.get(p_name, {}).get(
                        "direction", "UNKNOWN"
                    ),
                }
            )

    # Sort and cap to max_patterns (8)
    fired_patterns.sort(key=lambda x: x["hit_idx"])
    if len(fired_patterns) > max_patterns:
        # Pick evenly spaced or most significant 8 patterns
        step = len(fired_patterns) / max_patterns
        fired_patterns = [
            fired_patterns[int(i * step)] for i in range(max_patterns)
        ]

    return fired_patterns


def load_trade_and_ohlcv(trade_id: int = 1, month_table: str = "jan_2025"):
    """Load Trade details and full OHLCV dataset."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at: {DB_PATH}")

    conn = duckdb.connect(str(DB_PATH), read_only=True)

    trade_df = conn.execute(
        """
        SELECT month_table, trade_id, entry_time, entry_price, sl_price, tp_price, exit_price, exit_reason, pnl, duration_candel, duration_mins
        FROM trades
        WHERE trade_id = ? AND month_table = ?
        LIMIT 1;
    """,
        (trade_id, month_table),
    ).fetchdf()

    if trade_df.empty:
        trade_df = conn.execute(
            """
            SELECT month_table, trade_id, entry_time, entry_price, sl_price, tp_price, exit_price, exit_reason, pnl, duration_candel, duration_mins
            FROM trades
            WHERE trade_id = ?
            LIMIT 1;
        """,
            (trade_id,),
        ).fetchdf()

    if trade_df.empty:
        conn.close()
        raise ValueError(f"Trade #{trade_id} not found in trades table.")

    trade = trade_df.iloc[0]
    entry_ts = pd.to_datetime(trade["entry_time"])

    ohlcv_df = conn.execute(
        """
        SELECT open, high, low, close, volume, timestamp
        FROM ohlcv
        ORDER BY timestamp;
    """
    ).fetchdf()

    conn.close()

    ohlcv_df["timestamp"] = pd.to_datetime(ohlcv_df["timestamp"])

    if entry_ts.tzinfo is not None:
        entry_ts_naive = entry_ts.tz_localize(None)
        ohlcv_df["timestamp_naive"] = ohlcv_df["timestamp"].dt.tz_localize(None)
        match_mask = ohlcv_df["timestamp_naive"] == entry_ts_naive
    else:
        match_mask = ohlcv_df["timestamp"] == entry_ts

    hit_indices = np.where(match_mask)[0]
    if len(hit_indices) == 0:
        diffs = (
            ohlcv_df[
                "timestamp_naive"
                if "timestamp_naive" in ohlcv_df
                else "timestamp"
            ]
            - (entry_ts_naive if entry_ts.tzinfo else entry_ts)
        ).abs()
        entry_idx = diffs.idxmin()
    else:
        entry_idx = hit_indices[0]

    return trade, ohlcv_df, entry_idx


def draw_subsegment(
    ax,
    sub_df,
    entry_sub_idx,
    pattern_indices,
    p_name,
    c_count,
    trade_meta,
):
    """Draw individual candlestick chart for one detected pattern with Blue pattern candle highlights."""
    opens = sub_df["open"].to_numpy()
    highs = sub_df["high"].to_numpy()
    lows = sub_df["low"].to_numpy()
    closes = sub_df["close"].to_numpy()
    timestamps = sub_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M").values

    n = len(closes)
    x = np.arange(n)
    signal_sub_idx = entry_sub_idx - 1

    ax.grid(False)

    for i in range(n):
        is_pattern_bar = i in pattern_indices
        is_bullish = closes[i] >= opens[i]

        if is_pattern_bar:
            color = "#1e88e5"  # Solid Bright Blue for pattern candles
            edge_color = "#1565c0"
            lw = 1.8
        else:
            if is_bullish:
                color = "#b0bec5"  # Light Ash
                edge_color = "#78909c"
            else:
                color = "#37474f"  # Dark Ash
                edge_color = "#263238"
            lw = 1.2

        body_bottom = min(opens[i], closes[i])
        body_top = max(opens[i], closes[i])
        body_height = max(abs(closes[i] - opens[i]), 0.00005)

        # Wicks
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
            linewidth=1.2 if is_pattern_bar else 0.8,
            alpha=1.0,
            zorder=3,
        )

    entry_price = float(trade_meta["entry_price"]) if not pd.isna(trade_meta["entry_price"]) else opens[entry_sub_idx]
    sl_price = float(trade_meta["sl_price"]) if not pd.isna(trade_meta["sl_price"]) else None
    tp_price = float(trade_meta["tp_price"]) if not pd.isna(trade_meta["tp_price"]) else None

    # Vertical Lines for Signal & Entry Candles
    if 0 <= signal_sub_idx < n:
        ax.axvline(x=signal_sub_idx, color="#7b1fa2", linestyle="--", linewidth=1.2, zorder=4)
    if 0 <= entry_sub_idx < n:
        ax.axvline(x=entry_sub_idx, color="#1565c0", linestyle="-", linewidth=1.5, zorder=4)

    # Horizontal Price Lines (Entry, SL, TP)
    ax.axhline(y=entry_price, color="#1565c0", linestyle=":", linewidth=1.2, zorder=4)
    if sl_price is not None:
        ax.axhline(y=sl_price, color="#d32f2f", linestyle="--", linewidth=1.5, zorder=4)
    if tp_price is not None:
        ax.axhline(y=tp_price, color="#2e7d32", linestyle="--", linewidth=1.5, zorder=4)

    # Subplot Title
    hit_ts_str = timestamps[entry_sub_idx] if 0 <= entry_sub_idx < n else ""
    ax.set_title(
        f"`{p_name}` [{c_count}c Blue]\nEntry: {hit_ts_str}",
        fontsize=8.5,
        fontweight="bold",
        color="#1a237e",
    )

    ax.tick_params(axis="both", which="both", labelsize=6.5)
    ax.set_xlim(-0.8, n - 0.2)

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)


def render_trade_canvas(
    trade, ohlcv_df, entry_idx: int, fired_patterns: list, output_path: Path
):
    """Render 8-chart canvas arranged as 3 + 3 + 2 grid."""
    n_patterns = len(fired_patterns)
    print(f"[+] Rendering {n_patterns} pattern subplots in 3+3+2 canvas layout...")

    sns.set_theme(style="white")
    fig = plt.figure(figsize=(16, 11))

    # Define 3 + 3 + 2 GridSpec (3 rows: Row 1 = 3 cols, Row 2 = 3 cols, Row 3 = 2 cols centered)
    gs = fig.add_gridspec(3, 6, hspace=0.45, wspace=0.35)

    axes = []
    # Row 1 (3 charts, 2 cols each)
    axes.append(fig.add_subplot(gs[0, 0:2]))
    axes.append(fig.add_subplot(gs[0, 2:4]))
    axes.append(fig.add_subplot(gs[0, 4:6]))

    # Row 2 (3 charts, 2 cols each)
    axes.append(fig.add_subplot(gs[1, 0:2]))
    axes.append(fig.add_subplot(gs[1, 2:4]))
    axes.append(fig.add_subplot(gs[1, 4:6]))

    # Row 3 (2 charts, 3 cols each centered)
    axes.append(fig.add_subplot(gs[2, 0:3]))
    axes.append(fig.add_subplot(gs[2, 3:6]))

    prior_bars = 15
    post_bars = 10
    duration_bars = int(trade["duration_candel"]) if trade["duration_candel"] and not pd.isna(trade["duration_candel"]) else 3

    for idx in range(min(8, n_patterns)):
        p_info = fired_patterns[idx]
        p_name = p_info["pattern_name"]
        hit_idx = p_info["hit_idx"]
        c_count = p_info["candle_count"]

        start_idx = max(0, entry_idx - prior_bars)
        end_idx = min(len(ohlcv_df), entry_idx + duration_bars + post_bars)

        sub_df = ohlcv_df.iloc[start_idx:end_idx].copy()
        entry_sub_idx = entry_idx - start_idx

        # Calculate pattern candle indices in subsegment
        hit_sub_idx = hit_idx - start_idx
        pattern_indices = set(
            range(max(0, hit_sub_idx - (c_count - 1)), hit_sub_idx + 1)
        )

        draw_subsegment(
            axes[idx],
            sub_df,
            entry_sub_idx,
            pattern_indices,
            p_name,
            c_count,
            trade,
        )

    # Hide unused subplots if fewer than 8 patterns
    for j in range(n_patterns, 8):
        axes[j].axis("off")

    pnl_val = float(trade["pnl"]) if not pd.isna(trade["pnl"]) else 0.0
    status_str = f"WIN (+{pnl_val:.2f}$)" if pnl_val > 0 else f"LOSS ({pnl_val:.2f}$)"
    title_text = (
        f"Trade #{int(trade['trade_id'])} ({trade['month_table']}) — {n_patterns} Candlestick Patterns Detected (15-Bar Lookback)\n"
        f"Entry Time: {trade['entry_time']} | Duration: {duration_bars} bars ({trade['duration_mins']}m) | Status: {status_str}"
    )

    fig.suptitle(title_text, fontsize=13, fontweight="bold", color="#1a237e", y=0.98)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"[+] Output 3+3+2 trade pattern canvas saved to: {output_path.resolve()}")


def main():
    trade_id = 1
    month_table = "jan_2025"
    if len(sys.argv) > 1:
        try:
            trade_id = int(sys.argv[1])
        except ValueError:
            pass
    if len(sys.argv) > 2:
        month_table = sys.argv[2]

    print(f"[+] Loading Trade #{trade_id} ({month_table}) from eur_usd_trades_5m.duckdb...")
    trade, ohlcv_df, entry_idx = load_trade_and_ohlcv(trade_id, month_table)

    print(f"[+] Detecting patterns in 15-candle lookback prior to Trade #{trade_id} entry...")
    fired_patterns = detect_patterns_for_trade(ohlcv_df, entry_idx, lookback_bars=15, max_patterns=8)

    render_trade_canvas(trade, ohlcv_df, entry_idx, fired_patterns, OUT_FILE)


if __name__ == "__main__":
    main()
