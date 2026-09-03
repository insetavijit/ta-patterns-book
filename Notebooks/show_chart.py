#!/usr/bin/env python3
"""Show Trade Chart Script.

Loads trade details and OHLCV data from Shared/Data/eur_usd_trades_5m.duckdb.
Window: 20 previous candles + Trade duration candles + 20 outcome candles.
Candle colors: Standard Green/Red (no blue candles).
Annotations: Horizontal SL line, TP line, Entry line, and Entry Candle marker.

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
DB_PATH = BASE_DIR / "Shared" / "Data" / "eur_usd_trades_5m.duckdb"
OUT_DIR = BASE_DIR / "Shared" / "OUTs" / "png"
OUT_FILE = OUT_DIR / "trade_1_chart.png"


def load_trade_and_ohlcv(trade_id: int = 1, month_table: str = "jan_2025"):
    """Load Trade details and surrounding OHLCV context from eur_usd_trades_5m.duckdb."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at: {DB_PATH}")

    conn = duckdb.connect(str(DB_PATH), read_only=True)

    # Fetch Trade details
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
        # Fallback to trade_id match
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

    # Fetch full OHLCV table
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


def draw_trade_chart(
    trade, ohlcv_df, entry_idx: int, prior_bars: int = 20, post_bars: int = 20
):
    """Render trade chart with 20 prior bars, 20 post bars, SL/TP lines, and Green/Red candles."""
    duration_bars = int(trade["duration_candel"]) if trade["duration_candel"] and not pd.isna(trade["duration_candel"]) else 3
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

    sns.set_theme(style="white")
    fig, ax = plt.subplots(figsize=(14, 7))
    ax.grid(False)

    # Standard Green / Red candle colors (NO BLUE CANDLES)
    for i in range(n):
        is_bullish = closes[i] >= opens[i]

        if is_bullish:
            color = "#26a69a"  # Solid Market Green
            edge_color = "#00897b"
        else:
            color = "#ef5350"  # Solid Market Red
            edge_color = "#c62828"

        body_bottom = min(opens[i], closes[i])
        body_top = max(opens[i], closes[i])
        body_height = max(abs(closes[i] - opens[i]), 0.00005)

        # Wicks
        ax.plot(
            [x[i], x[i]],
            [body_top, highs[i]],
            color=edge_color,
            linewidth=1.2,
            zorder=2,
        )
        ax.plot(
            [x[i], x[i]],
            [lows[i], body_bottom],
            color=edge_color,
            linewidth=1.2,
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
            linewidth=0.8,
            alpha=1.0,
            zorder=3,
        )

    # Prices for SL, TP, Entry
    entry_price = float(trade["entry_price"]) if not pd.isna(trade["entry_price"]) else opens[entry_sub_idx]
    sl_price = float(trade["sl_price"]) if not pd.isna(trade["sl_price"]) else None
    tp_price = float(trade["tp_price"]) if not pd.isna(trade["tp_price"]) else None

    # Draw Entry Price Line (Blue dotted)
    ax.axhline(
        y=entry_price,
        color="#1565c0",
        linestyle=":",
        linewidth=1.5,
        label=f"Entry: {entry_price:.5f}",
        zorder=4,
    )

    # Draw Stop Loss Line (Red dashed)
    if sl_price is not None:
        ax.axhline(
            y=sl_price,
            color="#d32f2f",
            linestyle="--",
            linewidth=1.8,
            label=f"SL: {sl_price:.5f}",
            zorder=4,
        )

    # Draw Take Profit Line (Green dashed)
    if tp_price is not None:
        ax.axhline(
            y=tp_price,
            color="#2e7d32",
            linestyle="--",
            linewidth=1.8,
            label=f"TP: {tp_price:.5f}",
            zorder=4,
        )

    # Annotate Entry Candle with Marker & Arrow
    entry_candle_high = highs[entry_sub_idx]
    ax.annotate(
        "ENTRY CANDLE",
        xy=(entry_sub_idx, entry_candle_high),
        xytext=(entry_sub_idx, entry_candle_high + 0.00040),
        arrowprops=dict(facecolor="#1565c0", edgecolor="#1565c0", shrink=0.08, width=1.5, headwidth=6),
        ha="center",
        fontsize=9,
        fontweight="bold",
        color="#0d47a1",
        zorder=5,
    )

    # Format Ticks & Aesthetics
    tick_step = max(1, n // 10)
    ax.set_xticks(x[::tick_step])
    ax.set_xticklabels(timestamps[::tick_step], rotation=20, fontsize=8)
    ax.tick_params(axis="both", which="both", labelsize=8)

    pnl_val = float(trade["pnl"]) if not pd.isna(trade["pnl"]) else 0.0
    status_str = f"WIN (+{pnl_val:.2f}$)" if pnl_val > 0 else f"LOSS ({pnl_val:.2f}$)"
    title_text = (
        f"Trade #{int(trade['trade_id'])} ({trade['month_table']}) — Entry: {timestamps[entry_sub_idx]} | "
        f"Duration: {duration_bars} bars ({trade['duration_mins']}m) | Status: {status_str}"
    )

    ax.set_title(title_text, fontsize=12, fontweight="bold", color="#1a237e", pad=12)
    ax.set_ylabel("EUR/USD Price", fontsize=9, fontweight="bold")
    ax.set_xlim(-0.8, n - 0.2)
    ax.legend(loc="upper left", fontsize=9, frameon=True, facecolor="#ffffff", edgecolor="#b0bec5")

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    fig.savefig(OUT_FILE, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"[+] Successfully rendered Trade #{int(trade['trade_id'])} chart to: {OUT_FILE.resolve()}")


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
    draw_trade_chart(trade, ohlcv_df, entry_idx, prior_bars=20, post_bars=20)


if __name__ == "__main__":
    main()
