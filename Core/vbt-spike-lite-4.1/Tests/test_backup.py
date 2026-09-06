"""Tests for the backup module (DL-V6-01)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _make_cfg(db_path, backup_dir, keep_last=3):
    from Core.vbtspike.config.schema import BackupConfig, VbtSpikeConfig
    return VbtSpikeConfig(
        duckdb_path=str(db_path),
        max_cache_age_default="24h",
        log_level="INFO",
        backup=BackupConfig(dir=str(backup_dir), keep_last=keep_last),
    )


class TestRunBackup:
    def test_missing_db_raises_file_not_found(self, tmp_path):
        from Core.vbtspike.storage.backup import run_backup
        cfg = _make_cfg(tmp_path / "nonexistent.duckdb", tmp_path / "snaps")
        with pytest.raises(FileNotFoundError):
            run_backup(cfg)

    def test_creates_snapshot_file(self, cfg, db_path, tmp_path):
        from Core.vbtspike.storage.backup import run_backup
        dst = tmp_path / "test.duckdb"
        shutil.copy2(str(db_path), str(dst))
        backup_dir = tmp_path / "snaps"
        test_cfg = _make_cfg(dst, backup_dir, keep_last=3)

        snap = run_backup(test_cfg)

        assert snap.exists()
        assert snap.suffix == ".duckdb"
        assert "vbtspike-" in snap.name

    def test_snapshot_is_queryable(self, cfg, db_path, tmp_path):
        """Snapshot must be a valid DuckDB file with the original tables."""
        from Core.vbtspike.storage.backup import run_backup
        dst = tmp_path / "test.duckdb"
        shutil.copy2(str(db_path), str(dst))
        snap = run_backup(_make_cfg(dst, tmp_path / "snaps"))

        conn = duckdb.connect(str(snap), read_only=True)
        tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
        conn.close()
        assert "ohlcv_1m_2025" in tables

    def test_prunes_old_snapshots(self, cfg, db_path, tmp_path):
        """Old snapshots beyond keep_last must be deleted."""
        from Core.vbtspike.storage.backup import run_backup
        backup_dir = tmp_path / "snaps"
        keep = 2

        for i in range(keep + 2):  # create 4 snapshots, keep only 2
            # Each iteration needs a fresh source file (unique name) so the
            # snapshot target path (timestamped) doesn't collide with a prior run.
            import time
            time.sleep(1.1)  # ensure unique timestamp in snapshot filename
            dst = tmp_path / f"test_{i}.duckdb"
            shutil.copy2(str(db_path), str(dst))
            run_backup(_make_cfg(dst, backup_dir, keep_last=keep))

        remaining = list(backup_dir.glob("vbtspike-*.duckdb"))
        assert len(remaining) <= keep
