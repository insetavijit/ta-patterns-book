# ADR-002: Unified Multi-Strategy DuckDB Schema with Strategy-Scoped Views

**Status**: Proposed  
**Date**: 2026-09-06  
**Deciders**: Avijit  
**Problem Specification**: [`PROB-03-multi-strategy-schema-fragmentation.md`](file:///home/avijit/workSpace/Code/ta-patterns-book/DOCs/Artifacts/ADRs/PROB-03-multi-strategy-schema-fragmentation.md)  
**Target Database**: `Shared/Data/ohlcv_eruusd.duckdb`

---

## 1. Context

The project now has a working concurrent monthly backtest runner (`1Mnbt.py`) and a ready-to-register strategy (`classic_floor_mod_v2`). As the number of strategies under test grows, the persistence layer needs a governed schema design that prevents fragmentation while maintaining per-strategy query ergonomics.

The full problem analysis, database schema inventory, live data snapshot, failure scenarios, and solution constraints are documented in [PROB-03](file:///home/avijit/workSpace/Code/ta-patterns-book/DOCs/Artifacts/ADRs/PROB-03-multi-strategy-schema-fragmentation.md). This ADR records the architectural decision taken in response to that problem.

---

## 2. Decision Drivers

| Driver | Description |
| :--- | :--- |
| **Ergonomics** | Researchers must query `sma_cross_trades` without writing JOINs every time |
| **Scalability** | 10+ strategies must not cause 10+ new physical tables |
| **Cross-strategy analysis** | Monthly Sharpe, win rate, and PnL comparisons across strategies must be a single SQL call |
| **Tool compatibility** | `duckdb_explorer`, `trade-book-charts`, and `loss-profile` must work against strategy views without modification |
| **Idempotency** | Re-running any strategy backtest must never corrupt or duplicate data |

---

## 3. Considered Options

### Option A — Per-Strategy Physical Tables *(Rejected)*

Create a dedicated DuckDB table for each strategy: `sma_cross_trades`, `classic_floor_v2_trades`, etc.

**Problems**:
- Table count grows linearly with each new strategy.
- Data is duplicated between the physical strategy table and the shared `trades` table.
- Cross-strategy comparisons require manual `UNION ALL` across tables.
- `duckdb_explorer list-tables` output becomes progressively noisier.
- Every downstream tool (`trade-book-charts --sql`, Notebooks) must be updated when a strategy is renamed.

**Verdict**: ❌ Rejected. Causes the exact schema fragmentation described in PROB-03.

---

### Option B — No Isolation, Raw Shared Tables Only *(Rejected)*

Keep only the 3 shared tables and require every query to use `JOIN test_runs ON fingerprint WHERE strategy_name = '...'`.

**Problems**:
- Manual JOIN required every time — high cognitive burden for day-to-day analysis.
- `trade-book-charts` and `loss-profile` cannot be pointed at a strategy-scoped dataset without query rewriting.
- Inconsistent user experience compared to the pattern established by `3candels_patterns_view` and `trades_view` already present in the primary database.

**Verdict**: ❌ Rejected. Ergonomically insufficient.

---

### Option C — Unified Tables + Auto-Generated Strategy Views *(Accepted)*

Retain the 3 unified physical tables (`batches`, `test_runs`, `trades`) unchanged. After each strategy's runs are persisted, automatically call `CREATE OR REPLACE VIEW {strategy_name}_trades AS ...` and `CREATE OR REPLACE VIEW {strategy_name}_monthly AS ...` inside `persist_results()`. Also maintain a global `all_trades` view.

**Verdict**: ✅ Accepted. Satisfies all constraints in PROB-03 §4.

---

## 4. Decision

**Keep the current 3-table unified schema as the single source of truth. Add a `create_strategy_views(con, strategy_name)` lifecycle hook to `persist_results()` in `1Mnbt.py` that automatically generates DuckDB views for every strategy after its runs are written.**

No physical schema migration is required. The existing 95 `sma_cross` trades and 1 `test_runs` row are already correctly stored and will be served by the new views immediately after they are created.

---

## 5. Solution Design

### 5.1 Views to Create Per Strategy

#### `{strategy_name}_trades` — Individual Trade Log View

```sql
CREATE OR REPLACE VIEW {strategy_name}_trades AS
SELECT
    t.vbt_trade_id,
    t.fingerprint,
    r.strategy_name,
    r.symbol,
    r.timeframe,
    r.start_date                            AS window_start,
    r.end_date                              AS window_end,
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

#### `{strategy_name}_monthly` — Monthly Performance Summary View

```sql
CREATE OR REPLACE VIEW {strategy_name}_monthly AS
SELECT
    strftime(r.start_date, '%Y-%m')         AS month,
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

### 5.2 Global Cross-Strategy Views

#### `all_trades` — Combined Trade Book Across All Strategies

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
    t.is_win
FROM trades t
JOIN test_runs r ON t.fingerprint = r.fingerprint;
```

#### `strategy_performance` — Cross-Strategy Monthly Ranking View

```sql
CREATE OR REPLACE VIEW strategy_performance AS
SELECT
    strftime(r.start_date, '%Y-%m')         AS month,
    r.strategy_name,
    r.symbol,
    r.total_return,
    r.sharpe_ratio,
    r.max_drawdown,
    r.win_rate,
    r.profit_factor,
    r.total_trades,
    RANK() OVER (PARTITION BY strftime(r.start_date, '%Y-%m')
                 ORDER BY r.sharpe_ratio DESC NULLS LAST) AS sharpe_rank
FROM test_runs r
ORDER BY month, sharpe_rank;
```

---

## 6. Code Change Location

The only file requiring modification is [`Utils/1Mnbt.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Utils/1Mnbt.py), specifically the `persist_results()` function.

A new `create_strategy_views(con, strategy_name)` helper is added and called once per strategy write:

```python
def create_strategy_views(con: duckdb.DuckDBPyConnection, strategy_name: str) -> None:
    """Auto-generate or refresh strategy-scoped views after each persist."""

    # Per-strategy individual trades view
    con.execute(f"""
        CREATE OR REPLACE VIEW {strategy_name}_trades AS
        SELECT
            t.vbt_trade_id, t.fingerprint,
            r.strategy_name, r.symbol, r.timeframe,
            r.start_date AS window_start, r.end_date AS window_end,
            t.direction, t.status, t.entry_time, t.exit_time,
            t.entry_price, t.exit_price, t.size,
            t.entry_fees, t.exit_fees, t.pnl, t.return_pct,
            t.holding_bars, t.holding_seconds, t.is_win
        FROM trades t
        JOIN test_runs r ON t.fingerprint = r.fingerprint
        WHERE r.strategy_name = '{strategy_name}'
    """)

    # Per-strategy monthly summary view
    con.execute(f"""
        CREATE OR REPLACE VIEW {strategy_name}_monthly AS
        SELECT
            strftime(r.start_date, '%Y-%m') AS month,
            r.strategy_name, r.symbol, r.timeframe,
            r.start_date, r.end_date,
            r.total_return, r.benchmark_return,
            r.sharpe_ratio, r.max_drawdown,
            r.win_rate, r.profit_factor, r.total_trades
        FROM test_runs r
        WHERE r.strategy_name = '{strategy_name}'
        ORDER BY r.start_date
    """)

    # Global combined trades view (all strategies)
    con.execute("""
        CREATE OR REPLACE VIEW all_trades AS
        SELECT
            t.vbt_trade_id, t.fingerprint,
            r.strategy_name, r.symbol, r.timeframe,
            t.direction, t.entry_time, t.exit_time,
            t.entry_price, t.exit_price,
            t.pnl, t.return_pct, t.holding_bars, t.is_win
        FROM trades t
        JOIN test_runs r ON t.fingerprint = r.fingerprint
    """)

    # Global cross-strategy monthly ranking view
    con.execute("""
        CREATE OR REPLACE VIEW strategy_performance AS
        SELECT
            strftime(r.start_date, '%Y-%m') AS month,
            r.strategy_name, r.symbol,
            r.total_return, r.sharpe_ratio, r.max_drawdown,
            r.win_rate, r.profit_factor, r.total_trades,
            RANK() OVER (
                PARTITION BY strftime(r.start_date, '%Y-%m')
                ORDER BY r.sharpe_ratio DESC NULLS LAST
            ) AS sharpe_rank
        FROM test_runs r
        ORDER BY month, sharpe_rank
    """)
```

---

## 7. Expected Database State After Implementation

After running `sma_cross` and `classic_floor_mod_v2` for January 2025:

```
Physical Tables (stable, 4 tables total — NEVER grows):
  ohlcv              | 76,403 rows    — EUR/USD OHLCV 2025
  batches            | 2+ rows        — one per 1Mnbt run
  test_runs          | 2+ rows        — one per strategy × month
  trades             | 95 + N rows    — all trades from all strategies

Auto-Refreshed Views (zero disk cost):
  sma_cross_trades          — sma_cross trade log, filterable by date
  sma_cross_monthly         — sma_cross monthly performance summary
  classic_floor_v2_trades   — classic_floor_mod_v2 trade log
  classic_floor_v2_monthly  — classic_floor_mod_v2 monthly summary
  all_trades                — combined trade book, all strategies
  strategy_performance      — cross-strategy monthly ranking by Sharpe
```

---

## 8. Consequences

### Positive

| Consequence | Detail |
| :--- | :--- |
| **Zero schema bloat** | 4 physical tables serve all strategies indefinitely |
| **Instant ergonomics** | `SELECT * FROM sma_cross_trades` — no JOIN needed |
| **Cross-strategy analysis** | `SELECT * FROM strategy_performance` returns a ranked leaderboard across all strategies and months |
| **Tool ecosystem compatible** | `trade-book-charts --sql "SELECT * FROM sma_cross_trades WHERE is_win = false"` works out of the box |
| **duckdb_explorer compatible** | `list-tables` shows views alongside physical tables naturally |
| **Idempotent** | `CREATE OR REPLACE VIEW` is safe to call on every run — no side effects |
| **Consistent with existing project conventions** | Mirrors the `trades_view`, `3candels_patterns_view` pattern already used in `eur_usd_trades_5m.duckdb` |

### Risks & Mitigations

| Risk | Mitigation |
| :--- | :--- |
| View references `t.*` — breaks if `trades` schema changes | List all columns explicitly in the view definition (already done above) |
| Strategy name contains special chars (e.g. hyphens) | Sanitise `strategy_name` to valid SQL identifier before interpolating into view name |
| Fingerprint collision between strategies | SHA-256 over full params JSON including `strategy_name` — collision probability negligible |

---

## 9. Status & Next Steps

| Step | Owner | Status |
| :--- | :--- | :--- |
| Review this ADR | Avijit | ⏳ Pending |
| Register `classic_floor_mod_v2` in `Core/strategies/registry.py` | Developer | 🔲 Not started |
| Add `create_strategy_views()` to `Utils/1Mnbt.py` → `persist_results()` | Developer | 🔲 Not started |
| Re-run `sma_cross` January test to generate views | Developer | 🔲 Not started |
| Verify `sma_cross_trades` view via `duckdb_explorer` | Developer | 🔲 Not started |
| Run `classic_floor_mod_v2` January test and verify views | Developer | 🔲 Not started |
