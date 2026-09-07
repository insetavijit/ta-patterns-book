import pandas as pd
import numpy as np
import pandas_ta_classic as ta

class ClassicFloorModV3:
    name = "classic_floor_mod_v3"
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
        ClassicFloorModV3: Strategy entering on the 3rd candle's open from signal.
        - Core Pivot math: Pivot, S1, R1 (20-period lookback, shifted by 1)
        - Signal Candle (Bar 0): close <= S1
        - Wait period: Bar +1 and Bar +2
        - Entry at Bar +3 Open (identical to Bar +2 Close in continuous market data)
        - Dynamic Stop Loss: lower of signal body low & 2nd candle body low minus half (R1 - S1) range
        - Take Profit at frozen R1
        - allow_same_bar_exit: if False (default), holds trade at least 1 candle, suppressing new signals
        - filter_zero_volume: if True (default), suppresses phantom entries on flat-line / 0-volume closed market bars
        - Clean raw trade execution table output.
        """
        allow_same_bar_exit = (params or {}).get("allow_same_bar_exit", self.allow_same_bar_exit)
        filter_zero_volume = (params or {}).get("filter_zero_volume", self.filter_zero_volume)
        if ohlcv.empty:
            empty_series = pd.Series(dtype=bool)
            return empty_series, empty_series, pd.DataFrame()

        df = ohlcv.copy().reset_index(drop=True)

        # 1. CLASSIC FLOOR TRADER PIVOTS via pandas rolling calculations
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
        in_trade = False
        trade_id_counter = 0

        signal_bar = None
        setup_s1 = None
        setup_r1 = None
        signal_body_low = None
        setup_c2_body_low = None

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
                    setup_c2_body_low = None
                    stop_price = None
                    target_price = None
                    entry_price_val = None
                    continue

            # Signal Condition (Bar 0: close <= s1)
            is_active_bar = (volume_arr[i] > 0 and high_arr[i] > low_arr[i]) if filter_zero_volume else True
            signal_condition = (not np.isnan(s1_arr[i])) and (close_arr[i] <= s1_arr[i]) and (not waiting_for_entry) and (not in_trade) and is_active_bar

            if signal_condition:
                waiting_for_entry = True
                signal_bar = i
                setup_s1 = s1_arr[i]
                setup_r1 = r1_arr[i]
                signal_body_low = body_low_arr[i]
                setup_c2_body_low = None

            # Track 2nd candle body low (signal_bar + 2)
            if waiting_for_entry and (signal_bar is not None) and (i == signal_bar + 2):
                setup_c2_body_low = body_low_arr[i]

            # Entry at 3rd Candle Open (signal_bar + 3)
            if waiting_for_entry and (signal_bar is not None) and (i == signal_bar + 3):
                waiting_for_entry = False
                in_trade = True
                trade_id_counter += 1

                c2_low = setup_c2_body_low if setup_c2_body_low is not None else body_low_arr[i - 1]
                sl_anchor = min(signal_body_low, c2_low)
                sl_distance = (setup_r1 - setup_s1) / 2.0

                entry_price_val = open_arr[i]  # 3rd candle's open (same as 2nd candle's close)
                stop_price = sl_anchor - sl_distance
                target_price = setup_r1

                in_trade_series[i] = True
                trade_id_series[i] = trade_id_counter
                entry_price_series[i] = entry_price_val
                sl_series[i] = stop_price
                tp_series[i] = target_price
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

                        signal_bar = None
                        setup_s1 = None
                        setup_r1 = None
                        signal_body_low = None
                        setup_c2_body_low = None
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

        entries.index = ohlcv.index
        exits.index = ohlcv.index

        return entries, exits, trades_df
