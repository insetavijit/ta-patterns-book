# Problem Specification — PROB-03
## Multi-Strategy Backtest Persistence: Schema Fragmentation & View Isolation

**Document Type**: Problem Specification  
**Status**: Open — Awaiting Implementation Decision  
**Date**: 2026-09-06  
**Author**: Avijit  
**References**: [ADR-002](file:///home/avijit/workSpace/Code/ta-patterns-book/DOCs/Artifacts/ADRs/ADR-002-unified-strategy-schema-and-views.md)  
**Target Database**: `Shared/Data/ohlcv_eruusd.duckdb`

---

## 1. Executive Summary

The current backtest persistence layer — bootstrapped by [`Utils/1Mnbt.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Utils/1Mnbt.py) — uses three shared physical DuckDB tables (`batches`, `test_runs`, `trades`) to store the results of any executed backtest strategy. While this relational foundation is architecturally sound, it contains two critical unresolved gaps:

1. **No per-strategy view isolation**: After running multiple strategies, there is no ergonomic way to query trades belonging only to a specific strategy without writing a manual `JOIN` every time.
2. **No per-strategy physical table governance**: If this gap is naively fixed by creating a physical `{strategy}_trades` table per strategy, the database will suffer from unbounded table proliferation and schema fragmentation over time.

This document specifies the exact problem, the current database landscape, the failure scenarios, and the constraints that any proposed solution must satisfy.

---

## 2. Current Database Landscape (Observed 2026-09-06)

### 2.1 Database Location

```
Shared/Data/ohlcv_eruusd.duckdb
```

### 2.2 Physical Tables (Complete Inventory)

| Table | Type | Row Count | Description |
| :--- | :--- | ---: | :--- |
| `ohlcv` | table | 76,403 | 5-minute EUR/USD OHLCV candles, full year 2025 |
| `batches` | table | 1 | Batch run grouping metadata |
| `test_runs` | table | 1 | Backtest aggregate metrics per strategy run |
| `trades` | table | 95 | Individual trade-level records |

### 2.3 `test_runs` Schema (Current)

| Column | Data Type | Nullable | Notes |
| :--- | :--- | :--- | :--- |
| `fingerprint` | `VARCHAR` | NOT NULL | SHA-256 primary key — uniquely identifies a run |
| `status` | `VARCHAR` | NOT NULL | `complete` / `in_progress` / `skipped` |
| `strategy_name` | `VARCHAR` | NOT NULL | e.g. `sma_cross`, `classic_floor_mod_v2` |
| `symbol` | `VARCHAR` | NOT NULL | e.g. `EURUSD` |
| `timeframe` | `VARCHAR` | NOT NULL | e.g. `5m` |
| `start_date` | `TIMESTAMPTZ` | YES | Backtest window start |
| `end_date` | `TIMESTAMPTZ` | YES | Backtest window end |
| `total_return` | `DOUBLE` | YES | Cumulative return for the window |
| `benchmark_return` | `DOUBLE` | YES | Buy-and-hold return for the same window |
| `sharpe_ratio` | `DOUBLE` | YES | Annualised Sharpe |
| `max_drawdown` | `DOUBLE` | YES | Maximum peak-to-trough drawdown |
| `win_rate` | `DOUBLE` | YES | Fraction of winning trades |
| `profit_factor` | `DOUBLE` | YES | Gross profit / gross loss |
| `total_trades` | `BIGINT` | YES | Number of closed trades in the window |
| `batch_id` | `VARCHAR` | YES | FK → `batches.batch_id` |
| `created_at` | `TIMESTAMPTZ` | YES | Auto-populated at insert time |
| `params_json` | `JSON` | YES | Full serialised params snapshot |

### 2.4 `trades` Schema (Current)

| Column | Data Type | Nullable | Notes |
| :--- | :--- | :--- | :--- |
| `vbt_trade_id` | `BIGINT` | NOT NULL | Trade sequence number within a run |
| `fingerprint` | `VARCHAR` | NOT NULL | FK → `test_runs.fingerprint` |
| `direction` | `VARCHAR` | YES | `Long` / `Short` |
| `status` | `VARCHAR` | YES | `Closed` / `Open` |
| `entry_time` | `TIMESTAMPTZ` | YES | Entry timestamp |
| `exit_time` | `TIMESTAMPTZ` | YES | Exit timestamp |
| `entry_price` | `DOUBLE` | YES | Entry fill price |
| `exit_price` | `DOUBLE` | YES | Exit fill price |
| `size` | `DOUBLE` | YES | Position size in base units |
| `entry_fees` | `DOUBLE` | YES | Commission paid at entry |
| `exit_fees` | `DOUBLE` | YES | Commission paid at exit |
| `pnl` | `DOUBLE` | YES | Net P&L in USD |
| `return_pct` | `DOUBLE` | YES | Net return percentage |
| `holding_bars` | `BIGINT` | YES | Trade duration in candles |
| `holding_seconds` | `BIGINT` | YES | Trade duration in seconds |
| `is_win` | `BOOLEAN` | YES | `True` if `pnl > 0` |

### 2.5 `batches` Schema (Current)

| Column | Data Type | Nullable | Notes |
| :--- | :--- | :--- | :--- |
| `batch_id` | `VARCHAR` | NOT NULL | e.g. `batch_1788669344` |
| `created_at` | `TIMESTAMPTZ` | YES | Auto-populated |
| `note` | `VARCHAR` | YES | e.g. `1Mnbt monthly runner` |

### 2.6 Live Data Snapshot (2026-09-06)

**`test_runs` — 1 row (current)**

```
fingerprint        : 2e8fc636a80ed1667186f310599733971db7fb71d229ef28146d81bd7f451f46
status             : complete
strategy_name      : sma_cross
symbol             : EURUSD
timeframe          : 5m
start_date         : 2025-01-02 03:30:00+05:30
end_date           : 2025-02-01 05:29:59+05:30
total_return       : -0.1867  (-18.67%)
benchmark_return   : -0.0013  (-0.13%)
sharpe_ratio       : -39.10
max_drawdown       :  0.2063  (20.63%)
win_rate           :  0.0947  (9.47%)
profit_factor      :  0.0854
total_trades       : 95
batch_id           : batch_1788669344
```

**`trades` — 5 sample rows**

```
vbt_trade_id | direction | entry_time                | exit_time                 | entry_price | exit_price | pnl ($)   | is_win
1            | Long      | 2025-01-02 13:10:00+05:30 | 2025-01-02 13:45:00+05:30 | 1.03681     | 1.03533    | -34.27    | False
2            | Long      | 2025-01-03 02:10:00+05:30 | 2025-01-03 09:50:00+05:30 | 1.02619     | 1.02674    | -14.64    | False
3            | Long      | 2025-01-03 11:25:00+05:30 | 2025-01-03 16:20:00+05:30 | 1.02717     | 1.02819    | -10.07    | False
4            | Long      | 2025-01-03 16:45:00+05:30 | 2025-01-03 19:55:00+05:30 | 1.02918     | 1.02910    | -20.78    | False
5            | Long      | 2025-01-03 20:30:00+05:30 | 2025-01-03 20:40:00+05:30 | 1.02999     | 1.02890    | -30.58    | False
```

---

## 3. Problem Definition

### 3.1 Immediate Trigger

The backtest runner `1Mnbt.py` currently supports a `--strategy` flag accepting any strategy registered in [`Core/strategies/registry.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Core/strategies/registry.py). As new strategies are registered and tested (e.g. `classic_floor_mod_v2`), every test run writes into the same shared `trades` and `test_runs` tables with no automatic strategy-level query isolation provided.

### 3.2 Problem Statement (Precise)

> **As a researcher running multiple strategies against the same OHLCV database, I cannot query trades or monthly performance summaries for a specific strategy without writing a manual `JOIN` against `test_runs` every time. Additionally, without a governed schema design, a naive fix (creating per-strategy physical tables) would cause unbounded database table sprawl that degrades maintainability and prevents cross-strategy analysis.**

### 3.3 Failure Scenarios

#### Scenario A — Manual Query Burden (Today)

To see all `sma_cross` trades, a user must currently write:

```sql
SELECT t.* 
FROM trades t
JOIN test_runs r ON t.fingerprint = r.fingerprint
WHERE r.strategy_name = 'sma_cross';
```

There is no `sma_cross_trades` shortcut. Every analytical query — whether from `duckdb_explorer`, a Notebook, or a report script — requires reconstructing this join.

#### Scenario B — Naïve Fix: Per-Strategy Physical Tables

If a developer addresses this by creating physical tables `sma_cross_trades`, `classic_floor_v2_trades`, etc., the following problems arise immediately:

| Problem | Impact |
| :--- | :--- |
| Table count grows linearly per strategy | After 10 strategies × 12 months = 10+ physical tables |
| Data duplicated across physical tables and `trades` | Inconsistency risk if `trades` is updated |
| Cross-strategy analysis impossible without UNION ALL | e.g. "compare all strategies by Sharpe" requires manual union |
| `duckdb_explorer list-tables` output becomes noisy | Operational confusion |
| `trade-book-charts` SQL queries must be updated per strategy | Tight coupling between tools and strategy naming |

#### Scenario C — No Governance (Overwriting)

If two different strategies share the same `fingerprint` due to a hashing collision or a bug in `compute_hash`, one strategy's trades would silently overwrite the other's via `INSERT OR REPLACE`. Currently there is no assertion or guard against this.

### 3.4 Root Cause

The root cause is **the absence of a `create_strategy_views()` lifecycle hook** inside `persist_results()` in `1Mnbt.py`. The relational schema is correct and sufficient — strategy-level isolation is one `CREATE OR REPLACE VIEW` statement away, but it is never called.

---

## 4. Constraints & Requirements for Any Solution

Any solution must satisfy all of the following:

| # | Constraint | Rationale |
| :--- | :--- | :--- |
| C-1 | Physical table count must not increase per strategy | Prevent schema fragmentation |
| C-2 | Every trade must remain attributable to exactly one strategy via the FK chain `trades.fingerprint` → `test_runs.strategy_name` | Maintain data integrity |
| C-3 | Strategy-specific queries must not require manual JOINs in day-to-day use | Ergonomics for Notebooks and CLI tools |
| C-4 | Cross-strategy queries must be possible from a single SQL entry point | Comparative analysis requirement |
| C-5 | Solution must be forward-compatible with `duckdb_explorer`, `trade-book-charts`, and `loss-profile` | Tool ecosystem stability |
| C-6 | Views must be idempotent — recreating them must never lose data | Repeatability of backtest runs |
| C-7 | View creation must be automatic — no manual DDL after every strategy run | Developer ergonomics |

---

## 5. Out of Scope

The following are explicitly out of scope for this problem specification:

- Changing the `trades` or `test_runs` physical table schema (no new columns required).
- Migrating existing `sma_cross` trade data — the current 95 rows are already correctly stored.
- Changing the fingerprinting / deduplication logic in `compute_hash()`.
- Performance optimisation of the OHLCV ingestion layer.

---

## 6. Related Documents

| Document | Location |
| :--- | :--- |
| Architecture Decision Record | [`DOCs/Artifacts/ADRs/ADR-002-unified-strategy-schema-and-views.md`](file:///home/avijit/workSpace/Code/ta-patterns-book/DOCs/Artifacts/ADRs/ADR-002-unified-strategy-schema-and-views.md) |
| 1Mnbt Backtest Runner | [`Utils/1Mnbt.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Utils/1Mnbt.py) |
| Strategy Registry | [`Core/strategies/registry.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Core/strategies/registry.py) |
| Classic Floor Strategy | [`Shared/straragYs/classic_floor_mod_v2.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Shared/straragYs/classic_floor_mod_v2.py) |
| DB Explorer Tool | [`Utils/duckdb-explorar-tool/duckdb_explorer.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Utils/duckdb-explorar-tool/duckdb_explorer.py) |
| Target Database | `Shared/Data/ohlcv_eruusd.duckdb` |
