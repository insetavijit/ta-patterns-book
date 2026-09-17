#!/usr/bin/env python3
"""
mt5-dn.py — Workspace Core entrypoint for MT5 Historical Data Downloader & Polars Resampler.

Usage:
    uv run python Core/mt5-dn.py --instrument EURUSD --lastWeek --tf 5m
    uv run python Core/mt5-dn.py --instrument EURUSD --start 2026-06-01 --end 2026-09-01 --tf 5m
"""

import sys
from pathlib import Path

_WORKSPACE_CORE = Path(__file__).resolve().parent
_REPO_ROOT = _WORKSPACE_CORE.parent
_SUBMODULE_DIR = _WORKSPACE_CORE / "mt5-wsl-tstSetup-01"
_SUBMODULE_CORE = _SUBMODULE_DIR / "Core"

for p in [_SUBMODULE_CORE, _SUBMODULE_DIR, _REPO_ROOT]:
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

from mt5bt.downloader import main

if __name__ == "__main__":
    main()
