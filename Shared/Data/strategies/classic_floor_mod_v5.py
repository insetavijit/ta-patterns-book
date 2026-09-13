import sys
from pathlib import Path
import numpy as np
import pandas as pd

# Ensure Core is available for pattern calculation
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "Core") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "Core"))

try:
    from ta_patterns_book.loss_profile.candles import compute_candlestick_pattern_columns
except ImportError:
    compute_candlestick_pattern_columns = None


FIB_RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)


class ClassicFloorModV5:
    name = "classic_floor_mod_v5"
    warmup_candles = 22

    def __init__(self, allow_same_bar_exit: bool = False, filter_zero_volume: bool = True):
        self.allow_same_bar_exit = allow_same_bar_exit
        self.filter_zero_volume = filter_zero_volume

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict | None = None,
    ) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
        """
        ClassicFloorModV5: Clean deterministic baseline strategy.
        - Core Pivot math: Pivot, S1, R1 (20-period lookback, shifted by 1)
        - Signal Candle: Bar 0 where close <= S1
        - Confirmation Candle & Scheduled Entry: Strictly Bar +3 Open (4th candle from signal).
          No delay filters and no cancellation rules.
        - Swing Low: min(body_low) across bars 0..3 inclusive (Signal through Confirmation/Entry).
        - Dynamic Stop Loss: swing_low minus half (R1 - S1) range
        - Take Profit: frozen R1
        - 4 Confirmation-Anchored Patterns (epatt_1..4)
        - 6 Candlestick Patterns (ecpatt_1..3 and epcpatt_1..3)
        """
        allow_same_bar_exit = (params or {}).get("allow_same_bar_exit", self.allow_same_bar_exit)
        filter_zero_volume = (params or {}).get("filter_zero_volume", self.filter_zero_volume)
        if ohlcv.empty:
            empty_series = pd.Series(dtype=bool)
            return empty_series, empty_series, pd.DataFrame()

        df = ohlcv.copy().reset_index(drop=True)

        # 1. CLASSIC FLOOR TRADER PIVOTS via rolling calculations
        high20 = df['high'].rolling(20).max().shift(1)
        low20 = df['low'].rolling(20).min().shift(1)
        prev_close = df['close'].shift(1)

        pivot = (high20 + low20 + prev_close) / 3
        s1 = (pivot * 2) - high20
        r1 = (pivot * 2) - low20

        df['pivot'] = pivot
        df['s1'] = s1
        df['r1'] = r1
        df['body_low'] = np.minimum(df['open'], df['close'])

        # 2. CANDLE STATE & 3-CANDLE PATTERN CLASSIFICATION INDICATORS
        prev_close_bar = df['close'].shift(1)
        prev_close_bar.iloc[0] = df['open'].iloc[0]

        is_up = df['close'] >= prev_close_bar
        is_green = df['close'] > df['open']
        dir_str = np.where(is_up, "U", "D")
        col_str = np.where(is_green, "G", "R")
        df['candle_state'] = dir_str + col_str

        # Confirmation-anchored patterns (epatt_1 to epatt_4)
        cs = df['candle_state']
        df['epatt_1'] = cs.shift(3) + "-" + cs.shift(2) + "-" + cs.shift(1)
        df['epatt_2'] = cs.shift(2) + "-" + cs.shift(1) + "-" + cs
        df['epatt_3'] = cs.shift(1) + "-" + cs + "-" + cs.shift(-1)
        df['epatt_4'] = cs + "-" + cs.shift(-1) + "-" + cs.shift(-2) + "-" + cs.shift(-3)

        # Also maintain entry_1..4 for full backward compatibility with loss_profile tools
        df['entry_1'] = df['epatt_1']
        df['entry_2'] = df['epatt_2']
        df['entry_3'] = df['epatt_3']
        df['entry_4'] = df['epatt_4']

        # 3. Calculate 6 Candlestick Patterns
        if compute_candlestick_pattern_columns is not None:
            patt_df = compute_candlestick_pattern_columns(df)
        else:
            patt_df = pd.DataFrame(
                np.nan,
                index=df.index,
                columns=['ecpatt_1', 'ecpatt_2', 'ecpatt_3', 'epcpatt_1', 'epcpatt_2', 'epcpatt_3']
            )

        entries = pd.Series(False, index=df.index)
        exits = pd.Series(False, index=df.index)

        n = len(df)
        open_arr = df['open'].values
        high_arr = df['high'].values
        low_arr = df['low'].values
        close_arr = df['close'].values
        volume_arr = df['volume'].values if 'volume' in df.columns else np.ones(n)
        s1_arr = df['s1'].values
        r1_arr = df['r1'].values
        pivot_arr = df['pivot'].values
        body_low_arr = df['body_low'].values

        waiting_for_entry = False
        in_trade = False
        trade_id_counter = 0

        orig_signal_bar = None
        current_target_bar = None
        setup_s1 = None
        setup_r1 = None
        setup_pivot = None
        stop_price = None
        target_price = None
        entry_price_val = None
        signal_time_val = None
        confirmation_time_val = None
        swing_low_val = None
        trade_entry_bar = None
        fib_levels = None
        first_touch_bar = None

        # Bar-aligned series arrays (same length n as ohlcv)
        in_trade_series = np.zeros(n, dtype=bool)
        trade_id_series = np.zeros(n, dtype=int)
        entry_price_series = np.full(n, np.nan)
        sl_series = np.full(n, np.nan)
        tp_series = np.full(n, np.nan)
        exit_price_series = np.full(n, np.nan)
        exit_reason_series = np.full(n, None, dtype=object)
        realized_pnl_series = np.full(n, np.nan)
        realized_pnl_pct_series = np.full(n, np.nan)
        is_win_series = np.zeros(n, dtype=int)
        signal_time_series = [None] * n
        confirmation_time_series = [None] * n
        swing_low_series = np.full(n, np.nan)
        fib_bsl_series = np.full(n, np.nan)
        fib_bsl_ambig_series = np.zeros(n, dtype=bool)

        for i in range(n):
            current_time = df['timestamp'].iloc[i] if 'timestamp' in df.columns else ohlcv.index[i]
            cur_open = open_arr[i]
            cur_high = high_arr[i]
            cur_low = low_arr[i]

            # In-trade position management (exits evaluated first)
            if in_trade:
                in_trade_series[i] = True
                trade_id_series[i] = trade_id_counter
                entry_price_series[i] = entry_price_val
                sl_series[i] = stop_price
                tp_series[i] = target_price
                signal_time_series[i] = signal_time_val
                confirmation_time_series[i] = confirmation_time_val
                swing_low_series[i] = swing_low_val

                # Track Fibonacci level touches on this candle
                if fib_levels is not None:
                    for j in range(5):
                        eps = max(fib_levels[j] * 1e-7, 1e-9)
                        if first_touch_bar[j] == -1 and cur_high >= fib_levels[j] - eps:
                            first_touch_bar[j] = i

                target_hit = cur_high >= target_price
                stop_hit = cur_low <= stop_price

                if target_hit or stop_hit:
                    exits.iloc[i] = True
                    in_trade = False

                    exit_price = target_price if target_hit else stop_price
                    pnl = exit_price - entry_price_val
                    pnl_pct = (pnl / entry_price_val) * 100.0

                    exit_price_series[i] = exit_price
                    realized_pnl_series[i] = pnl
                    realized_pnl_pct_series[i] = pnl_pct
                    is_win_series[i] = 1 if target_hit else -1
                    exit_reason_series[i] = "TP" if target_hit else "SL"

                    # Compute fib_bsl
                    if target_hit:
                        f_bsl = 0.786
                        f_ambig = False
                    else:
                        sl_bar = i
                        reached = [FIB_RATIOS[j] for j in range(5) if first_touch_bar is not None and first_touch_bar[j] != -1 and first_touch_bar[j] < sl_bar]
                        f_bsl = max(reached) if reached else 0.0
                        tied = [FIB_RATIOS[j] for j in range(5) if first_touch_bar is not None and first_touch_bar[j] == sl_bar]
                        f_ambig = bool(tied and max(tied) > f_bsl)

                    fib_bsl_series[i] = f_bsl
                    fib_bsl_ambig_series[i] = f_ambig
                    if trade_entry_bar is not None and trade_entry_bar < n:
                        fib_bsl_series[trade_entry_bar] = f_bsl
                        fib_bsl_ambig_series[trade_entry_bar] = f_ambig

                    orig_signal_bar = None
                    current_target_bar = None
                    setup_s1 = None
                    setup_r1 = None
                    setup_pivot = None
                    stop_price = None
                    target_price = None
                    entry_price_val = None
                    trade_entry_bar = None
                    fib_levels = None
                    first_touch_bar = None
                    continue

            # Signal Condition (Bar 0: close <= s1)
            is_active_bar = (volume_arr[i] > 0 and high_arr[i] > low_arr[i]) if filter_zero_volume else True
            signal_condition = (not np.isnan(s1_arr[i])) and (close_arr[i] <= s1_arr[i]) and (not waiting_for_entry) and (not in_trade) and is_active_bar

            if signal_condition:
                waiting_for_entry = True
                orig_signal_bar = i
                signal_time_val = current_time
                current_target_bar = i + 3  # Confirmation candle is strictly at i + 3 (4th candle)
                setup_s1 = s1_arr[i]
                setup_r1 = r1_arr[i]
                setup_pivot = pivot_arr[i]

            # Confirmation Candle Open Execution (Strictly at current_target_bar)
            if waiting_for_entry and i == current_target_bar:
                waiting_for_entry = False
                in_trade = True
                trade_id_counter += 1
                trade_entry_bar = i
                entries.iloc[i] = True

                confirmation_time_val = current_time
                entry_price_val = cur_open

                # Swing Low = lowest body_low from signal bar through confirmation bar (0..3)
                swing_low_val = float(np.min(body_low_arr[orig_signal_bar:i + 1]))
                half_range = 0.5 * (setup_r1 - setup_s1)
                stop_price = swing_low_val - half_range
                target_price = setup_r1

                # Record on entry bar
                trade_id_series[i] = trade_id_counter
                entry_price_series[i] = entry_price_val
                sl_series[i] = stop_price
                tp_series[i] = target_price
                signal_time_series[i] = signal_time_val
                confirmation_time_series[i] = confirmation_time_val
                swing_low_series[i] = swing_low_val

                # Pre-calculate Fibonacci levels
                fib_levels = [entry_price_val + r * (target_price - entry_price_val) for r in FIB_RATIOS]
                first_touch_bar = [-1] * 5

        # Build Clean Strategy Trade Table aligned with ohlcv.index
        trades_df = pd.DataFrame(index=ohlcv.index)
        trades_df['pivot'] = pivot.values
        trades_df['s1'] = s1.values
        trades_df['r1'] = r1.values
        trades_df['upper_pivot'] = r1.values
        trades_df['lower_pivot'] = s1.values
        trades_df['entries'] = entries.values
        trades_df['exits'] = exits.values
        trades_df['in_trade'] = in_trade_series
        trades_df['trade_id'] = trade_id_series
        trades_df['entry_price'] = entry_price_series
        trades_df['sl_price'] = sl_series
        trades_df['tp_price'] = tp_series
        trades_df['exit_price'] = exit_price_series
        trades_df['exit_reason'] = exit_reason_series
        trades_df['realized_pnl'] = realized_pnl_series
        trades_df['realized_pnl_pct'] = realized_pnl_pct_series
        trades_df['is_win'] = is_win_series
        trades_df['signal_time'] = signal_time_series
        trades_df['confirmation_time'] = confirmation_time_series
        trades_df['swing_low'] = swing_low_series
        trades_df['fib_bsl'] = fib_bsl_series
        trades_df['fib_bsl_ambiguous'] = fib_bsl_ambig_series

        # Attach Confirmation-Anchored 3-Candle Patterns (epatt_1..4 and entry_1..4)
        trades_df['epatt_1'] = df['epatt_1'].values
        trades_df['epatt_2'] = df['epatt_2'].values
        trades_df['epatt_3'] = df['epatt_3'].values
        trades_df['epatt_4'] = df['epatt_4'].values
        trades_df['entry_1'] = df['entry_1'].values
        trades_df['entry_2'] = df['entry_2'].values
        trades_df['entry_3'] = df['entry_3'].values
        trades_df['entry_4'] = df['entry_4'].values

        # Attach 6 Candlestick Patterns
        trades_df['ecpatt_1'] = patt_df['ecpatt_1'].values
        trades_df['ecpatt_2'] = patt_df['ecpatt_2'].values
        trades_df['ecpatt_3'] = patt_df['ecpatt_3'].values
        trades_df['epcpatt_1'] = patt_df['epcpatt_1'].values
        trades_df['epcpatt_2'] = patt_df['epcpatt_2'].values
        trades_df['epcpatt_3'] = patt_df['epcpatt_3'].values

        entries.index = ohlcv.index
        exits.index = ohlcv.index

        return entries, exits, trades_df
