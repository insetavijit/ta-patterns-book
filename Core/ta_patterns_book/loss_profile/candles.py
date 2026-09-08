"""Single, double, and triple candlestick pattern classifier using pandas_ta_classic and price action anatomy."""

from __future__ import annotations

import numpy as np
import pandas as pd

# 1-Candle functions
from pandas_ta_classic.candles.cdl_doji import cdl_doji
from pandas_ta_classic.candles.cdl_hammer import cdl_hammer
from pandas_ta_classic.candles.cdl_shootingstar import cdl_shootingstar
from pandas_ta_classic.candles.cdl_hangingman import cdl_hangingman
from pandas_ta_classic.candles.cdl_invertedhammer import cdl_invertedhammer
from pandas_ta_classic.candles.cdl_marubozu import cdl_marubozu
from pandas_ta_classic.candles.cdl_spinningtop import cdl_spinningtop
from pandas_ta_classic.candles.cdl_dragonflydoji import cdl_dragonflydoji
from pandas_ta_classic.candles.cdl_gravestonedoji import cdl_gravestonedoji
from pandas_ta_classic.candles.cdl_belthold import cdl_belthold

# 2-Candle functions
from pandas_ta_classic.candles.cdl_engulfing import cdl_engulfing
from pandas_ta_classic.candles.cdl_harami import cdl_harami
from pandas_ta_classic.candles.cdl_haramicross import cdl_haramicross
from pandas_ta_classic.candles.cdl_piercing import cdl_piercing
from pandas_ta_classic.candles.cdl_darkcloudcover import cdl_darkcloudcover
from pandas_ta_classic.candles.cdl_kicking import cdl_kicking
from pandas_ta_classic.candles.cdl_inside import cdl_inside
from pandas_ta_classic.candles.cdl_matchinglow import cdl_matchinglow
from pandas_ta_classic.candles.cdl_homingpigeon import cdl_homingpigeon
from pandas_ta_classic.candles.cdl_2crows import cdl_2crows

# 3-Candle functions
from pandas_ta_classic.candles.cdl_morningstar import cdl_morningstar
from pandas_ta_classic.candles.cdl_morningdojistar import cdl_morningdojistar
from pandas_ta_classic.candles.cdl_eveningstar import cdl_eveningstar
from pandas_ta_classic.candles.cdl_eveningdojistar import cdl_eveningdojistar
from pandas_ta_classic.candles.cdl_3whitesoldiers import cdl_3whitesoldiers
from pandas_ta_classic.candles.cdl_3blackcrows import cdl_3blackcrows
from pandas_ta_classic.candles.cdl_3inside import cdl_3inside
from pandas_ta_classic.candles.cdl_3outside import cdl_3outside
from pandas_ta_classic.candles.cdl_3linestrike import cdl_3linestrike
from pandas_ta_classic.candles.cdl_abandonedbaby import cdl_abandonedbaby
from pandas_ta_classic.candles.cdl_tristar import cdl_tristar
from pandas_ta_classic.candles.cdl_unique3river import cdl_unique3river


def classify_single_candles(df: pd.DataFrame) -> pd.Series:
    """Classify every candle in DataFrame into a single candlestick pattern.

    Combines pandas_ta_classic indicators with anatomical pinbar/expansion metrics.
    Defaults non-matches to Normal_Bull / Normal_Bear for full coverage.
    """
    o = df['open']
    h = df['high']
    l = df['low']
    c = df['close']

    pats = {
        'Hammer': cdl_hammer(o, h, l, c),
        'Inverted_Hammer': cdl_invertedhammer(o, h, l, c),
        'Shooting_Star': cdl_shootingstar(o, h, l, c),
        'Hanging_Man': cdl_hangingman(o, h, l, c),
        'Dragonfly_Doji': cdl_dragonflydoji(o, h, l, c),
        'Gravestone_Doji': cdl_gravestonedoji(o, h, l, c),
        'Doji': cdl_doji(o, h, l, c),
        'Marubozu': cdl_marubozu(o, h, l, c),
        'Spinning_Top': cdl_spinningtop(o, h, l, c),
        'Belt_Hold': cdl_belthold(o, h, l, c),
    }

    rng = np.maximum(h.values - l.values, 1e-6)
    body = np.abs(c.values - o.values)
    upper_wick = h.values - np.maximum(o.values, c.values)
    lower_wick = np.minimum(o.values, c.values) - l.values
    is_green = c.values >= o.values

    b_ratio = body / rng
    lw_ratio = lower_wick / rng
    uw_ratio = upper_wick / rng

    labels = np.where(
        lw_ratio >= 0.5,
        np.where(is_green, 'Bull_Pinbar', 'Bear_Pinbar'),
        np.where(
            uw_ratio >= 0.5,
            np.where(is_green, 'Bull_Inverted_Pinbar', 'Bear_Inverted_Pinbar'),
            np.where(
                b_ratio >= 0.6,
                np.where(is_green, 'Bull_Expansion', 'Bear_Expansion'),
                np.where(is_green, 'Normal_Bull', 'Normal_Bear')
            )
        )
    )

    for name, s in reversed(list(pats.items())):
        if s is not None:
            vals = s.values
            labels[vals > 0] = f'Bull_{name}'
            labels[vals < 0] = f'Bear_{name}'

    return pd.Series(labels, index=df.index, name='candle_1')


def classify_ecpatt_1(df: pd.DataFrame) -> pd.Series:
    """Classify 1-candle patterns on entry bar. Returns NaN for non-matches."""
    o = df['open']
    h = df['high']
    l = df['low']
    c = df['close']

    pats = {
        'Hammer': cdl_hammer(o, h, l, c),
        'Inverted_Hammer': cdl_invertedhammer(o, h, l, c),
        'Shooting_Star': cdl_shootingstar(o, h, l, c),
        'Hanging_Man': cdl_hangingman(o, h, l, c),
        'Dragonfly_Doji': cdl_dragonflydoji(o, h, l, c),
        'Gravestone_Doji': cdl_gravestonedoji(o, h, l, c),
        'Doji': cdl_doji(o, h, l, c),
        'Marubozu': cdl_marubozu(o, h, l, c),
        'Spinning_Top': cdl_spinningtop(o, h, l, c),
        'Belt_Hold': cdl_belthold(o, h, l, c),
    }

    labels = np.full(len(df), np.nan, dtype=object)

    # Pinbars and expansions as distinct single-candle price action patterns
    rng = np.maximum(h.values - l.values, 1e-6)
    body = np.abs(c.values - o.values)
    upper_wick = h.values - np.maximum(o.values, c.values)
    lower_wick = np.minimum(o.values, c.values) - l.values
    is_green = c.values >= o.values

    b_ratio = body / rng
    lw_ratio = lower_wick / rng
    uw_ratio = upper_wick / rng

    # Pinbars (wick >= 50% of candle range)
    pin_bull = lw_ratio >= 0.5
    pin_bear = uw_ratio >= 0.5
    labels[pin_bull & is_green] = 'Bull_Pinbar'
    labels[pin_bull & ~is_green] = 'Bear_Pinbar'
    labels[pin_bear & is_green] = 'Bull_Inverted_Pinbar'
    labels[pin_bear & ~is_green] = 'Bear_Inverted_Pinbar'

    # Expansion bars (body >= 60% of candle range)
    exp_mask = (b_ratio >= 0.6) & (labels == np.nan)
    labels[exp_mask & is_green] = 'Bull_Expansion'
    labels[exp_mask & ~is_green] = 'Bear_Expansion'

    # Overlay specific pandas_ta_classic patterns
    for name, s in reversed(list(pats.items())):
        if s is not None:
            vals = s.values
            labels[vals > 0] = f'Bull_{name}'
            labels[vals < 0] = f'Bear_{name}'

    return pd.Series(labels, index=df.index, name='ecpatt_1')


def classify_ecpatt_2(df: pd.DataFrame) -> pd.Series:
    """Classify 2-candle patterns ending at the current candle. Returns NaN for non-matches."""
    o = df['open']
    h = df['high']
    l = df['low']
    c = df['close']

    pats = {
        'Engulfing': cdl_engulfing(o, h, l, c),
        'Harami': cdl_harami(o, h, l, c),
        'Harami_Cross': cdl_haramicross(o, h, l, c),
        'Piercing_Line': cdl_piercing(o, h, l, c),
        'Dark_Cloud_Cover': cdl_darkcloudcover(o, h, l, c),
        'Kicking': cdl_kicking(o, h, l, c),
        'Matching_Low': cdl_matchinglow(o, h, l, c),
        'Homing_Pigeon': cdl_homingpigeon(o, h, l, c),
        'Two_Crows': cdl_2crows(o, h, l, c),
        'Inside_Bar': cdl_inside(o, h, l, c),
    }

    labels = np.full(len(df), np.nan, dtype=object)

    # Price action: Tweezer Bottom / Top
    pip_threshold = 0.0001
    prev_l = l.shift(1).values
    prev_h = h.shift(1).values
    prev_c = c.shift(1).values
    prev_o = o.shift(1).values

    tweezer_bot = (np.abs(l.values - prev_l) <= pip_threshold) & (prev_c < prev_o) & (c.values > o.values)
    tweezer_top = (np.abs(h.values - prev_h) <= pip_threshold) & (prev_c > prev_o) & (c.values < o.values)
    labels[tweezer_bot] = 'Tweezer_Bottom'
    labels[tweezer_top] = 'Tweezer_Top'

    # Overlay pandas_ta_classic patterns
    for name, s in reversed(list(pats.items())):
        if s is not None:
            vals = s.values
            labels[vals > 0] = f'Bull_{name}'
            labels[vals < 0] = f'Bear_{name}'

    return pd.Series(labels, index=df.index, name='ecpatt_2')


def classify_ecpatt_3(df: pd.DataFrame) -> pd.Series:
    """Classify 3-candle patterns ending at the current candle. Returns NaN for non-matches."""
    o = df['open']
    h = df['high']
    l = df['low']
    c = df['close']

    pats = {
        'Morning_Star': cdl_morningstar(o, h, l, c),
        'Morning_Doji_Star': cdl_morningdojistar(o, h, l, c),
        'Evening_Star': cdl_eveningstar(o, h, l, c),
        'Evening_Doji_Star': cdl_eveningdojistar(o, h, l, c),
        'Three_White_Soldiers': cdl_3whitesoldiers(o, h, l, c),
        'Three_Black_Crows': cdl_3blackcrows(o, h, l, c),
        'Three_Inside': cdl_3inside(o, h, l, c),
        'Three_Outside': cdl_3outside(o, h, l, c),
        'Three_Line_Strike': cdl_3linestrike(o, h, l, c),
        'Abandoned_Baby': cdl_abandonedbaby(o, h, l, c),
        'TriStar': cdl_tristar(o, h, l, c),
        'Unique_Three_River': cdl_unique3river(o, h, l, c),
    }

    labels = np.full(len(df), np.nan, dtype=object)

    for name, s in reversed(list(pats.items())):
        if s is not None:
            vals = s.values
            labels[vals > 0] = f'Bull_{name}'
            labels[vals < 0] = f'Bear_{name}'

    return pd.Series(labels, index=df.index, name='ecpatt_3')


def compute_candlestick_pattern_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all 6 single, double, and triple candle patterns for entry and pre-entry bars.

    Returns DataFrame with columns:
        ecpatt_1: 1-candle pattern at entry bar
        ecpatt_2: 2-candle pattern ending at entry bar
        ecpatt_3: 3-candle pattern ending at entry bar
        epcpatt_1: 1-candle pattern at pre-entry setup bar (shift 1)
        epcpatt_2: 2-candle pattern ending at pre-entry setup bar (shift 1)
        epcpatt_3: 3-candle pattern ending at pre-entry setup bar (shift 1)
    """
    ec1 = classify_ecpatt_1(df)
    ec2 = classify_ecpatt_2(df)
    ec3 = classify_ecpatt_3(df)

    patt_df = pd.DataFrame(index=df.index)
    patt_df['ecpatt_1'] = ec1
    patt_df['ecpatt_2'] = ec2
    patt_df['ecpatt_3'] = ec3
    patt_df['epcpatt_1'] = ec1.shift(1)
    patt_df['epcpatt_2'] = ec2.shift(1)
    patt_df['epcpatt_3'] = ec3.shift(1)

    return patt_df
