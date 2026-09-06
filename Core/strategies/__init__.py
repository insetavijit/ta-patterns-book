"""Strategy package — Protocol-based strategy definitions.

All strategies must implement the StrategyProtocol interface defined in base.py.
The registry maps string names to strategy instances for CLI lookup.
"""

from .base import StrategyProtocol
from .sma_cross import SmaCrossStrategy
from .registry import get_strategy, list_strategies

__all__ = ["StrategyProtocol", "SmaCrossStrategy", "get_strategy", "list_strategies"]
