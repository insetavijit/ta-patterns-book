#!/usr/bin/env python3
"""
upload-to-hf.py — Upload a local file to a Hugging Face dataset repository.

Usage:
    uv run python Utils/upload-to-hf.py --target "Shared/Data/classic_floor_mod-v6-1.duckdb"
    uv run python Utils/upload-to-hf.py --target "Shared/Data/classic_floor_mod-v6-1.duckdb" \
        --repo "your-hf-username/your-dataset-repo" \
        --path-in-repo "data/classic_floor_mod-v6-1.duckdb" \
        --repo-type dataset \
        --commit-message "Upload DuckDB snapshot"

Requirements:
    uv add huggingface_hub

Authentication:
    Set the HF_TOKEN environment variable or run `huggingface-cli login` beforehand.
"""

import argparse
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="upload-to-hf",
        description="Upload a local file to a Hugging Face Hub repository.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--target",
        required=True,
        metavar="PATH",
        help="Path to the local source file to upload (e.g. Shared/Data/classic_floor_mod-v6-1.duckdb).",
    )
    parser.add_argument(
        "--repo",
        default="Sarkaravijit123/my-tst-data",
        metavar="REPO_ID",
        help=(
            "Hugging Face repo ID in the form 'username/repo-name'. "
            "Defaults to 'Sarkaravijit123/my-tst-data'."
        ),
    )
    parser.add_argument(
        "--path-in-repo",
        default=None,
        metavar="DEST_PATH",
        help=(
            "Destination path inside the HF repo (e.g. 'data/file.duckdb'). "
            "Defaults to the basename of --target."
        ),
    )
    parser.add_argument(
        "--repo-type",
        default="dataset",
        choices=["dataset", "model", "space"],
        help="HF repository type (default: dataset).",
    )
    parser.add_argument(
        "--commit-message",
        default=None,
        metavar="MSG",
        help="Commit message for the upload. Auto-generated if not provided.",
    )
    parser.add_argument(
        "--token",
        default=None,
        metavar="HF_TOKEN",
        help=(
            "Hugging Face API token. Falls back to HF_TOKEN env var or "
            "the token stored by `huggingface-cli login`."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and print the upload plan without actually uploading.",
    )
    return parser.parse_args()


def resolve_token(cli_token: str | None) -> str | None:
    """Return the HF token from CLI arg → env var → None (let hf_hub handle it)."""
    if cli_token:
        return cli_token
    return os.environ.get("HF_TOKEN")


def main() -> None:
    args = parse_args()

    # ── Resolve source file ────────────────────────────────────────────────
    source = Path(args.target).expanduser()

    # Support both absolute paths and paths relative to the project root.
    if not source.is_absolute():
        # Walk up from this script's location to find the project root
        # (the directory that contains pyproject.toml / GEMINI.md).
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir.parent  # Utils/../  →  ta-patterns-book/
        source = (project_root / source).resolve()

    if not source.exists():
        print(f"[ERROR] Source file not found: {source}", file=sys.stderr)
        sys.exit(1)

    if not source.is_file():
        print(f"[ERROR] --target must point to a file, not a directory: {source}", file=sys.stderr)
        sys.exit(1)

    # ── Resolve repo ID ────────────────────────────────────────────────────
    repo_id: str = args.repo

    # ── Resolve destination path inside the repo ───────────────────────────
    path_in_repo: str = args.path_in_repo or source.name

    # ── Resolve commit message ─────────────────────────────────────────────
    commit_message: str = (
        args.commit_message
        or f"Upload {source.name} via upload-to-hf.py"
    )

    # ── Resolve token ──────────────────────────────────────────────────────
    token = resolve_token(args.token)

    # ── Print upload plan ──────────────────────────────────────────────────
    print("=" * 60)
    print("  Hugging Face Upload Plan")
    print("=" * 60)
    print(f"  Source file   : {source}")
    print(f"  File size     : {source.stat().st_size / 1_048_576:.2f} MB")
    print(f"  Repo ID       : {repo_id}")
    print(f"  Repo type     : {args.repo_type}")
    print(f"  Path in repo  : {path_in_repo}")
    print(f"  Commit message: {commit_message}")
    print(f"  Token         : {'<from env/cache>' if token else '<not set — using cached login>'}")
    print("=" * 60)

    if args.dry_run:
        print("\n[DRY RUN] No upload performed.")
        return

    # ── Import huggingface_hub (deferred so --dry-run works without it) ────
    try:
        from huggingface_hub import HfApi
    except ImportError:
        print(
            "[ERROR] huggingface_hub is not installed.\n"
            "  Run:  uv add huggingface_hub",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Upload ─────────────────────────────────────────────────────────────
    api = HfApi(token=token)

    print("\nUploading …")
    try:
        url = api.upload_file(
            path_or_fileobj=str(source),
            path_in_repo=path_in_repo,
            repo_id=repo_id,
            repo_type=args.repo_type,
            commit_message=commit_message,
        )
        print("\n[OK] Upload complete.")
        print(f"     URL: {url}")
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] Upload failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
