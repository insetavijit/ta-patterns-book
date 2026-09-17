#!/usr/bin/env python3
"""
tree.py — Print the list of relative paths for each Python (.py) file in the project.

Usage:
    uv run python Utils/tree.py
    uv run python Utils/tree.py --tree
    uv run python Utils/tree.py --table
    uv run python Utils/tree.py --json
    uv run python Utils/tree.py --root Core
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

DEFAULT_EXCLUDES = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".tmp",
    "__trash",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",
    ".agents",
    "build",
    "dist",
    ".egg-info",
}


def find_py_files(
    root_dir: Path,
    excludes: set[str] | None = None,
    include_all: bool = False,
) -> list[Path]:
    """Find all .py files under root_dir, respecting exclusion rules."""
    ex = set(excludes or DEFAULT_EXCLUDES)
    py_files: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(root_dir, followlinks=False):
        dp = Path(dirpath)
        # Filter directories in-place to avoid descending into ignored dirs
        if not include_all:
            dirnames[:] = [
                d for d in dirnames
                if d not in ex and not d.startswith(".") and not (dp / d).is_symlink()
            ]

        for fname in filenames:
            if fname.endswith(".py"):
                fpath = dp / fname
                py_files.append(fpath)

    py_files.sort()
    return py_files


def render_plain(paths: Sequence[str]) -> None:
    for p in paths:
        print(p)


def render_json(paths: Sequence[str]) -> None:
    print(json.dumps(list(paths), indent=2))


def render_tree(paths: Sequence[str], root_name: str = ".") -> None:
    try:
        from rich.console import Console
        from rich.tree import Tree

        console = Console()
        tree = Tree(f"[bold cyan]{root_name}[/bold cyan]")
        nodes = {(): tree}

        for path_str in paths:
            parts = Path(path_str).parts
            # Build directory branches
            for i in range(1, len(parts)):
                sub_parts = parts[:i]
                if sub_parts not in nodes:
                    parent_node = nodes[sub_parts[:-1]]
                    nodes[sub_parts] = parent_node.add(f"[bold blue]{sub_parts[-1]}/[/bold blue]")
            # Add file leaf
            parent_node = nodes[parts[:-1]]
            parent_node.add(f"[green]{parts[-1]}[/green]")

        console.print(tree)
    except ImportError:
        # Fallback to plain if rich not installed
        render_plain(paths)


def render_table(paths: Sequence[str], base_dir: Path) -> None:
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(box=None, title=f"Python Files in {base_dir.name} ({len(paths)} files)")
        table.add_column("Relative Path", style="cyan")
        table.add_column("Lines", justify="right", style="magenta")
        table.add_column("Size", justify="right", style="green")

        total_lines = 0
        total_bytes = 0

        for rel_p in paths:
            full_p = base_dir / rel_p
            try:
                size = full_p.stat().st_size
                with open(full_p, "r", encoding="utf-8", errors="ignore") as f:
                    lines = sum(1 for _ in f)
            except Exception:
                size = 0
                lines = 0

            total_lines += lines
            total_bytes += size
            size_kb = f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B"
            table.add_row(rel_p, f"{lines:,}", size_kb)

        table.add_section()
        total_kb = f"{total_bytes / 1024:.1f} KB"
        table.add_row(f"[bold]Total: {len(paths)} files[/bold]", f"[bold]{total_lines:,}[/bold]", f"[bold]{total_kb}[/bold]")
        console.print(table)
    except ImportError:
        render_plain(paths)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print the list of relative paths for each Python (.py) file in the project.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--root",
        "-r",
        default=None,
        help="Root directory to search (defaults to project workspace root).",
    )
    parser.add_argument(
        "--tree",
        "-t",
        action="store_true",
        help="Render visual ASCII/Rich directory tree.",
    )
    parser.add_argument(
        "--table",
        action="store_true",
        help="Render borderless summary table with line counts and file sizes.",
    )
    parser.add_argument(
        "--json",
        "-j",
        action="store_true",
        help="Output raw JSON array of relative paths.",
    )
    parser.add_argument(
        "--count",
        "-c",
        action="store_true",
        help="Print only the total count of .py files.",
    )
    parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Include all files without excluding .venv, __pycache__, or hidden directories.",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        help="Additional directory names to exclude.",
    )

    args = parser.parse_args()

    # Determine workspace root
    here = Path(__file__).resolve().parent
    repo_root = here.parent if (here.parent / "pyproject.toml").exists() else Path.cwd()

    if args.root:
        search_root = Path(args.root).resolve()
    else:
        search_root = repo_root.resolve()

    if not search_root.exists() or not search_root.is_dir():
        print(f"Error: Directory not found: {search_root}", file=sys.stderr)
        sys.exit(1)

    excludes = set(DEFAULT_EXCLUDES)
    if args.exclude:
        excludes.update(args.exclude)

    py_files = find_py_files(search_root, excludes=excludes, include_all=args.all)

    # Compute relative paths
    rel_paths = []
    for f in py_files:
        try:
            rel = f.relative_to(search_root)
            rel_paths.append(str(rel))
        except ValueError:
            rel_paths.append(str(f))

    if args.count:
        print(len(rel_paths))
        return

    if args.json:
        render_json(rel_paths)
    elif args.tree:
        render_tree(rel_paths, root_name=search_root.name)
    elif args.table:
        render_table(rel_paths, search_root)
    else:
        # Default: stdio list of relative paths for each .py file
        render_plain(rel_paths)


if __name__ == "__main__":
    main()
