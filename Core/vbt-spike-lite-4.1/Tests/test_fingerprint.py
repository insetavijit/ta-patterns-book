"""Tests for Research Integrity — canonical ordering and SHA-256 fingerprint."""

from __future__ import annotations

import hashlib

import pytest

from Core.vbtspike.integrity.canonical import canonical_params, canonical_string
from Core.vbtspike.integrity.fingerprint import compute_fingerprint


BASE_PARAMS = {
    "strategy_name": "sma_cross",
    "strategy_version": "1.0.0",
    "fast_window": 10,
    "slow_window": 50,
}


class TestCanonical:
    def test_output_is_sorted_by_key(self):
        pairs = canonical_params(BASE_PARAMS)
        keys = [k for k, _ in pairs]
        assert keys == sorted(keys)

    def test_values_are_strings(self):
        for _, v in canonical_params(BASE_PARAMS):
            assert isinstance(v, str)

    def test_canonical_string_format(self):
        assert canonical_string([("a", "1"), ("b", "2")]) == "a=1|b=2"

    def test_missing_strategy_name_raises(self):
        with pytest.raises(ValueError, match="strategy_name"):
            canonical_params({"strategy_version": "1.0.0"})

    def test_missing_strategy_version_raises(self):
        with pytest.raises(ValueError, match="strategy_version"):
            canonical_params({"strategy_name": "sma_cross"})

    def test_extra_keys_included(self):
        pairs = canonical_params(dict(BASE_PARAMS, extra="hello"))
        assert "extra" in [k for k, _ in pairs]


class TestFingerprint:
    def test_returns_64_char_hex(self):
        fp = compute_fingerprint(BASE_PARAMS)
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_deterministic(self):
        assert compute_fingerprint(BASE_PARAMS) == compute_fingerprint(BASE_PARAMS)

    def test_different_params_differ(self):
        fp1 = compute_fingerprint(BASE_PARAMS)
        fp2 = compute_fingerprint(dict(BASE_PARAMS, fast_window=20))
        assert fp1 != fp2

    def test_order_independent(self):
        p1 = {"strategy_name": "sma_cross", "strategy_version": "1.0.0", "fast_window": 10}
        p2 = {"fast_window": 10, "strategy_version": "1.0.0", "strategy_name": "sma_cross"}
        assert compute_fingerprint(p1) == compute_fingerprint(p2)

    def test_matches_manual_sha256(self):
        params = {"strategy_name": "sma_cross", "strategy_version": "1.0.0"}
        raw = "strategy_name=sma_cross|strategy_version=1.0.0"
        expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        assert compute_fingerprint(params) == expected
