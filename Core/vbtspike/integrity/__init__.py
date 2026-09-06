"""Research Integrity package — fingerprinting and dedup logic.

The canonical fingerprint is computed purely in Python (never DuckDB hash()).
See canonical.py for the scalar-ordering rule (v2 DL-N3).
"""

from .fingerprint import compute_fingerprint

__all__ = ["compute_fingerprint"]
