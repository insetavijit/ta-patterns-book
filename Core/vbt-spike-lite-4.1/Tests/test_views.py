"""Tests that the OHLCV data from the provided DB is usable by strategies."""

from __future__ import annotations

import pandas as pd
import pytest


class TestOhlcvDataFrame:
    def test_sample_is_dataframe(self, ohlcv_sample):
        assert isinstance(ohlcv_sample, pd.DataFrame)

    def test_sample_has_required_columns(self, ohlcv_sample):
        assert {"open", "high", "low", "close", "volume"}.issubset(ohlcv_sample.columns)

    def test_sample_has_datetime_index(self, ohlcv_sample):
        assert isinstance(ohlcv_sample.index, pd.DatetimeIndex)

    def test_sample_index_is_timezone_aware(self, ohlcv_sample):
        assert ohlcv_sample.index.tz is not None

    def test_no_nulls_in_close(self, ohlcv_sample):
        assert ohlcv_sample["close"].isna().sum() == 0

    def test_close_positive(self, ohlcv_sample):
        assert (ohlcv_sample["close"] > 0).all()

    def test_full_table_loadable(self, db_conn):
        df = db_conn.execute(
            "SELECT timestamp, open, high, low, close, volume FROM ohlcv_1m_2025"
        ).df()
        assert len(df) > 100_000
        assert "close" in df.columns

    def test_eurusd_table_loadable(self, db_conn):
        df = db_conn.execute(
            "SELECT timestamp, open, high, low, close, volume FROM ohlcv_eurusd_1m_2025"
        ).df()
        assert len(df) > 100_000

    def test_close_in_forex_range(self, ohlcv_sample):
        mean = ohlcv_sample["close"].mean()
        assert 0.5 < mean < 2.0
