#!/usr/bin/env python3
"""compare-trade-by-trade.py — Root runner alias to Utils/compare_trade_by_trade.py."""

import runpy
from pathlib import Path

_ENGINE_SCRIPT = Path(__file__).resolve().parent / "Utils" / "compare_trade_by_trade.py"

if __name__ == "__main__":
    runpy.run_path(str(_ENGINE_SCRIPT), run_name="__main__")
