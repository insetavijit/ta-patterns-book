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


def get_duckdb_path() -> str:
    config = load_config()
    rel_path = config.get("data", {}).get("duckdb_path", DEFAULT_DUCKDB_PATH)
    full_path = rel_path if os.path.isabs(rel_path) else os.path.normpath(os.path.join(PROJECT_ROOT, rel_path))
    if os.path.exists(full_path):
        return full_path

    search_dirs = [
        os.path.join(PROJECT_ROOT, "Shared", "Data"),
        os.path.join(PROJECT_ROOT, ".tmp")
    ]
    for d in search_dirs:
        duck_files = glob.glob(os.path.join(d, "*.duckdb"))
        if duck_files:
            return duck_files[0]

    return DEFAULT_DUCKDB_PATH


def get_db_connection(db_path: str = None, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    path = db_path if db_path else get_duckdb_path()
    if not os.path.exists(path):
        raise FileNotFoundError(f"DuckDB database file not found at '{path}'")
    return duckdb.connect(path, read_only=read_only)
