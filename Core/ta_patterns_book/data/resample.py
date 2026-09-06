"""Centralized OHLCV resampling utility for ta-patterns-book and CLI runners.

Provides standardized financial candlestick resampling across timeframes,
validating inputs, mapping timeframe aliases, preserving OHLCV relationships,
and preventing illegal downsampling (e.g. 5m to 1m without tick data).
"""

from __future__ import annotations

import logging
from typing import Mapping
import pandas as pd

logger = logging.getLogger(__name__)

# Standard timeframe mapping from common shorthand to pandas resampling rules
TIMEFRAME_MAP: dict[str, str] = {
    "1m": "1min",
    "1min": "1min",
    "2m": "2min",
    "3m": "3min",
    "5m": "5min",
    "10m": "10min",
    "15m": "15min",
    "30m": "30min",
    "45m": "45min",
    "1h": "1h",
    "2h": "2h",
    "3h": "3h",
    "4h": "4h",
    "6h": "6h",
    "8h": "8h",
    "12h": "12h",
    "1d": "1D",
    "1w": "1W",
}

# Standard aggregation dictionary for OHLCV bars
OHLCV_AGGREGATIONS: dict[str, str] = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


def normalize_timeframe_rule(timeframe: str) -> str:
    """Normalize a timeframe string to a standard pandas offset string.

    Args:
        timeframe: Shorthand or pandas offset (e.g., '1m', '5m', '1h', '1D').

    Returns:
        Standard pandas resample offset string (e.g., '1min', '5min', '1h', '1D').
    """
    tf_lower = timeframe.strip().lower()
    return TIMEFRAME_MAP.get(tf_lower, timeframe)


def resample_ohlcv(
    df: pd.DataFrame,
    target_timeframe: str,
    ts_column: str | None = None,
    aggregations: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Resample an OHLCV DataFrame to a target timeframe using pandas.

    Supports both DateTimeIndex DataFrames and DataFrames with an explicit timestamp column.
    Guarantees that:
      - 'open' gets first price
      - 'high' gets max price
      - 'low' gets min price
      - 'close' gets last price
      - 'volume' gets sum of volume
      - Empty off-market periods are removed (.dropna)
      - Unmodified DataFrame is returned if data already matches target resolution.

    Args:
        df: Input DataFrame containing open, high, low, close (and optional volume).
        target_timeframe: Target timeframe string (e.g. '5m', '15m', '1h', '1d').
        ts_column: Name of timestamp column if df is not already DateTimeIndexed.
        aggregations: Optional custom mapping for column aggregations.

    Returns:
        Resampled OHLCV DataFrame with DateTimeIndex.
    """
    if df.empty:
        return df.copy()

    # Ensure DateTimeIndex
    data = df.copy()
    if ts_column and ts_column in data.columns:
        data[ts_column] = pd.to_datetime(data[ts_column], utc=True)
        data = data.set_index(ts_column)
    elif not isinstance(data.index, pd.DatetimeIndex):
        # Check if 'ts' or 'timestamp' exists in columns
        for candidate in ("ts", "timestamp", "date", "datetime"):
            if candidate in data.columns:
                data[candidate] = pd.to_datetime(data[candidate], utc=True)
                data = data.set_index(candidate)
                break

    if not isinstance(data.index, pd.DatetimeIndex):
        raise ValueError("DataFrame index must be a DatetimeIndex or specify ts_column.")

    data = data.sort_index()

    # Map target timeframe
    rule = normalize_timeframe_rule(target_timeframe)

    # Estimate native data frequency from deltas
    if len(data) >= 2:
        deltas = data.index.to_series().diff().dropna()
        median_delta = deltas.median()
        target_td = pd.to_timedelta(pd.tseries.frequencies.to_offset(rule))

        # If data is already at target frequency, return directly
        if median_delta == target_td:
            return data

        # If user tries to downsample to a finer resolution (e.g., 5m data into 1m)
        if median_delta > target_td:
            raise ValueError(
                f"Cannot downsample data with native resolution ~{median_delta} "
                f"into finer target resolution '{target_timeframe}' ({target_td})."
            )

    # Prepare aggregation dictionary matching available columns
    agg_rules: dict[str, str] = {}
    custom_aggs = aggregations or OHLCV_AGGREGATIONS

    for col in data.columns:
        col_lower = col.lower()
        if col_lower in custom_aggs:
            agg_rules[col] = custom_aggs[col_lower]
        elif col in custom_aggs:
            agg_rules[col] = custom_aggs[col]

    if "close" not in [c.lower() for c in agg_rules.keys()]:
        raise ValueError("DataFrame must contain a 'close' column to resample OHLCV.")

    resampled = data.resample(rule, label="left", closed="left").agg(agg_rules)
    
    # Drop empty buckets (periods with no trades / bars)
    resampled = resampled.dropna(subset=[col for col in resampled.columns if col.lower() in ("open", "close")])

    return resampled
