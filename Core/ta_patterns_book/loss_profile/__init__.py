"""Loss profiling package for trading strategies."""

from .cli import main
from .distribution import generate_distribution_table, generate_loss_profile
from .duration import generate_duration_table
from .formatter import print_dataframe
from .loss_group import generate_loss_group_table
from .monthly import generate_monthly_table
from .weekly import generate_weekly_table

__all__ = [
    "main",
    "generate_loss_profile",
    "generate_monthly_table",
    "generate_weekly_table",
    "generate_duration_table",
    "generate_loss_group_table",
    "generate_distribution_table",
    "print_dataframe",
]
