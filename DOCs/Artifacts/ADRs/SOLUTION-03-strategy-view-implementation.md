# Solution — PROB-03
## Multi-Strategy Backtest Persistence: Unified Schema + Auto-Generated Strategy Views

**Document Type**: Solution Specification  
**Status**: Ready for Implementation  
**Date**: 2026-09-06  
**Author**: Avijit  
**Solves**: [`PROB-03-multi-strategy-schema-fragmentation.md`](file:///home/avijit/workSpace/Code/ta-patterns-book/DOCs/Artifacts/ADRs/PROB-03-multi-strategy-schema-fragmentation.md)  
**Decision Record**: [`ADR-002-unified-strategy-schema-and-views.md`](file:///home/avijit/workSpace/Code/ta-patterns-book/DOCs/Artifacts/ADRs/ADR-002-unified-strategy-schema-and-views.md)

---

## 1. Solution Summary

The problem described in PROB-03 has a precise, minimal fix. The relational foundation — three unified physical tables (`batches`, `test_runs`, `trades`) — is already architecturally correct. No schema migration, no new columns, and no new physical tables are required.

The entire solution is:

> **Add a single function `create_strategy_views(con, strategy_name)` to [`Utils/1Mnbt.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Utils/1Mnbt.py), called at the end of `persist_results()`, that issues `CREATE OR REPLACE VIEW` statements for every strategy written.**

This takes the existing FK relationship `trades.fingerprint → test_runs.fingerprint → test_runs.strategy_name` and makes it ergonomic by materialising it as named, reusable DuckDB views — automatically, after every run.

---

## 2. Reasoning Behind the Solution

### 2.1 Why Not Per-Strategy Physical Tables?

A physical table (`sma_cross_trades`, `classic_floor_v2_trades`) would solve the ergonomics problem but creates three worse problems:

| Issue | Consequence |
| :--- | :--- |
| **Data duplication** | Every trade exists twice — in the shared `trades` table and in the strategy-specific table. When `trades` is updated (e.g. a re-run with `INSERT OR REPLACE`), the strategy table goes stale unless synchronised manually. |
| **Schema drift** | If the `trades` schema gains a column in the future, every per-strategy physical table must be `ALTER TABLE`'d individually. Views derived from `trades` inherit the change automatically. |
| **No cross-strategy query path** | To compare two strategies' Sharpe ratios by month, a user must write `UNION ALL sma_cross_trades UNION ALL classic_floor_v2_trades` — which breaks every time a new strategy is added. |

### 2.2 Why Not Just Leave It as Raw Tables Only?

The shared tables already work correctly for storage. The problem is ergonomics: every query against a single strategy requires a manual `JOIN` on `fingerprint`. This friction is unacceptable for:

- Notebook analysis (forces boilerplate every cell)
- `trade-book-charts --sql "SELECT * FROM ..."` (forces embedded JOIN in CLI args)
- `duckdb_explorer query "..."` (forces multi-table SQL for every inspection)

The pattern of naming views after the entity they serve is already established in this project. In `eur_usd_trades_5m.duckdb`, the pattern `3candels_patterns` → `3candels_patterns_view`, `trades` → `trades_view` is already in use. This solution extends that same convention to the backtest layer.

### 2.3 Why `CREATE OR REPLACE VIEW` and Not `CREATE VIEW IF NOT EXISTS`?

`CREATE OR REPLACE VIEW` is deliberately chosen over `IF NOT EXISTS` for one critical reason:

> The view definition references `test_runs.strategy_name`. If a strategy is renamed or its registry key is changed, the existing view must be refreshed to reflect the new `WHERE strategy_name = '...'` clause. `IF NOT EXISTS` would silently leave the old, now-incorrect view in place. `OR REPLACE` guarantees the view is always current after a run.

### 2.4 Why Are Global Views (`all_trades`, `strategy_performance`) Included?

These two views address the cross-strategy analysis gap identified in PROB-03 §3.3 Scenario B. Without them, comparing strategies by Sharpe ratio across months requires a manually constructed query spanning all `test_runs` rows. The `strategy_performance` view pre-applies a `RANK()` window function, turning a complex comparative query into a single `SELECT * FROM strategy_performance` call.

---

## 3. Views to Be Created

### View 1: `{strategy_name}_trades`

**Purpose**: Per-strategy, per-trade log. Direct replacement for the ergonomically-burdened JOIN pattern.

**When created**: After every call to `persist_results()` for a given strategy.

**SQL Definition** (parameterised by `strategy_name`):

```sql
CREATE OR REPLACE VIEW {strategy_name}_trades AS
SELECT
    t.vbt_trade_id,
    t.fingerprint,
    r.strategy_name,
    r.symbol,
    r.timeframe,
    r.start_date        AS window_start,
    r.end_date          AS window_end,
    t.direction,
    t.status,
    t.entry_time,
    t.exit_time,
    t.entry_price,
    t.exit_price,
    t.size,
    t.entry_fees,
    t.exit_fees,
    t.pnl,
    t.return_pct,
    t.holding_bars,
    t.holding_seconds,
    t.is_win
FROM trades t
JOIN test_runs r ON t.fingerprint = r.fingerprint
WHERE r.strategy_name = '{strategy_name}';
```

**Usage Examples**:
```sql
-- All sma_cross trades
SELECT * FROM sma_cross_trades;

-- Only losing sma_cross trades, ordered by loss severity
SELECT * FROM sma_cross_trades WHERE is_win = false ORDER BY pnl ASC;

-- Feed directly to trade-book-charts for visual playbook
-- uv run trade-book-charts tradebook \
--   --sql "SELECT * FROM sma_cross_trades WHERE is_win = false LIMIT 12" ...
```

---

### View 2: `{strategy_name}_monthly`

**Purpose**: Monthly performance summary per strategy. Directly mirrors the `--dist monthly` output of `loss-profile` but for backtested strategies rather than real trades.

**When created**: After every call to `persist_results()` for a given strategy.

**SQL Definition**:

```sql
CREATE OR REPLACE VIEW {strategy_name}_monthly AS
SELECT
    strftime(r.start_date, '%Y-%m')     AS month,
    r.strategy_name,
    r.symbol,
    r.timeframe,
    r.start_date,
    r.end_date,
    r.total_return,
    r.benchmark_return,
    r.sharpe_ratio,
    r.max_drawdown,
    r.win_rate,
    r.profit_factor,
    r.total_trades
FROM test_runs r
WHERE r.strategy_name = '{strategy_name}'
ORDER BY r.start_date;
```

**Usage Examples**:
```sql
-- Full year monthly breakdown for sma_cross
SELECT month, total_return, sharpe_ratio, win_rate FROM sma_cross_monthly;

-- Best months by Sharpe for classic_floor_mod_v2
SELECT month, sharpe_ratio, total_trades
FROM classic_floor_mod_v2_monthly
ORDER BY sharpe_ratio DESC LIMIT 3;
```

---

### View 3: `all_trades` (Global)

**Purpose**: Unified trade book spanning every strategy ever tested. The single entry point for cross-strategy trade analysis.

**When created**: Refreshed on every `persist_results()` call, regardless of strategy.

**SQL Definition**:

```sql
CREATE OR REPLACE VIEW all_trades AS
SELECT
    t.vbt_trade_id,
    t.fingerprint,
    r.strategy_name,
    r.symbol,
    r.timeframe,
    t.direction,
    t.entry_time,
    t.exit_time,
    t.entry_price,
    t.exit_price,
    t.pnl,
    t.return_pct,
    t.holding_bars,
    t.holding_seconds,
    t.is_win
FROM trades t
JOIN test_runs r ON t.fingerprint = r.fingerprint;
```

**Usage Examples**:
```sql
-- Count total trades and win rate per strategy
SELECT strategy_name,
       COUNT(*)               AS total_trades,
       AVG(is_win::INT)       AS win_rate,
       SUM(pnl)               AS total_pnl
FROM all_trades
GROUP BY strategy_name;

-- Compare holding duration distributions across strategies
SELECT strategy_name,
       ROUND(AVG(holding_bars), 1) AS avg_bars,
       MIN(holding_bars)           AS min_bars,
       MAX(holding_bars)           AS max_bars
FROM all_trades
GROUP BY strategy_name;
```

---

### View 4: `strategy_performance` (Global)

**Purpose**: Monthly strategy leaderboard. Ranks all tested strategies by Sharpe ratio for each calendar month.

**When created**: Refreshed on every `persist_results()` call.

**SQL Definition**:

```sql
CREATE OR REPLACE VIEW strategy_performance AS
SELECT
    strftime(r.start_date, '%Y-%m')     AS month,
    r.strategy_name,
    r.symbol,
    r.total_return,
    r.benchmark_return,
    r.sharpe_ratio,
    r.max_drawdown,
    r.win_rate,
    r.profit_factor,
    r.total_trades,
    RANK() OVER (
        PARTITION BY strftime(r.start_date, '%Y-%m')
        ORDER BY r.sharpe_ratio DESC NULLS LAST
    ) AS sharpe_rank
FROM test_runs r
ORDER BY month, sharpe_rank;
```

**Usage Examples**:
```sql
-- Best strategy per month
SELECT month, strategy_name, sharpe_ratio
FROM strategy_performance
WHERE sharpe_rank = 1;

-- Full leaderboard for January 2025
SELECT strategy_name, sharpe_ratio, win_rate, total_return
FROM strategy_performance
WHERE month = '2025-01'
ORDER BY sharpe_rank;
```

---

## 4. Implementation Plan

### 4.1 Files to Modify

| File | Change Type | Scope |
| :--- | :--- | :--- |
| [`Utils/1Mnbt.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Utils/1Mnbt.py) | Add function + call | `persist_results()` — last 4 lines |
| [`Core/strategies/registry.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Core/strategies/registry.py) | Register new strategy | 2 lines (import + dict entry) |

### 4.2 No Files to Migrate

| File | Status |
| :--- | :--- |
| `Shared/Data/ohlcv_eruusd.duckdb` physical schema | No changes — tables are already correct |
| `Core/strategies/base.py` | No changes — `StrategyProtocol` is already compatible |
| `Core/strategies/sma_cross.py` | No changes |
| All other project files | Untouched |

---

### 4.3 Change 1 — `Utils/1Mnbt.py`: Add `create_strategy_views()`

Add the following function **before** `persist_results()`:

```python
import re

def _safe_view_name(strategy_name: str) -> str:
    """Sanitise strategy name to a valid DuckDB identifier.
    
    Replaces any character that is not alphanumeric or underscore with '_'.
    Prevents SQL injection when interpolating strategy names into view DDL.
    
    Example:
        'classic_floor_mod_v2' → 'classic_floor_mod_v2'  (unchanged)
        'my-strategy.v1'       → 'my_strategy_v1'
    """
    return re.sub(r"[^a-zA-Z0-9_]", "_", strategy_name)


def create_strategy_views(
    con: duckdb.DuckDBPyConnection,
    strategy_name: str,
) -> None:
    """Auto-generate or refresh all four DuckDB views after a strategy persist.

    Creates:
      - {strategy_name}_trades     : Per-trade log for this strategy only.
      - {strategy_name}_monthly    : Monthly performance summary for this strategy.
      - all_trades                 : Combined trade book across all strategies.
      - strategy_performance       : Cross-strategy monthly leaderboard by Sharpe.

    All views use CREATE OR REPLACE to guarantee they stay current on every run.
    The strategy name is sanitised before interpolation to prevent SQL injection.

    Args:
        con:           An open, writable DuckDB connection.
        strategy_name: The strategy name as stored in test_runs.strategy_name.
    """
    safe_name = _safe_view_name(strategy_name)

    # View 1: Per-strategy individual trade log
    con.execute(f"""
        CREATE OR REPLACE VIEW {safe_name}_trades AS
        SELECT
            t.vbt_trade_id,
            t.fingerprint,
            r.strategy_name,
            r.symbol,
            r.timeframe,
            r.start_date        AS window_start,
            r.end_date          AS window_end,
            t.direction,
            t.status,
            t.entry_time,
            t.exit_time,
            t.entry_price,
            t.exit_price,
            t.size,
            t.entry_fees,
            t.exit_fees,
            t.pnl,
            t.return_pct,
            t.holding_bars,
            t.holding_seconds,
            t.is_win
        FROM trades t
        JOIN test_runs r ON t.fingerprint = r.fingerprint
        WHERE r.strategy_name = '{strategy_name}'
    """)

    # View 2: Per-strategy monthly performance summary
    con.execute(f"""
        CREATE OR REPLACE VIEW {safe_name}_monthly AS
        SELECT
            strftime(r.start_date, '%Y-%m')     AS month,
            r.strategy_name,
            r.symbol,
            r.timeframe,
            r.start_date,
            r.end_date,
            r.total_return,
            r.benchmark_return,
            r.sharpe_ratio,
            r.max_drawdown,
            r.win_rate,
            r.profit_factor,
            r.total_trades
        FROM test_runs r
        WHERE r.strategy_name = '{strategy_name}'
        ORDER BY r.start_date
    """)

    # View 3: Global combined trade book — all strategies
    con.execute("""
        CREATE OR REPLACE VIEW all_trades AS
        SELECT
            t.vbt_trade_id,
            t.fingerprint,
            r.strategy_name,
            r.symbol,
            r.timeframe,
            t.direction,
            t.entry_time,
            t.exit_time,
            t.entry_price,
            t.exit_price,
            t.pnl,
            t.return_pct,
            t.holding_bars,
            t.holding_seconds,
            t.is_win
        FROM trades t
        JOIN test_runs r ON t.fingerprint = r.fingerprint
    """)

    # View 4: Cross-strategy monthly performance leaderboard
    con.execute("""
        CREATE OR REPLACE VIEW strategy_performance AS
        SELECT
            strftime(r.start_date, '%Y-%m')     AS month,
            r.strategy_name,
            r.symbol,
            r.total_return,
            r.benchmark_return,
            r.sharpe_ratio,
            r.max_drawdown,
            r.win_rate,
            r.profit_factor,
            r.total_trades,
            RANK() OVER (
                PARTITION BY strftime(r.start_date, '%Y-%m')
                ORDER BY r.sharpe_ratio DESC NULLS LAST
            ) AS sharpe_rank
        FROM test_runs r
        ORDER BY month, sharpe_rank
    """)
```

Then modify `persist_results()` — add one call to `create_strategy_views()` before `con.close()`:

```python
# Current last 2 lines of persist_results():
    con.close()

# Replace with:
    # Extract strategy name from the first successful result
    strategy_name = next(
        (r["params"]["strategy_name"] for r in results if r["status"] == "SUCCESS"),
        None,
    )
    if strategy_name:
        create_strategy_views(con, strategy_name)

    con.close()
```

---

### 4.4 Change 2 — `Core/strategies/registry.py`: Register `classic_floor_mod_v2`

> **Note**: This change requires first adapting `ClassicFloorModV2.generate_signals()` to return only `(entries, exits)` instead of `(entries, exits, trades_df)`, as the current signature is incompatible with `StrategyProtocol`. The adapter wrapper below handles this without modifying the original file.

Create a thin adapter in `Core/strategies/` (e.g. `classic_floor_v2.py`):

```python
"""Adapter wrapping ClassicFloorModV2 to conform to StrategyProtocol."""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any
import pandas as pd

# Resolve the strategy file from its non-standard location
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "Shared" / "straragYs"))
from classic_floor_mod_v2 import ClassicFloorModV2 as _ClassicFloorModV2


class ClassicFloorV2Strategy:
    """StrategyProtocol-compatible wrapper for ClassicFloorModV2."""

    name: str = "classic_floor_mod_v2"
    version: str = "2.0.0"

    def __init__(self) -> None:
        self._inner = _ClassicFloorModV2()

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict[str, Any],
    ) -> tuple[pd.Series, pd.Series]:
        """Delegate to ClassicFloorModV2 and strip the third return value."""
        entries, exits, _trades_df = self._inner.generate_signals(ohlcv)
        return entries, exits
```

Then add two lines to `Core/strategies/registry.py`:

```python
# Add this import alongside the existing one:
from .classic_floor_v2 import ClassicFloorV2Strategy

# Add this entry to _REGISTRY:
_REGISTRY: dict[str, "StrategyProtocol"] = {
    "sma_cross":             SmaCrossStrategy(),
    "classic_floor_mod_v2":  ClassicFloorV2Strategy(),   # ← new
}
```

---

## 5. Expected Database State After Full Implementation

After running both strategies for January 2025:

```
Physical Tables (4 — permanently stable, never grows):
┌───────────────────┬────────┬───────────────────────────────────────────┐
│ Table             │ Rows   │ Contents                                  │
├───────────────────┼────────┼───────────────────────────────────────────┤
│ ohlcv             │ 76,403 │ EUR/USD 5m candles, full year 2025        │
│ batches           │ 2      │ One batch per 1Mnbt invocation            │
│ test_runs         │ 2      │ sma_cross + classic_floor_mod_v2 Jan 2025 │
│ trades            │ 95 + N │ All trades from all strategies combined   │
└───────────────────┴────────┴───────────────────────────────────────────┘

Auto-Generated Views (6 — zero disk cost, always current):
┌──────────────────────────────────┬──────────────────────────────────────────────┐
│ View Name                        │ Contents                                     │
├──────────────────────────────────┼──────────────────────────────────────────────┤
│ sma_cross_trades                 │ 95 trades — sma_cross only                   │
│ sma_cross_monthly                │ 1 row — sma_cross Jan 2025 monthly summary   │
│ classic_floor_mod_v2_trades      │ N trades — classic_floor_mod_v2 only         │
│ classic_floor_mod_v2_monthly     │ 1 row — classic_floor_mod_v2 Jan 2025 summary│
│ all_trades                       │ 95 + N rows — every trade, every strategy    │
│ strategy_performance             │ 2 rows — ranked Jan 2025 leaderboard         │
└──────────────────────────────────┴──────────────────────────────────────────────┘
```

---

## 6. Verification Steps

After implementation, verify correctness by running the following commands in order:

### Step 1 — Confirm Views Exist

```bash
uv run python Utils/duckdb-explorar-tool/duckdb_explorer.py \
  --output table Shared/Data/ohlcv_eruusd.duckdb list-tables
```

**Expected**: `sma_cross_trades`, `sma_cross_monthly`, `all_trades`, `strategy_performance` appear alongside the 4 physical tables.

---

### Step 2 — Verify `sma_cross_trades` Returns Correct Data

```bash
uv run python Utils/duckdb-explorar-tool/duckdb_explorer.py \
  --output table Shared/Data/ohlcv_eruusd.duckdb \
  query "SELECT strategy_name, COUNT(*) AS trades, AVG(pnl) AS avg_pnl FROM sma_cross_trades GROUP BY strategy_name"
```

**Expected**: 1 row, `strategy_name = sma_cross`, `trades = 95`.

---

### Step 3 — Verify Cross-Strategy Leaderboard (After Both Strategies Run)

```bash
uv run python Utils/duckdb-explorar-tool/duckdb_explorer.py \
  --output table Shared/Data/ohlcv_eruusd.duckdb \
  query "SELECT month, strategy_name, sharpe_ratio, win_rate, sharpe_rank FROM strategy_performance"
```

**Expected**: 2 rows for `2025-01`, each strategy ranked by Sharpe.

---

### Step 4 — Verify `all_trades` Spans Both Strategies

```bash
uv run python Utils/duckdb-explorar-tool/duckdb_explorer.py \
  --output table Shared/Data/ohlcv_eruusd.duckdb \
  query "SELECT strategy_name, COUNT(*) AS trades FROM all_trades GROUP BY strategy_name"
```

**Expected**: 2 rows — one for `sma_cross` and one for `classic_floor_mod_v2`.

---

### Step 5 — Idempotency Check (Re-run without `--force`)

```bash
# Re-run sma_cross January — should not duplicate data
uv run python Utils/1Mnbt.py --month 2025-01 --strategy sma_cross --db Shared/Data/ohlcv_eruusd.duckdb
```

Then verify row counts are unchanged:

```bash
uv run python Utils/duckdb-explorar-tool/duckdb_explorer.py \
  --output table Shared/Data/ohlcv_eruusd.duckdb list-tables
```

**Expected**: `test_runs` still has 1 row for `sma_cross Jan 2025` (not 2), `trades` still has 95 rows.

---

## 7. Dependency Map

```
PROB-03 (Problem)
  └─── ADR-002 (Decision: unified tables + views)
         └─── SOLUTION-03 (This document)
                ├─── Utils/1Mnbt.py
                │      ├─── persist_results()      [modified: add view call]
                │      ├─── create_strategy_views() [new function]
                │      └─── _safe_view_name()       [new helper]
                └─── Core/strategies/
                       ├─── classic_floor_v2.py     [new adapter file]
                       └─── registry.py             [modified: add entry]
```

---

## 8. Open Questions for Review

| # | Question | Impact |
| :--- | :--- | :--- |
| Q-1 | Should `classic_floor_mod_v2.py` be moved from `Shared/straragYs/` to `Core/strategies/` directly? | Low — adapter pattern works from either location; moving is cleaner long-term |
| Q-2 | Should the `classic_floor_mod_v2` adapter strip the `trades_df` return silently, or log a debug message? | Very low — informational only |
| Q-3 | Should `strategy_performance` rank by Sharpe, or should the ranking metric be configurable? | Low — Sharpe is the standard; can add `win_rate_rank` column later |
| Q-4 | Should a `{strategy_name}_losing_trades` convenience view also be auto-generated? | Low — equivalent to `SELECT * FROM {strategy_name}_trades WHERE is_win = false`; a full view may be superfluous |
