"""TradeView: Modular SmartGrid Trade Playbook & Layout Engine Package."""

from .cli import main
from .engine import SmartGridEngine, compute_layout
from .models import LayoutConfig, __version__
from .renderer import generate_trade_book

__all__ = [
    "__version__",
    "LayoutConfig",
    "SmartGridEngine",
    "compute_layout",
    "generate_trade_book",
    "main",
]
