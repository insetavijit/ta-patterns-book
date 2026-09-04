"""Loss profiling package for trading strategies."""

from .cli import main
from .reporters import (
    generate_distribution_table,
    generate_duration_table,
    generate_loss_group_table,
    generate_loss_profile,
    generate_monthly_table,
    generate_weekly_table,
)

__all__ = [
    "main",
    "generate_loss_profile",
    "generate_monthly_table",
    "generate_weekly_table",
    "generate_duration_table",
    "generate_loss_group_table",
    "generate_distribution_table",
]
