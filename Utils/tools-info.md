# Utils Directory Tooling & Executable Specifications

This document serves as the authoritative guide for AI coding agents (Gemini, Antigravity) and human developers to discover, understand, and execute CLI utilities located in the `Utils/` directory.

---

## 🛠️ Registered Utility Tools

The `Utils/` directory contains modular tool packages organized into dedicated subdirectories:

| Tool Name | Executable Path | Spec / Manual | Primary Purpose | Default Execution |
| :--- | :--- | :--- | :--- | :--- |
| **DuckDB Explorer CLI** | [`Utils/duckdb-explorar-tool/duckdb_explorer.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Utils/duckdb-explorar-tool/duckdb_explorer.py) | [`utils.yaml`](file:///home/avijit/workSpace/Code/ta-patterns-book/Utils/duckdb-explorar-tool/utils.yaml) | Read-only inspection, SQL querying, column profiling, Pandas transformations, & exporting. | `uv run python Utils/duckdb-explorar-tool/duckdb_explorer.py` |
| **Tradebook & SmartGrid CLI** | [`Utils/trade-view-tool/tradebook_tool_v4.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Utils/trade-view-tool/tradebook_tool_v4.py) | [`tradebook_tool-manual-v2.yaml`](file:///home/avijit/workSpace/Code/ta-patterns-book/Utils/trade-view-tool/tradebook_tool-manual-v2.yaml) | SmartGrid chart packing, trade playbook PNG generation, & standalone layout engine. | `uv run python Utils/trade-view-tool/tradebook_tool_v4.py` |

---

## 1. DuckDB Explorer CLI (`duckdb_explorer.py`)

* **Location**: [`Utils/duckdb-explorar-tool/duckdb_explorer.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Utils/duckdb-explorar-tool/duckdb_explorer.py)
* **Specification File**: [`Utils/duckdb-explorar-tool/utils.yaml`](file:///home/avijit/workSpace/Code/ta-patterns-book/Utils/duckdb-explorar-tool/utils.yaml)
* **Agent Output**: Machine-readable JSON by default (`--output json`) or formatted markdown/tables (`--output table`).

### Key Capabilities
* **`list-tables`**: Inspect all tables, views, and row counts in a DuckDB file.
* **`schema` / `schema-all`**: Display data types, nullabilities, and column specifications.
* **`pandas`**: Execute direct Pandas expressions (`"df.groupby(...)"`, `"df.describe()"`, `"df.head()"`) on any table or SQL query result.
* **`profile`**: Compute native column statistics (`SUMMARIZE`) and sample data in a single call.
* **`query`**: Execute arbitrary read-only SQL queries (requires `--write` for mutations).
* **`search-columns`**: Locate tables and column names matching a keyword.
* **`export`**: Export query results to CSV, JSON, NDJSON, or Parquet.

### Agent Quickstart Commands

```bash
# 1. List all tables in a DuckDB database
uv run python Utils/duckdb_explorar-tool/duckdb_explorer.py Shared/Data/eur_usd_trades_5m.duckdb list-tables

# 2. Inspect table column schema
uv run python Utils/duckdb_explorar-tool/duckdb_explorer.py Shared/Data/eur_usd_trades_5m.duckdb schema trades

# 3. Direct Pandas aggregation via CLI
uv run python Utils/duckdb_explorar-tool/duckdb_explorer.py Shared/Data/eur_usd_trades_5m.duckdb \
  pandas trades "df.groupby('status')['pnl'].sum()"

# 4. Preview table sample rows
uv run python Utils/duckdb_explorar-tool/duckdb_explorer.py Shared/Data/eur_usd_trades_5m.duckdb sample trades --limit 5

# 5. Execute custom SQL query
uv run python Utils/duckdb_explorar-tool/duckdb_explorer.py Shared/Data/eur_usd_trades_5m.duckdb \
  query "SELECT trade_id, entry_time, entry_price, pnl FROM trades WHERE pnl > 100 LIMIT 10"
```

---

## 2. Tradebook & SmartGrid CLI (`tradebook_tool_v4.py`)

* **Location**: [`Utils/trade-view-tool/tradebook_tool_v4.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Utils/trade-view-tool/tradebook_tool_v4.py)
* **Specification File**: [`Utils/trade-view-tool/tradebook_tool-manual-v2.yaml`](file:///home/avijit/workSpace/Code/ta-patterns-book/Utils/trade-view-tool/tradebook_tool-manual-v2.yaml)
* **Agent Output**: Structured JSON envelope on stdout when `--json` is passed. Exit codes are semantic (`0`: OK, `2`: Bad Input, `3`: DB Not Found).

### Subcommand Overview

1. **`tradebook`**:
   * Runs an `--sql` query against a DuckDB database to select trades.
   * Fetches corresponding OHLCV candle windows from an `--ohlcv-table`.
   * Packs charts using the SmartGrid packing engine.
   * Renders paginated PNG playbook canvases showing entry, stop-loss (SL), take-profit (TP), and custom reference lines.
2. **`smartgrid`**:
   * Standalone layout packing engine test bench (no database, no image rendering).
   * Packs arbitrary chart candle counts using `optimal` (O(n²) DP), `wordwrap` (O(n) greedy), or `bestfit` (bin packing) strategies.
3. **`describe`**:
   * Self-introspecting contract generator (`describe --pretty`). Emits full machine-readable JSON schema of flags, choices, defaults, and trade column contracts.

### Agent Quickstart Commands

```bash
# 1. Introspect tool contract and flags schema
uv run python Utils/trade-view-tool/tradebook_tool_v4.py describe --pretty

# 2. Dry-run validation of a tradebook query (zero rendering cost)
uv run python Utils/trade-view-tool/tradebook_tool_v4.py tradebook \
  --db Shared/Data/eur_usd_trades_5m.duckdb \
  --sql "SELECT trade_id, entry_time, entry_price, sl_price, tp_price, pnl FROM trades WHERE pnl < 0 LIMIT 6" \
  --ohlcv-table ohlcv --dry-run --json

# 3. Render trade playbook PNG canvas
uv run python Utils/trade-view-tool/tradebook_tool_v4.py tradebook \
  --db Shared/Data/eur_usd_trades_5m.duckdb \
  --sql "SELECT trade_id, entry_time, entry_price, sl_price, tp_price, pnl FROM trades WHERE pnl < 0 LIMIT 6" \
  --ohlcv-table ohlcv --output Shared/OUTs/png/playbook_losers.png --json

# 4. Test SmartGrid layout algorithm standalone
uv run python Utils/trade-view-tool/tradebook_tool_v4.py smartgrid \
  --candles 200 150 350 25 180 --row-capacity 400 --dry-run --json
```

---

## 💡 Operational Rules for Agents (Gemini / Antigravity)

1. **Environment Manager**: Always execute tools using `uv run python <script_path>` to ensure the workspace environment and dependencies (`duckdb`, `pandas`, `mplfinance`, `matplotlib`) are loaded.
2. **JSON-First Output**:
   * For `duckdb_explorer.py`: Use default `--output json` or `--output table` when rendering Markdown tables for human review.
   * For `tradebook_tool_v4.py`: Always pass `--json` to receive structured machine-readable JSON on `stdout`.
3. **Dry-Run Validation**: Always test queries with `--dry-run` first to validate SQL syntax and column mappings before launching heavy rendering tasks.
4. **Read-Only Safety**: `duckdb_explorer.py` operates in read-only mode by default. Never pass `--write` unless explicitly creating or modifying database structures.
