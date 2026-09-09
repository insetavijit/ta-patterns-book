"""Constants for Post-Trade Excursion Analysis."""

from __future__ import annotations

# Standard 14-level Fibonacci expansion/extension grid
PFIB_RATIO_GRID: tuple[float, ...] = (
    0.236, 0.382, 0.500, 0.618, 0.786, 1.000,
    1.272, 1.382, 1.618, 1.786, 2.000, 2.272, 2.618, 3.000
)

# Standard post-exit evaluation horizons in candles
DEFAULT_HORIZONS: tuple[int, ...] = (15, 30, 60)

# Nominal 5m candle duration in seconds
NOMINAL_STEP_SECONDS: float = 300.0
