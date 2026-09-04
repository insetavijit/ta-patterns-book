"""Rich & Markdown table formatting utilities."""

import pandas as pd
from rich.console import Console
from rich.table import Table

from .db import load_config


def print_dataframe(df: pd.DataFrame, title_text: str = None, totals_str: str = None, output_fmt: str = "text"):
    """Prints DataFrame using rich borderless tables (based on cnf.yaml display config) or markdown."""
    config = load_config()
    display_cfg = config.get("display", {})
    table_cfg = display_cfg.get("table", {})
    
    if output_fmt == "markdown":
        if title_text:
            print(f"### {title_text}\n")
        print(df.to_markdown(index=False))
        if totals_str:
            print(f"\n{totals_str}\n")
    else:
        console = Console()
        rich_table = Table(
            box=None,
            show_header=table_cfg.get("show_header", True),
            header_style=table_cfg.get("header_style", "bold cyan"),
            show_edge=table_cfg.get("show_edge", False),
            pad_edge=table_cfg.get("pad_edge", False),
        )

        for col in df.columns:
            justify = "right" if pd.api.types.is_numeric_dtype(df[col]) or col in ["win%", "number of trades", "win", "loss"] else "left"
            rich_table.add_column(str(col), justify=justify)

        for _, row in df.iterrows():
            rich_table.add_row(*[str(val) for val in row.values])

        if title_text:
            console.print(f"\n[bold yellow]{title_text}[/bold yellow]")
        console.print(rich_table)
        if totals_str:
            console.print(f"[bold green]{totals_str}[/bold green]\n")
