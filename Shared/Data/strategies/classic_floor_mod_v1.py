import pandas as pd
import numpy as np

class ClassicFloorModV1:
    name = "classic_floor_mod_v1"
    warmup_candles = 22

    def __init__(self, allow_same_bar_exit: bool = False, filter_zero_volume: bool = True):
        self.allow_same_bar_exit = allow_same_bar_exit
        self.filter_zero_volume = filter_zero_volume

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict | None = None,
    ) -> tuple[pd.Series, pd.Series]:
        """
        Generates buy entry and exit signals matching classic_floor_mod_v1.pine:
        - Pivot calculations: 20-period high/low/close shifted by 1 bar.
        - Signal candle: close <= S1.
        - Entry candle: 2nd candle after signal candle (Bar +2).
        - Target Price (TP): Frozen R1 level from the signal bar.
        - Stop Loss (SL): slAnchor - slDistance
            where slAnchor = min(signal_body_low, entry_body_low)
            and slDistance = (setup_R1 - setup_S1) / 2
        - allow_same_bar_exit: if False (default), holds trade at least 1 candle, suppressing new signals
        - filter_zero_volume: if True (default), suppresses phantom entries on flat-line / 0-volume closed market bars
        """
        allow_same_bar_exit = (params or {}).get("allow_same_bar_exit", self.allow_same_bar_exit)
        filter_zero_volume = (params or {}).get("filter_zero_volume", self.filter_zero_volume)
        if ohlcv.empty:
            empty_series = pd.Series(dtype=bool)
            return empty_series, empty_series

        df = ohlcv.copy().reset_index(drop=True)

        # 1. CLASSIC FLOOR TRADER PIVOTS (20-period lookback, shifted by 1)
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

        # State tracking variables matching Pine Script
        waiting_for_entry = False
        in_trade = False

        signal_bar = None
        setup_s1 = None
        setup_r1 = None
        signal_body_low = None

        stop_price = None
        target_price = None

        n = len(df)
        open_arr = df['open'].values
        high_arr = df['high'].values
        low_arr = df['low'].values
        close_arr = df['close'].values
        volume_arr = df['volume'].values if 'volume' in df.columns else np.ones(n)
        s1_arr = df['s1'].values
        r1_arr = df['r1'].values
        body_low_arr = df['body_low'].values

        for i in range(n):
            # Check if in trade and hit TP/SL first
            if in_trade:
                target_hit = high_arr[i] >= target_price
                stop_hit = low_arr[i] <= stop_price

                if target_hit or stop_hit:
                    exits.iloc[i] = True
                    in_trade = False
                    waiting_for_entry = False
                    signal_bar = None
                    setup_s1 = None
                    setup_r1 = None
                    signal_body_low = None
                    stop_price = None
                    target_price = None
                    continue

            # 3. SIGNAL CANDLE
            # close <= s1 and not waitingForEntry and not inTrade
            is_active_bar = (volume_arr[i] > 0 and high_arr[i] > low_arr[i]) if filter_zero_volume else True
            signal_condition = (not np.isnan(s1_arr[i])) and (close_arr[i] <= s1_arr[i]) and (not waiting_for_entry) and (not in_trade) and is_active_bar

            if signal_condition:
                waiting_for_entry = True
                signal_bar = i
                setup_s1 = s1_arr[i]
                setup_r1 = r1_arr[i]
                signal_body_low = body_low_arr[i]

            # 4. SECOND CANDLE AFTER SIGNAL = ENTRY (i == signal_bar + 2)
            if waiting_for_entry and (signal_bar is not None) and (i == signal_bar + 2):
                waiting_for_entry = False
                in_trade = True

                entry_body_low = body_low_arr[i]
                sl_anchor = min(signal_body_low, entry_body_low)
                sl_distance = (setup_r1 - setup_s1) / 2.0

                stop_price = sl_anchor - sl_distance
                target_price = setup_r1

                entries.iloc[i] = True

                # Check if exit condition occurs on entry bar (if allowed)
                if allow_same_bar_exit:
                    target_hit = high_arr[i] >= target_price
                    stop_hit = low_arr[i] <= stop_price
                    if target_hit or stop_hit:
                        exits.iloc[i] = True
                        in_trade = False
                        signal_bar = None
                        setup_s1 = None
                        setup_r1 = None
                        signal_body_low = None
                        stop_price = None
                        target_price = None

        # Re-align with original dataframe index
        entries.index = ohlcv.index
        exits.index = ohlcv.index

        return entries, exits


if __name__ == "__main__":
    # Quick sanity check with dummy OHLCV data
    dates = pd.date_range("2026-01-01", periods=50, freq="1h")
    np.random.seed(42)
    close_prices = 100 + np.random.randn(50).cumsum()
    df_test = pd.DataFrame({
        "open": close_prices - 0.5,
        "high": close_prices + 1.0,
        "low": close_prices - 1.0,
        "close": close_prices,
        "volume": 1000
    }, index=dates)

    strat = ClassicFloorModV1()
    entries, exits = strat.generate_signals(df_test)
    print(f"Generated {entries.sum()} entries and {exits.sum()} exits.")
