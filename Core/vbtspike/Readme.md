# vbtspike — VectorBT Backtest & DuckDB Persistence Engine

`vbtspike` is a streamlined VectorBT backtest execution runner and analytical persistence layer. It executes strategy simulations, extracts detailed trade telemetry, validates schema and financial integrity, and saves results into DuckDB tables and views.

---

## Features
- **Deterministic Backtesting**: Window enforcement, 1-month window validation, parameter logging.
- **DuckDB Persistence**: Automated transaction-safe storage for `test_runs`, `trades`, and `batches`.
- **Pre-flight & Post-flight Integrity**: Validates data completeness, price consistency, and trade record constraints.
- **Analytical Views**: Generates standardized analytical views (`all_trades`, `strategy_performance`, `trade_book`, etc.).
- **Maintenance Tools**: Built-in snapshot backup (`vbtspike backup`) and verification clean-up (`vbtspike clean`).

---

## CLI Usage

```bash
# Run a backtest
uv run vbtspike run --strategy classic_floor_mod_v2 --start 2025-01-01 --end 2025-01-31

# Verify and remove backtest runs and analytical views
uv run vbtspike clean --dry-run
uv run vbtspike clean -y

# On-demand DuckDB database snapshot
uv run vbtspike backup
```

---

## Testing

```bash
uv run python -m unittest discover -s Tests
```
