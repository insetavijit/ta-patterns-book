import argparse
import glob
import os
import sys
import duckdb
import pandas as pd
import yaml

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NOTEBOOKS_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
PROJECT_ROOT = os.path.abspath(os.path.join(NOTEBOOKS_DIR, ".."))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "Shared", "cnf.yaml")
DEFAULT_DUCKDB_PATH = os.path.join(PROJECT_ROOT, "Shared", "data", "EURUSD_5m_2025_v2_trades_and_ohlcv.duckdb")

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}

def get_duckdb_path():
    config = load_config()
    rel_path = config.get("data", {}).get("duckdb_path", DEFAULT_DUCKDB_PATH)
    full_path = rel_path if os.path.isabs(rel_path) else os.path.normpath(os.path.join(PROJECT_ROOT, rel_path))
    if os.path.exists(full_path):
        return full_path

    search_dirs = [
        os.path.join(PROJECT_ROOT, "Shared", "data"),
        os.path.join(PROJECT_ROOT, ".tmp")
    ]
    for d in search_dirs:
        duck_files = glob.glob(os.path.join(d, "*.duckdb"))
        if duck_files:
            return duck_files[0]

    return DEFAULT_DUCKDB_PATH

def check_3_red_candles(timestamp, db_path=None, table_name="ohlcv_5m"):
    """
    Reads the last 3 candles from table_name ending at or before the given timestamp.
    Returns True if all 3 candles are red (close < open), otherwise False.
    """
    if db_path is None:
        db_path = get_duckdb_path()

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DuckDB database file not found at '{db_path}'")

    ts_str = str(timestamp).strip()

    con = duckdb.connect(db_path, read_only=True)
    query = f"""
        SELECT 
            timestamp,
            open,
            high,
            low,
            close,
            (close < open) AS is_red
        FROM "{table_name}"
        WHERE CAST(timestamp AS VARCHAR) <= '{ts_str}'
        ORDER BY timestamp DESC
        LIMIT 3;
    """
    df = con.execute(query).df()
    con.close()

    if len(df) < 3:
        # Not enough candles available before this timestamp
        return False

    # Check if all 3 candles are red (close < open)
    all_red = bool(df['is_red'].all())
    return all_red

def main():
    parser = argparse.ArgumentParser(description="Check if last 3 candles ending at timestamp are all RED (close < open)")
    parser.add_argument("--timestamp", "-t", type=str, required=True, help="Target timestamp (e.g. '2025-01-01 23:30:00')")
    parser.add_argument("--db", type=str, default=None, help="Path to DuckDB database file")
    parser.add_argument("--table", type=str, default="ohlcv_5m", help="OHLCV table name (default: ohlcv_5m)")

    args = parser.parse_args()
    db_path = args.db if args.db else get_duckdb_path()

    result = check_3_red_candles(args.timestamp, db_path=db_path, table_name=args.table)

    print(f"Timestamp : {args.timestamp}")
    print(f"Result    : {result}")

if __name__ == "__main__":
    main()
