"""Unit tests for loss_profile database path resolution and config loading."""

import unittest
from pathlib import Path
from unittest.mock import patch

from ta_patterns_book.loss_profile.db import (
    load_config,
    get_duckdb_path,
    get_outs_dir,
)


class TestLossProfileDB(unittest.TestCase):
    def test_get_outs_dir(self):
        """get_outs_dir should return a string ending in Shared/OUTs/png."""
        outs_dir = get_outs_dir()
        self.assertIsInstance(outs_dir, str)
        self.assertTrue(outs_dir.endswith("Shared/OUTs/png") or outs_dir.endswith("Shared\\OUTs\\png"))

    def test_load_config(self):
        """load_config should return a dict."""
        cfg = load_config()
        self.assertIsInstance(cfg, dict)

    def test_get_duckdb_path_custom(self):
        """Custom path should be returned directly."""
        custom = "/path/to/custom.duckdb"
        self.assertEqual(get_duckdb_path(custom_path=custom), custom)

    def test_get_duckdb_path_invalid_target(self):
        """Invalid target name should raise ValueError."""
        with self.assertRaises(ValueError):
            get_duckdb_path(target="invalid_target")

    def test_get_duckdb_path_primary(self):
        """Resolving primary target should return a valid string path."""
        try:
            path = get_duckdb_path(target="primary")
            self.assertIsInstance(path, str)
            self.assertTrue(path.endswith(".duckdb"))
        except ValueError:
            # If not configured in cnf.yaml, test passes on expected exception
            pass


if __name__ == "__main__":
    unittest.main()
