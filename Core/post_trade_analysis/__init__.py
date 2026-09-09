"""Post-Trade Excursion Analysis Package.

Dedicated package for post-exit runner analysis, multi-horizon Fibonacci excursions,
and post-trade telemetry.
"""

from post_trade_analysis.constants import (
    DEFAULT_HORIZONS,
    NOMINAL_STEP_SECONDS,
    PFIB_RATIO_GRID,
)
from post_trade_analysis.engine import (
    analyze_trade_multi_horizon,
    run_post_trade_analysis,
)

__all__ = [
    "DEFAULT_HORIZONS",
    "NOMINAL_STEP_SECONDS",
    "PFIB_RATIO_GRID",
    "analyze_trade_multi_horizon",
    "run_post_trade_analysis",
]
