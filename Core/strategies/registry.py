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
from .classic_floor_v3 import ClassicFloorV3Strategy
from .classic_floor_v3a import ClassicFloorV3AStrategy
from .classic_floor_v3b import ClassicFloorV3BStrategy
from .classic_floor_v3c import ClassicFloorV3CStrategy
from .classic_floor_v3e import ClassicFloorV3EStrategy
from .classic_floor_v4 import ClassicFloorV4Strategy
from .classic_floor_v4a import ClassicFloorV4AStrategy
from .classic_floor_v4c import ClassicFloorV4CStrategy

_REGISTRY: dict[str, "StrategyProtocol"] = {
    "sma_cross":             SmaCrossStrategy(),
    "classic_floor_mod_v1":  ClassicFloorV1Strategy(),
    "classic_floor_mod_v2":  ClassicFloorV2Strategy(),
    "classic_floor_mod_v2a": ClassicFloorV2AStrategy(),
    "classic_floor_mod_v3":  ClassicFloorV3Strategy(),
    "classic_floor_mod_v3a": ClassicFloorV3AStrategy(),
    "classic_floor_mod_v3b": ClassicFloorV3BStrategy(),
    "classic_floor_mod_v3c": ClassicFloorV3CStrategy(),
    "classic_floor_mod_v3e": ClassicFloorV3EStrategy(),
    "classic_floor_mod_v4":  ClassicFloorV4Strategy(),
    "classic_floor_mod_v4a": ClassicFloorV4AStrategy(),
    "classic_floor_mod_v4c": ClassicFloorV4CStrategy(),
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
