---
title: Fibonacci Price-Level Touch Before Stop-Loss Analysis — Implemented Architecture
status: active
version: 1
type: implementation-record
area: backtesting
tags:
  - analytics
  - backtesting
  - fibonacci
  - duckdb
  - strategy-telemetry
created: 2026-09-09
related:
  - "[[features-fibs.md]]"
  - "Shared/straragYs/classic_floor_mod_v4c.py"
  - "Core/strategies/classic_floor_v4c.py"
  - "Notebooks/1Ybt.py"
---

# Fibonacci Price-Level Touch Before Stop-Loss (`fib_bsl`) — Implemented Architecture

## Overview
This document records the implemented production architecture of the **Price-Level Touch Before Stop-Loss (`fib_bsl`)** feature in the `ta-patterns-book` repository, serving as an authoritative reference alongside the original design proposal in [`features-fibs.md`](features-fibs.md).

Rather than requiring an external post-processing step with timestamp-to-array re-indexing, the feature is implemented as **native strategy telemetry** in [`classic_floor_mod_v4c.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Shared/straragYs/classic_floor_mod_v4c.py), with automated pipeline persistence through [`1Ybt.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Notebooks/1Ybt.py) into DuckDB.

---

## 1. Mathematical Definitions & Core Rules

| Concept | Definition / Implementation Formula |
|---|---|
| **TP-SL Block (Leg)** | Structural reference range between Stop-Loss and Take-Profit: `leg_span = TP - SL`. |
| **Fibonacci Ratios** | Fixed set of standard ratios: `(0.236, 0.382, 0.500, 0.618, 0.786)`. |
| **Level Price** | `level_price = SL + ratio * (TP - SL)` (calculated at position entry). |
| **Tolerance ($\epsilon$)** | Relative epsilon margin: `eps = max(level_price * 1e-7, 1e-9)` to prevent floating-point rounding errors. |
| **Touch Condition** | Long trade: candle `High >= level_price - eps`. SL touched: candle `Low <= SL + eps`. |
| **Scan Window** | Traverses every candle the position is open, beginning at entry candle (post-open) through the exit candle. |
| **Tie Policy** | `sl_first` (default confirmed): If a ratio and SL first touch on the *same candle*, SL is assumed first; that ratio is not counted as reached before SL, and `fib_bsl_ambiguous = True` is flagged. |

---

## 2. Telemetry Output Columns

The results are stored directly in the `trades` table and `{strategy}_trades` view in DuckDB:

| Column | DuckDB Type | Description |
|---|---|---|
| `fib_bsl` | `DOUBLE` | Deepest Fibonacci ratio reached before SL was touched. <br>• `0.786`: Trade exited at TP (or reached top ratio).<br>• `0.0`: No Fibonacci level was reached before stop out.<br>• `NaN`: Trade had no valid SL/TP leg defined. |
| `fib_bsl_ambiguous` | `BOOLEAN` | `True` only if a candidate higher ratio was touched on the *exact same candle* as the SL, making the reported maximum dependent on the intra-candle order. |

---

## 3. Implementation Workflow & Code Map

### A. Strategy Level ([`Shared/straragYs/classic_floor_mod_v4c.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Shared/straragYs/classic_floor_mod_v4c.py))
1. **Entry Initialization**:
   When entering a trade at `i = trade_entry_bar`:
   ```python
   leg_span = target_price - stop_price
   fib_levels = [stop_price + r * leg_span for r in FIB_RATIOS]
   first_touch_bar = [-1] * 5
   # Check entry candle high against levels
   for j in range(5):
       eps = max(fib_levels[j] * 1e-7, 1e-9)
       if high_arr[i] >= fib_levels[j] - eps:
           first_touch_bar[j] = i
   ```

2. **In-Trade Tracking (`if in_trade:`)**:
   On every subsequent candle `i`:
   ```python
   if fib_levels is not None:
       for j in range(5):
           eps = max(fib_levels[j] * 1e-7, 1e-9)
           if first_touch_bar[j] == -1 and cur_high >= fib_levels[j] - eps:
               first_touch_bar[j] = i
   ```

3. **Exit Resolution (`target_hit or stop_hit`)**:
   ```python
   if target_hit:
       f_bsl = 0.786
       f_ambig = False
   else:
       sl_bar = i
       reached = [FIB_RATIOS[j] for j in range(5) if first_touch_bar[j] != -1 and first_touch_bar[j] < sl_bar]
       f_bsl = max(reached) if reached else 0.0
       tied = [FIB_RATIOS[j] for j in range(5) if first_touch_bar[j] == sl_bar]
       f_ambig = bool(tied and max(tied) > f_bsl)
   ```
   Stored in `trades_df['fib_bsl']` and `trades_df['fib_bsl_ambiguous']`.

---

### B. Runner & Persistence Level ([`Notebooks/1Ybt.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Notebooks/1Ybt.py))
1. **Trade Record Extraction**: `simulate_signals()` captures `fib_bsl` and `fib_bsl_ambiguous` from `trades_df`.
2. **DuckDB Schema & Migrations**: Added `fib_bsl DOUBLE` and `fib_bsl_ambiguous BOOLEAN` to `trades` DDL and automated schema migrations.
3. **Strategy Views**: `create_strategy_views()` automatically includes `t.fib_bsl` and `t.fib_bsl_ambiguous` in `{strategy}_trades` view.

---

## 4. Analytical Interpretation

- **`tp_hit` Trades**: By definition, trades hitting TP reach the full 1.0 extension of the leg and report `fib_bsl = 0.786`.
- **`sl_hit` Trades (The Primary Signal)**: For losing trades that stopped out:
  - `0.0`: Price immediately plummeted to SL without even reaching the 23.6% bracket level.
  - `0.236` / `0.382`: Price traded within the lower band of the TP-SL block before stopping out.
  - `0.500`: Price made it halfway to target before reversing.
  - `0.618` / `0.786`: Heartbreaking near-misses where price achieved 61.8% to 78.6% of the target span before collapsing into the stop loss.
