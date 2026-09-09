---
name: loss-profile
description: >-
  Analyze trading strategy loss profiles, win/loss distributions, 3-candle patterns (entry_1 to entry_4),
  trade holding durations, projected R:R brackets, and monthly/weekly breakdowns using the loss-profile CLI.
  Use whenever analyzing trade performance, evaluating setup patterns, or diagnosing trading strategy losses.
---

# Loss Profiler CLI Skill (`loss-profile`)

The `loss-profile` CLI is a specialized performance and pattern analytics tool for backtested trading strategies stored in DuckDB databases. It evaluates win rates, loss severity, pattern distributions, candle holding durations, and multi-dimensional cross-axis comparisons.

---

## 1. Invocation Contract & Mandatory Requirements

Every `loss-profile` execution **requires** two explicit arguments:

1. **Database Flag (Choose Exactly One)**:
   - `--primary`: Active development database (`Shared/INPs/Ohlcv_2325Eurusd.duckdb`) configured in `Shared/cnf.yaml`.
   - `--secondary`: Baseline database (`Shared/Data/eur_usd_trades_5m.duckdb`) with 531 historical baseline trades.
   - `--db <path>`: Explicit custom path to a DuckDB database file.

2. **Source View/Table (`--view <name>`)**:
   - Must specify the exact view or table to query.
   - The CLI automatically checks and validates that the view exists in the chosen database before running queries.

```bash
uv run loss-profile --primary --view <view_name> [options]
uv run loss-profile --secondary --view <view_name> [options]
```

### Common Available Views
- **Primary Database (`--primary`)**:
  - `classic_floor_mod_v3a_trades`: 2025 EUR/USD trades with embedded 3-candle patterns (`entry_1`..`entry_4`).
  - `classic_floor_mod_v3_trades`: 2025 EUR/USD trades for v3.
  - `classic_floor_mod_v2_trades`: 2025 EUR/USD trades for v2.
  - `classic_floor_mod_v3a_monthly`, `classic_floor_mod_v3_monthly`: Monthly aggregation tables.
- **Secondary Database (`--secondary`)**:
  - `trades`: 531 baseline trades (joins with `3candels_patterns` and `projected_rr`).

---

## 2. Core Distribution Axes (`--dist <axis>`)

The `--dist` (or `--distribution`) flag partitions strategy performance across specific analytical dimensions:

| Axis | Description | Value Example / Granularity |
| :--- | :--- | :--- |
| `entry_1` | 3 setup candles strictly before entry bar (`pos-3`, `pos-2`, `pos-1`) | `DR-DR-DR`, `UG-UR-DG`, `DR-UG-DR` |
| `entry_2` | 2 setup candles before entry + entry bar (`pos-2`, `pos-1`, `pos`) | `DR-DR-UG`, `UG-UG-DR` |
| `entry_3` | 1 candle before + entry bar + 1 candle after (`pos-1`, `pos`, `pos+1`) | `DR-UG-UG` |
| `entry_4` | Entry bar + 3 candles after entry (`pos`, `pos+1`, `pos+2`, `pos+3`) | `UG-DR-UG-DR` |
| `1candle` (`cdl`, `candle_1`) | Single-candlestick pattern on the entry candle (`pandas_ta_classic` + price action) | `Bull_Marubozu`, `Bull_Belt_Hold`, `Bull_Hammer`, `Bear_Belt_Hold`, etc. |
| `duration` | Trade holding duration brackets | `1 candle (5m)`, `2 candles (10m)`, `6-10 candles (30-50m)`, `60+ candles` |
| `loss` | Dollar loss severity brackets | `01. Wins (PnL > $0)`, `02. Small Loss ($0-$50)`, `05. Severe Loss (> $200)` |
| `prr` | Projected Risk-to-Reward ratio brackets | `01. < 2.0 RR`, `02. 2.0 - 3.0 RR`, `05. >= 5.0 RR` |
| `monthly` | Calendar month breakdown | `2025-01`, `2025-02`, etc. |
| `weekly` | Calendar week breakdown | `W01`, `W02`, etc. |
| `all` (`*`) | Comprehensive suite of all available distributions (monthly, weekly, duration, prr, loss, entry_1..4, epcpatt_1..3, ecpatt_1..3) | All analytical tables |

### Candle Pattern Nomenclature
- **Direction**: `U` (Up: Close >= Prev Close) or `D` (Down: Close < Prev Close).
- **Color**: `G` (Green: Close > Open) or `R` (Red: Close <= Open).
- **Example**: `DR-DR-DR` = Three consecutive down-red candles.

---

## 3. Composable Modifiers & Filters

You can compose any distribution axis with filtering and sorting modifiers:

### Filtering
- `--filter "<expression>"`: SQL filter on trade or pattern columns.
  - Examples: `--filter "entry_1 = DR-DR-DR"`, `--filter "pnl > 50"`, `--filter "exit_reason = 'SL'"`
- `--losses-only`: Filter dataset strictly to losing trades (`pnl <= 0`).
- `--wins-only`: Filter dataset strictly to winning trades (`pnl > 0`).
- `--duration <N>`: Filter trades by exact candle holding duration (e.g. `--duration 1`).
- `--duration-till <N>`: Limit duration table output up to candle count $N$ (e.g. `--duration-till 5`).
- `--min-trades <N>`: Exclude sparse categories with fewer than $N$ trades.

### Sorting & Limiting
- `--sort {win%,trades,pnl}`: Sort distribution rows by win percentage, trade count, or net PnL.
- `--top <N>`: Keep top $N$ rows after sorting.
- `--bottom <N>`: Keep bottom $N$ rows after sorting.

### Cross-Axis Comparison (Pivot Table)
- `--compare <axis>`: Produces a 2D cross-axis pivot table comparing the primary `--dist` axis against `--compare`.
  - Example: `uv run loss-profile --primary --view classic_floor_mod_v3a_trades --dist prr --compare entry_1`

### Formatting & Output
- `--output {text,markdown}` (or `-o md`): Render tables in rich borderless terminal format (`text`, default) or pure GFM Markdown (`markdown`).
- `--dump [FILENAME]`: Cleanly dumps the stdio tables into a `.txt` file in `Shared/OUTs/` (e.g. `Shared/OUTs/loss_profile_<view>_<axis>.txt`).
- `--head [N]`: Print the first $N$ individual matching trade rows (default 10).
- `--loss [N]`: Print losing trades head and render SmartGrid Playbook canvas PNG to `Shared/OUTs/png/`.

---

## 4. Standard Command Recipes

### A. Setup Pattern Win/Loss Distributions
```bash
# Analyze entry_1 setup pattern performance on active v3a strategy
uv run loss-profile --primary --view classic_floor_mod_v3a_trades --dist entry_1

# Find top 10 most frequent entry_1 patterns with at least 10 trades
uv run loss-profile --primary --view classic_floor_mod_v3a_trades --dist entry_1 --sort trades --top 10 --min-trades 10

# Find worst performing entry_1 patterns by win rate
uv run loss-profile --primary --view classic_floor_mod_v3a_trades --dist entry_1 --sort win% --bottom 5 --min-trades 5
```

### B. Nested Pattern Breakdown
```bash
# Analyze entry_2 (post-entry) distribution specifically when setup was DR-DR-DR
uv run loss-profile --primary --view classic_floor_mod_v3a_trades --dist entry_2 --filter "entry_1 = DR-DR-DR"
```

### C. Duration & Loss Severity Analysis
```bash
# Candle duration performance breakdown
uv run loss-profile --primary --view classic_floor_mod_v3a_trades --dist duration

# Duration breakdown for specific pattern filter
uv run loss-profile --primary --view classic_floor_mod_v3a_trades --dist duration --filter "entry_1 = DR-DR-DR"

# Loss severity breakdown ($0-$50, $50-$100, etc.)
uv run loss-profile --primary --view classic_floor_mod_v3a_trades --dist loss
```

### D. Time Aggregations (Monthly & Weekly)
```bash
# Monthly performance breakdown
uv run loss-profile --primary --view classic_floor_mod_v3a_trades --dist monthly

# Weekly performance breakdown
uv run loss-profile --primary --view classic_floor_mod_v3a_trades --dist weekly
```

### E. Cross-Axis Matrix Comparison
```bash
# Compare Projected R:R distribution across entry_1 patterns
uv run loss-profile --primary --view classic_floor_mod_v3a_trades --dist prr --compare entry_1
```

### F. Inspecting Specific Trades
```bash
# Show head of 10 trades with entry_1 = DR-UG-DR
uv run loss-profile --primary --view classic_floor_mod_v3a_trades --head 10 --filter "entry_1 = DR-UG-DR"
```
