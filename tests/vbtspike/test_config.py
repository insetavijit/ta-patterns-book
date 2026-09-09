"""Unit tests for config schema validation in vbtspike."""

import unittest
from vbtspike.config.schema import BackupConfig, VbtSpikeConfig


class TestVbtSpikeConfig(unittest.TestCase):
    def test_backup_config_valid(self):
        """Valid BackupConfig parameters should pass."""
        bc = BackupConfig(dir="my_backups", keep_last=3)
        self.assertEqual(bc.dir, "my_backups")
        self.assertEqual(bc.keep_last, 3)

    def test_backup_config_invalid(self):
        """Invalid BackupConfig parameters should raise TypeError."""
        with self.assertRaises(TypeError):
            BackupConfig(dir="", keep_last=3)
        with self.assertRaises(TypeError):
            BackupConfig(dir="my_backups", keep_last=0)

    def test_vbtspike_config_valid(self):
        """Valid VbtSpikeConfig initialization."""
        cfg = VbtSpikeConfig(duckdb_path="data.duckdb", log_level="DEBUG")
        self.assertEqual(cfg.duckdb_path, "data.duckdb")
        self.assertEqual(cfg.log_level, "DEBUG")

    def test_vbtspike_config_invalid_log_level(self):
        """Invalid log level should raise ValueError."""
        with self.assertRaises(ValueError):
            VbtSpikeConfig(duckdb_path="data.duckdb", log_level="INVALID")


if __name__ == "__main__":
    unittest.main()
