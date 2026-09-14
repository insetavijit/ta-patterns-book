#!/usr/bin/env python3
"""Convenience launcher for Utils/classic_floor_mod_v6-info.py.

Usage:
    uv run python Utils/classic_floor_mod_v6-info.py --target <path_to_duckdb>
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from Utils.strategy_info import main

if __name__ == "__main__":
    main()
