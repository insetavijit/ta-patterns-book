#!/usr/bin/env python3
"""
mt5-dn.py — Workspace root entrypoint for MT5 Data Downloader and Polars Resampler.

Delegates directly to the Core/mt5-wsl-tstSetup-01 engine.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SUBMODULE_DIR = _REPO_ROOT / "Core" / "mt5-wsl-tstSetup-01"
_CORE_DIR = _SUBMODULE_DIR / "Core"

for p in [_CORE_DIR, _SUBMODULE_DIR]:
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

from mt5bt.downloader import main

if __name__ == "__main__":
    main()
