"""Tests for the config loader and schema validation (DL-V6-02)."""

from __future__ import annotations

import textwrap

import pytest


class TestConfigSchema:
    """Unit tests for VbtSpikeConfig and BackupConfig dataclasses."""

    def test_valid_config_loads(self, cfg):
        from Core.vbtspike.config.schema import VbtSpikeConfig
        assert isinstance(cfg, VbtSpikeConfig)

    def test_duckdb_path_is_string(self, cfg):
        assert isinstance(cfg.duckdb_path, str) and cfg.duckdb_path

    def test_log_level_is_valid(self, cfg):
        assert cfg.log_level in {"DEBUG", "INFO", "WARNING", "ERROR"}

    def test_max_cache_age_is_string(self, cfg):
        assert isinstance(cfg.max_cache_age_default, str) and cfg.max_cache_age_default

    def test_backup_config_shape(self, cfg):
        from Core.vbtspike.config.schema import BackupConfig
        assert isinstance(cfg.backup, BackupConfig)
        assert isinstance(cfg.backup.dir, str)
        assert isinstance(cfg.backup.keep_last, int)
        assert cfg.backup.keep_last >= 1

    def test_config_is_frozen(self, cfg):
        with pytest.raises((AttributeError, TypeError)):
            cfg.log_level = "DEBUG"  # type: ignore


class TestConfigLoader:
    """Integration tests for load_config()."""

    def test_missing_file_exits_1(self, tmp_path):
        from Core.vbtspike.config.loader import load_config
        with pytest.raises(SystemExit) as exc_info:
            load_config(tmp_path / "nonexistent.yaml")
        assert exc_info.value.code == 1

    def test_missing_vbtspike_key_exits_1(self, tmp_path):
        bad = tmp_path / "cnf.yaml"
        bad.write_text("other_package:\n  key: val\n")
        from Core.vbtspike.config.loader import load_config
        with pytest.raises(SystemExit) as exc_info:
            load_config(bad)
        assert exc_info.value.code == 1

    def test_missing_required_key_exits_1(self, tmp_path):
        bad = tmp_path / "cnf.yaml"
        bad.write_text(textwrap.dedent("""\
            vbtspike:
              max_cache_age_default: "24h"
              log_level: "INFO"
              backup:
                dir: "backups"
                keep_last: 5
        """))
        from Core.vbtspike.config.loader import load_config
        with pytest.raises(SystemExit) as exc_info:
            load_config(bad)
        assert exc_info.value.code == 1

    def test_invalid_log_level_exits_1(self, tmp_path):
        bad = tmp_path / "cnf.yaml"
        bad.write_text(textwrap.dedent("""\
            vbtspike:
              duckdb_path: "x.duckdb"
              max_cache_age_default: "24h"
              log_level: "VERBOSE"
              backup:
                dir: "backups"
                keep_last: 5
        """))
        from Core.vbtspike.config.loader import load_config
        with pytest.raises(SystemExit) as exc_info:
            load_config(bad)
        assert exc_info.value.code == 1

    def test_minimal_valid_config_loads(self, tmp_path):
        good = tmp_path / "cnf.yaml"
        good.write_text(textwrap.dedent("""\
            vbtspike:
              duckdb_path: "ohlcv_dump.duckdb"
              max_cache_age_default: "24h"
              log_level: "INFO"
              backup:
                dir: "backups"
                keep_last: 3
        """))
        from Core.vbtspike.config.loader import load_config
        result = load_config(good)
        assert result.duckdb_path == "ohlcv_dump.duckdb"
        assert result.backup.keep_last == 3
