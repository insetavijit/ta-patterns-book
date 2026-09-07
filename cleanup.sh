#!/usr/bin/env bash
set -euo pipefail

# cleanup.sh — Project maintenance & workspace cleanup utility

print_help() {
    cat << 'HELP'
Usage: ./cleanup.sh [OPTIONS]

Options:
  --tmp       Remove all files and scratchpads in .tmp/ directory
  --trash     Remove all contents in __trash/ directory
  --pycache   Remove all __pycache__ directories and .pytest_cache
  --all       Perform full cleanup (tmp, trash, pycache)
  -h, --help  Show this help message
HELP
}

if [[ $# -eq 0 ]]; then
    print_help
    exit 0
fi

CLEAN_TMP=false
CLEAN_TRASH=false
CLEAN_PYCACHE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tmp)
            CLEAN_TMP=true
            shift
            ;;
        --trash)
            CLEAN_TRASH=true
            shift
            ;;
        --pycache)
            CLEAN_PYCACHE=true
            shift
            ;;
        --all)
            CLEAN_TMP=true
            CLEAN_TRASH=true
            CLEAN_PYCACHE=true
            shift
            ;;
        -h|--help)
            print_help
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            print_help
            exit 1
            ;;
    esac
done

if [[ "$CLEAN_TMP" == true ]]; then
    if [[ -d ".tmp" ]]; then
        echo "Cleaning .tmp/ directory..."
        rm -rf .tmp/* .tmp/.* 2>/dev/null || true
        echo "✓ .tmp/ cleared."
    else
        echo ".tmp/ directory does not exist, creating empty..."
        mkdir -p .tmp
    fi
fi

if [[ "$CLEAN_TRASH" == true ]]; then
    if [[ -d "__trash" ]]; then
        echo "Cleaning __trash/ directory..."
        rm -rf __trash/* __trash/.* 2>/dev/null || true
        echo "✓ __trash/ cleared."
    fi
fi

if [[ "$CLEAN_PYCACHE" == true ]]; then
    echo "Cleaning Python bytecode caches..."
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
    echo "✓ Python cache cleared."
fi

echo "Done."
