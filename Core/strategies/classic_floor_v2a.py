"""Adapter wrapping ClassicFloorModV2A to conform to StrategyProtocol.

ClassicFloorModV2A.generate_signals() returns a 3-tuple (entries, exits, trades_df).
This adapter delegates to Shared/straragYs/classic_floor_mod_v2A.py and conforms
to the StrategyProtocol 2-tuple (entries, exits).
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

from classic_floor_mod_v2A import ClassicFloorModV2 as _ClassicFloorModV2A


class ClassicFloorV2AStrategy:
    """StrategyProtocol-compatible wrapper for ClassicFloorModV2A."""

    name: str = "classic_floor_mod_v2a"
    version: str = "2.1.0"

    def __init__(self) -> None:
        self._inner = _ClassicFloorModV2A()

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict[str, Any] | None = None,
    ) -> tuple[pd.Series, pd.Series]:
        """Delegate to ClassicFloorModV2A and discard the trades_df third element."""
        entries, exits, _trades_df = self._inner.generate_signals(ohlcv)
        return entries, exits
