# GEMINI.md - Project Guidelines & Context

## Package Manager & Tooling & Rules
- **Default Package Manager:** `uv` is used as the default package/environment manager for this project (`uv run`, `uv add`, `uv sync`, etc.).
- **External CLI Tools Reference:** Always read [`Utils/tools-info.md`](file:///home/avijit/workSpace/Code/ta-patterns-book/Utils/tools-info.md) to discover, inspect, and understand the list of available project CLI tools, their flag contracts, and operational guidelines.
- **Historical Corrections Log:** Always inspect [`Shared/corrections.md`](file:///home/avijit/workSpace/Code/ta-patterns-book/Shared/corrections.md) to review past user feedback and avoid repeating operational mistakes.
- **Suo-Moto Artifacts Policy:** Do NOT create any suo-moto artifacts or Markdown (`.md`) files unless explicitly requested by the user. Ask for permission first if you feel the need to create one.

---

## Registered Core Packages & Workspaces

1. **Loss Profiler CLI (`loss-profile`)**:
   - **Location**: [`Core/ta_patterns_book/loss_profile/`](file:///home/avijit/workSpace/Code/ta-patterns-book/Core/ta_patterns_book/loss_profile/)
   - **CLI Commands**:
     - `uv run loss-profile --dist entry_1`: 3-candle setup pattern win/loss performance distribution.
     - `uv run loss-profile --dist entry_2 --filter "entry_1 = DR-DR-DR"`: Nested pattern filter distribution.
     - `uv run loss-profile --dist duration --filter "entry_1 = DR-DR-DR"`: Candle duration breakdown for specific pattern filter.
     - `uv run loss-profile --dist prr --filter "entry_1 = DR-DR-DR"`: Projected R:R bracket breakdown.
     - `uv run loss-profile --dist loss`: Dollar loss amount severity breakdown.
     - `uv run loss-profile --output markdown`: Render markdown tables.
   - **Architecture**:
     - `sql.py`: Pure SQL query builders (`build_distribution_query`, `build_duration_query`, etc.).
     - `reporters.py`: Orchestration layer and rich borderless terminal formatting.
     - `cli.py`: Argument parsing.

2. **Tradebook & SmartGrid CLI (`trade-book-charts`)**:
   - **Location**: [`Core/trade_book_charts/`](file:///home/avijit/workSpace/Code/ta-patterns-book/Core/trade_book_charts/)
   - **CLI Commands**:
     - `uv run trade-book-charts tradebook`: Render SmartGrid trade playbook PNGs.
     - Supports `--limit` / `-l` flag to specify charts per page (auto-paginating to `p1.png`, `p2.png`, etc.).

3. **DuckDB Explorer CLI**:
   - **Location**: [`Utils/duckdb-explorar-tool/duckdb_explorer.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Utils/duckdb-explorar-tool/duckdb_explorer.py)
   - Read-only inspection, schema profiling, Pandas transformations, and SQL query runner.

---

## Database Schemas & Key Conventions

- **Primary Database**: `Shared/Data/eur_usd_trades_5m.duckdb`
- **Trades Primary Key**: Join on `trades.uid` = `"3candels_patterns".trade_number` (`BIGINT PRIMARY KEY`, integers `1..531`).
- **3-Candle Pattern Classifications** (`"3candels_patterns"` table & `"3candels_patterns_view"` view):
  - `entry_1`: 3 setup candles strictly before entry bar (`pos-3`, `pos-2`, `pos-1`).
  - `entry_2`: 2 setup candles before entry + entry bar (`pos-2`, `pos-1`, `pos`).
  - `entry_3`: 1 candle before entry + entry bar + 1 candle after entry (`pos-1`, `pos`, `pos+1`).
  - `entry_4`: Entry bar + 3 candles after entry (`pos`, `pos+1`, `pos+2`, `pos+3`).
- **Candle State Nomenclature**:
  - Direction: `U` (Close >= Prev Close) or `D` (Close < Prev Close)
  - Color: `G` (Close > Open) or `R` (Close <= Open)
- **Stdio Formatting Standard**:
  - All terminal table outputs must use `rich` with borderless formatting (`box: null` / `box=None`) as configured in [`Shared/cnf.yaml`](file:///home/avijit/workSpace/Code/ta-patterns-book/Shared/cnf.yaml).

---

## Directory Structure & File Placement
- Refer to [`DOCs/agents/dir-tree.md`](file:///home/avijit/workSpace/Code/ta-patterns-book/DOCs/agents/dir-tree.md) for the authoritative project directory tree, path descriptions, and file routing rules.
- Project path mappings and terminal formatting rules are configured in [`Shared/cnf.yaml`](file:///home/avijit/workSpace/Code/ta-patterns-book/Shared/cnf.yaml).
- Always place newly created files, datasets, notes, plans, or artifacts into their designated paths according to [`dir-tree.md`](file:///home/avijit/workSpace/Code/ta-patterns-book/DOCs/agents/dir-tree.md).
