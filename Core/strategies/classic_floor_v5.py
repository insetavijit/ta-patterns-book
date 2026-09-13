"""Adapter wrapping ClassicFloorModV5 to conform to StrategyProtocol.

ClassicFloorModV5.generate_signals() returns a 3-tuple (entries, exits, trades_df).
The StrategyProtocol contract requires exactly (entries, exits).
This adapter strips the third element and delegates everything else unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

# Resolve Shared/Data/strategies from any working directory
_STRATEGIES_DIR = Path(__file__).resolve().parents[2] / "Shared" / "strategies"
if str(_STRATEGIES_DIR) not in sys.path:
    sys.path.insert(0, str(_STRATEGIES_DIR))

from classic_floor_mod_v5 import ClassicFloorModV5 as _ClassicFloorModV5


class ClassicFloorV5Strategy:
    """StrategyProtocol-compatible wrapper for ClassicFloorModV5.

    Adapts the 3-tuple return (entries, exits, trades_df) to the standard
    2-tuple (entries, exits) required by 1Mnbt.py, 1Ybt.py, and StrategyProtocol.
    """

    name: str = "classic_floor_mod_v5"
    version: str = "5.0.0"

    def __init__(self) -> None:
        self._inner = _ClassicFloorModV5()
        self.last_trades_df: pd.DataFrame | None = None
        self.completed_trades: list[dict] = []

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict[str, Any] | None = None,
    ) -> tuple[pd.Series, pd.Series]:
        """Delegate to ClassicFloorModV5 and cache the trades_df third element.

        Args:
            ohlcv:  DataFrame with columns [open, high, low, close, volume].
            params: Strategy parameter dict (supports allow_same_bar_exit).

        Returns:
            (entries, exits): Boolean pd.Series aligned to ohlcv.index.
        """
        entries, exits, trades_df = self._inner.generate_signals(ohlcv, params=params)
        self.last_trades_df = trades_df
        self.completed_trades = getattr(self._inner, "completed_trades", [])
        return entries, exits
