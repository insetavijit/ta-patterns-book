"""Tests for strategy Protocol, registry, and SMA cross implementation."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.strategies.base import StrategyProtocol
from Core.strategies.registry import get_strategy, list_strategies
from Core.strategies.sma_cross import SmaCrossStrategy


PARAMS = {
    "strategy_name": "sma_cross",
    "strategy_version": "1.0.0",
    "fast_window": 5,
    "slow_window": 20,
}


@pytest.fixture
def strategy():
    return SmaCrossStrategy()


@pytest.fixture
def synthetic_ohlcv():
    """200-bar synthetic EURUSD-like data."""
    n = 200
    idx = pd.date_range("2025-01-01", periods=n, freq="1min", tz="UTC")
    rng = np.random.default_rng(42)
    close = 1.05 + rng.normal(0, 0.001, n).cumsum()
    return pd.DataFrame(
        {
            "open":   close + rng.uniform(-0.0005, 0.0005, n),
            "high":   close + rng.uniform(0, 0.001, n),
            "low":    close - rng.uniform(0, 0.001, n),
            "close":  close,
            "volume": rng.uniform(1, 100, n),
        },
        index=idx,
    )


class TestStrategyProtocol:
    def test_satisfies_protocol(self, strategy):
        assert isinstance(strategy, StrategyProtocol)

    def test_has_name(self, strategy):
        assert strategy.name == "sma_cross"

    def test_has_version(self, strategy):
        assert isinstance(strategy.version, str) and strategy.version

    def test_has_generate_signals(self, strategy):
        assert callable(strategy.generate_signals)


class TestSmaCrossStrategy:
    def test_returns_two_series(self, strategy, synthetic_ohlcv):
        entries, exits = strategy.generate_signals(synthetic_ohlcv, PARAMS)
        assert isinstance(entries, pd.Series)
        assert isinstance(exits, pd.Series)

    def test_signals_are_boolean(self, strategy, synthetic_ohlcv):
        entries, exits = strategy.generate_signals(synthetic_ohlcv, PARAMS)
        assert entries.dtype == bool
        assert exits.dtype == bool

    def test_signals_aligned_to_index(self, strategy, synthetic_ohlcv):
        entries, exits = strategy.generate_signals(synthetic_ohlcv, PARAMS)
        assert len(entries) == len(synthetic_ohlcv)
        assert len(exits) == len(synthetic_ohlcv)

    def test_no_nans_in_signals(self, strategy, synthetic_ohlcv):
        entries, exits = strategy.generate_signals(synthetic_ohlcv, PARAMS)
        assert not entries.isna().any()
        assert not exits.isna().any()

    def test_fast_gte_slow_raises(self, strategy, synthetic_ohlcv):
        with pytest.raises(ValueError, match="fast_window"):
            strategy.generate_signals(synthetic_ohlcv, dict(PARAMS, fast_window=50, slow_window=10))

    def test_equal_windows_raises(self, strategy, synthetic_ohlcv):
        with pytest.raises(ValueError):
            strategy.generate_signals(synthetic_ohlcv, dict(PARAMS, fast_window=20, slow_window=20))

    def test_signals_on_real_data(self, strategy, ohlcv_sample):
        """Strategy must not error on real EURUSD 1m data."""
        entries, exits = strategy.generate_signals(ohlcv_sample, PARAMS)
        assert isinstance(entries, pd.Series)
        assert not entries.isna().any()
        assert not exits.isna().any()


class TestRegistry:
    def test_get_known_strategy(self):
        s = get_strategy("sma_cross")
        assert s.name == "sma_cross"

    def test_get_unknown_raises_key_error(self):
        with pytest.raises(KeyError, match="Available"):
            get_strategy("nonexistent_strategy")

    def test_list_strategies_returns_list(self):
        assert isinstance(list_strategies(), list)
        assert "sma_cross" in list_strategies()

    def test_list_strategies_is_sorted(self):
        names = list_strategies()
        assert names == sorted(names)
