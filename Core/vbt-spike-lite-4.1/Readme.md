# vbtSpike-4

A hardened vectorbt backtest runner and DuckDB persistence engine.

## Project Structure

```
vbtSpike-4/
├── __trash/                  # Deprecated / archived legacy files
├── .tmp/                     # Temporary runtime scratch & caches
├── Core/                     # Engine & Strategy Implementations
│   ├── vbtspike/             # Core runner, storage, config & integrity
│   │   ├── cli.py            # CLI entrypoint
│   │   ├── config/           # Schema validation & YAML config loader
│   │   ├── simulation/       # Vectorbt portfolio execution
│   │   ├── storage/          # DuckDB database manager & writer
│   │   └── integrity/        # SHA-256 fingerprinting & dedup
│   └── strategies/           # Protocol-based strategy implementations
│       ├── base.py           # StrategyProtocol contract
│       ├── registry.py       # Strategy registry & lookup
│       └── sma_cross.py      # SMA Crossover strategy
├── DOCs/                     # Specifications and architectural decisions
│   ├── Artifacts/            # Generated performance reports & plots
│   ├── vbSpike-v6-spec.md
│   └── vbSpike-v6-decisions.md
├── Notebooks/                # Analysis & research notebooks
├── Shared/                   # Shared configurations, data & outputs
│   ├── cnf.yaml              # Single unified project configuration
│   ├── Data/                 # Input databases (e.g. ohlcv_dump.duckdb)
│   ├── INPs/                 # Parameter configurations & inputs
│   └── OUTs/                 # Strategy output databases & reports
├── Tests/                    # Test suite
├── Utils/                    # Utility scripts & helpers
├── GEMINI.md                 # AI assistant instructions & architecture guide
└── Readme.md                 # Project README
```

## Quick Start

```bash
# Sync dependencies
uv sync

# Run backtest for February 2025
uv run vbtspike run --strategy sma_cross --symbol EURUSD --timeframe 1m --start 2025-02-01 --end 2025-02-28

# Force re-run (bypass dedup cache)
uv run vbtspike run --strategy sma_cross --symbol EURUSD --timeframe 1m --start 2025-02-01 --end 2025-02-28 --force

# Backup database snapshot
uv run vbtspike backup
```
