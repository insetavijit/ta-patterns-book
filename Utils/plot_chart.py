#!/usr/bin/env python3
"""Self-contained Trade Candlestick Chart Plotter.

Provides a unified, flexible `plot_chart` function to render high-density,
publication-quality multi-chart candlestick playbooks from OHLCV and trade DataFrames.

Usage from Python / Notebooks:
    from Utils.plot_chart import plot_chart

    fig, axes = plot_chart(ohlcv_df, trades_df, [5, 2, 6, 4], output_path="trades.png")

Usage from CLI:
    uv run python Utils/plot_chart.py --uids 5 2 6 4 --output Shared/Outputs/trades.png
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path
from typing import Any, Sequence

import matplotlib
if "matplotlib.pyplot" not in sys.modules:
    matplotlib.use("Agg")  # Safe headless default
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd


def _to_naive_datetime(val: Any) -> pd.Timestamp:
    """Normalize any date/timestamp into a timezone-naive pandas Timestamp."""
    ts = pd.to_datetime(val)
    if isinstance(ts, pd.Timestamp) and ts.tzinfo is not None:
        return ts.tz_localize(None)
    return ts


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure standard datetime index and Open, High, Low, Close columns."""
    df = df.copy()

    # Resolve timestamp column
    time_col = None
    for candidate in ("timestamp", "time", "datetime", "date", "Time", "Date"):
        if candidate in df.columns:
            time_col = candidate
            break

    if time_col is not None:
        df["Time"] = pd.to_datetime(df[time_col]).apply(
            lambda t: t.tz_localize(None) if hasattr(t, "tzinfo") and t.tzinfo is not None else t
        )
        df = df.set_index("Time")
    elif not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index).map(
            lambda t: t.tz_localize(None) if hasattr(t, "tzinfo") and t.tzinfo is not None else t
        )

    # Standardize column casing
    col_map = {}
    for c in df.columns:
        clow = str(c).lower().strip()
        if clow == "open":
            col_map[c] = "Open"
        elif clow == "high":
            col_map[c] = "High"
        elif clow == "low":
            col_map[c] = "Low"
        elif clow == "close":
            col_map[c] = "Close"
        elif clow == "volume":
            col_map[c] = "Volume"

    df = df.rename(columns=col_map)
    df = df.sort_index()
    return df


def _find_trade_row(trades_df: pd.DataFrame, uid: Any) -> pd.Series:
    """Locate a single trade row by UID, trade_id, trade_number, or index."""
    # Check candidate ID columns
    for col in ("uid", "trade_id", "trade_number", "id"):
        if col in trades_df.columns:
            # Try matching as direct value or string/int conversion
            match = trades_df[trades_df[col] == uid]
            if not match.empty:
                return match.iloc[0]
            try:
                match = trades_df[trades_df[col] == int(uid)]
                if not match.empty:
                    return match.iloc[0]
            except (ValueError, TypeError):
                pass
            match = trades_df[trades_df[col].astype(str) == str(uid)]
            if not match.empty:
                return match.iloc[0]

    # Check dataframe index
    if uid in trades_df.index:
        return trades_df.loc[uid]

    try:
        idx_int = int(uid)
        if idx_int in trades_df.index:
            return trades_df.loc[idx_int]
        if 0 <= idx_int < len(trades_df):
            return trades_df.iloc[idx_int]
    except (ValueError, TypeError):
        pass

    raise KeyError(f"Trade with UID/ID '{uid}' not found in trades_df")


def _draw_candlesticks(ax: plt.Axes, df_sub: pd.DataFrame, width: float = 0.6) -> None:
    """Draw candlesticks without gaps using consecutive integer bar indices."""
    n = len(df_sub)
    if n == 0:
        return

    x = np.arange(n)
    opens = df_sub["Open"].values
    highs = df_sub["High"].values
    lows = df_sub["Low"].values
    closes = df_sub["Close"].values

    bullish = closes >= opens
    bearish = ~bullish

    up_color = "#26a69a"    # Clean Teal Green
    down_color = "#ef5350"  # Clean Coral Red
    wick_color = "#787b86"  # Neutral Slate Gray

    # Draw wicks
    ax.vlines(x, lows, highs, color=wick_color, linewidth=0.9, alpha=0.9, zorder=2)

    # Draw candle bodies
    body_lows = np.minimum(opens, closes)
    body_heights = np.maximum(np.abs(closes - opens), (highs - lows) * 0.01)

    # Bullish candles
    if np.any(bullish):
        ax.bar(
            x[bullish],
            body_heights[bullish],
            bottom=body_lows[bullish],
            width=width,
            color=up_color,
            edgecolor=up_color,
            linewidth=0.5,
            zorder=3,
        )

    # Bearish candles
    if np.any(bearish):
        ax.bar(
            x[bearish],
            body_heights[bearish],
            bottom=body_lows[bearish],
            width=width,
            color=down_color,
            edgecolor=down_color,
            linewidth=0.5,
            zorder=3,
        )

    # Format X-axis with sensible timestamps
    num_ticks = min(6, n)
    if num_ticks > 1:
        tick_indices = np.linspace(0, n - 1, num_ticks, dtype=int)
        tick_labels = [df_sub.index[i].strftime("%m-%d %H:%M") for i in tick_indices]
        ax.set_xticks(tick_indices)
        ax.set_xticklabels(tick_labels, rotation=0, fontsize=6.5, color="#555555")
    else:
        ax.set_xticks([])

    ax.set_xlim(-0.8, n - 0.2)
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.5f" if df_sub["Close"].max() < 10 else "%.2f"))
    ax.tick_params(axis="both", which="both", labelsize=6.5, colors="#555555", length=2)
    ax.grid(True, linestyle="--", alpha=0.2, color="#999999")


def plot_chart(
    ohlcv_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    trade_uids: Sequence[int | str] | int | str,
    pad_candles: int = 15,
    output_path: str | Path | None = None,
    cols: int | None = None,
    dpi: int = 150,
    title: str | None = None,
    show: bool = False,
) -> tuple[plt.Figure, np.ndarray]:
    """Plot candlestick charts for selected trade UIDs in an aesthetically packed grid.

    Args:
        ohlcv_df: DataFrame containing OHLCV market candles.
        trades_df: DataFrame containing trade records (entry/exit times, prices, SL/TP).
        trade_uids: Single UID or list/tuple of trade UIDs to plot (e.g. [5, 2, 6, 4]).
        pad_candles: Number of context candles to include before entry and after exit.
        output_path: Optional file path to save the generated figure (e.g. 'playbook.png').
        cols: Optional number of grid columns. If None, automatically computed.
        dpi: Resolution of exported image (default: 150).
        title: Overall super-title for the figure.
        show: If True, invoke plt.show() (useful for interactive notebooks).

    Returns:
        tuple (matplotlib.figure.Figure, numpy.ndarray of Axes)
    """
    if isinstance(trade_uids, (int, str)):
        trade_uids = [trade_uids]
    trade_uids = list(trade_uids)

    if not trade_uids:
        raise ValueError("trade_uids list must not be empty")

    ohlcv = _normalize_ohlcv(ohlcv_df)

    # Determine optimal grid layout
    n_charts = len(trade_uids)
    if cols is None:
        if n_charts == 1:
            cols = 1
        elif n_charts <= 4:
            cols = 2
        elif n_charts <= 9:
            cols = 3
        else:
            cols = 4

    rows = math.ceil(n_charts / cols)

    # Dynamic figure dimensions
    fig_w = min(18.0, max(8.0, cols * 5.0))
    fig_h = min(24.0, max(4.0, rows * 3.6))

    fig, axes = plt.subplots(rows, cols, figsize=(fig_w, fig_h), squeeze=False)
    axes_flat = axes.flatten()

    for idx, uid in enumerate(trade_uids):
        ax = axes_flat[idx]
        try:
            t_row = _find_trade_row(trades_df, uid)
        except KeyError as err:
            ax.text(0.5, 0.5, f"Trade #{uid} Not Found", ha="center", va="center", color="#d32f2f")
            ax.set_axis_off()
            continue

        # Extract timestamps and prices
        entry_time_val = t_row.get("entry_time")
        exit_time_val = t_row.get("exit_time")
        entry_p = t_row.get("entry_price")
        exit_p = t_row.get("exit_price")
        sl_p = t_row.get("sl_price")
        tp_p = t_row.get("tp_price")
        pnl = t_row.get("pnl")
        direction = t_row.get("direction", "LONG")
        exit_reason = t_row.get("exit_reason", "")
        ret_pct = t_row.get("return_pct")

        entry_dt = _to_naive_datetime(entry_time_val) if pd.notna(entry_time_val) else None
        exit_dt = _to_naive_datetime(exit_time_val) if pd.notna(exit_time_val) else None

        # Slice candle window
        if entry_dt is not None:
            # Find integer position of entry candle
            mask_before = ohlcv.index <= entry_dt
            if mask_before.any():
                entry_pos = int(np.where(mask_before)[0][-1])
                start_pos = max(0, entry_pos - pad_candles)
            else:
                start_pos = 0

            if exit_dt is not None:
                mask_exit = ohlcv.index <= exit_dt
                exit_pos = int(np.where(mask_exit)[0][-1]) if mask_exit.any() else len(ohlcv) - 1
                end_pos = min(len(ohlcv), exit_pos + pad_candles + 1)
            else:
                end_pos = min(len(ohlcv), entry_pos + pad_candles + 30)

            df_window = ohlcv.iloc[start_pos:end_pos].copy()
        else:
            df_window = ohlcv.iloc[: pad_candles * 2].copy()

        if df_window.empty:
            ax.text(0.5, 0.5, f"Trade #{uid}: No Candlestick Data", ha="center", va="center", color="#777777")
            ax.set_axis_off()
            continue

        # Draw candlesticks
        _draw_candlesticks(ax, df_window)

        # Plot Price Reference Lines
        # Entry Price Line (Blue dotted)
        if pd.notna(entry_p):
            ax.axhline(float(entry_p), color="#1976d2", linestyle=":", linewidth=1.1, alpha=0.9)
            ax.text(
                0.01, float(entry_p), f" Entry {entry_p:.5f}",
                transform=ax.get_yaxis_transform(), fontsize=5.5, color="#1976d2",
                va="bottom", ha="left", backgroundcolor="#ffffff88"
            )

        # Stop Loss Line (Red dashed)
        if pd.notna(sl_p):
            ax.axhline(float(sl_p), color="#d32f2f", linestyle="--", linewidth=1.0, alpha=0.85)
            ax.text(
                0.01, float(sl_p), f" SL {sl_p:.5f}",
                transform=ax.get_yaxis_transform(), fontsize=5.5, color="#d32f2f",
                va="top", ha="left", backgroundcolor="#ffffff88"
            )

        # Take Profit Line (Green dashed)
        if pd.notna(tp_p):
            ax.axhline(float(tp_p), color="#388e3c", linestyle="--", linewidth=1.0, alpha=0.85)
            ax.text(
                0.01, float(tp_p), f" TP {tp_p:.5f}",
                transform=ax.get_yaxis_transform(), fontsize=5.5, color="#388e3c",
                va="bottom", ha="left", backgroundcolor="#ffffff88"
            )

        # Plot Vertical Entry / Exit Markers
        if entry_dt is not None and entry_dt in df_window.index:
            x_entry = int(np.where(df_window.index == entry_dt)[0][0])
            ax.axvline(x_entry, color="#1976d2", linestyle="-.", linewidth=0.8, alpha=0.7)

        if exit_dt is not None and exit_dt in df_window.index:
            x_exit = int(np.where(df_window.index == exit_dt)[0][0])
            ax.axvline(x_exit, color="#ff9800", linestyle="-.", linewidth=0.8, alpha=0.7)

        # Header Title formatting
        dir_str = "LONG" if (str(direction).upper() in ("LONG", "1", "BUY")) else "SHORT"
        
        pnl_val = float(pnl) if pd.notna(pnl) else None
        if pnl_val is not None:
            outcome_color = "#2e7d32" if pnl_val >= 0 else "#c62828"
            pnl_sign = "+" if pnl_val >= 0 else ""
            pnl_str = f"{pnl_sign}{pnl_val:.2f}"
            if pd.notna(ret_pct):
                pnl_str += f" ({pnl_sign}{float(ret_pct):.2f}%)"
        else:
            outcome_color = "#333333"
            pnl_str = "OPEN"

        reason_str = f" | {exit_reason}" if exit_reason else ""
        header = f"Trade #{uid} ({dir_str}) : PnL {pnl_str}{reason_str}"
        ax.set_title(header, fontsize=8.0, fontweight="bold", color=outcome_color, pad=4)

    # Hide unused subplots in the grid
    for idx in range(n_charts, len(axes_flat)):
        axes_flat[idx].set_visible(False)

    if title:
        fig.suptitle(title, fontsize=11, fontweight="bold", y=0.995)

    fig.tight_layout()

    # Save to disk if requested
    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(out_p), dpi=dpi, bbox_inches="tight")
        print(f"Chart successfully saved to {out_p} ({out_p.stat().st_size / 1024:.1f} KB)")

    if show:
        plt.show()

    return fig, axes


def _cli_main():
    """Command line interface for plot_chart."""
    parser = argparse.ArgumentParser(
        description="Render candlestick charts for specific trade UIDs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=str,
        default="Shared/Data/classic_floor_mod_v5_5m_eurusd.duckdb",
        help="Path to DuckDB database",
    )
    parser.add_argument(
        "--trades-table",
        type=str,
        default="trades",
        help="Table name containing trades",
    )
    parser.add_argument(
        "--ohlcv-table",
        type=str,
        default="ohlcv",
        help="Table name containing market OHLCV candles",
    )
    parser.add_argument(
        "--uids",
        nargs="+",
        default=[1, 2, 3, 4],
        help="List of trade UIDs to plot (e.g. --uids 5 2 6 4)",
    )
    parser.add_argument(
        "--pad",
        type=int,
        default=15,
        help="Number of context candles before entry / after exit",
    )
    parser.add_argument(
        "--cols",
        type=int,
        default=None,
        help="Number of grid columns (default: auto)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="Shared/Outputs/trades_plot.png",
        help="Output PNG image path",
    )

    args = parser.parse_args()

    import duckdb

    if not os.path.exists(args.db):
        print(f"Error: Database file not found at {args.db}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading data from {args.db}...")
    with duckdb.connect(args.db, read_only=True) as con:
        trades_df = con.execute(f"SELECT * FROM {args.trades_table}").df()
        ohlcv_df = con.execute(f"SELECT * FROM {args.ohlcv_table}").df()

    print(f"Loaded {len(trades_df):,} trades and {len(ohlcv_df):,} candles.")
    print(f"Plotting trades: {args.uids} -> {args.output}")

    plot_chart(
        ohlcv_df=ohlcv_df,
        trades_df=trades_df,
        trade_uids=args.uids,
        pad_candles=args.pad,
        cols=args.cols,
        output_path=args.output,
    )


if __name__ == "__main__":
    _cli_main()
