"""Explicit schema for the vbtspike section of config/cnf.yaml.

This is the contract for what config/cnf.yaml must contain (spec §5, DL-V6-02).
Any missing or wrong-typed field causes a loud failure at startup — never a
silent default.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BackupConfig:
    """Backup sub-section of the vbtspike config."""

    dir: str
    """Directory for local DuckDB snapshot files."""

    keep_last: int
    """Number of snapshots to retain before pruning oldest."""

    def __post_init__(self) -> None:
        if not isinstance(self.dir, str) or not self.dir:
            raise TypeError("backup.dir must be a non-empty string")
        if not isinstance(self.keep_last, int) or self.keep_last < 1:
            raise TypeError("backup.keep_last must be a positive integer")


@dataclass(frozen=True)
class VbtSpikeConfig:
    """Top-level validated configuration for vbtspike.

    Loaded from the ``vbtspike:`` key in config/cnf.yaml.
    All fields are required — no silent defaults.
    """

    VALID_LOG_LEVELS: frozenset[str] = field(
        default=frozenset({"DEBUG", "INFO", "WARNING", "ERROR"}),
        init=False,
        repr=False,
        compare=False,
    )

    duckdb_path: str
    """Path (absolute or relative) to the single DuckDB file."""

    results_dir: str = "Shared/OUTs"
    """Directory where strategy result DuckDB files are saved."""

    max_cache_age_default: str = "24h"
    """Default max cache age, e.g. '24h'. Overridable via --max-cache-age."""

    log_level: str = "INFO"
    """Logging verbosity. One of: DEBUG, INFO, WARNING, ERROR."""

    backup: BackupConfig = field(default_factory=lambda: BackupConfig(dir="backups", keep_last=5))
    """Backup configuration sub-section."""

    def __post_init__(self) -> None:
        if not isinstance(self.duckdb_path, str) or not self.duckdb_path:
            raise TypeError("duckdb_path must be a non-empty string")
        if not isinstance(self.results_dir, str) or not self.results_dir:
            raise TypeError("results_dir must be a non-empty string")
        if not isinstance(self.max_cache_age_default, str) or not self.max_cache_age_default:
            raise TypeError("max_cache_age_default must be a non-empty string")
        if self.log_level not in self.VALID_LOG_LEVELS:
            raise ValueError(
                f"log_level must be one of {sorted(self.VALID_LOG_LEVELS)}, "
                f"got: '{self.log_level}'"
            )
        if not isinstance(self.backup, BackupConfig):
            raise TypeError("backup must be a BackupConfig")
