---
name: trade-book-charts
description: >-
  Generate multi-chart candlestick trade playbook PNGs, validate SQL trade queries,
  and compute SmartGrid dynamic layout packing using the trade-book-charts CLI.
  Use whenever generating visual trade playbook charts, plotting trade entry/exit/SL/TP candles,
  or testing SmartGrid grid layouts.
---

# TradeBook Charts & SmartGrid Skill (`trade-book-charts`)

The `trade-book-charts` CLI is a specialized candlestick chart packing and visual trade playbook generator. It extracts trade records from DuckDB, pulls corresponding OHLCV candle slices, executes the SmartGrid packing algorithm, and renders publication-ready multi-chart PNG canvases with entry, stop-loss (SL), take-profit (TP), and custom reference lines.

---

## 1. CLI Invocations & Commands

The tool is accessible via `uv run`:

```bash
uv run trade-book-charts [tradebook|smartgrid|describe] [options]
```

*(Registered aliases: `trade-view`, `tradebook-tool`)*

### Subcommand Overview
1. **`tradebook`**: Main rendering workflow — queries trades from DuckDB, loads OHLCV candles, and generates paginated playbook PNG canvases.
2. **`smartgrid`**: Standalone layout packing testbench — computes optimal chart placement across rows without database queries or image rendering.
3. **`describe`**: Self-introspecting contract inspector — outputs full JSON schema of flags, parameter constraints, required columns, and exit codes.

---

## 2. TradeBook Playbook Generation (`tradebook`)

### Execution Syntax
```bash
uv run trade-book-charts tradebook \
  --db <path/to/duckdb> \
  --sql "<SELECT query>" \
  --ohlcv-table <ohlcv_table_name> \
  [options]
```

### Trade Column Contract (`--sql`)
The `--sql` query must return specific column names (case-insensitive). Always alias columns to match this contract:

| Column | Type | Requirement | Purpose |
| :--- | :--- | :--- | :--- |
| `entry_time` | TIMESTAMP | **Required** | Candle timestamp where trade was entered |
| `entry_price` | FLOAT | **Required** | Execution price at entry |
| `trade_id` | TEXT / INT | Optional | Displayed in individual chart title (defaults to row index) |
| `sl_price` | FLOAT | Optional | Stop-loss price $\rightarrow$ rendered as red dashed horizontal line |
| `tp_price` | FLOAT | Optional | Take-profit price $\rightarrow$ rendered as green dashed horizontal line |
| `exit_time` | TIMESTAMP | Optional | Explicit trade exit time (skips forward SL/TP candle scanning) |
| `exit_price` | FLOAT | Optional | Explicit exit execution price |
| `exit_reason` | TEXT | Optional | Exit label in chart header (e.g. `SL`, `TP`, `TIME`) |
| `pnl` | FLOAT | Optional | Trade PnL; sets title color to green (win) or red (loss) |

### Custom Reference Lines (`--hline-cols`)
Any additional numeric columns returned by `--sql` can be plotted as horizontal reference levels by passing comma-separated column names:
```bash
--hline-cols pivot,s1,r1
```
The renderer cycles through distinct colors (`darkorange`, `purple`, `teal`, `brown`, `magenta`, `slategray`) for each extra reference line.

---

## 3. Key Flags and Options Reference

### Data & Source Options
- `--db <path>`: Path to DuckDB database file (or set `TRADEBOOK_DB` environment variable).
- `--sql "<query>"`: Trade selection SQL string. Must be a read-only `SELECT` (or `WITH ... SELECT`).
- `--sql-file <path>`: Alternative path to a `.sql` query file instead of `--sql`.
- `--sql-params '<json_array>'`: JSON array of parameter values bound to `?` placeholders (e.g. `'["2025-01-01"]'`).
- `--ohlcv-table <name>`: Table or view containing OHLCV historical candles.
- `--ohlcv-time-col <col>`: Timestamp column name (default: `timestamp`).
- `--ohlcv-open-col <col>`: Open price column name (default: `open`).
- `--ohlcv-high-col <col>`: High price column name (default: `high`).
- `--ohlcv-low-col <col>`: Low price column name (default: `low`).
- `--ohlcv-close-col <col>`: Close price column name (default: `close`).
- `--ohlcv-volume-col <col>`: Volume column name (default: `volume`). Set to `""` if no volume exists.

### Window & Lookahead Tuning
- `--pad`, `-p <N>`: Context candle count before trade entry and after trade exit (default: `15`, must be $\ge 0$).
- `--exit-lookahead <N>`: Maximum candles scanned forward from entry to find SL or TP hit when `exit_time` is omitted (default: `288`, must be $\ge 1$).

### Grid Layout & Pagination
- `--row-capacity`, `-r <N>`: Target candle capacity per grid row (default: `350`, must be $> 0$).
- `--max-charts`, `--limit`, `-l <N>`: Maximum charts per page / canvas (default: `18`, must be $\ge 1$). If the query yields more trades than this limit, the CLI automatically paginates into numbered files (`_p1.png`, `_p2.png`, etc.).
- `--strategy`: SmartGrid packing algorithm:
  - `optimal` (default): Dynamic programming $O(N^2)$ optimal partition minimizing row slack.
  - `wordwrap`: Greedy $O(N)$ row packing.
  - `bestfit`: Bin-packing algorithm.

### Output & Automation
- `--output <path>`: Destination path for output PNG (default: `./outs/<run-name>.png`).
- `--output-dir <dir>`: Directory for default output when `--output` is omitted (default: `./outs`).
- `--run-name <name>`: Prefix used in chart canvas titles and auto-generated filenames (default: `tradebook`).
- `--dry-run`: Validates SQL, checks schemas, resolves trade windows, and calculates layout without rendering PNGs.
- `--json`: Emits compact, machine-readable JSON result envelope to `stdout`.
- `--quiet`: Suppresses informational progress logs on `stderr`.

---

## 4. Standard Command Recipes

### A. Secondary Database: Historical Baseline Trades
Secondary DB: `Shared/Data/eur_usd_trades_5m.duckdb` (tables: `trades`, `ohlcv`).
```bash
# Render first 6 losing trades to PNG playbook
uv run trade-book-charts tradebook \
  --db Shared/Data/eur_usd_trades_5m.duckdb \
  --sql "SELECT trade_id, entry_time, entry_price, sl_price, tp_price, exit_price, exit_reason, pnl FROM trades WHERE pnl < 0 LIMIT 6" \
  --ohlcv-table ohlcv \
  --output Shared/OUTs/png/playbook_losers.png

# Include Pivot, S1, and R1 horizontal reference lines
uv run trade-book-charts tradebook \
  --db Shared/Data/eur_usd_trades_5m.duckdb \
  --sql "SELECT trade_id, entry_time, entry_price, sl_price, tp_price, exit_price, exit_reason, pnl, pivot, s1, r1 FROM trades WHERE pnl < 0 LIMIT 6" \
  --ohlcv-table ohlcv \
  --hline-cols pivot,s1,r1 \
  --output Shared/OUTs/png/playbook_pivots.png
```

### B. Primary Database: Active Strategy Backtest Trades
Primary DB: `Shared/INPs/Ohlcv_2325Eurusd.duckdb` (view: `classic_floor_mod_v3a_trades`, OHLCV: `ohlcv_eurusd_1m_2025`).
```bash
# Render 8 trades with specific setup pattern DR-DR-DR
uv run trade-book-charts tradebook \
  --db Shared/INPs/Ohlcv_2325Eurusd.duckdb \
  --sql "SELECT vbt_trade_id AS trade_id, entry_time, exit_time, entry_price, exit_price, pnl FROM classic_floor_mod_v3a_trades WHERE entry_1 = 'DR-DR-DR' LIMIT 8" \
  --ohlcv-table ohlcv_eurusd_1m_2025 \
  --output Shared/OUTs/png/playbook_v3a_dr3.png
```

### C. Fast Dry-Run Validation (Zero Image Rendering Cost)
Before rendering large playbooks, verify SQL syntax, candle window slicing, and trade counts:
```bash
uv run trade-book-charts tradebook \
  --db Shared/Data/eur_usd_trades_5m.duckdb \
  --sql "SELECT trade_id, entry_time, entry_price, sl_price, tp_price, pnl FROM trades WHERE pnl < 0 LIMIT 12" \
  --ohlcv-table ohlcv \
  --dry-run \
  --json
```

### D. Standalone SmartGrid Layout Benchmarking
Test the grid packing engine with synthetic candle counts:
```bash
uv run trade-book-charts smartgrid \
  --candles 200 150 350 25 180 90 \
  --row-capacity 400 \
  --strategy optimal \
  --dry-run \
  --json
```

### E. Introspect Contract Schema
```bash
uv run trade-book-charts describe --pretty
```
