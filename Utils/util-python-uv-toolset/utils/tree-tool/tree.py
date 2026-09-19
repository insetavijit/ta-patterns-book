#!/usr/bin/env python3
"""
tree.py — Universal project file tree, listing, and dependency discovery tool.

Lists relative paths, renders visual trees, summary tables, or JSON
for Python (.py) files by default, or any target file type/pattern via
--find and --match.

Also inspects codebase cross-references and dependencies via --relate,
with optional --py filter to restrict references to Python files only.

Usage:
    uv run python Utils/util-python-uv-toolset/utils/tree-tool/tree.py
    uv run python Utils/util-python-uv-toolset/utils/tree-tool/tree.py --find .ipynb
    uv run python Utils/util-python-uv-toolset/utils/tree-tool/tree.py --match "cli-*.yaml"
    uv run python Utils/util-python-uv-toolset/utils/tree-tool/tree.py --relate Shared/strategies/classic_floor_mod_v6/CFMV0601B.py --py
    uv run python Utils/util-python-uv-toolset/utils/tree-tool/tree.py --relate duckdb_explorer.py --table
    uv run python Utils/util-python-uv-toolset/utils/tree-tool/tree.py --tree
    uv run python Utils/util-python-uv-toolset/utils/tree-tool/tree.py --table
    uv run python Utils/util-python-uv-toolset/utils/tree-tool/tree.py --json
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

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

DEFAULT_SCAN_EXTS = {
    ".py",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".md",
    ".sh",
    ".ipynb",
    ".txt",
    ".ini",
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


def search_references(
    workspace_root: Path,
    target_path_input: str,
    strict: bool = False,
    only_py: bool = False,
    excludes: set[str] | None = None,
    include_all: bool = False,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Search workspace files for occurrences of target path, filename, or module stem."""
    target = Path(target_path_input)
    target_abs = (workspace_root / target).resolve() if not target.is_absolute() else target.resolve()
    try:
        rel_path = target_abs.relative_to(workspace_root).as_posix()
    except ValueError:
        rel_path = target.as_posix()

    filename = target.name
    stem = target.stem

    terms: dict[str, str] = {
        "path": rel_path,
        "filename": filename,
    }
    if not strict and stem and stem != filename:
        terms["stem"] = stem

    ex = set(excludes or DEFAULT_EXCLUDES)
    exts = {".py"} if only_py else DEFAULT_SCAN_EXTS
    matches: list[dict[str, Any]] = []

    stem_pattern = re.compile(rf"\b{re.escape(stem)}\b") if "stem" in terms else None

    for dirpath, dirnames, filenames in os.walk(workspace_root, followlinks=False):
        dp = Path(dirpath)
        if not include_all:
            dirnames[:] = [
                d for d in dirnames
                if d not in ex and not d.startswith(".") and not (dp / d).is_symlink()
            ]

        for fname in filenames:
            fpath = dp / fname
            if fpath.suffix.lower() not in exts:
                continue

            # Avoid matching the target file against itself
            if fpath.resolve() == target_abs:
                continue

            rel_file = fpath.relative_to(workspace_root).as_posix()

            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for line_num, line in enumerate(f, start=1):
                        stripped = line.strip()
                        if not stripped:
                            continue

                        matched_kind = None
                        if rel_path in line or rel_path.replace("/", "\\") in line:
                            matched_kind = "path"
                        elif filename in line:
                            matched_kind = "filename"
                        elif stem_pattern and stem_pattern.search(line):
                            matched_kind = "module/symbol"

                        if matched_kind:
                            matches.append({
                                "file": rel_file,
                                "line_number": line_num,
                                "match_kind": matched_kind,
                                "snippet": stripped[:120],
                            })
            except Exception:
                continue

    return terms, matches


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


def render_relate_table(terms: dict[str, str], matches: list[dict[str, Any]], unique_files: list[str]) -> None:
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        title = f"References for '{terms['path']}' ({len(matches)} matches in {len(unique_files)} files)"
        table = Table(
            title=title,
            show_header=True,
            header_style="bold cyan",
            box=None,
            pad_edge=False,
        )
        table.add_column("Referencing File", style="bold green")
        table.add_column("Line", justify="right", style="magenta")
        table.add_column("Type", style="cyan")
        table.add_column("Snippet", style="white")

        for m in matches:
            table.add_row(
                m["file"],
                str(m["line_number"]),
                m["match_kind"],
                m["snippet"][:90],
            )

        console.print()
        console.print(table)
        console.print(
            f"\n[bold cyan]Target:[/bold cyan] {terms['path']} | "
            f"[bold green]Referencing Files:[/bold green] {len(unique_files)} | "
            f"[bold green]Total Hits:[/bold green] {len(matches)}\n"
        )
    except ImportError:
        render_plain(unique_files)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print relative paths, tree, or table for Python files, extensions, or cross-references.",
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
        "--relate",
        default=None,
        help="Find all files referencing/importing the specified target path or script.",
    )
    parser.add_argument(
        "--py",
        action="store_true",
        help="Restrict search or references to Python (.py) files only.",
    )
    parser.add_argument(
        "--strict",
        "-s",
        action="store_true",
        help="With --relate: only match full path or filename, skipping bare stem/symbol names.",
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
        help="Output raw JSON array of relative paths or relate match details.",
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

    # -------------------------------------------------------------------------
    # Mode A: Cross-Reference Inspection (--relate)
    # -------------------------------------------------------------------------
    if args.relate:
        terms, matches = search_references(
            workspace_root=search_root,
            target_path_input=args.relate,
            strict=args.strict,
            only_py=args.py,
            excludes=excludes,
            include_all=args.all,
        )
        unique_files = sorted(set(m["file"] for m in matches))

        if args.count:
            print(len(unique_files))
            return

        if args.json:
            out_data = {
                "search_terms": terms,
                "only_py": args.py,
                "total_matches": len(matches),
                "unique_files_count": len(unique_files),
                "referencing_files": unique_files,
                "matches": matches,
            }
            print(json.dumps(out_data, indent=2))
            return

        if args.tree:
            render_tree(unique_files, root_name=search_root.name)
        elif args.table:
            render_relate_table(terms, matches, unique_files)
        else:
            # Default: list unique relative paths of referencing files
            render_plain(unique_files)
        return

    # -------------------------------------------------------------------------
    # Mode B: Standard File Discovery / Tree
    # -------------------------------------------------------------------------
    find_ext = ".py" if args.py and not args.find else args.find

    files = find_files(
        search_root,
        find_ext=find_ext,
        match_pattern=args.match,
        excludes=excludes,
        include_all=args.all,
    )

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
    if find_ext:
        label = f"{find_ext} Files"
    elif args.match:
        label = f"'{args.match}' Files"
    elif not find_ext and not args.match:
        label = "Python Files"

    if args.json:
        render_json(rel_paths)
    elif args.tree:
        render_tree(rel_paths, root_name=search_root.name)
    elif args.table:
        render_table(rel_paths, search_root, file_type_label=label)
    else:
        render_plain(rel_paths)


if __name__ == "__main__":
    main()
