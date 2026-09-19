#!/usr/bin/env python3
"""dn-ohlcv.py — Dukascopy historical OHLCV downloader in Core.

Usage:
    uv run python Core/dn-ohlcv.py --instrument eurusd --start 2025-01-01 --end 2025-01-07 --tf 5m
"""

import sys
import runpy
from pathlib import Path

_DN_DUKAS = Path(__file__).resolve().parent / "vbtspike" / "Core" / "dn-ducas.py"

if __name__ == "__main__":
    runpy.run_path(str(_DN_DUKAS), run_name="__main__")
