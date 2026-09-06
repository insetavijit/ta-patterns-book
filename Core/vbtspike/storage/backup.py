"""DuckDB backup routine — COPY FROM DATABASE snapshot (spec §6, DL-V6-01).

Produces a timestamped copy of the live DuckDB file. Prunes old snapshots
according to backup.keep_last from the config.

Recovery: stop vbtspike, replace live file with most recent snapshot, restart.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from ..config.schema import VbtSpikeConfig

logger = logging.getLogger(__name__)


def run_backup(cfg: VbtSpikeConfig) -> Path:
    """Create a timestamped DuckDB snapshot of the live database.

    Uses DuckDB's ``COPY FROM DATABASE ... TO ...`` command, which opens the
    live file read-only and writes a full copy to a new file. Safe to run
    while the database is not mid-write.

    Args:
        cfg: Validated vbtspike config (for duckdb_path and backup settings).

    Returns:
        Path to the newly created snapshot file.

    Raises:
        FileNotFoundError: If the live database file does not exist yet.
    """
    live_path = Path(cfg.duckdb_path)
    if not live_path.exists():
        raise FileNotFoundError(
            f"Cannot back up — live database not found: {live_path}"
        )

    backup_dir = Path(cfg.backup.dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    snap_path = backup_dir / f"vbtspike-{ts}.duckdb"

    logger.info("Starting backup snapshot -> %s", snap_path)

    import shutil
    shutil.copy2(str(live_path), str(snap_path))

    logger.info("Backup complete: %s", snap_path)

    _prune(backup_dir, cfg.backup.keep_last)
    return snap_path


def _prune(backup_dir: Path, keep_last: int) -> None:
    """Remove oldest snapshot files, keeping only the `keep_last` most recent.

    Args:
        backup_dir: Directory containing snapshot files.
        keep_last: Number of files to retain.
    """
    snapshots = sorted(
        backup_dir.glob("vbtspike-*.duckdb"),
        key=lambda p: p.stat().st_mtime,
    )
    to_delete = snapshots[: max(0, len(snapshots) - keep_last)]
    for old in to_delete:
        old.unlink()
        logger.info("Pruned old snapshot: %s", old.name)
