import pandas as pd
import numpy as np
try:
    import pandas_ta_classic as ta
except ImportError:
    ta = None

class ClassicFloorModV2:
    name = "classic_floor_mod_v2"
    warmup_candles = 22

    def generate_signals(self, ohlcv: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
        """
        ClassicFloorModV2 (exp-3): Updated strategy in exp-3 with 3-candle pattern state classification
        and dynamic DR-DR-DR delay logic.
        - Core Pivot math: Pivot, S1, R1 (20-period lookback, shifted by 1)
        - Scheduled Entry at Bar +3
        - DR-DR-DR Pattern Check: If pre-entry 3-candle setup (entry_1) is DR-DR-DR, delay entry by 3 additional candles
        - Dynamic Stop Loss (lower of signal & entry body low minus half R1-S1 range)
        - Take Profit at frozen R1
        """
        if ohlcv.empty:
            empty_series = pd.Series(dtype=bool)
            return empty_series, empty_series, pd.DataFrame()

        df = ohlcv.copy().reset_index(drop=True)

        # 1. CLASSIC FLOOR TRADER PIVOTS via pandas_ta_classic / pandas rolling calculations
        # 20-period lookback, shifted by 1 bar
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

        # Output signal arrays
        entries = pd.Series(False, index=df.index)
        exits = pd.Series(False, index=df.index)

        n = len(df)
        open_arr = df['open'].values
        high_arr = df['high'].values
        low_arr = df['low'].values
        close_arr = df['close'].values
        s1_arr = df['s1'].values
        r1_arr = df['r1'].values
        body_low_arr = df['body_low'].values

        waiting_for_entry = False
        in_trade = False
        trade_id_counter = 0

        signal_bar = None
        setup_s1 = None
        setup_r1 = None
        signal_body_low = None

        stop_price = None
        target_price = None
        entry_price_val = None

        # Analytics / Trade Execution arrays
        in_trade_series = np.full(n, False)
        trade_id_series = np.full(n, np.nan)
        entry_price_series = np.full(n, np.nan)
        sl_series = np.full(n, np.nan)
        tp_series = np.full(n, np.nan)
        exit_price_series = np.full(n, np.nan)
        realized_pnl_series = np.full(n, np.nan)
        realized_pnl_pct_series = np.full(n, np.nan)
        is_win_series = np.full(n, 0)
        exit_reason_series = np.full(n, "", dtype=object)

        for i in range(n):
            if in_trade:
                in_trade_series[i] = True
                trade_id_series[i] = trade_id_counter
                entry_price_series[i] = entry_price_val
                sl_series[i] = stop_price
                tp_series[i] = target_price

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

                    waiting_for_entry = False
                    signal_bar = None
                    setup_s1 = None
                    setup_r1 = None
                    signal_body_low = None
                    stop_price = None
                    target_price = None
                    entry_price_val = None
                    continue

            # Signal Condition (Bar 0: close <= s1)
            signal_condition = (not np.isnan(s1_arr[i])) and (close_arr[i] <= s1_arr[i]) and (not waiting_for_entry) and (not in_trade)

            if signal_condition:
                waiting_for_entry = True
                signal_bar = i
                setup_s1 = s1_arr[i]
                setup_r1 = r1_arr[i]
                signal_body_low = body_low_arr[i]

            # Entry evaluation at scheduled entry bar (default: signal_bar + 3)
            if waiting_for_entry and (signal_bar is not None) and (i == signal_bar + 3):
                # If pre-entry 3-candle setup (entry_1) is DR-DR-DR, delay entry by 3 additional candles
                if df['entry_1'].iloc[i] == 'DR-DR-DR':
                    signal_bar = signal_bar + 3  # Shift scheduled entry bar to signal_bar + 6
                else:
                    waiting_for_entry = False
                    in_trade = True
                    trade_id_counter += 1

                    entry_body_low = body_low_arr[i]
                    sl_anchor = min(signal_body_low, entry_body_low)
                    sl_distance = (setup_r1 - setup_s1) / 2.0

                    entry_price_val = open_arr[i]
                    stop_price = sl_anchor - sl_distance
                    target_price = setup_r1

                    in_trade_series[i] = True
                    trade_id_series[i] = trade_id_counter
                    entry_price_series[i] = entry_price_val
                    sl_series[i] = stop_price
                    tp_series[i] = target_price
                    entries.iloc[i] = True

                    # Check intrabar exit on entry bar
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

                        signal_bar = None
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

        # Indicator Columns
        trades_df['candle_state'] = df['candle_state'].values
        trades_df['entry_1'] = df['entry_1'].values
        trades_df['entry_2'] = df['entry_2'].values
        trades_df['entry_3'] = df['entry_3'].values
        trades_df['entry_4'] = df['entry_4'].values

        entries.index = ohlcv.index
        exits.index = ohlcv.index

        return entries, exits, trades_df
