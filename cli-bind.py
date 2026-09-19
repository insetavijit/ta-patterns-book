#!/usr/bin/env python3
"""
cli-bind.py — Universal CLI Registry Binder & Updater

Discovers all modular `cli-*.yaml` tool definition files across the project
and merges them into the central `Shared/cli.yaml` workflow registry.

Usage:
    uv run python cli-bind.py
    uv run python cli-bind.py --dry-run
    uv run python cli-bind.py --verbose
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required. Run: uv run python cli-bind.py")

try:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    HAS_RICH = True
except ImportError:
    console = None
    HAS_RICH = False

# Default directories to skip during discovery
EXCLUDE_DIRS = {
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


def find_cli_specs(workspace_root: Path) -> list[Path]:
    """Find all `cli-*.yaml` and `cli-*.yml` specification files."""
    matched_files: list[Path] = []

    for path in sorted(workspace_root.rglob("cli-*.y*ml")):
        # Skip excluded directories
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        # Avoid treating output as an input
        if path.name in ("cli.yaml", "cli.yml"):
            continue
        matched_files.append(path)

    return matched_files


def load_yaml(path: Path) -> dict[str, Any]:
    """Safely load and parse a YAML file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[WARN] Failed to parse {path}: {e}", file=sys.stderr)
        return {}


def merge_cli_registries(
    workspace_root: Path,
    target_cli_file: Path,
    spec_files: list[Path],
    verbose: bool = False,
) -> dict[str, Any]:
    """Merge discovered cli-*.yaml specifications into target registry."""
    # 1. Load existing target file if present
    target_data = load_yaml(target_cli_file) if target_cli_file.exists() else {}
    existing_cli_list: list[dict[str, Any]] = target_data.get("cli", [])
    if not isinstance(existing_cli_list, list):
        existing_cli_list = []

    # Map of existing commands by name to preserve order or update
    commands_by_name: dict[str, dict[str, Any]] = {}
    ordered_names: list[str] = []

    for entry in existing_cli_list:
        if isinstance(entry, dict) and "name" in entry:
            name = entry["name"]
            commands_by_name[name] = entry
            ordered_names.append(name)

    # 2. Process each discovered spec file
    processed_tools: dict[str, dict[str, Any]] = target_data.get("tools", {})
    if not isinstance(processed_tools, dict):
        processed_tools = {}

    for spec_path in spec_files:
        rel_spec_path = spec_path.relative_to(workspace_root).as_posix()
        spec_content = load_yaml(spec_path)

        # Extract tool-level metadata if present
        tool_meta = spec_content.get("tool")
        if isinstance(tool_meta, dict) and "name" in tool_meta:
            tool_name = tool_meta["name"]
            tool_meta["spec_file"] = rel_spec_path
            processed_tools[tool_name] = tool_meta
            if verbose:
                print(f"[INFO] Discovered tool '{tool_name}' in {rel_spec_path}")

        # Extract command-level entries
        cli_entries = spec_content.get("cli", [])
        if not isinstance(cli_entries, list):
            continue

        for cmd in cli_entries:
            if not isinstance(cmd, dict) or "name" not in cmd:
                continue

            cmd_name = cmd["name"]
            # Track origin spec file
            cmd["spec_file"] = rel_spec_path

            if cmd_name not in commands_by_name:
                ordered_names.append(cmd_name)
            commands_by_name[cmd_name] = cmd

            if verbose:
                print(f"  -> Registered command: {cmd_name}")

    # 3. Assemble merged structure
    merged_cli_list = [commands_by_name[name] for name in ordered_names]

    result: dict[str, Any] = {
        "cli": merged_cli_list,
    }

    if processed_tools:
        result["tools"] = processed_tools

    return result


def render_summary(spec_files: list[Path], merged_data: dict[str, Any], target_path: Path) -> None:
    """Render a clean summary table of the merged CLI registry."""
    cli_entries = merged_data.get("cli", [])
    tool_entries = merged_data.get("tools", {})

    if HAS_RICH and console:
        table = Table(
            title=f"CLI Registry Binder Summary -> {target_path}",
            show_header=True,
            header_style="bold cyan",
            box=None,
            pad_edge=False,
        )
        table.add_column("Command Name", style="bold green")
        table.add_column("Purpose", style="white")
        table.add_column("Spec File", style="dim")

        for cmd in cli_entries:
            name = cmd.get("name", "")
            purpose = cmd.get("purpose", "")
            if len(purpose) > 65:
                purpose = purpose[:62] + "..."
            spec = cmd.get("spec_file", "Shared/cli.yaml")
            table.add_row(name, purpose, spec)

        console.print()
        console.print(table)
        console.print(
            f"\n[bold green]✓[/bold green] Discovered [bold]{len(spec_files)}[/bold] spec files | "
            f"Registered [bold]{len(tool_entries)}[/bold] tools | "
            f"Total commands: [bold]{len(cli_entries)}[/bold]\n"
        )
    else:
        print(f"\n=== CLI Registry Binder Summary ({target_path}) ===")
        for cmd in cli_entries:
            print(f"- {cmd.get('name')}: {cmd.get('purpose')}")
        print(f"\nTotal spec files: {len(spec_files)} | Total commands: {len(cli_entries)}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find all cli-*.yaml files across workspace and merge into Shared/cli.yaml."
    )
    parser.add_argument(
        "--target",
        "-t",
        type=Path,
        default=Path("Shared/cli.yaml"),
        help="Target output CLI registry YAML file (default: Shared/cli.yaml).",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Inspect discovery and merge preview without modifying target file.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print verbose processing logs.",
    )
    args = parser.parse_args()

    workspace_root = Path(__file__).resolve().parent
    target_path = (workspace_root / args.target).resolve()

    # 1. Discover all cli-*.yaml files
    spec_files = find_cli_specs(workspace_root)
    if args.verbose:
        print(f"[INFO] Found {len(spec_files)} spec files in workspace.")
        for p in spec_files:
            print(f"  - {p.relative_to(workspace_root)}")

    # 2. Merge registries
    merged_data = merge_cli_registries(
        workspace_root=workspace_root,
        target_cli_file=target_path,
        spec_files=spec_files,
        verbose=args.verbose,
    )

    # 3. Output / Save
    if args.dry_run:
        print("\n[DRY RUN] Target file will not be updated.")
        render_summary(spec_files, merged_data, target_path)
        return

    # Write merged YAML with standard header
    header = (
        "# Project CLI Workflow Registry\n"
        "# Shared/cli.yaml\n"
        "# Generated & consolidated by cli-bind.py\n\n"
    )

    yaml_str = yaml.dump(
        merged_data,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        indent=2,
    )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(header + yaml_str)

    render_summary(spec_files, merged_data, target_path)


if __name__ == "__main__":
    main()
