"""Multi-Horizon Post-Exit Fibonacci Excursion Analysis Engine.

Complies with DOCs/pfib_bsl-v3.md and DOCs/feature_pfibs.md:
- Direction-aware touch detection (Long and Short)
- 14-ratio Fibonacci extension grid (0.236 to 3.000)
- Multi-horizon evaluation (default: 15, 30, 60 candles) in a single pass
- Dual invalidation tracking (Stop-Loss and Breakeven)
- Window completeness and session gap flags
- Idempotent table storage ({strategy}_pfib) and view join ({strategy}_trades_pfib)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from post_trade_analysis.constants import (
    DEFAULT_HORIZONS,
    NOMINAL_STEP_SECONDS,
    PFIB_RATIO_GRID,
)

logger = logging.getLogger("post_trade_analysis")


def analyze_trade_multi_horizon(
    entry_price: float,
    sl_price: float,
    tp_price: float,
    direction: str,
    forward_candles: pd.DataFrame,
    exit_time: Any | None = None,
    nominal_step_seconds: float = NOMINAL_STEP_SECONDS,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    ratio_grid: tuple[float, ...] = PFIB_RATIO_GRID,
) -> dict[str, Any] | None:
    """Analyze a single trade's post-exit forward window across multiple horizons in a single pass.
    
    Parameters
    ----------
    entry_price : float
        Trade entry price.
    sl_price : float
        Trade stop-loss price.
    tp_price : float
        Trade take-profit price.
    direction : str
        'Long' or 'Short' (case-insensitive).
    forward_candles : pd.DataFrame
        DataFrame with columns ['timestamp', 'open', 'high', 'low', 'close'].
    exit_time : Any | None
        Timestamp of exit bar (for gap detection).
    nominal_step_seconds : float
        Nominal timeframe seconds (300.0 for 5m).
    horizons : tuple[int, ...]
        Horizons to evaluate (e.g. (15, 30, 60)).
    ratio_grid : tuple[float, ...]
        Fibonacci ratios to test.
    """
    leg_span = abs(tp_price - sl_price)
    if leg_span < 1e-9:
        logger.warning("Degenerate leg span (abs(tp - sl) < 1e-9); skipping trade.")
        return None

    is_long = str(direction).strip().lower().startswith("long")
    dir_str = "long" if is_long else "short"

    sorted_horizons = sorted(horizons)
    max_h = max(sorted_horizons) if sorted_horizons else 0

    window_len = len(forward_candles)
    if window_len == 0 or max_h == 0:
        empty_res: dict[str, Any] = {
            "pfib_direction": dir_str,
            "pfib_gap_crossed": False,
            "pfib_computed_at": datetime.now(timezone.utc),
        }
        for h in sorted_horizons:
            empty_res.update({
                f"pfib{h}_bsl": None,
                f"pfib{h}_candles": None,
                f"pfib{h}_be_hit": False,
                f"pfib{h}_sl_hit": False,
                f"pfib{h}_window_candles": 0,
                f"pfib{h}_window_complete": False,
                f"pfib{h}_gap_crossed": False,
            })
        base_h = 15 if 15 in sorted_horizons else (sorted_horizons[0] if sorted_horizons else 15)
        empty_res.update({
            "pfib_bsl": None,
            "pfib_candles": None,
            "pfib_be_hit": False,
            "pfib_sl_hit": False,
            "pfib_window_candles": 0,
            "pfib_window_complete": False,
        })
        return empty_res

    gap_so_far = False
    max_step = nominal_step_seconds * 1.5

    timestamps = pd.to_datetime(forward_candles["timestamp"], utc=True)
    if exit_time is not None and not timestamps.empty:
        exit_ts = pd.to_datetime(exit_time, utc=True)
        if (timestamps.iloc[0] - exit_ts).total_seconds() > max_step:
            gap_so_far = True

    level_prices = np.array([sl_price + r * (tp_price - sl_price) for r in ratio_grid])

    highs = forward_candles["high"].values
    lows = forward_candles["low"].values

    deepest_ratio = 0.0
    deepest_offset: int | None = None
    be_hit = False
    sl_hit = False

    limit_k = min(window_len, max_h)
    horizon_results: dict[int, dict[str, Any]] = {}

    eps_entry = max(abs(entry_price) * 1e-7, 1e-9)
    eps_sl = max(abs(sl_price) * 1e-7, 1e-9)

    for k in range(limit_k):
        offset = k + 1
        cur_high = highs[k]
        cur_low = lows[k]

        if k > 0 and not gap_so_far:
            diff_sec = (timestamps.iloc[k] - timestamps.iloc[k - 1]).total_seconds()
            if diff_sec > max_step:
                gap_so_far = True

        if is_long:
            if cur_low <= entry_price + eps_entry:
                be_hit = True
            if cur_low <= sl_price + eps_sl:
                sl_hit = True

            for r_idx, r_val in enumerate(ratio_grid):
                lvl = level_prices[r_idx]
                eps_lvl = max(abs(lvl) * 1e-7, 1e-9)
                if cur_high >= lvl - eps_lvl:
                    if r_val > deepest_ratio:
                        deepest_ratio = r_val
                        deepest_offset = offset
        else:
            if cur_high >= entry_price - eps_entry:
                be_hit = True
            if cur_high >= sl_price - eps_sl:
                sl_hit = True

            for r_idx, r_val in enumerate(ratio_grid):
                lvl = level_prices[r_idx]
                eps_lvl = max(abs(lvl) * 1e-7, 1e-9)
                if cur_low <= lvl + eps_lvl:
                    if r_val > deepest_ratio:
                        deepest_ratio = r_val
                        deepest_offset = offset

        # Snapshot any horizon ending exactly at offset
        for h in sorted_horizons:
            if h not in horizon_results and offset == h:
                horizon_results[h] = {
                    f"pfib{h}_bsl": deepest_ratio,
                    f"pfib{h}_candles": deepest_offset,
                    f"pfib{h}_be_hit": be_hit,
                    f"pfib{h}_sl_hit": sl_hit,
                    f"pfib{h}_window_candles": min(window_len, h),
                    f"pfib{h}_window_complete": window_len >= h,
                    f"pfib{h}_gap_crossed": gap_so_far,
                }

        # If Stop-Loss was hit, invalidation stops further excursion for all pending horizons
        if sl_hit:
            for h in sorted_horizons:
                if h not in horizon_results:
                    horizon_results[h] = {
                        f"pfib{h}_bsl": deepest_ratio,
                        f"pfib{h}_candles": deepest_offset,
                        f"pfib{h}_be_hit": be_hit,
                        f"pfib{h}_sl_hit": True,
                        f"pfib{h}_window_candles": min(window_len, h),
                        f"pfib{h}_window_complete": window_len >= h,
                        f"pfib{h}_gap_crossed": gap_so_far,
                    }
            break

    # Finalize any pending horizons where available data ended before horizon length
    for h in sorted_horizons:
        if h not in horizon_results:
            horizon_results[h] = {
                f"pfib{h}_bsl": deepest_ratio,
                f"pfib{h}_candles": deepest_offset,
                f"pfib{h}_be_hit": be_hit,
                f"pfib{h}_sl_hit": sl_hit,
                f"pfib{h}_window_candles": min(window_len, h),
                f"pfib{h}_window_complete": window_len >= h,
                f"pfib{h}_gap_crossed": gap_so_far,
            }

    # Assemble complete dictionary
    trade_result: dict[str, Any] = {
        "pfib_direction": dir_str,
        "pfib_gap_crossed": gap_so_far,
        "pfib_computed_at": datetime.now(timezone.utc),
    }
    for h in sorted_horizons:
        trade_result.update(horizon_results[h])

    # Standard baseline aliases (points to 15 if present, else smallest horizon)
    base_h = 15 if 15 in sorted_horizons else sorted_horizons[0]
    trade_result["pfib_bsl"] = trade_result[f"pfib{base_h}_bsl"]
    trade_result["pfib_candles"] = trade_result[f"pfib{base_h}_candles"]
    trade_result["pfib_be_hit"] = trade_result[f"pfib{base_h}_be_hit"]
    trade_result["pfib_sl_hit"] = trade_result[f"pfib{base_h}_sl_hit"]
    trade_result["pfib_window_candles"] = trade_result[f"pfib{base_h}_window_candles"]
    trade_result["pfib_window_complete"] = trade_result[f"pfib{base_h}_window_complete"]

    return trade_result


def run_post_trade_analysis(
    db_path: str | Path,
    strategy_name: str = "classic_floor_mod_v4c",
    ohlcv_table: str | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> int:
    """Execute post-trade excursion analysis across all strategy trades in DuckDB."""
    db_path = str(db_path)
    con = duckdb.connect(db_path, read_only=False)

    safe_strat = strategy_name.replace("-", "_").replace(".", "_")
    view_name = f"{safe_strat}_trades"

    tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
    if view_name not in tables:
        con.close()
        raise ValueError(f"Strategy view '{view_name}' not found in {db_path}")

    if not ohlcv_table:
        for candidate in ["ohlcv_eurusd_5m_2025", "ohlcv_5m", "ohlcv"]:
            if candidate in tables:
                ohlcv_table = candidate
                break
    if not ohlcv_table:
        con.close()
        raise ValueError("Could not find a 5m OHLCV table in DuckDB.")

    trades_df = con.execute(f"""
        SELECT 
            trade_id, vbt_trade_id, fingerprint, direction, 
            entry_time, exit_time, entry_price, sl_price, tp_price, exit_reason
        FROM "{view_name}"
        ORDER BY trade_id ASC
    """).df()

    if trades_df.empty:
        logger.info("No trades found in '%s'.", view_name)
        con.close()
        return 0

    ohlcv_df = con.execute(f"""
        SELECT timestamp, open, high, low, close
        FROM "{ohlcv_table}"
        ORDER BY timestamp ASC
    """).df()

    ts_series = pd.to_datetime(ohlcv_df["timestamp"], utc=True)
    ts_index = pd.DatetimeIndex(ts_series)

    max_h = max(horizons)
    results: list[dict[str, Any]] = []

    for _, tr in trades_df.iterrows():
        tid = int(tr["trade_id"])
        vbt_id = int(tr["vbt_trade_id"])
        fp = tr["fingerprint"]
        direction = tr["direction"]
        entry_price = float(tr["entry_price"]) if pd.notna(tr["entry_price"]) else None
        sl_price = float(tr["sl_price"]) if pd.notna(tr["sl_price"]) else None
        tp_price = float(tr["tp_price"]) if pd.notna(tr["tp_price"]) else None
        exit_time = tr["exit_time"]

        if entry_price is None or sl_price is None or tp_price is None or pd.isna(exit_time):
            continue

        exit_ts = pd.to_datetime(exit_time, utc=True)
        pos = ts_index.get_indexer([exit_ts])[0]
        if pos != -1:
            exit_idx = pos
        else:
            s_idx = ts_index.searchsorted(exit_ts)
            exit_idx = s_idx - 1 if s_idx > 0 else 0

        start_slice = exit_idx + 1
        end_slice = min(len(ohlcv_df), start_slice + max_h)

        forward_slice = ohlcv_df.iloc[start_slice:end_slice]

        res = analyze_trade_multi_horizon(
            entry_price=entry_price,
            sl_price=sl_price,
            tp_price=tp_price,
            direction=direction,
            forward_candles=forward_slice,
            exit_time=exit_time,
            horizons=horizons,
        )

        if res is not None:
            res["trade_id"] = tid
            res["vbt_trade_id"] = vbt_id
            res["fingerprint"] = fp
            results.append(res)

    if not results:
        con.close()
        return 0

    res_df = pd.DataFrame(results)

    table_name = f"{safe_strat}_pfib"

    # Dynamically build table columns
    col_defs = [
        "trade_id BIGINT PRIMARY KEY",
        "vbt_trade_id BIGINT",
        "fingerprint VARCHAR",
        "pfib_direction VARCHAR",
        "pfib_gap_crossed BOOLEAN",
        "pfib_computed_at TIMESTAMP WITH TIME ZONE",
    ]
    for h in sorted(horizons):
        col_defs.extend([
            f"pfib{h}_bsl DOUBLE",
            f"pfib{h}_candles INTEGER",
            f"pfib{h}_be_hit BOOLEAN",
            f"pfib{h}_sl_hit BOOLEAN",
            f"pfib{h}_window_candles INTEGER",
            f"pfib{h}_window_complete BOOLEAN",
            f"pfib{h}_gap_crossed BOOLEAN",
        ])
    col_defs.extend([
        "pfib_bsl DOUBLE",
        "pfib_candles INTEGER",
        "pfib_be_hit BOOLEAN",
        "pfib_sl_hit BOOLEAN",
        "pfib_window_candles INTEGER",
        "pfib_window_complete BOOLEAN",
    ])

    con.execute(f'DROP TABLE IF EXISTS "{table_name}";')
    con.execute(f"""
        CREATE TABLE "{table_name}" (
            {', '.join(col_defs)}
        );
    """)

    con.register("temp_res_df", res_df)

    # Insert matched columns from temp_res_df
    insert_cols = [c.split()[0] for c in col_defs]
    cols_sql = ", ".join([f'"{c}"' for c in insert_cols])
    con.execute(f"""
        INSERT INTO "{table_name}" ({cols_sql})
        SELECT {cols_sql}
        FROM temp_res_df;
    """)

    # Create joined view
    view_cols_sql = ", ".join([f'p."{c}"' for c in insert_cols if c not in ("trade_id", "vbt_trade_id", "fingerprint")])
    con.execute(f"""
        CREATE OR REPLACE VIEW "{safe_strat}_trades_pfib" AS
        SELECT 
            t.*,
            {view_cols_sql}
        FROM "{view_name}" t
        LEFT JOIN "{table_name}" p ON t.trade_id = p.trade_id;
    """)

    con.close()
    logger.info("Successfully analyzed %d trades into '%s'.", len(results), table_name)
    return len(results)
