#!/usr/bin/env python3
"""Convenience launcher for candel_patterns.py.

Usage:
    uv run python candel_patterns.py --target Shared/Data/classic_floor_mod-v5-1.duckdb
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Utils.candel_patterns import main

if __name__ == "__main__":
    main()
