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


class ClassicFloorModV4:
    name = "classic_floor_mod_v4"
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
        ClassicFloorModV4: Strategy entering on 3rd candle's open from signal,
        with dynamic delay & confirmation filters plus 6 single/double/triple candlestick pattern metrics:
        - Core Pivot math: Pivot, S1, R1 (20-period lookback, shifted by 1)
        - Scheduled Entry: Bar +3 Open
        - DR-DR-DR Filter: If pre-entry 3 candles (entry_1) are DR-DR-DR, delay entry by 3 additional candles
        - DR-UG-DR Filter: If entry_1 is DR-UG-DR, hold for next candle (Bar +1) to form.
          If that candle forms UG-DR-DR (closed down-red), delay entry for 2 additional candles.
          Else, enter immediately on the confirmed open.
        - DR-DR-UG Filter: If entry_1 is DR-DR-UG, hold for next candle (Bar +1) to form.
          If that candle forms DR-UG-DR (closed down-red), delay entry by 1 additional candle (enter at Signal + 5th candle Open).
          Else (green confirmation printed), enter immediately on the confirmed open.
        - UG-DR-UG Filter: If entry_1 is UG-DR-UG, hold for next candle (Bar +1) to form.
          If that candle forms DR-UG-DR (closed down-red), delay entry by 3 additional candles.
          Else (green confirmation printed, e.g. DR-UG-UG), enter immediately on the confirmed open.
        - Dynamic Stop Loss: lower of signal body low & lowest wait-candle body low minus half (R1 - S1) range
        - Take Profit at frozen R1
        - 6 Candlestick Pattern Metrics:
          * ecpatt_1: 1-candle pattern on entry bar (NaN if no pattern)
          * ecpatt_2: 2-candle pattern on entry bar (NaN if no pattern)
          * ecpatt_3: 3-candle pattern on entry bar (NaN if no pattern)
          * epcpatt_1: 1-candle pattern on previous setup bar (shift 1)
          * epcpatt_2: 2-candle pattern on previous setup bar (shift 1)
          * epcpatt_3: 3-candle pattern on previous setup bar (shift 1)
        """
        allow_same_bar_exit = (params or {}).get("allow_same_bar_exit", self.allow_same_bar_exit)
        filter_zero_volume = (params or {}).get("filter_zero_volume", self.filter_zero_volume)
        if ohlcv.empty:
            empty_series = pd.Series(dtype=bool)
            return empty_series, empty_series, pd.DataFrame()

        df = ohlcv.copy().reset_index(drop=True)

        # 1. CLASSIC FLOOR TRADER PIVOTS via rolling calculations
        high20 = df['high'].rolling(20).max().shift(1)
        low20  = df['low'].rolling(20).min().shift(1)
        prev_close = df['close'].shift(1)

        pivot = (high20 + low20 + prev_close) / 3
        s1 = (pivot * 2) - high20
        r1 = (pivot * 2) - low20

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

        # Calculate pattern variants (entry_1 to entry_4) for each bar
        cs = df['candle_state']
        df['entry_1'] = cs.shift(3) + "-" + cs.shift(2) + "-" + cs.shift(1)
        df['entry_2'] = cs.shift(2) + "-" + cs.shift(1) + "-" + cs
        df['entry_3'] = cs.shift(1) + "-" + cs + "-" + cs.shift(-1)
        df['entry_4'] = cs + "-" + cs.shift(-1) + "-" + cs.shift(-2) + "-" + cs.shift(-3)

        # 3. Calculate 6 Candlestick Patterns (ecpatt_1..3 and epcpatt_1..3)
        if compute_candlestick_pattern_columns is not None:
            patt_df = compute_candlestick_pattern_columns(df)
        else:
            patt_df = pd.DataFrame(
                np.nan,
                index=df.index,
                columns=['ecpatt_1', 'ecpatt_2', 'ecpatt_3', 'epcpatt_1', 'epcpatt_2', 'epcpatt_3']
            )

        # Output signal arrays
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
        body_low_arr = df['body_low'].values

        waiting_for_entry = False
        checking_drugdr = False
        checking_drdrug = False
        checking_ugdrug = False
        in_trade = False
        trade_id_counter = 0

        orig_signal_bar = None
        current_target_bar = None
        setup_s1 = None
        setup_r1 = None
        signal_body_low = None
        stop_price = None
        target_price = None
        entry_price_val = None
        signal_time_val = None

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

        for i in range(n):
            current_time = df['timestamp'].iloc[i] if 'timestamp' in df.columns else ohlcv.index[i]
            cur_open = open_arr[i]
            cur_high = high_arr[i]
            cur_low = low_arr[i]
            cur_vol = volume_arr[i]

            # In-trade position management (exits take precedence)
            if in_trade:
                in_trade_series[i] = True
                trade_id_series[i] = trade_id_counter
                entry_price_series[i] = entry_price_val
                sl_series[i] = stop_price
                tp_series[i] = target_price
                signal_time_series[i] = signal_time_val

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

                    orig_signal_bar = None
                    current_target_bar = None
                    setup_s1 = None
                    setup_r1 = None
                    signal_body_low = None
                    stop_price = None
                    target_price = None
                    entry_price_val = None
                continue

            # Signal Condition (Bar 0: close <= s1)
            is_active_bar = (volume_arr[i] > 0 and high_arr[i] > low_arr[i]) if filter_zero_volume else True
            signal_condition = (not np.isnan(s1_arr[i])) and (close_arr[i] <= s1_arr[i]) and (not waiting_for_entry) and (not in_trade) and is_active_bar

            if signal_condition:
                waiting_for_entry = True
                checking_drugdr = False
                checking_drdrug = False
                checking_ugdrug = False
                orig_signal_bar = i
                signal_time_val = current_time
                current_target_bar = i + 3
                setup_s1 = s1_arr[i]
                setup_r1 = r1_arr[i]
                signal_body_low = body_low_arr[i]

            # Scheduled Entry Evaluation
            if waiting_for_entry and i == current_target_bar:
                # 1. If we previously delayed 1 candle specifically to check UG-DR-UG confirmation
                if checking_ugdrug:
                    checking_ugdrug = False
                    if df['entry_1'].iloc[i] == 'DR-UG-DR':
                        current_target_bar = i + 3
                        continue

                # 2. If we previously delayed 1 candle specifically to check DR-DR-UG confirmation
                if checking_drdrug:
                    checking_drdrug = False
                    if df['entry_1'].iloc[i] == 'DR-UG-DR':
                        current_target_bar = i + 1
                        continue

                # 3. If we previously delayed 1 candle specifically to check DR-UG-DR confirmation
                if checking_drugdr:
                    checking_drugdr = False
                    if df['entry_1'].iloc[i] == 'UG-DR-DR':
                        current_target_bar = i + 2
                        continue

                # 4. Check if pre-entry 3-candle setup (entry_1) is DR-DR-DR
                if df['entry_1'].iloc[i] == 'DR-DR-DR':
                    current_target_bar = i + 3
                    continue

                # 5. Check if pre-entry 3-candle setup (entry_1) is DR-UG-DR
                if df['entry_1'].iloc[i] == 'DR-UG-DR':
                    checking_drugdr = True
                    current_target_bar = i + 1
                    continue

                # 6. Check if pre-entry 3-candle setup (entry_1) is DR-DR-UG
                if df['entry_1'].iloc[i] == 'DR-DR-UG':
                    checking_drdrug = True
                    current_target_bar = i + 1
                    continue

                # 7. Check if pre-entry 3-candle setup (entry_1) is UG-DR-UG
                if df['entry_1'].iloc[i] == 'UG-DR-UG':
                    checking_ugdrug = True
                    current_target_bar = i + 1
                    continue

                # Normal Entry Execution
                waiting_for_entry = False
                in_trade = True
                trade_id_counter += 1
                active_signal_time = signal_time_val

                # Dynamic Stop Loss
                wait_low = np.min(body_low_arr[orig_signal_bar + 1 : i]) if i > orig_signal_bar + 1 else body_low_arr[i - 1]
                sl_anchor = min(signal_body_low, wait_low)
                sl_distance = (setup_r1 - setup_s1) / 2.0

                entry_price_val = open_arr[i]
                stop_price = sl_anchor - sl_distance
                target_price = setup_r1

                in_trade_series[i] = True
                trade_id_series[i] = trade_id_counter
                entry_price_series[i] = entry_price_val
                sl_series[i] = stop_price
                tp_series[i] = target_price
                signal_time_series[i] = active_signal_time
                entries.iloc[i] = True

                # Check intrabar exit on entry bar (if allowed)
                if allow_same_bar_exit:
                    target_hit = high_arr[i] >= target_price
                    stop_hit = low_arr[i] <= stop_price
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

                        orig_signal_bar = None
                        current_target_bar = None
                        setup_s1 = None
                        setup_r1 = None
                        signal_body_low = None
                        stop_price = None
                        target_price = None
                        entry_price_val = None

        # Build Clean Strategy Trade Table
        trades_df = pd.DataFrame(index=ohlcv.index)
        trades_df['pivot'] = pivot.values
        trades_df['s1'] = s1.values
        trades_df['r1'] = r1.values
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

        # Attach 3-Candle State Patterns
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
