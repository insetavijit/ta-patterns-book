"""Base Protocol contract for all vbtSpike strategies.

Strategies are deliberately decoupled from vectorbt and the storage layer.
The only contract is generate_signals — everything else is implementation detail.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class StrategyProtocol(Protocol):
    """Contract that every vbtSpike strategy must satisfy.

    A strategy is a pure function-style object: it receives OHLCV data and
    parameters, and returns entry/exit boolean Series. It has no knowledge of
    vectorbt, DuckDB, or the persistence layer.
    """

    #: Human-readable strategy name — used as part of the fingerprint tuple.
    name: str

    #: Semantic version string — bump this whenever signal logic changes.
    version: str

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict[str, Any],
    ) -> tuple[pd.Series, pd.Series]:
        """Compute entry and exit signals from OHLCV data.

        Args:
            ohlcv: DataFrame with columns [open, high, low, close, volume]
                   indexed by timestamp.
            params: Strategy-specific parameter dict. Every key that feeds the
                    fingerprint tuple must be present (see spec DL-V6-04).

        Returns:
            (entries, exits): Two boolean pd.Series aligned to ohlcv.index.
                              True = signal at that bar.
        """
        ...
