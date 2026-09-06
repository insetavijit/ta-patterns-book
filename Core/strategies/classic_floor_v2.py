"""Adapter wrapping ClassicFloorModV2 to conform to StrategyProtocol.

ClassicFloorModV2.generate_signals() returns a 3-tuple (entries, exits, trades_df).
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

from classic_floor_mod_v2 import ClassicFloorModV2 as _ClassicFloorModV2


class ClassicFloorV2Strategy:
    """StrategyProtocol-compatible wrapper for ClassicFloorModV2.

    Adapts the 3-tuple return (entries, exits, trades_df) to the standard
    2-tuple (entries, exits) required by 1Mnbt.py and StrategyProtocol.
    """

    name: str = "classic_floor_mod_v2"
    version: str = "2.0.0"

    def __init__(self) -> None:
        self._inner = _ClassicFloorModV2()

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict[str, Any] | None = None,
    ) -> tuple[pd.Series, pd.Series]:
        """Delegate to ClassicFloorModV2 and discard the trades_df third element.

        Args:
            ohlcv:  DataFrame with columns [open, high, low, close, volume].
            params: Strategy parameter dict (supports allow_same_bar_exit).

        Returns:
            (entries, exits): Boolean pd.Series aligned to ohlcv.index.
        """
        entries, exits, _trades_df = self._inner.generate_signals(ohlcv, params=params)
        return entries, exits
