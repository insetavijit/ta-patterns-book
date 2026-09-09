"""Unit tests for canonical ordering and fingerprinting in vbtspike."""

import unittest
from vbtspike.integrity.canonical import canonical_params, canonical_string
from vbtspike.integrity.fingerprint import compute_fingerprint


class TestVbtSpikeIntegrity(unittest.TestCase):
    def test_canonical_params_ordering(self):
        """canonical_params must sort keys lexicographically."""
        raw = {
            "strategy_version": "1.0.0",
            "strategy_name": "classic_floor_v4c",
            "tp_ratio": 1.0,
            "fast_window": 10,
        }
        pairs = canonical_params(raw)
        keys = [k for k, _ in pairs]
        self.assertEqual(keys, ["fast_window", "strategy_name", "strategy_version", "tp_ratio"])

    def test_canonical_params_missing_required_keys(self):
        """canonical_params must raise ValueError if strategy_name or strategy_version is missing."""
        with self.assertRaises(ValueError):
            canonical_params({"strategy_name": "test"})
        with self.assertRaises(ValueError):
            canonical_params({"strategy_version": "1.0.0"})

    def test_canonical_string(self):
        """canonical_string must format key=value pairs joined by pipe."""
        pairs = [("fast_window", "10"), ("strategy_name", "sma_cross")]
        s = canonical_string(pairs)
        self.assertEqual(s, "fast_window=10|strategy_name=sma_cross")

    def test_compute_fingerprint_deterministic(self):
        """compute_fingerprint must produce stable, 64-char hex SHA-256 digest."""
        params1 = {
            "strategy_name": "classic_floor_v4c",
            "strategy_version": "1.0.0",
            "fast_window": 10,
            "slow_window": 50,
        }
        params2 = {
            "slow_window": 50,
            "strategy_version": "1.0.0",
            "fast_window": 10,
            "strategy_name": "classic_floor_v4c",
        }
        fp1 = compute_fingerprint(params1)
        fp2 = compute_fingerprint(params2)
        self.assertEqual(len(fp1), 64)
        self.assertEqual(fp1, fp2)

    def test_compute_fingerprint_sensitive_to_changes(self):
        """Changing any parameter value must produce a distinct fingerprint."""
        fp1 = compute_fingerprint({"strategy_name": "s", "strategy_version": "1.0", "p": 1})
        fp2 = compute_fingerprint({"strategy_name": "s", "strategy_version": "1.0", "p": 2})
        self.assertNotEqual(fp1, fp2)


if __name__ == "__main__":
    unittest.main()
