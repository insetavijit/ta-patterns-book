#!/usr/bin/env python3
"""relate.py — Root launcher delegating to Utils/util-python-uv-toolset/utils/relate-tool/relate.py."""

import runpy
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent / "Utils" / "util-python-uv-toolset" / "utils" / "relate-tool" / "relate.py"

if __name__ == "__main__":
    runpy.run_path(str(_SCRIPT), run_name="__main__")
