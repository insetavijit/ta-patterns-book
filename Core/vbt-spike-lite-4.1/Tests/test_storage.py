"""Tests for the storage layer against the provided ohlcv_dump.duckdb."""

from __future__ import annotations

import pytest


class TestProvidedDatabase:
    """Validate the provided DuckDB file structure and content."""

    def test_db_file_exists(self, db_path):
        assert db_path.exists()
        assert db_path.suffix == ".duckdb"

    def test_expected_tables_present(self, db_conn):
        tables = {r[0] for r in db_conn.execute("SHOW TABLES").fetchall()}
        assert "ohlcv_1m_2025" in tables
        assert "ohlcv_eurusd_1m_2025" in tables

    def test_ohlcv_1m_has_rows(self, db_conn):
        assert db_conn.execute("SELECT COUNT(*) FROM ohlcv_1m_2025").fetchone()[0] > 0

    def test_ohlcv_eurusd_has_rows(self, db_conn):
        assert db_conn.execute("SELECT COUNT(*) FROM ohlcv_eurusd_1m_2025").fetchone()[0] > 0

    def test_ohlcv_1m_columns(self, db_conn):
        cols = {r[0] for r in db_conn.execute("DESCRIBE ohlcv_1m_2025").fetchall()}
        assert cols >= {"timestamp", "open", "high", "low", "close", "volume"}

    def test_ohlcv_eurusd_columns(self, db_conn):
        cols = {r[0] for r in db_conn.execute("DESCRIBE ohlcv_eurusd_1m_2025").fetchall()}
        assert cols >= {"timestamp", "open", "high", "low", "close", "volume"}

    def test_no_null_close_prices(self, db_conn):
        nulls = db_conn.execute(
            "SELECT COUNT(*) FROM ohlcv_1m_2025 WHERE close IS NULL"
        ).fetchone()[0]
        assert nulls == 0

    def test_high_gte_low(self, db_conn):
        violations = db_conn.execute(
            "SELECT COUNT(*) FROM ohlcv_1m_2025 WHERE high < low"
        ).fetchone()[0]
        assert violations == 0

    def test_high_gte_open_and_close(self, db_conn):
        violations = db_conn.execute(
            "SELECT COUNT(*) FROM ohlcv_1m_2025 WHERE high < open OR high < close"
        ).fetchone()[0]
        assert violations == 0

    def test_low_lte_open_and_close(self, db_conn):
        violations = db_conn.execute(
            "SELECT COUNT(*) FROM ohlcv_1m_2025 WHERE low > open OR low > close"
        ).fetchone()[0]
        assert violations == 0

    def test_timestamps_are_ordered(self, db_conn):
        result = db_conn.execute("""
            SELECT COUNT(*) FROM (
                SELECT timestamp,
                       LAG(timestamp) OVER (ORDER BY timestamp) AS prev_ts
                FROM ohlcv_1m_2025
            ) t WHERE timestamp < prev_ts
        """).fetchone()[0]
        assert result == 0

    def test_volume_non_negative(self, db_conn):
        violations = db_conn.execute(
            "SELECT COUNT(*) FROM ohlcv_1m_2025 WHERE volume < 0"
        ).fetchone()[0]
        assert violations == 0

    def test_both_tables_same_row_count(self, db_conn):
        c1 = db_conn.execute("SELECT COUNT(*) FROM ohlcv_1m_2025").fetchone()[0]
        c2 = db_conn.execute("SELECT COUNT(*) FROM ohlcv_eurusd_1m_2025").fetchone()[0]
        assert c1 == c2

    def test_date_range_starts_2025(self, db_conn):
        """Data should start in 2025 and end in 2025 or early 2026."""
        min_ts, max_ts = db_conn.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM ohlcv_1m_2025"
        ).fetchone()
        assert min_ts.year == 2025
        assert max_ts.year in (2025, 2026)

    def test_close_price_in_forex_range(self, db_conn):
        """EURUSD close should be in plausible forex range (0.5 < x < 2.0)."""
        mean_close = db_conn.execute(
            "SELECT AVG(close) FROM ohlcv_1m_2025"
        ).fetchone()[0]
        assert 0.5 < mean_close < 2.0


class TestDbConnection:
    def test_missing_db_exits_1(self, tmp_path):
        from Core.vbtspike.storage.db import get_connection
        with pytest.raises(SystemExit) as exc_info:
            get_connection(tmp_path / "nonexistent.duckdb")
        assert exc_info.value.code == 1
