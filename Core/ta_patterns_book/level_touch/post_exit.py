"""Post-Exit 15-Candle Fibonacci Excursion Analysis (pfib_bsl) Engine.

Complies with the v3 architectural specification in DOCs/pfib_bsl-v3.md:
- Direction-aware touch detection (Long and Short)
- 15 standard Fibonacci extension ratios (0.236 to 3.000)
- Dual invalidation tracking (Stop-Loss and Breakeven)
- Window completeness and session gap flags
- Idempotent table storage ({strategy}_pfib) and view join ({strategy}_trades_pfib)
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

logger = logging.getLogger("pfib_engine")

PFIB_RATIO_GRID: tuple[float, ...] = (
    0.236, 0.382, 0.500, 0.618, 0.786, 1.000,
    1.272, 1.382, 1.618, 1.786, 2.000, 2.272, 2.618, 3.000
)


def analyze_trade_post_exit(
    entry_price: float,
    sl_price: float,
    tp_price: float,
    direction: str,
    forward_candles: pd.DataFrame,
    exit_time: Any | None = None,
    nominal_step_seconds: float = 300.0,
    horizon: int = 15,
    ratio_grid: tuple[float, ...] = PFIB_RATIO_GRID,
) -> dict[str, Any] | None:
    """Analyze a single trade's post-exit forward window against Fibonacci levels."""
    leg_span = abs(tp_price - sl_price)
    if leg_span < 1e-9:
        logger.warning("Degenerate leg span (abs(tp - sl) < 1e-9); skipping trade.")
        return None

    is_long = str(direction).strip().lower().startswith("long")
    dir_str = "long" if is_long else "short"

    window_len = len(forward_candles)
    if window_len == 0:
        return {
            "pfib_direction": dir_str,
            "pfib_bsl": None,
            "pfib_candles": None,
            "pfib_be_hit": False,
            "pfib_sl_hit": False,
            "pfib_window_candles": 0,
            "pfib_window_complete": False,
            "pfib_gap_crossed": False,
            "pfib_computed_at": datetime.now(timezone.utc),
        }

    gap_crossed = False
    max_step = nominal_step_seconds * 1.5

    timestamps = pd.to_datetime(forward_candles["timestamp"], utc=True)
    if exit_time is not None and not timestamps.empty:
        exit_ts = pd.to_datetime(exit_time, utc=True)
        if (timestamps.iloc[0] - exit_ts).total_seconds() > max_step:
            gap_crossed = True

    if not gap_crossed and len(timestamps) > 1:
        diffs = timestamps.diff().dropna()
        if any(d.total_seconds() > max_step for d in diffs):
            gap_crossed = True

    level_prices = np.array([sl_price + r * (tp_price - sl_price) for r in ratio_grid])

    highs = forward_candles["high"].values
    lows = forward_candles["low"].values

    deepest_ratio = 0.0
    deepest_offset: int | None = None
    be_hit = False
    sl_hit = False

    limit_k = min(window_len, horizon)

    for k in range(limit_k):
        cur_high = highs[k]
        cur_low = lows[k]
        offset = k + 1

        if is_long:
            eps_entry = max(abs(entry_price) * 1e-7, 1e-9)
            eps_sl = max(abs(sl_price) * 1e-7, 1e-9)
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
            eps_entry = max(abs(entry_price) * 1e-7, 1e-9)
            eps_sl = max(abs(sl_price) * 1e-7, 1e-9)
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

        if sl_hit:
            break

    return {
        "pfib_direction": dir_str,
        "pfib_bsl": deepest_ratio,
        "pfib_candles": deepest_offset,
        "pfib_be_hit": be_hit,
        "pfib_sl_hit": sl_hit,
        "pfib_window_candles": limit_k,
        "pfib_window_complete": limit_k == horizon,
        "pfib_gap_crossed": gap_crossed,
        "pfib_computed_at": datetime.now(timezone.utc),
    }


def run_post_exit_analysis(
    db_path: str | Path,
    strategy_name: str = "classic_floor_mod_v4c",
    ohlcv_table: str | None = None,
    horizon: int = 15,
) -> int:
    """Execute post-exit Fibonacci runner analysis across all strategy trades."""
    db_path = str(db_path)
    con = duckdb.connect(db_path, read_only=False)

    safe_strat = strategy_name.replace("-", "_").replace(".", "_")
    view_name = f"{safe_strat}_trades"

    tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
    if view_name not in tables:
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
        end_slice = min(len(ohlcv_df), start_slice + horizon)

        forward_slice = ohlcv_df.iloc[start_slice:end_slice]

        res = analyze_trade_post_exit(
            entry_price=entry_price,
            sl_price=sl_price,
            tp_price=tp_price,
            direction=direction,
            forward_candles=forward_slice,
            exit_time=exit_time,
            horizon=horizon,
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
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS "{table_name}" (
            trade_id BIGINT PRIMARY KEY,
            vbt_trade_id BIGINT,
            fingerprint VARCHAR,
            pfib_direction VARCHAR,
            pfib_bsl DOUBLE,
            pfib_candles INTEGER,
            pfib_be_hit BOOLEAN,
            pfib_sl_hit BOOLEAN,
            pfib_window_candles INTEGER,
            pfib_window_complete BOOLEAN,
            pfib_gap_crossed BOOLEAN,
            pfib_computed_at TIMESTAMP WITH TIME ZONE
        );
    """)

    con.register("temp_res_df", res_df)
    con.execute(f'DELETE FROM "{table_name}" WHERE trade_id IN (SELECT trade_id FROM temp_res_df);')
    con.execute(f"""
        INSERT INTO "{table_name}"
        SELECT 
            trade_id, vbt_trade_id, fingerprint, pfib_direction,
            pfib_bsl, pfib_candles, pfib_be_hit, pfib_sl_hit,
            pfib_window_candles, pfib_window_complete, pfib_gap_crossed,
            pfib_computed_at
        FROM temp_res_df;
    """)

    con.execute(f"""
        CREATE OR REPLACE VIEW "{safe_strat}_trades_pfib" AS
        SELECT 
            t.*,
            p.pfib_direction,
            p.pfib_bsl,
            p.pfib_candles,
            p.pfib_be_hit,
            p.pfib_sl_hit,
            p.pfib_window_candles,
            p.pfib_window_complete,
            p.pfib_gap_crossed,
            p.pfib_computed_at
        FROM "{view_name}" t
        LEFT JOIN "{table_name}" p ON t.trade_id = p.trade_id;
    """)

    con.close()
    logger.info("Successfully analyzed %d trades into '%s'.", len(results), table_name)
    return len(results)


def main() -> None:
    parser = argparse.ArgumentParser(description="Post-Exit Fibonacci Runner Excursion Analyzer")
    parser.add_argument("--db", default="Shared/INPs/Ohlcv_2325Eurusd.duckdb", help="Path to DuckDB database")
    parser.add_argument("--strategy", "-s", default="classic_floor_mod_v4c", help="Strategy name")
    parser.add_argument("--ohlcv-table", default=None, help="OHLCV 5m table name")
    parser.add_argument("--horizon", type=int, default=15, help="Forward candle horizon (default: 15)")

    args = parser.parse_args()
    count = run_post_exit_analysis(
        db_path=args.db,
        strategy_name=args.strategy,
        ohlcv_table=args.ohlcv_table,
        horizon=args.horizon,
    )
    print(f"✓ Analyzed {count} trades for strategy '{args.strategy}' with horizon={args.horizon}")


if __name__ == "__main__":
    main()
