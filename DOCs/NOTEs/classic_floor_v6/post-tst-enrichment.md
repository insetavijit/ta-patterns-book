# Post-Test Database Enrichment Pipeline (`post-tst-enrichment.md`)

**Document Version:** 1.0.0  
**Date:** 2026-09-14  
**Script Location:** [`Shared/strategies/_helpers/post-test-enrichment.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Shared/strategies/_helpers/post-test-enrichment.py)  
**Status:** Defined & Ready (Execution Deferred)

---

## 1. Executive Summary & Purpose

The **Post-Test Database Enrichment Pipeline** is an automated post-processing engine designed to run immediately after a VectorBT or custom strategy backtest completes.

When a backtest simulation runs, it produces raw execution records and fills (`trades` or `classic_floor_mod_v6_1_trades`). To make the resulting DuckDB database 100% self-contained, auditable, and compatible with visual tools (e.g. `loss-profile`, `trade-book-charts`, and DuckDB Explorer), the enrichment pipeline injects:
1. **Full 62-Pattern Candlestick Classifications** computed from OHLCV candles (`candel_patters_{tf}` & view `candel_patters_tf`).
2. **User-Provided Metadata Workflow**: Strategy information and column data dictionaries can be supplied directly by the user, or automatically generated using the `--with-info` flag.
3. **Database Integrity Audit & Profiling Summary**.

---

## 2. Core Functional Components

### 2.1 `resolve_default_target_db(repo_root: Path) -> Path | None`
- **Function**: Automatically discovers the appropriate target DuckDB if `--target` is omitted on the CLI.
- **Resolution Order**:
  1. Searches [`Shared/OUTs/duckdb/`](file:///home/avijit/workSpace/Code/ta-patterns-book/Shared/OUTs/duckdb/) for the most recently generated `.duckdb` artifact.
  2. Reads [`Shared/cnf.yaml`](file:///home/avijit/workSpace/Code/ta-patterns-book/Shared/cnf.yaml) for `paths.shared.data.backtest_db` or `active_db_path`.
  3. Falls back to default reference database [`Shared/Data/Ohlcv_2325Eurusd.duckdb`](file:///home/avijit/workSpace/Code/ta-patterns-book/Shared/Data/Ohlcv_2325Eurusd.duckdb).

### 2.2 `detect_strategy_from_db(target_db: Path) -> str`
- **Function**: Introspects table names and column schemas inside the target DuckDB to identify the exact strategy generation.
- **Heuristics**:
  - If `sl_mode` or `primary_sl_hit_timestamp` exists in trade columns $\rightarrow$ identifies as `classic_floor_mod_v6_1`.
  - If `strategy_name` column exists $\rightarrow$ reads registered strategy string directly.
  - If `pfib15_bsl` or `safe_sl_hit` exists $\rightarrow$ identifies as `classic_floor_mod_v6`.
  - Fallback checks database filename patterns (`v6_1`, `v6`, `v5`).

### 2.3 `run_post_test_enrichment(...)`
The orchestrator executing the 3-stage enrichment workflow:

```
Target DuckDB Database
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│ Stage 1: Candlestick Pattern Engine (Utils.candel_patterns)  │
│  - Scans 'ohlcv' table                                       │
│  - Calculates 62 candlestick patterns via pandas-ta-classic  │
│  - Creates 'candel_patters_{tf}' table & view                │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Stage 2: Data Dictionary & Metadata (Utils.strategy_info)    │
│  - Matches strategy version (v6.1 = 76 columns, v6 = 69 cols)│
│  - Generates 'info' table with schema:                       │
│    (clmn_name, brif, calcuation, remars)                     │
│  - Documents SL breach timestamps and dynamic sl_mode        │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Stage 3: Schema Verification & Table Profiling               │
│  - Inspects all relations, views, row counts, and columns    │
│  - Renders borderless Rich summary table to stdout           │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Database Relations Created & Enriched

| Target Relation | Relation Type | Source Engine | Purpose & Content |
| :--- | :---: | :--- | :--- |
| **`candel_patters_{tf}`** | Table | `Utils.candel_patterns` | Persistent table containing all 62 TA candlestick patterns mapped by timestamp (`single_patt`, `dubble_patt`, `triple_patt`, `multi_patt`, `total_patterns`). |
| **`candel_patters_tf`** | View | `Utils.candel_patterns` | Canonical timeframe-agnostic view proxying `candel_patters_{tf}`. |
| **`info`** | Table | `Utils.strategy_info` | Data dictionary (`clmn_name PRIMARY KEY`, `brif`, `calcuation`, `remars`) documenting all 76 v6.1 columns. |

---

## 4. Configuration Contract (`Shared/cnf.yaml`)

The enrichment architecture separates the **orchestrator runner** from the individual **worker scripts**:

```yaml
# Post-Test Database Enrichment Pipeline Configuration
post_test_enrichment:
  status: "on"                 # "on" | "off" (master switch to auto-enrich after backtests)
  enabled: true
  runner: "Shared/strategies/_helpers/post-test-enrichment.py"
  scripts:
    - "Shared/strategies/_helpers/candel_patterns.py"
  with_info: false             # Set to true to automatically generate column metadata 'info' table
  force: false                 # Overwrite existing enrichment tables if present
```

### Roles & Responsibilities
- **`runner`**: The orchestrator (`post-test-enrichment.py`) called by `1Ybt-v2.py` upon backtest completion.
- **`scripts`**: A list of independent worker scripts (e.g. `candel_patterns.py`). The runner inspects this list and executes each worker script in sequence, passing `--target`, `--tf`, `--ohlcv-table`, and flags.
- **`status`**: Global default toggle (`"on"` or `"off"`).
- **`with_info`**: Flag indicating whether the 'info' data dictionary table should be auto-packed (default `false`).

---

## 5. Backtest Pipeline Integration (`Notebooks/1Ybt-v2.py`)

`Notebooks/1Ybt-v2.py` supports the CLI flag `--post-enrich {on,off}`:

```bash
# Run 1-year backtest with post-test enrichment enabled
uv run python Notebooks/1Ybt-v2.py --strategy classic_floor_mod_v6_1 --post-enrich on

# Explicitly bypass post-test enrichment
uv run python Notebooks/1Ybt-v2.py --strategy classic_floor_mod_v6_1 --post-enrich off
```

When enabled (or defaulting to `"on"` in `cnf.yaml`), Step 7 in `1Ybt-v2.py` triggers the configured `runner`, which then executes each script in `scripts: [...]` against the generated backtest database.

---

## 6. Command-Line Interface (CLI) Specification

```bash
# Enrich the most recent backtest output database in Shared/OUTs/duckdb/
uv run python Shared/strategies/_helpers/post-test-enrichment.py

# Enrich an explicit target DuckDB database
uv run python Shared/strategies/_helpers/post-test-enrichment.py --target Shared/OUTs/duckdb/classic_floor_mod_v6_1_trades.duckdb

# Dry-run simulation (inspects without committing changes to disk)
uv run python Shared/strategies/_helpers/post-test-enrichment.py --dry-run

# Explicit strategy override
uv run python Shared/strategies/_helpers/post-test-enrichment.py --target <db_path> --strategy classic_floor_mod_v6_1

# Force regeneration of existing pattern tables
uv run python Shared/strategies/_helpers/post-test-enrichment.py --target <db_path> --force

# Override worker scripts list from CLI
uv run python Shared/strategies/_helpers/post-test-enrichment.py --target <db_path> --scripts Shared/strategies/_helpers/candel_patterns.py
```

### CLI Flags Reference
- `--target` / `-t`: Path to target DuckDB database. Defaults to active backtest DB if omitted.
- `--strategy` / `-s`: Strategy identifier override (`classic_floor_mod_v6_1`, `classic_floor_mod_v6`, `classic_floor_mod_v5`).
- `--ohlcv-table`: Name of source OHLCV table (defaults to `'ohlcv'`).
- `--tf` / `--timeframe`: Timeframe string (e.g. `'5m'`, `'1m'`).
- `--scripts`: List of worker script paths to execute (overrides `cnf.yaml` `scripts` list).
- `--dry-run`: Preview changes without database mutation.
- `--force` / `-f`: Force re-calculation and overwrite of existing enrichment tables.
- `--with-info`: Include automatic generation of the 'info' data dictionary table (defaults to off; metadata is user-provided).
