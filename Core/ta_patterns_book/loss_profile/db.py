"""Core database utilities for loss profiling."""

import glob
import os
import duckdb
import yaml

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "Shared", "cnf.yaml")
DEFAULT_DUCKDB_PATH = os.path.join(PROJECT_ROOT, "Shared", "Data", "eur_usd_trades_5m.duckdb")


def get_outs_dir() -> str:
    return os.path.join(PROJECT_ROOT, "Shared", "OUTs", "png")


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}


def get_duckdb_path(target: str = "primary", custom_path: str = None) -> str:
    """Resolve DuckDB database path based on explicit CLI flags and Shared/cnf.yaml.
    
    Args:
        target: 'primary' or 'secondary'
        custom_path: Explicit path passed via --db
        
    Returns:
        Absolute or relative path to the DuckDB file.
    """
    if custom_path:
        return custom_path

    config = load_config()
    data_paths = config.get("paths", {}).get("shared", {}).get("data", {})
    
    if target == "primary":
        rel_path = (
            data_paths.get("primary_db")
            or config.get("paths", {}).get("shared", {}).get("strategies", {}).get("active_db_path")
            or config.get("data", {}).get("primary_db")
        )
    elif target == "secondary":
        rel_path = (
            data_paths.get("secondary_db")
            or data_paths.get("backtest_db")
            or config.get("data", {}).get("secondary_db")
        )
    else:
        raise ValueError(f"Unknown database target '{target}'. Use 'primary', 'secondary', or pass --db <path>.")

    if not rel_path:
        raise ValueError(
            f"No '{target}' database configured in Shared/cnf.yaml. "
            "Please specify --primary, --secondary, or pass --db <path> explicitly."
        )

    full_path = rel_path if os.path.isabs(rel_path) else os.path.normpath(os.path.join(PROJECT_ROOT, rel_path))
    return full_path


def get_db_connection(db_path: str = None, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    path = db_path if db_path else get_duckdb_path()
    if not os.path.exists(path):
        raise FileNotFoundError(f"DuckDB database file not found at '{path}'")
    return duckdb.connect(path, read_only=read_only)
