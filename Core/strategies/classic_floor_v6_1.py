"""Adapter wrapping ClassicFloorModV6_1 to conform to StrategyProtocol.

ClassicFloorModV6_1.generate_signals() returns a 3-tuple (entries, exits, trades_df).
The StrategyProtocol contract requires exactly (entries, exits).
This adapter strips the third element, delegates everything else, and caches
trades_df and completed_trades.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

# Resolve Shared/strategies and subdirectories from any working directory
_STRATEGIES_DIR = Path(__file__).resolve().parents[2] / "Shared" / "strategies"
if str(_STRATEGIES_DIR) not in sys.path:
    sys.path.insert(0, str(_STRATEGIES_DIR))
_V6_DIR = _STRATEGIES_DIR / "classic_floor_mod_v6"
if str(_V6_DIR) not in sys.path:
    sys.path.insert(0, str(_V6_DIR))

try:
    from classic_floor_mod_v6_1 import ClassicFloorModV6_1 as _ClassicFloorModV6_1
except ImportError:
    from Shared.strategies.classic_floor_mod_v6.classic_floor_mod_v6_1 import ClassicFloorModV6_1 as _ClassicFloorModV6_1


class ClassicFloorV6_1Strategy:
    """StrategyProtocol-compatible wrapper for ClassicFloorModV6_1."""

    name: str = "classic_floor_mod_v6_1"
    version: str = "6.1.0"

    def __init__(self) -> None:
        self._inner = _ClassicFloorModV6_1()
        self.last_trades_df: pd.DataFrame | None = None
        self.completed_trades: list[dict[str, Any]] = []

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict[str, Any] | None = None,
    ) -> tuple[pd.Series, pd.Series]:
        """Delegate to ClassicFloorModV6_1 and cache trades_df and completed_trades."""
        entries, exits, trades_df = self._inner.generate_signals(ohlcv, params=params)
        self.last_trades_df = trades_df
        self.completed_trades = getattr(self._inner, "completed_trades", [])
        return entries, exits
