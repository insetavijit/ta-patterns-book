#!/usr/bin/env python3
"""1Ybt-3.py — Direct Parquet & Dual-Mode Backtest Runner (alias to 1Ybt-v3.py)."""

import runpy
from pathlib import Path

_V3_SCRIPT = Path(__file__).resolve().parent / "1Ybt-v3.py"

if __name__ == "__main__":
    runpy.run_path(str(_V3_SCRIPT), run_name="__main__")
