# GEMINI AI Guide for vbtSpike-4

## Overview
`vbtSpike-4` is a quantitative backtesting engine pairing `vectorbt` with DuckDB for durable persistence and research integrity.

## Directory Standards
- `Core/vbtspike`: Core engine modules (`cli.py`, `config/`, `integrity/`, `simulation/`, `storage/`).
- `Core/strategies`: Protocol-based strategies implementing `StrategyProtocol`.
- `Shared/cnf.yaml`: The single runtime configuration file.
- `Shared/Data`: OHLCV datasets and DuckDB storage files.
- `Shared/OUTs`: Destination for strategy result DuckDB databases (e.g. `sma_cross.duckdb`).
- `Shared/INPs`: Input parameter files.
- `DOCs`: Architectural specs and decision records.
- `DOCs/Artifacts`: Output artifacts, charts, tables, diagrams.
- `Tests`: Test suite covering storage, simulation, integrity, configuration, and CLI.
- `Utils`: Utility scripts and tooling.
- `Notebooks`: Jupyter exploratory notebooks.
- `__trash`: Archived deprecated files.
- `.tmp`: Scratch files and intermediate caches.

## Execution Rules
- Always use `uv` for package management and script execution (`uv run vbtspike ...`).
- Only `Core.vbtspike.simulation` may import `vectorbt`.
- Results must be isolated in `Shared/OUTs/<strategy_name>.duckdb`.
- Maximum backtest duration per run is strictly 1 month (<= 31 days).
