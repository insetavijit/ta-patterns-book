"""SMA crossover strategy — reference implementation.

Signal logic:
  - Entry:  fast SMA crosses above slow SMA (golden cross)
  - Exit:   fast SMA crosses below slow SMA (death cross)

Fingerprint-relevant params: fast_window, slow_window (+ name, version from Protocol).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .base import StrategyProtocol  # noqa: F401 — satisfies the Protocol


class SmaCrossStrategy:
    """Simple Moving Average crossover strategy."""

    name: str = "sma_cross"
    version: str = "1.0.0"

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict[str, Any],
    ) -> tuple[pd.Series, pd.Series]:
        """Generate entry/exit signals based on SMA crossover.

        Args:
            ohlcv: OHLCV DataFrame indexed by timestamp.
            params: Must contain 'fast_window' (int) and 'slow_window' (int).

        Returns:
            (entries, exits) boolean Series.

        Raises:
            KeyError: If required params are missing.
            ValueError: If fast_window >= slow_window.
        """
        fast = int(params["fast_window"])
        slow = int(params["slow_window"])

        if fast >= slow:
            raise ValueError(
                f"fast_window ({fast}) must be less than slow_window ({slow})"
            )

        close = ohlcv["close"]
        fast_sma = close.rolling(fast).mean()
        slow_sma = close.rolling(slow).mean()

        # Golden cross: fast crosses above slow
        entries = (fast_sma > slow_sma) & (fast_sma.shift(1) <= slow_sma.shift(1))
        # Death cross: fast crosses below slow
        exits = (fast_sma < slow_sma) & (fast_sma.shift(1) >= slow_sma.shift(1))

        return entries.fillna(False), exits.fillna(False)
