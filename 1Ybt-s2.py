#!/usr/bin/env python3
"""1Ybt-s2.py — Root alias delegating to Notebooks/1Ybt-s2.py."""

import runpy
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent / "Notebooks" / "1Ybt-s2.py"

if __name__ == "__main__":
    runpy.run_path(str(_SCRIPT), run_name="__main__")
