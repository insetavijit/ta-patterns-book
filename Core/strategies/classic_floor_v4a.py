"""Adapter wrapping ClassicFloorModV4A to conform to StrategyProtocol.

ClassicFloorModV4A.generate_signals() returns a 3-tuple (entries, exits, trades_df).
The StrategyProtocol contract requires exactly (entries, exits).
This adapter strips the third element and delegates everything else unchanged.
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

from classic_floor_mod_v4a import ClassicFloorModV4A as _ClassicFloorModV4A


class ClassicFloorV4AStrategy:
    """StrategyProtocol-compatible wrapper for ClassicFloorModV4A.

    Adapts the 3-tuple return (entries, exits, trades_df) to the standard
    2-tuple (entries, exits) required by 1Mnbt.py, 1Ybt.py, and StrategyProtocol.
    """

    name: str = "classic_floor_mod_v4a"
    version: str = "4.1.0"

    def __init__(self) -> None:
        self._inner = _ClassicFloorModV4A()
        self.last_trades_df: pd.DataFrame | None = None

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict[str, Any] | None = None,
    ) -> tuple[pd.Series, pd.Series]:
        """Delegate to ClassicFloorModV4A and cache the trades_df third element.

        Args:
            ohlcv:  DataFrame with columns [open, high, low, close, volume].
            params: Strategy parameter dict (supports allow_same_bar_exit).

        Returns:
            (entries, exits): Boolean pd.Series aligned to ohlcv.index.
        """
        res = self._inner.generate_signals(ohlcv, params=params)
        if len(res) == 3:
            entries, exits, trades_df = res
            self.last_trades_df = trades_df
        else:
            entries, exits = res
            self.last_trades_df = None
        return entries, exits
