"""Canonical scalar-ordering rule for fingerprint tuples (v2 DL-N3).

The canonical form of a fingerprint tuple is derived by:
  1. Taking every scalar that feeds the fingerprint (strategy name, version,
     and each strategy parameter used by generate_signals).
  2. Sorting them by key name (lexicographic, case-sensitive).
  3. Forming a stable string representation of each (key, value) pair.

This ordering rule is immutable. Changes here break all historical fingerprints.
"""

from __future__ import annotations

from typing import Any


def canonical_params(params: dict[str, Any]) -> list[tuple[str, str]]:
    """Produce a canonically ordered list of (key, value) pairs from params.

    Args:
        params: Raw params dict. Must contain at minimum: strategy_name,
                strategy_version, and all strategy-specific parameter keys.

    Returns:
        Sorted list of (key, str(value)) tuples, ordered by key name.

    Raises:
        ValueError: If required fingerprint keys are missing.
    """
    required = {"strategy_name", "strategy_version"}
    missing = required - params.keys()
    if missing:
        raise ValueError(
            f"Fingerprint params missing required keys: {sorted(missing)}. "
            "See spec DL-V6-04."
        )
    return [(k, str(v)) for k, v in sorted(params.items())]


def canonical_string(pairs: list[tuple[str, str]]) -> str:
    """Serialize canonical pairs to a stable string for hashing.

    Format: ``key=value`` joined by ``|``.
    Example: ``fast_window=10|slow_window=50|strategy_name=sma_cross|strategy_version=1.0.0``
    """
    return "|".join(f"{k}={v}" for k, v in pairs)
