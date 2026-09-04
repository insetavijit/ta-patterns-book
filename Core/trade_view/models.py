"""Models, Constants, and Dependency Containers for TradeView."""

from __future__ import annotations

import re
from dataclasses import dataclass

__version__ = "4.1.0"

# Semantic exit codes
EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_BAD_INPUT = 2
EXIT_DB_NOT_FOUND = 3
EXIT_INTERRUPTED = 130

# Default baseline dataset for SmartGrid layout testing and dry-runs
_DEFAULT_DUMMY_CANDLES: tuple[int, ...] = (200, 150, 350, 25, 45, 500, 80, 120, 300, 60, 90, 200, 40, 70)

# Colors cycled through for --hline-cols reference lines beyond SL/TP
_HLINE_COLOR_CYCLE = ["darkorange", "purple", "teal", "brown", "magenta", "slategray"]

# Plain SQL identifier pattern
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Columns required by --sql queries (case-insensitive)
TRADE_REQUIRED_COLUMNS = ("entry_time", "entry_price")


class TradebookInputError(ValueError):
    """Raised for invalid CLI or user input -> maps to EXIT_BAD_INPUT."""


@dataclass
class LayoutConfig:
    """Configuration options for the SmartGrid layout packing engine."""

    row_capacity_candles: int = 500       # Canvas width, in candle units
    px_per_candle: float = 3.0            # Fixed zoom level, in px/candle
    gap_candles: int = 2                  # Spacing between charts in a row
    max_charts_per_canvas: int = 12       # Pagination limit
    max_extension_ratio: float = 1.3      # Extension cap ratio for stage B fill
    min_candles: int = 15                 # Floor so no chart gets too narrow
    packing_strategy: str = "optimal"     # "wordwrap" | "bestfit" | "optimal"


class _TradebookDeps:
    """Explicit container for heavy, lazily-imported tradebook dependencies."""

    __slots__ = ("duckdb", "pd", "mpf", "mdates", "gridspec", "plt", "Image")

    def __init__(self, duckdb_mod, pd_mod):
        self.duckdb = duckdb_mod
        self.pd = pd_mod
        self.mpf = None
        self.mdates = None
        self.gridspec = None
        self.plt = None
        self.Image = None

    def load_render_deps(self) -> None:
        """Second-stage import: loads matplotlib, mplfinance, Pillow when rendering PNGs."""
        if self.mpf is not None:
            return
        import mplfinance as mpf
        import matplotlib.dates as mdates
        import matplotlib.gridspec as gridspec
        import matplotlib.pyplot as plt
        from PIL import Image

        self.mpf, self.mdates, self.gridspec, self.plt, self.Image = (
            mpf,
            mdates,
            gridspec,
            plt,
            Image,
        )
