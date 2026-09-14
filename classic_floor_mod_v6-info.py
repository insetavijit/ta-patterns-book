#!/usr/bin/env python3
"""Convenience launcher for classic_floor_mod_v6-info.py.

Inserts the 'info' metadata table (clmn_name, brif, calcuation, remars)
into a target DuckDB database.

Usage:
    uv run python classic_floor_mod_v6-info.py --target Shared/Data/classic_floor_mod-v5-1.duckdb
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add repository root to Python path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from Utils.strategy_info import main

if __name__ == "__main__":
    main()
