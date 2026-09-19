"""CFMV0601NB-1 — Classic Floor Mod V6.1 Non-Blocking (Concurrent) Core Strategy.

Streamlined implementation containing strictly the CORE STRATEGY LOGIC:
- 20-period Rolling Classic Floor Pivots (Shifted 1 bar, zero lookahead)
- Setup Signal: Close <= Lower Pivot
- 3-Bar Confirmation: Enter on Bar +3 Open
- Dynamic Stop-Loss Adaptation: Switches from safe_sl to pivot_sl if projected_rr_safe < 1.0 (with entry_price > pivot_sl sanity guard)
- Non-Blocking: Supports multiple concurrent pending setups and active trades
- Fixes entry candle lookahead bias in swing_low calculation
- Omit all auxiliary calculations (no candlestick patterns, no runner/in-trade Fibonacci grids, no session tagging)
"""

from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd


class CFMV0601NB1:
    """Core Classic Floor Mod V6.1 Non-Blocking (Concurrent) Strategy."""

    name = "CFMV0601NB-1"
    version = "6.1.0-nb1"
    warmup_candles = 22

    def __init__(
        self,
        risk_per_trade: float = 100.0,
        filter_zero_volume: bool = True,
        allow_same_bar_exit: bool = False,
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
        """Execute non-blocking core signal generation and trade simulation."""
        risk_per_trade = float((params or {}).get("risk_per_trade", self.risk_per_trade))
        filter_zero_volume = bool((params or {}).get("filter_zero_volume", self.filter_zero_volume))
        allow_same_bar_exit = bool((params or {}).get("allow_same_bar_exit", self.allow_same_bar_exit))

        if ohlcv.empty:
            empty_s = pd.Series(dtype=bool)
            return empty_s, empty_s, pd.DataFrame()

        df = ohlcv.copy().reset_index(drop=True)
        n = len(df)

        # -------------------------------------------------------------
        # 1. Core Pivot Math (20-period rolling, shifted by 1 bar)
        # -------------------------------------------------------------
        high20 = df["high"].rolling(20).max().shift(1)
        low20 = df["low"].rolling(20).min().shift(1)
        prev_close = df["close"].shift(1)

        pivot = (high20 + low20 + prev_close) / 3.0
        lower_pivot = (pivot * 2.0) - high20  # Canonical Support line
        upper_pivot = (pivot * 2.0) - low20   # Canonical Resistance line / Target

        open_arr = df["open"].values
        high_arr = df["high"].values
        low_arr = df["low"].values
        close_arr = df["close"].values
        volume_arr = df["volume"].values if "volume" in df.columns else np.ones(n)
        lower_pivot_arr = lower_pivot.values
        upper_pivot_arr = upper_pivot.values
        pivot_arr = pivot.values

        # Candle body lows for swing_low calculation
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
                    h_bars = i - trade["entry_bar"]

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
                    trade_rec["holding_bars"] = h_bars

                    completed_trades.append(trade_rec)
                    closed_trades.append(trade)

            for ct in closed_trades:
                active_trades.remove(ct)

            # --- B. Execute Ready Setups at Bar +3 Open ---
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

                # Lookahead-safe swing_low: uses closed bars [orig_sig_bar : i] plus entry open
                prior_closed_body_min = float(np.min(body_low_arr[orig_sig_bar:i]))
                swing_low_val = min(prior_closed_body_min, entry_price_val)

                half_range = 0.5 * (setup_upper - setup_lower)
                safe_sl_val = swing_low_val - half_range
                primary_sl_val = float(close_arr[orig_sig_bar])
                pivot_sl_val = float(setup_lower)

                risk_safe_val = max(entry_price_val - safe_sl_val, 1e-6)
                risk_primary_val = max(entry_price_val - primary_sl_val, 1e-6)
                risk_pivot_val = max(entry_price_val - pivot_sl_val, 1e-6)

                proj_rr_safe = (setup_upper - entry_price_val) / risk_safe_val
                proj_rr_primary = (setup_upper - entry_price_val) / risk_primary_val

                # Dynamic SL Adaptation: If projected_rr_safe < 1.0 AND pivot_sl is below entry
                if proj_rr_safe < 1.0 and pivot_sl_val < entry_price_val:
                    active_sl_val = pivot_sl_val
                    active_risk_val = risk_pivot_val
                    sl_mode_val = "PIVOT"
                else:
                    active_sl_val = safe_sl_val
                    active_risk_val = risk_safe_val
                    sl_mode_val = "SAFE"

                size_val = risk_per_trade / active_risk_val
                lot_size_val = size_val / 100000.0

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
                    "active_sl": active_sl_val,
                    "active_risk": active_risk_val,
                    "sl_mode": sl_mode_val,
                    "swing_low": swing_low_val,
                    "risk_safe": risk_safe_val,
                    "risk_primary": risk_primary_val,
                    "risk_pivot": risk_pivot_val,
                    "size": size_val,
                    "lot_size": lot_size_val,
                    "risk_amount": active_risk_val * size_val,
                    "projected_rr_safe": proj_rr_safe,
                    "projected_rr_primary": proj_rr_primary,
                    "status": "OPEN",
                }
                active_trades.append(trade_obj)

            # --- C. Detect New Setup Signal (Close <= Lower Pivot, Non-Blocking) ---
            is_active_bar = (volume_arr[i] > 0 and high_arr[i] > low_arr[i]) if filter_zero_volume else True
            signal_condition = (
                (not np.isnan(lower_pivot_arr[i]))
                and (cur_close <= lower_pivot_arr[i])
                and is_active_bar
            )

            if signal_condition:
                pending_setups.append({
                    "orig_signal_bar": i,
                    "signal_time": current_time,
                    "target_bar": i + 3,
                    "lower_pivot": lower_pivot_arr[i],
                    "upper_pivot": upper_pivot_arr[i],
                    "pivot": pivot_arr[i],
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

        # Convert completed trades to DataFrame
        trades_df = pd.DataFrame(completed_trades) if completed_trades else pd.DataFrame()

        return entries, exits, trades_df


# Aliases
CFMV0601NB = CFMV0601NB1
ClassicFloorModV6_1ConcurrentCore = CFMV0601NB1


if __name__ == "__main__":
    import duckdb

    duckdb_path = "Shared/Data/Classic_floor_v6.duckdb"
    try:
        con = duckdb.connect(duckdb_path, read_only=True)
        ohlcv_df = con.execute('SELECT * FROM "ohlcv" ORDER BY timestamp').df()
        con.close()
        print(f"Loaded OHLCV from {duckdb_path}: {len(ohlcv_df)} bars.")

        strat = CFMV0601NB1(risk_per_trade=100.0)
        entries, exits, trades = strat.generate_signals(ohlcv_df)

        print(f"Completed Trades: {len(strat.completed_trades)}")
        print(f"Total Wins: {sum(1 for t in strat.completed_trades if t['is_win'] == 1)}")
        print(f"Total Losses: {sum(1 for t in strat.completed_trades if t['is_win'] == -1)}")
        print(f"Total Net PnL ($): ${sum(t['pnl'] for t in strat.completed_trades):.2f}")
        print("\nSample Completed Trades (First 3):")
        for t in strat.completed_trades[:3]:
            print({k: t[k] for k in ["trade_id", "signal_time", "entry_time", "entry_price", "exit_price", "sl_mode", "pnl", "exit_reason"]})
    except Exception as exc:
        print(f"Standalone run without duckdb: {exc}")
