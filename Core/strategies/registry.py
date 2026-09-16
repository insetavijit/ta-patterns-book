"""Strategy registry — maps strategy names to active instances.

Contains only active strategies:
  - CFMV0601B (ClassicFloorMod V06.01 Blocking)
  - CFMV0601C (ClassicFloorMod V06.01 Concurrent)
Older strategy versions have been deprecated.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import StrategyProtocol

# Dynamically add Shared/strategies and all versioned subdirectories to sys.path
_STRATEGIES_BASE = Path(__file__).resolve().parents[2] / "Shared" / "strategies"
if _STRATEGIES_BASE.exists():
    if str(_STRATEGIES_BASE) not in sys.path:
        sys.path.insert(0, str(_STRATEGIES_BASE))
    for _sub in _STRATEGIES_BASE.iterdir():
        if _sub.is_dir() and str(_sub) not in sys.path:
            sys.path.insert(0, str(_sub))

from .classic_floor_v6_1 import (
    CFMV0601BStrategy,
    CFMV0601CStrategy,
)

_REGISTRY: dict[str, "StrategyProtocol"] = {
    "CFMV0601B": CFMV0601BStrategy(),
    "cfmv0601b": CFMV0601BStrategy(),
    "CFMV0601C": CFMV0601CStrategy(),
    "cfmv0601c": CFMV0601CStrategy(),
    "classic_floor_mod_v6_1": CFMV0601BStrategy(),
    "CLASSIC_FLOOR_MOD_V6_1": CFMV0601BStrategy(),
}


def get_strategy(name: str) -> "StrategyProtocol":
    """Retrieve a strategy instance by name.

    Args:
        name: The strategy name as registered in _REGISTRY.

    Returns:
        The strategy instance.

    Raises:
        KeyError: If the strategy name is not registered.
    """
    if name in _REGISTRY:
        return _REGISTRY[name]
    if name.lower() in _REGISTRY:
        return _REGISTRY[name.lower()]
    available = ", ".join(sorted(_REGISTRY.keys()))
    raise KeyError(f"Unknown strategy '{name}'. Available: {available}")


def list_strategies() -> list[str]:
    """Return sorted list of canonical registered strategy names."""
    return [k for k in sorted(_REGISTRY.keys()) if k.isupper()]
