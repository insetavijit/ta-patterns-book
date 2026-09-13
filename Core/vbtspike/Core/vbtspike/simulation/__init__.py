"""Simulation package — the ONLY module permitted to import vectorbt.

All vectorbt Portfolio runs are isolated here. No other module in vbtspike
may import vectorbt directly.
"""

from .runner import get_vbt_version, run_backtest

__all__ = ["get_vbt_version", "run_backtest"]
