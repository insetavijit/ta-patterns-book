"""Config loader — reads and validates config/cnf.yaml at startup.

Only the ``vbtspike:`` key is read and validated. All other top-level keys in
cnf.yaml are ignored, so other packages editing that file cannot break vbtspike
validation (spec §5, DL-V6-02).

Fails loudly (SystemExit 1) on any missing or malformed key.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import yaml

from .schema import BackupConfig, VbtSpikeConfig

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATHS = [Path("Shared/cnf.yaml"), Path("config/cnf.yaml")]


def load_config(path: Path | str | None = None) -> VbtSpikeConfig:
    """Load and validate the vbtspike section of Shared/cnf.yaml.

    Args:
        path: Path to the config file. Defaults to Shared/cnf.yaml (or config/cnf.yaml)
              relative to the current working directory.

    Returns:
        A validated, frozen VbtSpikeConfig instance.

    Raises:
        SystemExit(1): If the file is missing, unreadable, or has invalid keys.
    """
    if path is not None:
        config_path = Path(path)
    else:
        config_path = next((p for p in _DEFAULT_CONFIG_PATHS if p.exists()), _DEFAULT_CONFIG_PATHS[0])

    if not config_path.exists():
        _die(f"Config file not found: {config_path}")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        _die(f"Failed to parse {config_path}: {exc}")

    if not isinstance(raw, dict) or "vbtspike" not in raw:
        _die(
            f"{config_path} must contain a top-level 'vbtspike:' key. "
            "Check the config schema in Docs/vbSpike-v6-spec.md §5."
        )

    section: dict[str, Any] = raw["vbtspike"]

    # Validate required keys
    required = {"duckdb_path", "max_cache_age_default", "log_level", "backup"}
    missing = required - section.keys()
    if missing:
        _die(f"Missing required keys in vbtspike config: {sorted(missing)}")

    backup_raw = section.get("backup", {})
    backup_required = {"dir", "keep_last"}
    backup_missing = backup_required - backup_raw.keys()
    if backup_missing:
        _die(f"Missing required keys in vbtspike.backup: {sorted(backup_missing)}")

    try:
        backup = BackupConfig(
            dir=backup_raw["dir"],
            keep_last=backup_raw["keep_last"],
        )
        config = VbtSpikeConfig(
            duckdb_path=section["duckdb_path"],
            results_dir=section.get("results_dir", "Shared/OUTs"),
            max_cache_age_default=section["max_cache_age_default"],
            log_level=section["log_level"],
            backup=backup,
        )
    except (TypeError, ValueError) as exc:
        _die(f"Invalid config value: {exc}")

    # Apply log level from config
    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.debug("Config loaded from %s", config_path)
    return config


def _die(message: str) -> None:
    """Print an error and exit with code 1."""
    print(f"[vbtspike] CONFIG ERROR: {message}", file=sys.stderr)
    sys.exit(1)
