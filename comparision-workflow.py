#!/usr/bin/env python3
"""comparision-workflow.py — Root runner alias to Utils/comparison_workflow.py."""

import runpy
from pathlib import Path

_WORKFLOW_SCRIPT = Path(__file__).resolve().parent / "Utils" / "comparison_workflow.py"

if __name__ == "__main__":
    runpy.run_path(str(_WORKFLOW_SCRIPT), run_name="__main__")
