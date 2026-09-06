"""Config package — schema validation and YAML loading for config/cnf.yaml."""

from .loader import load_config
from .schema import VbtSpikeConfig

__all__ = ["load_config", "VbtSpikeConfig"]
