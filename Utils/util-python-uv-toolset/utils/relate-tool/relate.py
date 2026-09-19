#!/usr/bin/env python3
"""
relate.py — Codebase Cross-Reference & Dependency Inspector

Inspects the codebase to discover which files reference, import, or mention
a target Python script by relative path, filename, or module stem.

Usage:
    uv run python relate.py --path Shared/strategies/classic_floor_mod_v6/CFMV0601B.py
    uv run python relate.py --path Utils/util-python-uv-toolset/utils/tree-tool/tree.py --table
    uv run python relate.py --path Utils/tools-info.md --plain
    uv run python relate.py --path duckdb_explorer.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    HAS_RICH = True
except ImportError:
    console = None
    HAS_RICH = False

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
    "build",
    "dist",
    ".egg-info",
}

DEFAULT_SCAN_EXTENSIONS = {
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


def search_references(
    workspace_root: Path,
    target_path_input: str,
    strict: bool = False,
    scan_exts: set[str] | None = None,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Search workspace files for occurrences of target path, filename, or module stem."""
    target = Path(target_path_input)
    # Target identifiers
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

    exts = scan_exts or DEFAULT_SCAN_EXTENSIONS
    matches: list[dict[str, Any]] = []

    # Regex pattern for stem word boundary search
    stem_pattern = re.compile(rf"\b{re.escape(stem)}\b") if "stem" in terms else None

    for dirpath, dirnames, filenames in os.walk(workspace_root, followlinks=False):
        dp = Path(dirpath)
        # Skip excluded dirs
        dirnames[:] = [
            d for d in dirnames
            if d not in DEFAULT_EXCLUDES and not d.startswith(".") and not (dp / d).is_symlink()
        ]

        for fname in filenames:
            fpath = dp / fname
            # Only scan targeted extensions
            if fpath.suffix.lower() not in exts:
                continue

            # Don't match the target file itself
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
                            # Ensure it is meaningful (e.g. import, call, quote)
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


def render_output(
    terms: dict[str, str],
    matches: list[dict[str, Any]],
    output_mode: str,
) -> None:
    """Format and render reference matches."""
    unique_files = sorted(set(m["file"] for m in matches))

    if output_mode == "plain":
        for uf in unique_files:
            print(uf)
        return

    if output_mode == "json":
        data = {
            "search_terms": terms,
            "total_matches": len(matches),
            "unique_files_count": len(unique_files),
            "referencing_files": unique_files,
            "matches": matches,
        }
        print(json.dumps(data, indent=2))
        return

    # Table / Default Mode
    if HAS_RICH and console:
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
            f"[bold green]Unique Referencing Files:[/bold green] {len(unique_files)} | "
            f"[bold green]Total Hits:[/bold green] {len(matches)}\n"
        )
    else:
        print(f"\n=== References for {terms['path']} ({len(matches)} matches) ===")
        for m in matches:
            print(f"{m['file']}:{m['line_number']} [{m['match_kind']}] {m['snippet']}")
        print(f"\nUnique Files: {len(unique_files)} | Total Matches: {len(matches)}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect codebase cross-references and dependencies for a target file or script."
    )
    parser.add_argument(
        "--path",
        "-p",
        required=True,
        help="Path or filename of the target script/file to search for.",
    )
    parser.add_argument(
        "--root",
        "-r",
        default=None,
        help="Root workspace directory to search (defaults to project root).",
    )
    parser.add_argument(
        "--strict",
        "-s",
        action="store_true",
        help="Match only full relative path or filename, skipping bare module stems.",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Output clean list of unique referencing file paths.",
    )
    parser.add_argument(
        "--table",
        action="store_true",
        help="Render borderless summary table with line numbers and snippets.",
    )
    parser.add_argument(
        "--json",
        "-j",
        action="store_true",
        help="Output structured JSON payload.",
    )

    args = parser.parse_args()

    here = Path(__file__).resolve().parent
    workspace_root = Path(args.root).resolve() if args.root else get_workspace_root(here)

    terms, matches = search_references(
        workspace_root=workspace_root,
        target_path_input=args.path,
        strict=args.strict,
    )

    output_mode = "table"
    if args.plain:
        output_mode = "plain"
    elif args.json:
        output_mode = "json"

    render_output(terms, matches, output_mode=output_mode)


if __name__ == "__main__":
    main()
