"""Unit tests for StrategyProtocol runtime checking and compliance."""

import unittest
from typing import Any
import pandas as pd

from strategies.base import StrategyProtocol


class DummyCompliantStrategy:
    name: str = "dummy"
    version: str = "1.0.0"

    def generate_signals(
        self, ohlcv: pd.DataFrame, params: dict[str, Any]
    ) -> tuple[pd.Series, pd.Series]:
        return pd.Series(dtype=bool), pd.Series(dtype=bool)


class DummyNonCompliantStrategy:
    # Missing generate_signals
    name: str = "invalid"


class TestStrategyBase(unittest.TestCase):
    def test_protocol_runtime_check(self):
        """StrategyProtocol should recognize compliant classes with isinstance."""
        strat = DummyCompliantStrategy()
        self.assertIsInstance(strat, StrategyProtocol)

        invalid = DummyNonCompliantStrategy()
        self.assertNotIsInstance(invalid, StrategyProtocol)


if __name__ == "__main__":
    unittest.main()
