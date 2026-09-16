"""Adapter wrapping CFMV0601B and CFMV0601C to conform to StrategyProtocol.

Conforms to StrategyProtocol: generate_signals() returns (entries, exits).
Caches trades_df and completed_trades on the adapter instance.
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
    from CFMV0601B import CFMV0601B
    from CFMV0601C import CFMV0601C
except ImportError:
    from Shared.strategies.classic_floor_mod_v6.CFMV0601B import CFMV0601B
    from Shared.strategies.classic_floor_mod_v6.CFMV0601C import CFMV0601C


class CFMV0601BStrategy:
    """StrategyProtocol-compatible wrapper for CFMV0601B (Blocking)."""

    name: str = "CFMV0601B"
    version: str = "6.1.0"

    def __init__(self) -> None:
        self._inner = CFMV0601B()
        self.last_trades_df: pd.DataFrame | None = None
        self.completed_trades: list[dict[str, Any]] = []

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict[str, Any] | None = None,
    ) -> tuple[pd.Series, pd.Series]:
        """Delegate to CFMV0601B and cache trades_df and completed_trades."""
        entries, exits, trades_df = self._inner.generate_signals(ohlcv, params=params)
        self.last_trades_df = trades_df
        self.completed_trades = getattr(self._inner, "completed_trades", [])
        return entries, exits


class CFMV0601CStrategy:
    """StrategyProtocol-compatible wrapper for CFMV0601C (Concurrent)."""

    name: str = "CFMV0601C"
    version: str = "6.1.0"

    def __init__(self) -> None:
        self._inner = CFMV0601C()
        self.last_trades_df: pd.DataFrame | None = None
        self.completed_trades: list[dict[str, Any]] = []

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict[str, Any] | None = None,
    ) -> tuple[pd.Series, pd.Series]:
        """Delegate to CFMV0601C and cache trades_df and completed_trades."""
        entries, exits, trades_df = self._inner.generate_signals(ohlcv, params=params)
        self.last_trades_df = trades_df
        self.completed_trades = getattr(self._inner, "completed_trades", [])
        return entries, exits


# Backward-compatible aliases for legacy imports
ClassicFloorV6_1BlockingStrategy = CFMV0601BStrategy
ClassicFloorV6_1ConcurrentStrategy = CFMV0601CStrategy
ClassicFloorV6_1Strategy = CFMV0601BStrategy
