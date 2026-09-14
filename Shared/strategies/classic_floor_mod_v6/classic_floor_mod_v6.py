"""ClassicFloorModV6 — Pure Canonical Technical Analysis Strategy.

Next-generation implementation featuring:
1. Pure Canonical Schema: All 8 legacy duplicate aliases (r1, s1, sl_price, projected_rr, entry_1..4)
   have been removed in favor of upper_pivot, lower_pivot, safe_sl, projected_rr_safe, and epatt_1..4.
2. 4-Phase Lifecycle Timestamps: signal_time, confirmation_time, entry_time, exit_time.
3. Multi-Tier Stop Loss Hierarchy: primary_sl, pivot_sl, safe_sl.
4. Multi-Tier SL Breach Telemetry: primary_sl_hit, pivot_sl_hit, safe_sl_hit.
5. In-Trade Excursions: mfe, mae, fib_bsl, fib_bsl_ambiguous.
6. Strategy-Level Post-Trade Fibonacci Runner Excursions (pfib):
   Directly computes 15, 30, and 60 forward-candle post-exit runner excursions:
   - pfib15_bsl, pfib15_be_hit, pfib15_sl_hit
   - pfib30_bsl, pfib30_be_hit, pfib30_sl_hit
   - pfib60_bsl, pfib60_be_hit, pfib60_sl_hit
7. Multi-Position Execution Toggle: allow_concurrent_trades (True | False) with independent trade tracking.
8. Self-Contained Record Generation: self.completed_trades containing 100% complete trade dictionaries.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Resolve Core from repository root
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "Core") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "Core"))

try:
    from ta_patterns_book.loss_profile.candles import compute_candlestick_pattern_columns
except ImportError:
    compute_candlestick_pattern_columns = None


# Standard Fibonacci Ratios for In-Trade BSL Excursion
IN_TRADE_FIB_RATIOS = (0.236, 0.382, 0.500, 0.618, 0.786)

# Standard 14-Level Fibonacci Expansion Grid for Post-Trade Runner Excursions
POST_TRADE_FIB_GRID = (
    0.236, 0.382, 0.500, 0.618, 0.786, 1.000,
    1.272, 1.382, 1.618, 1.786, 2.000, 2.272, 2.618, 3.000,
)

POST_TRADE_HORIZONS = (15, 30, 60)


def _detect_session(ts: Any) -> str:
    """Classify UTC timestamp into major Forex market session."""
    try:
        dt = pd.to_datetime(ts, utc=True)
        h = dt.hour
        if 7 <= h < 12:
            return "London"
        elif 12 <= h < 16:
            return "London/NY Overlap"
        elif 16 <= h < 21:
            return "New York"
        else:
            return "Asian"
    except Exception:
        return "Unknown"


class ClassicFloorModV6:
    """Pure Canonical Classic Floor Trader Pivot Bounce Strategy with Native pfib."""

    name = "classic_floor_mod_v6"
    version = "6.0.0"
    warmup_candles = 22

    def __init__(
        self,
        allow_same_bar_exit: bool = False,
        filter_zero_volume: bool = True,
        allow_concurrent_trades: bool = False,
        risk_per_trade: float = 100.0,
    ):
        self.allow_same_bar_exit = allow_same_bar_exit
        self.filter_zero_volume = filter_zero_volume
        self.allow_concurrent_trades = allow_concurrent_trades
        self.risk_per_trade = risk_per_trade
        self.completed_trades: list[dict[str, Any]] = []

    def _compute_post_trade_pfib(
        self,
        exit_bar: int,
        entry_price: float,
        safe_sl: float,
        tp_price: float,
        high_arr: np.ndarray,
        low_arr: np.ndarray,
        n: int,
    ) -> dict[str, Any]:
        """Compute native 15, 30, and 60-candle post-trade runner excursions."""
        leg_span = abs(tp_price - safe_sl)
        if leg_span < 1e-9:
            return {
                "pfib15_bsl": 0.0, "pfib15_be_hit": False, "pfib15_sl_hit": False,
                "pfib30_bsl": 0.0, "pfib30_be_hit": False, "pfib30_sl_hit": False,
                "pfib60_bsl": 0.0, "pfib60_be_hit": False, "pfib60_sl_hit": False,
            }

        level_prices = [safe_sl + r * leg_span for r in POST_TRADE_FIB_GRID]
        max_h = 60
        forward_len = min(max_h, n - 1 - exit_bar)

        results = {
            15: {"bsl": 0.0, "be_hit": False, "sl_hit": False},
            30: {"bsl": 0.0, "be_hit": False, "sl_hit": False},
            60: {"bsl": 0.0, "be_hit": False, "sl_hit": False},
        }

        if forward_len <= 0:
            return {
                f"pfib{h}_{k}": results[h][k]
                for h in POST_TRADE_HORIZONS
                for k in ("bsl", "be_hit", "sl_hit")
            }

        deepest_ratio = 0.0
        be_hit = False
        sl_hit = False

        for k in range(1, forward_len + 1):
            bar_idx = exit_bar + k
            cur_h = high_arr[bar_idx]
            cur_l = low_arr[bar_idx]

            # Invalidation touches (Long)
            if cur_l <= entry_price + 1e-7:
                be_hit = True
            if cur_l <= safe_sl + 1e-7:
                sl_hit = True

            # Excursion touches
            for r_idx, r_val in enumerate(POST_TRADE_FIB_GRID):
                if cur_h >= level_prices[r_idx] - 1e-7:
                    if r_val > deepest_ratio:
                        deepest_ratio = r_val

            # Horizon checkpoints
            for h in POST_TRADE_HORIZONS:
                if k == h:
                    results[h] = {
                        "bsl": deepest_ratio,
                        "be_hit": be_hit,
                        "sl_hit": sl_hit,
                    }

            # If SL hit, stop further excursion progression for pending horizons
            if sl_hit:
                for h in POST_TRADE_HORIZONS:
                    if k < h:
                        results[h] = {
                            "bsl": deepest_ratio,
                            "be_hit": be_hit,
                            "sl_hit": True,
                        }
                break

        # Fill any horizon that extended beyond the end of data
        for h in POST_TRADE_HORIZONS:
            if forward_len < h and not results[h]["sl_hit"] and results[h]["bsl"] == 0.0:
                results[h] = {
                    "bsl": deepest_ratio,
                    "be_hit": be_hit,
                    "sl_hit": sl_hit,
                }

        return {
            "pfib15_bsl": float(results[15]["bsl"]),
            "pfib15_be_hit": bool(results[15]["be_hit"]),
            "pfib15_sl_hit": bool(results[15]["sl_hit"]),
            "pfib30_bsl": float(results[30]["bsl"]),
            "pfib30_be_hit": bool(results[30]["be_hit"]),
            "pfib30_sl_hit": bool(results[30]["sl_hit"]),
            "pfib60_bsl": float(results[60]["bsl"]),
            "pfib60_be_hit": bool(results[60]["be_hit"]),
            "pfib60_sl_hit": bool(results[60]["sl_hit"]),
        }

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict | None = None,
    ) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
        """Execute signal generation, trade simulation, and complete telemetry calculation."""
        allow_same_bar_exit = (params or {}).get("allow_same_bar_exit", self.allow_same_bar_exit)
        filter_zero_volume = (params or {}).get("filter_zero_volume", self.filter_zero_volume)
        allow_concurrent_trades = (params or {}).get("allow_concurrent_trades", self.allow_concurrent_trades)
        risk_per_trade = float((params or {}).get("risk_per_trade", self.risk_per_trade))

        if ohlcv.empty:
            empty_s = pd.Series(dtype=bool)
            return empty_s, empty_s, pd.DataFrame()

        df = ohlcv.copy().reset_index(drop=True)

        # 1. PIVOT MATH via 20-period rolling calculations shifted by 1 bar
        high20 = df["high"].rolling(20).max().shift(1)
        low20 = df["low"].rolling(20).min().shift(1)
        prev_close = df["close"].shift(1)

        pivot = (high20 + low20 + prev_close) / 3.0
        lower_pivot = (pivot * 2.0) - high20  # Canonical Support line
        upper_pivot = (pivot * 2.0) - low20   # Canonical Resistance line / Frozen Target

        df["pivot"] = pivot
        df["lower_pivot"] = lower_pivot
        df["upper_pivot"] = upper_pivot
        df["body_low"] = np.minimum(df["open"], df["close"])

        # 2. CANDLE STATE & 3-CANDLE PATTERN CLASSIFICATION
        prev_close_bar = df["close"].shift(1)
        prev_close_bar.iloc[0] = df["open"].iloc[0]

        is_up = df["close"] >= prev_close_bar
        is_green = df["close"] > df["open"]
        dir_str = np.where(is_up, "U", "D")
        col_str = np.where(is_green, "G", "R")
        df["candle_state"] = dir_str + col_str

        # Confirmation-anchored patterns (epatt_1 to epatt_4)
        cs = df["candle_state"]
        df["epatt_1"] = cs.shift(3) + "-" + cs.shift(2) + "-" + cs.shift(1)
        df["epatt_2"] = cs.shift(2) + "-" + cs.shift(1) + "-" + cs
        df["epatt_3"] = cs.shift(1) + "-" + cs + "-" + cs.shift(-1)
        df["epatt_4"] = cs + "-" + cs.shift(-1) + "-" + cs.shift(-2) + "-" + cs.shift(-3)

        # 3. TA Candlestick Patterns
        if compute_candlestick_pattern_columns is not None:
            patt_df = compute_candlestick_pattern_columns(df)
        else:
            patt_df = pd.DataFrame(
                np.nan,
                index=df.index,
                columns=["ecpatt_1", "ecpatt_2", "ecpatt_3", "epcpatt_1", "epcpatt_2", "epcpatt_3"],
            )

        n = len(df)
        open_arr = df["open"].values
        high_arr = df["high"].values
        low_arr = df["low"].values
        close_arr = df["close"].values
        volume_arr = df["volume"].values if "volume" in df.columns else np.ones(n)
        body_low_arr = df["body_low"].values
        lower_pivot_arr = df["lower_pivot"].values
        upper_pivot_arr = df["upper_pivot"].values
        pivot_arr = df["pivot"].values

        entries = pd.Series(False, index=df.index)
        exits = pd.Series(False, index=df.index)

        # Bar-aligned telemetry arrays
        in_trade_series = np.zeros(n, dtype=bool)
        trade_id_series = np.zeros(n, dtype=int)
        direction_series = np.full(n, None, dtype=object)
        status_series = np.full(n, None, dtype=object)
        session_series = np.full(n, None, dtype=object)

        signal_time_series = [None] * n
        confirmation_time_series = [None] * n
        entry_time_series = [None] * n
        exit_time_series = [None] * n

        entry_price_series = np.full(n, np.nan)
        exit_price_series = np.full(n, np.nan)
        tp_price_series = np.full(n, np.nan)
        swing_low_series = np.full(n, np.nan)

        primary_sl_series = np.full(n, np.nan)
        pivot_sl_series = np.full(n, np.nan)
        safe_sl_series = np.full(n, np.nan)

        primary_sl_hit_series = np.zeros(n, dtype=bool)
        pivot_sl_hit_series = np.zeros(n, dtype=bool)
        safe_sl_hit_series = np.zeros(n, dtype=bool)

        risk_primary_series = np.full(n, np.nan)
        risk_pivot_series = np.full(n, np.nan)
        risk_safe_series = np.full(n, np.nan)
        size_series = np.full(n, np.nan)
        lot_size_series = np.full(n, np.nan)
        risk_amount_series = np.full(n, np.nan)
        entry_fees_series = np.zeros(n, dtype=float)
        exit_fees_series = np.zeros(n, dtype=float)

        projected_rr_primary_series = np.full(n, np.nan)
        projected_rr_safe_series = np.full(n, np.nan)
        r_multiple_series = np.full(n, np.nan)
        realized_pnl_series = np.full(n, np.nan)
        realized_pnl_pct_series = np.full(n, np.nan)
        is_win_series = np.zeros(n, dtype=int)
        exit_reason_series = np.full(n, None, dtype=object)

        holding_bars_series = np.zeros(n, dtype=int)
        holding_seconds_series = np.full(n, np.nan)

        mfe_series = np.full(n, np.nan)
        mae_series = np.full(n, np.nan)
        fib_bsl_series = np.full(n, np.nan)
        fib_bsl_ambig_series = np.zeros(n, dtype=bool)

        # Strategy-level native pfib series
        pfib15_bsl_series = np.full(n, np.nan)
        pfib15_be_hit_series = np.zeros(n, dtype=bool)
        pfib15_sl_hit_series = np.zeros(n, dtype=bool)
        pfib30_bsl_series = np.full(n, np.nan)
        pfib30_be_hit_series = np.zeros(n, dtype=bool)
        pfib30_sl_hit_series = np.zeros(n, dtype=bool)
        pfib60_bsl_series = np.full(n, np.nan)
        pfib60_be_hit_series = np.zeros(n, dtype=bool)
        pfib60_sl_hit_series = np.zeros(n, dtype=bool)

        concurrent_trades_count_series = np.zeros(n, dtype=int)

        active_trades: list[dict[str, Any]] = []
        pending_setups: list[dict[str, Any]] = []
        completed_trades: list[dict[str, Any]] = []
        trade_id_counter = 0

        for i in range(n):
            current_time = df["timestamp"].iloc[i] if "timestamp" in df.columns else ohlcv.index[i]
            cur_open = open_arr[i]
            cur_high = high_arr[i]
            cur_low = low_arr[i]
            cur_close = close_arr[i]
            cur_session = _detect_session(current_time)

            # --- A. In-Trade Management & Exits Evaluation ---
            closed_trades = []
            for trade in list(active_trades):
                t_id = trade["trade_id"]
                t_entry_bar = trade["entry_bar"]
                t_entry_price = trade["entry_price"]
                t_target = trade["tp_price"]
                t_safe_sl = trade["safe_sl"]
                t_primary_sl = trade["primary_sl"]
                t_pivot_sl = trade["pivot_sl"]

                # Excursion extremes tracking
                trade["mfe"] = max(trade["mfe"], cur_high - t_entry_price)
                trade["mae"] = max(trade["mae"], t_entry_price - cur_low)

                # SL touch breach tracking
                if cur_low <= t_primary_sl:
                    trade["primary_sl_hit"] = True
                if cur_low <= t_pivot_sl:
                    trade["pivot_sl_hit"] = True
                if cur_low <= t_safe_sl:
                    trade["safe_sl_hit"] = True

                # In-trade Fibonacci level touches tracking
                if trade["fib_levels"] is not None:
                    for j in range(5):
                        eps = max(trade["fib_levels"][j] * 1e-7, 1e-9)
                        if trade["first_touch_bar"][j] == -1 and cur_high >= trade["fib_levels"][j] - eps:
                            trade["first_touch_bar"][j] = i

                target_hit = cur_high >= t_target
                stop_hit = cur_low <= t_safe_sl

                if target_hit or stop_hit:
                    exits.iloc[i] = True
                    exit_price = t_target if target_hit else t_safe_sl
                    pnl_points = exit_price - t_entry_price
                    raw_ret = pnl_points / t_entry_price
                    pnl_pct = raw_ret * 100.0
                    monetary_pnl = pnl_points * trade["size"]
                    r_mult = pnl_points / trade["risk_safe"] if trade["risk_safe"] > 0 else np.nan
                    h_bars = i - t_entry_bar

                    try:
                        h_sec = float((pd.to_datetime(current_time) - pd.to_datetime(trade["entry_time"])).total_seconds())
                    except Exception:
                        h_sec = float(h_bars * 60)

                    # Compute in-trade fib_bsl
                    if target_hit:
                        f_bsl = 0.786
                        f_ambig = False
                    else:
                        sl_bar = i
                        reached = [IN_TRADE_FIB_RATIOS[j] for j in range(5) if trade["first_touch_bar"][j] != -1 and trade["first_touch_bar"][j] < sl_bar]
                        f_bsl = max(reached) if reached else 0.0
                        tied = [IN_TRADE_FIB_RATIOS[j] for j in range(5) if trade["first_touch_bar"][j] == sl_bar]
                        f_ambig = bool(tied and max(tied) > f_bsl)

                    # Native Strategy-Level Post-Trade pfib Excursion
                    pfib_metrics = self._compute_post_trade_pfib(
                        exit_bar=i,
                        entry_price=t_entry_price,
                        safe_sl=t_safe_sl,
                        tp_price=t_target,
                        high_arr=high_arr,
                        low_arr=low_arr,
                        n=n,
                    )

                    # Record on exit bar
                    exit_price_series[i] = exit_price
                    exit_time_series[i] = current_time
                    realized_pnl_series[i] = pnl_points
                    realized_pnl_pct_series[i] = pnl_pct
                    r_multiple_series[i] = r_mult
                    is_win_series[i] = 1 if target_hit else -1
                    exit_reason_series[i] = "TP" if target_hit else "SL"
                    status_series[i] = "CLOSED"
                    holding_bars_series[i] = h_bars
                    holding_seconds_series[i] = h_sec
                    mfe_series[i] = trade["mfe"]
                    mae_series[i] = trade["mae"]
                    fib_bsl_series[i] = f_bsl
                    fib_bsl_ambig_series[i] = f_ambig
                    primary_sl_hit_series[i] = trade["primary_sl_hit"]
                    pivot_sl_hit_series[i] = trade["pivot_sl_hit"]
                    safe_sl_hit_series[i] = trade["safe_sl_hit"]

                    pfib15_bsl_series[i] = pfib_metrics["pfib15_bsl"]
                    pfib15_be_hit_series[i] = pfib_metrics["pfib15_be_hit"]
                    pfib15_sl_hit_series[i] = pfib_metrics["pfib15_sl_hit"]
                    pfib30_bsl_series[i] = pfib_metrics["pfib30_bsl"]
                    pfib30_be_hit_series[i] = pfib_metrics["pfib30_be_hit"]
                    pfib30_sl_hit_series[i] = pfib_metrics["pfib30_sl_hit"]
                    pfib60_bsl_series[i] = pfib_metrics["pfib60_bsl"]
                    pfib60_be_hit_series[i] = pfib_metrics["pfib60_be_hit"]
                    pfib60_sl_hit_series[i] = pfib_metrics["pfib60_sl_hit"]

                    # Retroactively assign trade-level outcomes back to entry bar
                    if t_entry_bar < n:
                        fib_bsl_series[t_entry_bar] = f_bsl
                        fib_bsl_ambig_series[t_entry_bar] = f_ambig
                        primary_sl_hit_series[t_entry_bar] = trade["primary_sl_hit"]
                        pivot_sl_hit_series[t_entry_bar] = trade["pivot_sl_hit"]
                        safe_sl_hit_series[t_entry_bar] = trade["safe_sl_hit"]
                        mfe_series[t_entry_bar] = trade["mfe"]
                        mae_series[t_entry_bar] = trade["mae"]
                        exit_price_series[t_entry_bar] = exit_price
                        exit_time_series[t_entry_bar] = current_time
                        exit_reason_series[t_entry_bar] = "TP" if target_hit else "SL"
                        realized_pnl_series[t_entry_bar] = pnl_points
                        realized_pnl_pct_series[t_entry_bar] = pnl_pct
                        r_multiple_series[t_entry_bar] = r_mult
                        is_win_series[t_entry_bar] = 1 if target_hit else -1
                        holding_bars_series[t_entry_bar] = h_bars
                        holding_seconds_series[t_entry_bar] = h_sec

                        pfib15_bsl_series[t_entry_bar] = pfib_metrics["pfib15_bsl"]
                        pfib15_be_hit_series[t_entry_bar] = pfib_metrics["pfib15_be_hit"]
                        pfib15_sl_hit_series[t_entry_bar] = pfib_metrics["pfib15_sl_hit"]
                        pfib30_bsl_series[t_entry_bar] = pfib_metrics["pfib30_bsl"]
                        pfib30_be_hit_series[t_entry_bar] = pfib_metrics["pfib30_be_hit"]
                        pfib30_sl_hit_series[t_entry_bar] = pfib_metrics["pfib30_sl_hit"]
                        pfib60_bsl_series[t_entry_bar] = pfib_metrics["pfib60_bsl"]
                        pfib60_be_hit_series[t_entry_bar] = pfib_metrics["pfib60_be_hit"]
                        pfib60_sl_hit_series[t_entry_bar] = pfib_metrics["pfib60_sl_hit"]

                    # Complete Trade Dictionary Record (Pure Canonical Schema)
                    trade_record = dict(trade)
                    trade_record["exit_bar"] = i
                    trade_record["exit_time"] = current_time
                    trade_record["exit_price"] = exit_price
                    trade_record["exit_reason"] = "TP" if target_hit else "SL"
                    trade_record["pnl"] = monetary_pnl
                    trade_record["realized_pnl"] = pnl_points
                    trade_record["return_pct"] = raw_ret
                    trade_record["realized_pnl_pct"] = pnl_pct
                    trade_record["r_multiple"] = r_mult
                    trade_record["is_win"] = 1 if target_hit else -1
                    trade_record["status"] = "CLOSED"
                    trade_record["direction"] = "LONG"
                    trade_record["session"] = cur_session
                    trade_record["holding_bars"] = h_bars
                    trade_record["holding_seconds"] = h_sec
                    trade_record["fib_bsl"] = f_bsl
                    trade_record["fib_bsl_ambiguous"] = f_ambig
                    trade_record["entry_fees"] = 0.0
                    trade_record["exit_fees"] = 0.0
                    trade_record["allow_concurrent_trades"] = allow_concurrent_trades

                    # Strategy-level pfib metrics
                    trade_record.update(pfib_metrics)

                    trade_record["pivot"] = float(pivot.iloc[t_entry_bar])
                    trade_record["lower_pivot"] = float(lower_pivot.iloc[t_entry_bar])
                    trade_record["upper_pivot"] = float(upper_pivot.iloc[t_entry_bar])

                    # Setup patterns from entry bar
                    trade_record["epatt_1"] = str(df["epatt_1"].iloc[t_entry_bar]) if "epatt_1" in df.columns else None
                    trade_record["epatt_2"] = str(df["epatt_2"].iloc[t_entry_bar]) if "epatt_2" in df.columns else None
                    trade_record["epatt_3"] = str(df["epatt_3"].iloc[t_entry_bar]) if "epatt_3" in df.columns else None
                    trade_record["epatt_4"] = str(df["epatt_4"].iloc[t_entry_bar]) if "epatt_4" in df.columns else None
                    trade_record["ecpatt_1"] = str(patt_df["ecpatt_1"].iloc[t_entry_bar]) if "ecpatt_1" in patt_df.columns else None
                    trade_record["ecpatt_2"] = str(patt_df["ecpatt_2"].iloc[t_entry_bar]) if "ecpatt_2" in patt_df.columns else None
                    trade_record["ecpatt_3"] = str(patt_df["ecpatt_3"].iloc[t_entry_bar]) if "ecpatt_3" in patt_df.columns else None
                    trade_record["epcpatt_1"] = str(patt_df["epcpatt_1"].iloc[t_entry_bar]) if "epcpatt_1" in patt_df.columns else None
                    trade_record["epcpatt_2"] = str(patt_df["epcpatt_2"].iloc[t_entry_bar]) if "epcpatt_2" in patt_df.columns else None
                    trade_record["epcpatt_3"] = str(patt_df["epcpatt_3"].iloc[t_entry_bar]) if "epcpatt_3" in patt_df.columns else None

                    # Clean internal helper keys
                    trade_record.pop("fib_levels", None)
                    trade_record.pop("first_touch_bar", None)

                    completed_trades.append(trade_record)
                    closed_trades.append(trade)

            for ct in closed_trades:
                active_trades.remove(ct)

            # --- B. Execute Pending Setup Confirmations at Bar i (Confirmation Bar Open) ---
            ready_setups = [s for s in pending_setups if s["target_bar"] == i]
            for setup in ready_setups:
                pending_setups.remove(setup)
                trade_id_counter += 1
                entry_bar = i
                entries.iloc[i] = True

                orig_sig_bar = setup["orig_signal_bar"]
                entry_price_val = cur_open
                setup_upper = setup["upper_pivot"]
                setup_lower = setup["lower_pivot"]

                swing_low_val = float(np.min(body_low_arr[orig_sig_bar:i + 1]))
                half_range = 0.5 * (setup_upper - setup_lower)
                safe_sl_val = swing_low_val - half_range
                primary_sl_val = float(close_arr[orig_sig_bar])
                pivot_sl_val = float(setup_lower)

                risk_safe_val = max(entry_price_val - safe_sl_val, 1e-6)
                risk_primary_val = max(entry_price_val - primary_sl_val, 1e-6)
                risk_pivot_val = max(entry_price_val - pivot_sl_val, 1e-6)

                size_val = risk_per_trade / risk_safe_val
                lot_size_val = size_val / 100000.0
                risk_amount_val = risk_safe_val * size_val

                proj_rr_safe = (setup_upper - entry_price_val) / risk_safe_val
                proj_rr_primary = (setup_upper - entry_price_val) / risk_primary_val

                fib_lvls = [entry_price_val + r * (setup_upper - entry_price_val) for r in IN_TRADE_FIB_RATIOS]

                trade_obj = {
                    "trade_id": trade_id_counter,
                    "orig_signal_bar": orig_sig_bar,
                    "signal_time": setup["signal_time"],
                    "confirmation_time": current_time,
                    "entry_bar": entry_bar,
                    "entry_time": current_time,
                    "entry_price": entry_price_val,
                    "tp_price": setup_upper,
                    "safe_sl": safe_sl_val,
                    "primary_sl": primary_sl_val,
                    "pivot_sl": pivot_sl_val,
                    "swing_low": swing_low_val,
                    "risk_safe": risk_safe_val,
                    "risk_primary": risk_primary_val,
                    "risk_pivot": risk_pivot_val,
                    "size": size_val,
                    "lot_size": lot_size_val,
                    "risk_amount": risk_amount_val,
                    "projected_rr_safe": proj_rr_safe,
                    "projected_rr_primary": proj_rr_primary,
                    "fib_levels": fib_lvls,
                    "first_touch_bar": [-1] * 5,
                    "mfe": 0.0,
                    "mae": 0.0,
                    "primary_sl_hit": False,
                    "pivot_sl_hit": False,
                    "safe_sl_hit": False,
                }
                active_trades.append(trade_obj)

                # Record on entry bar
                trade_id_series[i] = trade_id_counter
                direction_series[i] = "LONG"
                status_series[i] = "OPEN"
                session_series[i] = cur_session
                signal_time_series[i] = setup["signal_time"]
                confirmation_time_series[i] = current_time
                entry_time_series[i] = current_time
                entry_price_series[i] = entry_price_val
                tp_price_series[i] = setup_upper
                safe_sl_series[i] = safe_sl_val
                primary_sl_series[i] = primary_sl_val
                pivot_sl_series[i] = pivot_sl_val
                swing_low_series[i] = swing_low_val
                risk_safe_series[i] = risk_safe_val
                risk_primary_series[i] = risk_primary_val
                risk_pivot_series[i] = risk_pivot_val
                size_series[i] = size_val
                lot_size_series[i] = lot_size_val
                risk_amount_series[i] = risk_amount_val
                projected_rr_safe_series[i] = proj_rr_safe
                projected_rr_primary_series[i] = proj_rr_primary

            # --- C. Detect New Setup Signal at Bar i (Bar 0 where Close <= Lower Pivot) ---
            is_active_bar = (volume_arr[i] > 0 and high_arr[i] > low_arr[i]) if filter_zero_volume else True
            has_capacity = allow_concurrent_trades or (len(active_trades) == 0 and len(pending_setups) == 0)

            signal_condition = (
                (not np.isnan(lower_pivot_arr[i]))
                and (cur_close <= lower_pivot_arr[i])
                and has_capacity
                and is_active_bar
            )

            if signal_condition:
                pending_setups.append({
                    "orig_signal_bar": i,
                    "signal_time": current_time,
                    "target_bar": i + 3,  # Confirmation strictly at 4th candle (Bar +3 Open)
                    "upper_pivot": upper_pivot_arr[i],
                    "lower_pivot": lower_pivot_arr[i],
                    "pivot": pivot_arr[i],
                })

            # --- D. Track Active State Across Candles ---
            num_active = len(active_trades)
            concurrent_trades_count_series[i] = num_active
            if num_active > 0:
                in_trade_series[i] = True
                lead_trade = active_trades[-1]
                if trade_id_series[i] == 0:
                    trade_id_series[i] = lead_trade["trade_id"]
                    direction_series[i] = "LONG"
                    status_series[i] = "OPEN"
                    session_series[i] = cur_session
                    entry_price_series[i] = lead_trade["entry_price"]
                    tp_price_series[i] = lead_trade["tp_price"]
                    safe_sl_series[i] = lead_trade["safe_sl"]
                    primary_sl_series[i] = lead_trade["primary_sl"]
                    pivot_sl_series[i] = lead_trade["pivot_sl"]
                    swing_low_series[i] = lead_trade["swing_low"]
                    signal_time_series[i] = lead_trade["signal_time"]
                    confirmation_time_series[i] = lead_trade["confirmation_time"]
                    entry_time_series[i] = lead_trade["entry_time"]
                    size_series[i] = lead_trade["size"]
                    lot_size_series[i] = lead_trade["lot_size"]
                    risk_amount_series[i] = lead_trade["risk_amount"]
                    risk_safe_series[i] = lead_trade["risk_safe"]
                    risk_primary_series[i] = lead_trade["risk_primary"]
                    risk_pivot_series[i] = lead_trade["risk_pivot"]
                    projected_rr_safe_series[i] = lead_trade["projected_rr_safe"]
                    projected_rr_primary_series[i] = lead_trade["projected_rr_primary"]

        # 4. BUILD UNIFIED PURE CANONICAL TRADES DATAFRAME
        trades_df = pd.DataFrame(index=ohlcv.index)

        # Pivots & Channels
        trades_df["pivot"] = pivot.values
        trades_df["lower_pivot"] = lower_pivot.values
        trades_df["upper_pivot"] = upper_pivot.values

        # Execution & Lifecycle
        trades_df["entries"] = entries.values
        trades_df["exits"] = exits.values
        trades_df["in_trade"] = in_trade_series
        trades_df["trade_id"] = trade_id_series
        trades_df["direction"] = direction_series
        trades_df["status"] = status_series
        trades_df["session"] = session_series

        # 4-Phase Timestamps
        trades_df["signal_time"] = signal_time_series
        trades_df["confirmation_time"] = confirmation_time_series
        trades_df["entry_time"] = entry_time_series
        trades_df["exit_time"] = exit_time_series

        # Orders & Stop Loss Levels
        trades_df["entry_price"] = entry_price_series
        trades_df["tp_price"] = tp_price_series
        trades_df["exit_price"] = exit_price_series
        trades_df["swing_low"] = swing_low_series
        trades_df["primary_sl"] = primary_sl_series
        trades_df["pivot_sl"] = pivot_sl_series
        trades_df["safe_sl"] = safe_sl_series

        # SL Breach Telemetry
        trades_df["primary_sl_hit"] = primary_sl_hit_series
        trades_df["pivot_sl_hit"] = pivot_sl_hit_series
        trades_df["safe_sl_hit"] = safe_sl_hit_series

        # Risk, Sizing & Fees
        trades_df["risk_primary"] = risk_primary_series
        trades_df["risk_pivot"] = risk_pivot_series
        trades_df["risk_safe"] = risk_safe_series
        trades_df["size"] = size_series
        trades_df["lot_size"] = lot_size_series
        trades_df["risk_amount"] = risk_amount_series
        trades_df["entry_fees"] = entry_fees_series
        trades_df["exit_fees"] = exit_fees_series

        # Outcomes & Expectancy
        trades_df["projected_rr_safe"] = projected_rr_safe_series
        trades_df["projected_rr_primary"] = projected_rr_primary_series
        trades_df["r_multiple"] = r_multiple_series
        trades_df["pnl"] = realized_pnl_series
        trades_df["realized_pnl"] = realized_pnl_series
        trades_df["return_pct"] = realized_pnl_pct_series
        trades_df["realized_pnl_pct"] = realized_pnl_pct_series
        trades_df["is_win"] = is_win_series
        trades_df["exit_reason"] = exit_reason_series

        # Holding Duration
        trades_df["holding_bars"] = holding_bars_series
        trades_df["holding_seconds"] = holding_seconds_series

        # In-Trade Excursions
        trades_df["mfe"] = mfe_series
        trades_df["mae"] = mae_series
        trades_df["fib_bsl"] = fib_bsl_series
        trades_df["fib_bsl_ambiguous"] = fib_bsl_ambig_series

        # Strategy-Level Post-Trade pfib Excursions
        trades_df["pfib15_bsl"] = pfib15_bsl_series
        trades_df["pfib15_be_hit"] = pfib15_be_hit_series
        trades_df["pfib15_sl_hit"] = pfib15_sl_hit_series
        trades_df["pfib30_bsl"] = pfib30_bsl_series
        trades_df["pfib30_be_hit"] = pfib30_be_hit_series
        trades_df["pfib30_sl_hit"] = pfib30_sl_hit_series
        trades_df["pfib60_bsl"] = pfib60_bsl_series
        trades_df["pfib60_be_hit"] = pfib60_be_hit_series
        trades_df["pfib60_sl_hit"] = pfib60_sl_hit_series

        # Concurrency
        trades_df["concurrent_trades_count"] = concurrent_trades_count_series

        # Patterns
        trades_df["epatt_1"] = df["epatt_1"].values
        trades_df["epatt_2"] = df["epatt_2"].values
        trades_df["epatt_3"] = df["epatt_3"].values
        trades_df["epatt_4"] = df["epatt_4"].values

        trades_df["ecpatt_1"] = patt_df["ecpatt_1"].values
        trades_df["ecpatt_2"] = patt_df["ecpatt_2"].values
        trades_df["ecpatt_3"] = patt_df["ecpatt_3"].values
        trades_df["epcpatt_1"] = patt_df["epcpatt_1"].values
        trades_df["epcpatt_2"] = patt_df["epcpatt_2"].values
        trades_df["epcpatt_3"] = patt_df["epcpatt_3"].values

        entries.index = ohlcv.index
        exits.index = ohlcv.index

        self.completed_trades = completed_trades

        return entries, exits, trades_df
