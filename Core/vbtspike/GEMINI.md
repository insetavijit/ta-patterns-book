# GEMINI AI Guide for vbtspike

## Overview
`vbtspike` is a specialized VectorBT backtest execution runner and DuckDB persistence engine designed for algorithmic trading strategy simulations, trade metrics extraction, and schema integrity validation.

---

## Directory Standards
- **`Core/`**: Package implementation source files (`Core/vbtspike/`).
  - `cli.py`: Click CLI entry point (`run`, `clean`, `backup`), parameter parsing, and console formatting.
  - `config/`: Configuration resolution, defaults, and schema loading (`loader.py`, `schema.py`).
  - `integrity/`: Pre-flight sanity checks and post-simulation data validation (`canonical.py`, `fingerprint.py`).
  - `simulation/`: VectorBT backtest execution, portfolio extraction, and telemetry generation (`runner.py`).
  - `storage/`: DuckDB writer, view synchronization, snapshot management, and migrations (`writer.py`, `backup.py`, `db.py`, `ingest.py`).
- **`DOCs/`**: Technical documentation.
  - `Architecture/`: Dataflow pipelines, telemetry design, and schema contracts.
  - `Artifacts/`: ADRs, data dictionary schemas, and baseline profiles.
  - `Decisions/`: Architecture Decision Records.
  - `Issues/`: Known simulation nuances, floating point tolerances, and bug tracking.
  - `Notes/`: Telemetry scratchpads and working notes.
  - `Plans/`: Version milestones and feature plans.
  - `Reports/`: Execution speed benchmarks and storage footprint logs.
  - `Research/`: VectorBT API investigations and vectorization patterns.
- **`Notebooks/`**:
  - `Active/`: Interactive strategy experimentation notebooks.
  - `Archives/`: Historical exploration notebooks.
  - `experiments/`: Execution benchmarks and vectorbt profiling.
  - `explore/`: Exploratory trade extraction notebooks.
- **`Shared/`**:
  - `cnf.yaml`: Default engine runtime configuration.
  - `Schemas/`: SQL view templates and JSON validation schemas.
  - `Data/`: Test fixtures and database seeds.
  - `Inputs/`: Sample price datasets.
  - `Outputs/`: Backtest snapshot outputs and diagnostic dumps.
- **`Tests/`**: Complete test suite for CLI, config, integrity, and simulation.
- **`Utils/`**: Diagnostic utilities and DuckDB maintenance scripts.

---

## Execution Rules
- Always execute commands using `uv`:
  - `uv run vbtspike --help`
  - `uv run python -m unittest discover -s Tests`
- Maintain zero corruption of raw market candle data (`ohlcv`).
- Terminal outputs must adhere to borderless formatting when Rich is used.
