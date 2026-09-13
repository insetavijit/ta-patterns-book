"""Lightweight inline candlestick chart plotter for Jupyter & Marimo notebooks."""

from __future__ import annotations

import math
from typing import Sequence
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd


def _strip_tz(val) -> pd.Timestamp | None:
    if val is None or pd.isna(val):
        return None
    ts = pd.to_datetime(val)
    if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
        return ts.tz_localize(None)
    return ts


def plot_chart(
    ohlcv_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    uids: Sequence[int | str] | int | str,
    pad: int = 15,
    show: bool = True,
):
    """Plot lightweight candlestick charts for specific trade UIDs inline in notebooks.

    Args:
        ohlcv_df: DataFrame containing market OHLCV candles.
        trades_df: DataFrame containing trade records.
        uids: Trade UID or list of trade UIDs to plot (e.g. [5, 2, 6, 4]).
        pad: Number of context candles before entry and after exit (default: 15).
        show: If True, invoke plt.show() inline (default: True).

    Returns:
        tuple (fig, axes)
    """
    uids = [uids] if isinstance(uids, (int, str)) else list(uids)

    # 1. Standardize OHLCV index & columns
    df = ohlcv_df.copy()
    time_col = next((c for c in ("timestamp", "time", "Time", "datetime", "Date") if c in df.columns), None)
    if time_col:
        df["Time"] = df[time_col].apply(_strip_tz)
        df = df.set_index("Time")
    elif not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index).map(_strip_tz)
    df.columns = [c.capitalize() for c in df.columns]
    df = df.sort_index()

    # 2. Grid layout
    n = len(uids)
    cols = 1 if n == 1 else (2 if n <= 4 else (3 if n <= 9 else 4))
    rows = math.ceil(n / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 5.2, rows * 3.4), squeeze=False)
    axes_flat = axes.flatten()

    for idx, uid in enumerate(uids):
        ax = axes_flat[idx]

        # Match trade row by uid, trade_id, trade_number, or index
        tr = None
        for col in ("uid", "trade_id", "trade_number"):
            if col in trades_df.columns:
                m = trades_df[trades_df[col] == uid]
                if not m.empty:
                    tr = m.iloc[0]
                    break
        if tr is None and uid in trades_df.index:
            tr = trades_df.loc[uid]

        if tr is None:
            ax.text(0.5, 0.5, f"Trade #{uid} Not Found", ha="center", va="center", color="#c62828")
            ax.set_axis_off()
            continue

        # Slice candle window
        entry_t = _strip_tz(tr.get("entry_time"))
        exit_t = _strip_tz(tr.get("exit_time"))

        if entry_t is not None:
            pos = np.where(df.index <= entry_t)[0]
            start_idx = max(0, pos[-1] - pad) if len(pos) else 0
            if exit_t is not None:
                end_pos = np.where(df.index <= exit_t)[0]
                end_idx = min(len(df), (end_pos[-1] if len(end_pos) else start_idx) + pad + 1)
            else:
                end_idx = min(len(df), start_idx + pad + 30)
            sub = df.iloc[start_idx:end_idx]
        else:
            sub = df.iloc[: pad * 2]

        if sub.empty:
            ax.text(0.5, 0.5, f"Trade #{uid}: No Candle Data", ha="center", va="center", color="#777777")
            ax.set_axis_off()
            continue

        # Draw Candlesticks
        x = np.arange(len(sub))
        o, h, l, c = sub["Open"].values, sub["High"].values, sub["Low"].values, sub["Close"].values
        bull = c >= o
        ax.vlines(x, l, h, color="#787b86", linewidth=0.9, zorder=2)
        ax.bar(x[bull], np.maximum(c - o, 1e-6)[bull], bottom=o[bull], color="#26a69a", width=0.6, zorder=3)
        ax.bar(x[~bull], np.maximum(o - c, 1e-6)[~bull], bottom=c[~bull], color="#ef5350", width=0.6, zorder=3)

        # Draw Entry, SL, TP price levels
        if pd.notna(tr.get("entry_price")):
            ax.axhline(float(tr["entry_price"]), color="#1976d2", linestyle=":", lw=1.1, zorder=4)
        if pd.notna(tr.get("sl_price")):
            ax.axhline(float(tr["sl_price"]), color="#d32f2f", linestyle="--", lw=1.0, zorder=4)
        if pd.notna(tr.get("tp_price")):
            ax.axhline(float(tr["tp_price"]), color="#388e3c", linestyle="--", lw=1.0, zorder=4)

        # Draw Entry & Exit vertical markers
        if entry_t is not None and entry_t in sub.index:
            ax.axvline(int(np.where(sub.index == entry_t)[0][0]), color="#1976d2", linestyle="-.", lw=0.8, alpha=0.7)
        if exit_t is not None and exit_t in sub.index:
            ax.axvline(int(np.where(sub.index == exit_t)[0][0]), color="#ff9800", linestyle="-.", lw=0.8, alpha=0.7)

        # X-axis timestamps & tick labels
        ticks = np.linspace(0, len(sub) - 1, min(5, len(sub)), dtype=int)
        ax.set_xticks(ticks)
        ax.set_xticklabels([sub.index[i].strftime("%m-%d %H:%M") for i in ticks], fontsize=6.5, color="#555555")
        ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.5f" if c.max() < 10 else "%.2f"))
        ax.tick_params(labelsize=6.5, colors="#555555")
        ax.grid(True, linestyle="--", alpha=0.2)

        # Title formatting with color-coded PnL
        pnl = float(tr.get("pnl", 0)) if pd.notna(tr.get("pnl")) else 0.0
        color = "#2e7d32" if pnl >= 0 else "#c62828"
        pnl_str = f"{pnl:+.2f}"
        if pd.notna(tr.get("return_pct")):
            pnl_str += f" ({float(tr['return_pct']):+.2f}%)"
        reason = f" | {tr.get('exit_reason')}" if pd.notna(tr.get("exit_reason")) else ""
        direction = str(tr.get("direction", "LONG")).upper()
        ax.set_title(f"Trade #{uid} ({direction}) : PnL {pnl_str}{reason}", fontsize=7.5, fontweight="bold", color=color, pad=3)

    # Hide extra unused subplot axes
    for i in range(n, len(axes_flat)):
        axes_flat[i].set_visible(False)

    plt.tight_layout()
    if show:
        plt.show()

    return fig, axes
