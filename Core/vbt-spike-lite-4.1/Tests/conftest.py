"""Shared pytest fixtures for vbtSpike tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "Shared" / "Data" / "ohlcv_dump.duckdb"
CONFIG_PATH = ROOT / "Shared" / "cnf.yaml"


@pytest.fixture(scope="session")
def db_path() -> Path:
    """Path to the provided DuckDB file."""
    assert DB_PATH.exists(), f"DuckDB file not found: {DB_PATH}"
    return DB_PATH


@pytest.fixture(scope="session")
def config_path() -> Path:
    assert CONFIG_PATH.exists(), f"Config not found: {CONFIG_PATH}"
    return CONFIG_PATH


@pytest.fixture(scope="session")
def cfg(config_path):
    """Loaded, validated VbtSpikeConfig."""
    from Core.vbtspike.config.loader import load_config
    return load_config(config_path)


@pytest.fixture(scope="session")
def db_conn(db_path):
    """Read-only connection to the provided DB."""
    import duckdb
    conn = duckdb.connect(str(db_path), read_only=True)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def ohlcv_sample(db_conn) -> pd.DataFrame:
    """500-row sample from ohlcv_1m_2025, indexed by timestamp."""
    df = db_conn.execute(
        "SELECT timestamp, open, high, low, close, volume "
        "FROM ohlcv_1m_2025 ORDER BY timestamp LIMIT 500"
    ).df()
    df = df.rename(columns={"timestamp": "ts"}).set_index("ts")
    df.index = pd.to_datetime(df.index, utc=True)
    return df
