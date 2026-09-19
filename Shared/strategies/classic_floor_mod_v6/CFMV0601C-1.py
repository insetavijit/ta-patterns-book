"""CFMV0601C-1 — Standalone Ultra-Lightweight Classic Floor Mod V6.1 Concurrent Strategy.

Pure, standalone implementation of the core trading rules with ZERO complexity:
- 100% Standalone (No project imports or external dependencies beyond numpy & pandas)
- Pure Core Logic: 20-period rolling Floor Pivots, 3-bar confirmation entry, dynamic SL adaptation
- Concurrent / Non-Blocking execution model
- Zero extra telemetry: No pattern classifiers, no runner Fibonacci grids, no session tracking
"""

from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd


class CFMV0601C1:
    """Standalone Core Classic Floor Mod V6.1 Concurrent (Non-Blocking) Strategy."""

    name = "CFMV0601C-1"
    version = "6.1.0-light"
    warmup_candles = 22

    def __init__(
        self,
        risk_per_trade: float = 100.0,
        filter_zero_volume: bool = True,
        allow_same_bar_exit: bool = True,
    ):
        self.risk_per_trade = float(risk_per_trade)
        self.filter_zero_volume = bool(filter_zero_volume)
        self.allow_same_bar_exit = bool(allow_same_bar_exit)
        self.completed_trades: list[dict[str, Any]] = []

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict | None = None,
    ) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
        """Run the core signal generation and trade simulation loop.

        Args:
            ohlcv: DataFrame containing 'open', 'high', 'low', 'close', and optional 'timestamp'/'volume'.
            params: Optional override dictionary for strategy parameters.

        Returns:
            entries: Boolean Series indicating trade entry bars.
            exits: Boolean Series indicating trade exit bars.
            trades_df: DataFrame of completed trades with core execution metrics.
        """
        risk_per_trade = float((params or {}).get("risk_per_trade", self.risk_per_trade))
        filter_zero_volume = bool((params or {}).get("filter_zero_volume", self.filter_zero_volume))
        allow_same_bar_exit = bool((params or {}).get("allow_same_bar_exit", self.allow_same_bar_exit))

        if ohlcv.empty:
            empty_s = pd.Series(dtype=bool)
            return empty_s, empty_s, pd.DataFrame()

        df = ohlcv.copy().reset_index(drop=True)
        n = len(df)

        # -------------------------------------------------------------
        # 1. Core Classic Floor Pivot Calculation (Rolling 20 bars)
        # -------------------------------------------------------------
        high20 = df["high"].rolling(20).max().shift(1)
        low20 = df["low"].rolling(20).min().shift(1)
        prev_close = df["close"].shift(1)

        pivot = (high20 + low20 + prev_close) / 3.0
        lower_pivot = (pivot * 2.0) - high20  # Canonical Support line (S1)
        upper_pivot = (pivot * 2.0) - low20   # Canonical Target line (R1)

        open_arr = df["open"].values
        high_arr = df["high"].values
        low_arr = df["low"].values
        close_arr = df["close"].values
        volume_arr = df["volume"].values if "volume" in df.columns else np.ones(n)
        lower_pivot_arr = lower_pivot.values
        upper_pivot_arr = upper_pivot.values
        body_low_arr = np.minimum(open_arr, close_arr)

        time_arr = [
            df["timestamp"].iloc[i] if "timestamp" in df.columns else ohlcv.index[i]
            for i in range(n)
        ]

        entries = pd.Series(False, index=df.index)
        exits = pd.Series(False, index=df.index)

        active_trades: list[dict[str, Any]] = []
        pending_setups: list[dict[str, Any]] = []
        completed_trades: list[dict[str, Any]] = []
        trade_id_counter = 0

        # -------------------------------------------------------------
        # 2. Main Simulation Loop (Bar-by-Bar)
        # -------------------------------------------------------------
        for i in range(n):
            current_time = time_arr[i]
            cur_open = open_arr[i]
            cur_high = high_arr[i]
            cur_low = low_arr[i]
            cur_close = close_arr[i]

            # --- A. Check Exits on Active Trades ---
            closed_trades = []
            for trade in active_trades:
                target_hit = cur_high >= trade["tp_price"]
                stop_hit = cur_low <= trade["active_sl"]

                if target_hit or stop_hit:
                    exits.iloc[i] = True
                    exit_price = trade["tp_price"] if target_hit else trade["active_sl"]
                    pnl_points = exit_price - trade["entry_price"]
                    monetary_pnl = pnl_points * trade["size"]
                    r_mult = pnl_points / trade["active_risk"] if trade["active_risk"] > 0 else np.nan

                    trade_rec = dict(trade)
                    trade_rec["exit_bar"] = i
                    trade_rec["exit_time"] = current_time
                    trade_rec["exit_price"] = exit_price
                    trade_rec["exit_reason"] = "TP" if target_hit else "SL"
                    trade_rec["pnl"] = monetary_pnl
                    trade_rec["realized_pnl"] = pnl_points
                    trade_rec["return_pct"] = (exit_price / trade["entry_price"] - 1.0) * 100.0
                    trade_rec["r_multiple"] = r_mult
                    trade_rec["is_win"] = 1 if target_hit else -1
                    trade_rec["status"] = "CLOSED"
                    trade_rec["holding_bars"] = i - trade["entry_bar"]

                    completed_trades.append(trade_rec)
                    closed_trades.append(trade)

            for ct in closed_trades:
                active_trades.remove(ct)

            # --- B. Execute Pending Setups at Bar +3 Open ---
            ready_setups = [s for s in pending_setups if s["target_bar"] == i]
            for setup in ready_setups:
                pending_setups.remove(setup)

                entry_price_val = round(float(cur_open), 5)
                setup_upper = round(float(setup["upper_pivot"]), 5)
                setup_lower = round(float(setup["lower_pivot"]), 5)

                orig_sig_bar = setup["orig_signal_bar"]
                # Swing low across elapsed closed bars [signal_bar : entry_bar]
                prior_body_min = float(np.min(body_low_arr[orig_sig_bar:i]))
                swing_low_val = prior_body_min

                half_range = 0.5 * (setup_upper - setup_lower)
                safe_sl_val = round(swing_low_val - half_range, 5)
                pivot_sl_val = setup_lower

                risk_safe_val = max(entry_price_val - safe_sl_val, 1e-6)
                risk_pivot_val = max(entry_price_val - pivot_sl_val, 1e-6)
                proj_rr_safe = (setup_upper - entry_price_val) / risk_safe_val

                # Core Rule: Dynamic SL Adaptation on Sub-1.0 Projected R:R
                if proj_rr_safe < 1.0 and pivot_sl_val < entry_price_val:
                    active_sl_val = pivot_sl_val
                    active_risk_val = risk_pivot_val
                    sl_mode_val = "PIVOT"
                else:
                    active_sl_val = safe_sl_val
                    active_risk_val = risk_safe_val
                    sl_mode_val = "SAFE"

                active_sl_val = round(active_sl_val, 5)

                # Stop Level Validation (matches MT5 Invalid Stops error 10016)
                if setup_upper <= entry_price_val or active_sl_val >= entry_price_val:
                    continue

                # Forex Weekend Session Filter (trading closed Friday >= 21:00 broker time, MT5 10018)
                if hasattr(current_time, "weekday") and current_time.weekday() == 4 and current_time.hour >= 21:
                    continue

                trade_id_counter += 1
                entries.iloc[i] = True

                size_val = risk_per_trade / active_risk_val
                lot_size_val = size_val / 100000.0

                trade_obj = {
                    "trade_id": trade_id_counter,
                    "signal_time": setup["signal_time"],
                    "confirmation_time": current_time,
                    "entry_bar": i,
                    "entry_time": current_time,
                    "entry_price": entry_price_val,
                    "tp_price": setup_upper,
                    "safe_sl": safe_sl_val,
                    "pivot_sl": pivot_sl_val,
                    "active_sl": active_sl_val,
                    "active_risk": active_risk_val,
                    "sl_mode": sl_mode_val,
                    "swing_low": swing_low_val,
                    "size": size_val,
                    "lot_size": lot_size_val,
                    "projected_rr_safe": proj_rr_safe,
                    "status": "OPEN",
                }
                active_trades.append(trade_obj)

            # --- C. Detect New Setup Signal (Close <= Lower Pivot, Concurrent) ---
            is_active_bar = (volume_arr[i] > 0 and high_arr[i] > low_arr[i]) if filter_zero_volume else True
            if (not np.isnan(lower_pivot_arr[i])) and (cur_close <= lower_pivot_arr[i]) and is_active_bar:
                pending_setups.append({
                    "orig_signal_bar": i,
                    "signal_time": current_time,
                    "target_bar": i + 4,
                    "lower_pivot": lower_pivot_arr[i],
                    "upper_pivot": upper_pivot_arr[i],
                })

            # --- D. Same Bar Exit Check (Optional) ---
            if allow_same_bar_exit:
                closed_same_bar = []
                for trade in active_trades:
                    if trade["entry_bar"] == i:
                        target_hit = cur_high >= trade["tp_price"]
                        stop_hit = cur_low <= trade["active_sl"]
                        if target_hit or stop_hit:
                            exits.iloc[i] = True
                            exit_price = trade["tp_price"] if target_hit else trade["active_sl"]
                            pnl_points = exit_price - trade["entry_price"]
                            monetary_pnl = pnl_points * trade["size"]
                            r_mult = pnl_points / trade["active_risk"] if trade["active_risk"] > 0 else np.nan

                            trade_rec = dict(trade)
                            trade_rec["exit_bar"] = i
                            trade_rec["exit_time"] = current_time
                            trade_rec["exit_price"] = exit_price
                            trade_rec["exit_reason"] = "TP" if target_hit else "SL"
                            trade_rec["pnl"] = monetary_pnl
                            trade_rec["realized_pnl"] = pnl_points
                            trade_rec["return_pct"] = (exit_price / trade["entry_price"] - 1.0) * 100.0
                            trade_rec["r_multiple"] = r_mult
                            trade_rec["is_win"] = 1 if target_hit else -1
                            trade_rec["status"] = "CLOSED"
                            trade_rec["holding_bars"] = 0

                            completed_trades.append(trade_rec)
                            closed_same_bar.append(trade)

                for ct in closed_same_bar:
                    active_trades.remove(ct)

        entries.index = ohlcv.index
        exits.index = ohlcv.index
        self.completed_trades = completed_trades

        trades_df = pd.DataFrame(completed_trades) if completed_trades else pd.DataFrame()
        return entries, exits, trades_df


# Aliases
CFMV0601C = CFMV0601C1
CFMV0601C_1 = CFMV0601C1
ClassicFloorModV6_1ConcurrentLight = CFMV0601C1
