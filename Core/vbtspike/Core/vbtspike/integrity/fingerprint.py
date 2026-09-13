"""Python-side fingerprint digest computation (spec DL-V5-04, DL-V6-04).

The fingerprint is a SHA-256 hex digest of the canonical param string.
It is computed entirely in Python — DuckDB's internal hash() is never used,
so fingerprints are stable and independently reproducible from params alone.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .canonical import canonical_params, canonical_string


def compute_fingerprint(params: dict[str, Any]) -> str:
    """Compute the canonical SHA-256 fingerprint for a set of run params.

    Args:
        params: Must contain ``strategy_name``, ``strategy_version``, and all
                strategy-specific parameters that feed ``generate_signals``.
                Additional keys are included in the fingerprint.

    Returns:
        A 64-character lowercase hex string (SHA-256 digest).

    Example::

        fp = compute_fingerprint({
            "strategy_name": "sma_cross",
            "strategy_version": "1.0.0",
            "fast_window": 10,
            "slow_window": 50,
        })
    """
    pairs = canonical_params(params)
    raw = canonical_string(pairs)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
