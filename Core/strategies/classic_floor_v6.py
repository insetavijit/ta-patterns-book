"""Adapter wrapping ClassicFloorModV6 to conform to StrategyProtocol.

ClassicFloorModV6.generate_signals() returns a 3-tuple (entries, exits, trades_df).
The StrategyProtocol contract requires exactly (entries, exits).
This adapter strips the third element, delegates everything else, and caches
trades_df and completed_trades.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

# Resolve Shared/strategies from any working directory
_STRATEGIES_DIR = Path(__file__).resolve().parents[2] / "Shared" / "strategies"
if str(_STRATEGIES_DIR) not in sys.path:
    sys.path.insert(0, str(_STRATEGIES_DIR))

from classic_floor_mod_v6 import ClassicFloorModV6 as _ClassicFloorModV6


class ClassicFloorV6Strategy:
    """StrategyProtocol-compatible wrapper for ClassicFloorModV6.

    Adapts the 3-tuple return (entries, exits, trades_df) to the standard
    2-tuple (entries, exits) required by 1Mnbt.py, 1Ybt.py, 1Ybt-v2.py, and StrategyProtocol.
    """

    name: str = "classic_floor_mod_v6"
    version: str = "6.0.0"

    def __init__(self) -> None:
        self._inner = _ClassicFloorModV6()
        self.last_trades_df: pd.DataFrame | None = None
        self.completed_trades: list[dict[str, Any]] = []

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict[str, Any] | None = None,
    ) -> tuple[pd.Series, pd.Series]:
        """Delegate to ClassicFloorModV6 and cache trades_df and completed_trades.

        Args:
            ohlcv:  DataFrame with columns [open, high, low, close, volume].
            params: Strategy parameter dict (supports allow_concurrent_trades, etc.).

        Returns:
            (entries, exits): Boolean pd.Series aligned to ohlcv.index.
        """
        entries, exits, trades_df = self._inner.generate_signals(ohlcv, params=params)
        self.last_trades_df = trades_df
        self.completed_trades = getattr(self._inner, "completed_trades", [])
        return entries, exits
