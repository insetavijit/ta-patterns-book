#!/usr/bin/env python3
"""
tree.py — Universal project file tree, listing, and discovery tool.

Lists relative paths, renders visual trees, summary tables, or JSON
for Python (.py) files by default, or any target file type/pattern via
--find and --match.

Usage:
    uv run python Utils/util-python-uv-toolset/utils/tree-tool/tree.py
    uv run python Utils/util-python-uv-toolset/utils/tree-tool/tree.py --find .ipynb
    uv run python Utils/util-python-uv-toolset/utils/tree-tool/tree.py --match "cli-*.yaml"
    uv run python Utils/util-python-uv-toolset/utils/tree-tool/tree.py --tree
    uv run python Utils/util-python-uv-toolset/utils/tree-tool/tree.py --table
    uv run python Utils/util-python-uv-toolset/utils/tree-tool/tree.py --json
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

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


def get_workspace_root(start_dir: Path) -> Path:
    """Find workspace root directory by looking for pyproject.toml or .git."""
    current = start_dir.resolve()
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return Path.cwd()


def find_files(
    root_dir: Path,
    find_ext: str | None = None,
    match_pattern: str | None = None,
    excludes: set[str] | None = None,
    include_all: bool = False,
) -> list[Path]:
    """Find all files under root_dir matching filter/pattern rules, respecting exclusions."""
    ex = set(excludes or DEFAULT_EXCLUDES)
    matched_files: list[Path] = []

    normalized_ext = None
    if find_ext:
        normalized_ext = find_ext.lower() if find_ext.startswith(".") else f".{find_ext.lower()}"

    for dirpath, dirnames, filenames in os.walk(root_dir, followlinks=False):
        dp = Path(dirpath)
        # Filter directories in-place to avoid descending into ignored dirs
        if not include_all:
            dirnames[:] = [
                d for d in dirnames
                if d not in ex and not d.startswith(".") and not (dp / d).is_symlink()
            ]

        for fname in filenames:
            fpath = dp / fname

            # 1. Match extension if specified
            if normalized_ext and fpath.suffix.lower() != normalized_ext:
                continue

            # 2. Match glob pattern if specified
            if match_pattern:
                rel_candidate = None
                try:
                    rel_candidate = str(fpath.relative_to(root_dir))
                except ValueError:
                    rel_candidate = str(fpath)

                if not fnmatch.fnmatch(fname, match_pattern) and not fnmatch.fnmatch(rel_candidate, match_pattern):
                    continue

            # 3. Default: if neither find_ext nor match_pattern is specified, default to .py
            if not normalized_ext and not match_pattern:
                if not fname.endswith(".py"):
                    continue

            matched_files.append(fpath)

    matched_files.sort()
    return matched_files


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


def render_table(paths: Sequence[str], base_dir: Path, file_type_label: str = "Files") -> None:
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(box=None, title=f"{file_type_label} in {base_dir.name} ({len(paths)} files)")
        table.add_column("Relative Path", style="cyan")
        table.add_column("Lines", justify="right", style="magenta")
        table.add_column("Size", justify="right", style="green")

        total_lines = 0
        total_bytes = 0

        for rel_p in paths:
            full_p = base_dir / rel_p
            try:
                size = full_p.stat().st_size
                with open(full_p, encoding="utf-8", errors="ignore") as f:
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
        description="Print relative paths, tree, or table for Python files or custom extensions/patterns.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--root",
        "-r",
        default=None,
        help="Root directory to search (defaults to project workspace root).",
    )
    parser.add_argument(
        "--find",
        "-f",
        default=None,
        help="Find files matching specific extension (e.g. .ipynb, .py, .yaml, .duckdb).",
    )
    parser.add_argument(
        "--match",
        "-m",
        default=None,
        help="Find files matching glob filename pattern (e.g. 'cli-*.yaml', '*test*').",
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
        help="Print only the total count of matched files.",
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
    repo_root = get_workspace_root(here)

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

    files = find_files(
        search_root,
        find_ext=args.find,
        match_pattern=args.match,
        excludes=excludes,
        include_all=args.all,
    )

    # Compute relative paths
    rel_paths = []
    for f in files:
        try:
            rel = f.relative_to(search_root)
            rel_paths.append(str(rel))
        except ValueError:
            rel_paths.append(str(f))

    if args.count:
        print(len(rel_paths))
        return

    label = "Files"
    if args.find:
        label = f"{args.find} Files"
    elif args.match:
        label = f"'{args.match}' Files"
    elif not args.find and not args.match:
        label = "Python Files"

    if args.json:
        render_json(rel_paths)
    elif args.tree:
        render_tree(rel_paths, root_name=search_root.name)
    elif args.table:
        render_table(rel_paths, search_root, file_type_label=label)
    else:
        # Default: stdio list of relative paths
        render_plain(rel_paths)


if __name__ == "__main__":
    main()
