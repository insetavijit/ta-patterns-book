#!/usr/bin/env python3
"""Show Chart Script for Trade #1 from EUR/USD 5m Dataset.

Fetches Trade #1 details from trade_duration_5m in
Shared/INPs/EURUSD_5m_2025_v2_trades_and_ohlcv.duckdb, extracts the
10-bar prior context + trade bars + 10-bar outcome context from ohlcv_5m,
and renders a crisp candlestick chart with 100% opaque candle bodies.

Output: Shared/OUTs/png/trade_1_chart.png
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

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "Shared" / "INPs" / "EURUSD_5m_2025_v2_trades_and_ohlcv.duckdb"
OUT_DIR = BASE_DIR / "Shared" / "OUTs" / "png"
OUT_FILE = OUT_DIR / "trade_1_chart.png"


def load_trade_and_ohlcv(trade_id: int = 1):
    """Load Trade details and surrounding OHLCV context from DuckDB."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at: {DB_PATH}")

    conn = duckdb.connect(str(DB_PATH), read_only=True)

    # 1. Fetch Trade details
    trade_df = conn.execute(
        f"""
        SELECT month_table, trade_id, entry_time, duration, duration_mins, status, pnl
        FROM trade_duration_5m
        WHERE trade_id = {trade_id}
        LIMIT 1;
    """
    ).fetchdf()

    if trade_df.empty:
        conn.close()
        raise ValueError(f"Trade #{trade_id} not found in trade_duration_5m.")

    trade = trade_df.iloc[0]
    entry_ts = pd.to_datetime(trade["entry_time"])

    # 2. Fetch full OHLCV table to find index of entry_time
    ohlcv_df = conn.execute(
        """
        SELECT open, high, low, close, volume, timestamp
        FROM ohlcv_5m
        ORDER BY timestamp;
    """
    ).fetchdf()

    conn.close()

    ohlcv_df["timestamp"] = pd.to_datetime(ohlcv_df["timestamp"])
    
    # Strip timezone for clean matching if needed
    if entry_ts.tzinfo is not None:
        entry_ts_naive = entry_ts.tz_localize(None)
        ohlcv_df["timestamp_naive"] = ohlcv_df["timestamp"].dt.tz_localize(None)
        match_mask = ohlcv_df["timestamp_naive"] == entry_ts_naive
    else:
        match_mask = ohlcv_df["timestamp"] == entry_ts

    hit_indices = np.where(match_mask)[0]
    if len(hit_indices) == 0:
        # Fallback: nearest bar
        diffs = (ohlcv_df["timestamp_naive" if "timestamp_naive" in ohlcv_df else "timestamp"] - (entry_ts_naive if entry_ts.tzinfo else entry_ts)).abs()
        entry_idx = diffs.idxmin()
    else:
        entry_idx = hit_indices[0]

    return trade, ohlcv_df, entry_idx


def draw_trade_chart(trade, ohlcv_df, entry_idx: int, prior_bars: int = 10, post_bars: int = 10):
    """Render 100% opaque candlestick chart for the target trade."""
    duration_bars = int(trade["duration"])
    start_idx = max(0, entry_idx - prior_bars)
    end_idx = min(len(ohlcv_df), entry_idx + duration_bars + post_bars)

    sub_df = ohlcv_df.iloc[start_idx:end_idx].copy()
    opens = sub_df["open"].to_numpy()
    highs = sub_df["high"].to_numpy()
    lows = sub_df["low"].to_numpy()
    closes = sub_df["close"].to_numpy()
    timestamps = sub_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M").values

    n = len(closes)
    x = np.arange(n)
    entry_sub_idx = entry_idx - start_idx
    trade_indices = set(range(entry_sub_idx, entry_sub_idx + duration_bars))

    sns.set_theme(style="white")
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.grid(False)

    for i in range(n):
        is_trade_bar = i in trade_indices
        is_bullish = closes[i] >= opens[i]

        if is_trade_bar:
            color = "#1e88e5"  # Solid Bright Blue trade bars
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
            linewidth=1.2 if is_trade_bar else 0.8,
            alpha=1.0,
            zorder=3,
        )

    # Format ticks & titles
    tick_step = max(1, n // 8)
    ax.set_xticks(x[::tick_step])
    ax.set_xticklabels(timestamps[::tick_step], rotation=15, fontsize=8)
    ax.tick_params(axis="both", which="both", labelsize=8)

    status_str = f"WIN (+{trade['pnl']:.2f}$)" if trade["pnl"] > 0 else f"LOSS ({trade['pnl']:.2f}$)"
    title_text = (
        f"Trade #{trade['trade_id']} ({trade['month_table']}) — Entry: {timestamps[entry_sub_idx]} | "
        f"Duration: {trade['duration_mins']}m ({duration_bars} bars) | Status: {status_str}"
    )

    ax.set_title(title_text, fontsize=12, fontweight="bold", color="#1a237e", pad=12)
    ax.set_ylabel("Price (EUR/USD)", fontsize=9, fontweight="bold")
    ax.set_xlim(-0.8, n - 0.2)

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    fig.savefig(OUT_FILE, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"[+] Successfully rendered Trade #{trade['trade_id']} chart to: {OUT_FILE.resolve()}")


def main():
    trade_id = 1
    if len(sys.argv) > 1:
        try:
            trade_id = int(sys.argv[1])
        except ValueError:
            pass

    print(f"[+] Loading Trade #{trade_id} data...")
    trade, ohlcv_df, entry_idx = load_trade_and_ohlcv(trade_id)
    draw_trade_chart(trade, ohlcv_df, entry_idx)


if __name__ == "__main__":
    main()
