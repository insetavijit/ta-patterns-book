"""Adapter wrapping ClassicFloorModV1 to conform to StrategyProtocol.

ClassicFloorModV1 manages all its internal rules, pivot math (20-period lookback),
2-bar delay entry, dynamic SL and TP internally.
This adapter conforms to StrategyProtocol so it can be loaded by the strategy registry.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

# Resolve Shared/straragYs from any working directory
_STRATEGIES_DIR = Path(__file__).resolve().parents[2] / "Shared" / "straragYs"
if str(_STRATEGIES_DIR) not in sys.path:
    sys.path.insert(0, str(_STRATEGIES_DIR))

from classic_floor_mod_v1 import ClassicFloorModV1 as _ClassicFloorModV1


class ClassicFloorV1Strategy:
    """StrategyProtocol-compatible wrapper for ClassicFloorModV1."""

    name: str = "classic_floor_mod_v1"
    version: str = "1.0.0"

    def __init__(self) -> None:
        self._inner = _ClassicFloorModV1()

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict[str, Any] | None = None,
    ) -> tuple[pd.Series, pd.Series]:
        """Delegate to ClassicFloorModV1 which self-contains all calculations.

        Args:
            ohlcv:  DataFrame with columns [open, high, low, close, volume].
            params: Optional parameter dict (unused as strategy is self-contained).

        Returns:
            (entries, exits): Boolean pd.Series aligned to ohlcv.index.
        """
        return self._inner.generate_signals(ohlcv)
