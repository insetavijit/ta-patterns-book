#!/usr/bin/env python3
"""sl-tp-outlook.py — Root launcher delegating to .tmp/sl-tp-outlook.py."""

import runpy
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent / ".tmp" / "sl-tp-outlook.py"

if __name__ == "__main__":
    runpy.run_path(str(_SCRIPT), run_name="__main__")
