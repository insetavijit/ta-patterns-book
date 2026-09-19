#!/usr/bin/env python3
"""vbt-stratagy-tester.py — Root alias delegating to Core/vbtspike/Core/vbt-stratagy-tester.py."""

import runpy
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent / "Core" / "vbtspike" / "Core" / "vbt-stratagy-tester.py"

if __name__ == "__main__":
    runpy.run_path(str(_SCRIPT), run_name="__main__")
