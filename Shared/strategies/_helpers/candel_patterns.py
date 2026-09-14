#!/usr/bin/env python3
"""Convenience launcher for candel_patterns.py.

Usage:
    uv run python candel_patterns.py --target Shared/Data/classic_floor_mod-v5-1.duckdb
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from Utils.candel_patterns import main

if __name__ == "__main__":
    main()
