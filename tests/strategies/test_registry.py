"""Unit tests for strategy registry discovery and resolution."""

import unittest
from strategies.base import StrategyProtocol
from strategies.registry import _REGISTRY, get_strategy


class TestStrategyRegistry(unittest.TestCase):
    def test_get_strategy_registered(self):
        """Registered strategy names must return valid StrategyProtocol instances."""
        strat = get_strategy("CFMV0601B")
        self.assertIsInstance(strat, StrategyProtocol)
        self.assertEqual(strat.name, "CFMV0601B")
        self.assertTrue(hasattr(strat, "version"))
        self.assertTrue(callable(strat.generate_signals))

    def test_get_strategy_concurrent(self):
        """CFMV0601C strategy should be registered and resolvable."""
        strat = get_strategy("CFMV0601C")
        self.assertIsInstance(strat, StrategyProtocol)
        self.assertEqual(strat.name, "CFMV0601C")

    def test_get_strategy_unknown_raises_keyerror(self):
        """Requesting an unregistered strategy must raise KeyError with available strategies listed."""
        with self.assertRaises(KeyError) as ctx:
            get_strategy("non_existent_strategy_xyz")
        self.assertIn("Unknown strategy", str(ctx.exception))
        self.assertIn("CFMV0601B", str(ctx.exception))

    def test_all_registered_strategies_satisfy_protocol(self):
        """Every entry in _REGISTRY must satisfy StrategyProtocol."""
        self.assertTrue(len(_REGISTRY) > 0)
        for name, strat in _REGISTRY.items():
            self.assertIsInstance(strat, StrategyProtocol, f"{name} does not implement StrategyProtocol")
            self.assertTrue(bool(strat.name))
            self.assertTrue(bool(strat.version))


if __name__ == "__main__":
    unittest.main()
