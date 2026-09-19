#!/usr/bin/env python3
"""
relate.py — Root launcher delegating to tree.py --relate.

Usage:
    uv run python relate.py --path <target_path> [--py] [--table] [--json] [--tree]
"""

import sys
from pathlib import Path

_TREE_SCRIPT = Path(__file__).resolve().parent / "Utils" / "util-python-uv-toolset" / "utils" / "tree-tool" / "tree.py"

if __name__ == "__main__":
    import runpy

    # Map legacy --path to --relate for tree.py compatibility
    args = sys.argv[1:]
    new_args = []
    i = 0
    while i < len(args):
        if args[i] in ("--path", "-p") and i + 1 < len(args):
            new_args.extend(["--relate", args[i + 1]])
            i += 2
        else:
            new_args.append(args[i])
            i += 1

    if "--relate" not in new_args and not any(a.startswith("--relate=") for a in new_args):
        if new_args and not new_args[0].startswith("-"):
            # Positional argument passed
            new_args = ["--relate", new_args[0]] + new_args[1:]

    sys.argv = [sys.argv[0]] + new_args
    runpy.run_path(str(_TREE_SCRIPT), run_name="__main__")
