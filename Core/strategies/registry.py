"""Strategy registry — maps strategy names to instances.

Add new strategies by importing them and adding to _REGISTRY.
The CLI and runner use get_strategy() to resolve --strategy flags.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import StrategyProtocol

from .sma_cross import SmaCrossStrategy
from .classic_floor_v1 import ClassicFloorV1Strategy
from .classic_floor_v2 import ClassicFloorV2Strategy
from .classic_floor_v2a import ClassicFloorV2AStrategy

_REGISTRY: dict[str, "StrategyProtocol"] = {
    "sma_cross":             SmaCrossStrategy(),
    "classic_floor_mod_v1":  ClassicFloorV1Strategy(),
    "classic_floor_mod_v2":  ClassicFloorV2Strategy(),
    "classic_floor_mod_v2a": ClassicFloorV2AStrategy(),
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
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        available = ", ".join(sorted(_REGISTRY.keys()))
        raise KeyError(
            f"Unknown strategy '{name}'. Available: {available}"
        ) from exc


def list_strategies() -> list[str]:
    """Return sorted list of all registered strategy names."""
    return sorted(_REGISTRY.keys())
