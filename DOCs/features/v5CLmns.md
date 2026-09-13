# ClassicFloorModV5 — Computed Columns Data Dictionary

This document details all **34 columns** produced in the `trades_df` output table by [`Shared/strategies/classic_floor_mod_v5.py`](file:///home/avijit/workSpace/Code/ta-patterns-book/Shared/strategies/classic_floor_mod_v5.py).

---

## 1. Summary Overview

| Category | Count | Columns |
| :--- | :---: | :--- |
| **Pivot & Price Reference** | 5 | `pivot`, `s1`, `r1`, `upper_pivot`, `lower_pivot` |
| **Signal & Position State** | 4 | `entries`, `exits`, `in_trade`, `trade_id` |
| **Execution & Order Levels** | 5 | `entry_price`, `sl_price`, `tp_price`, `exit_price`, `swing_low` |
| **Outcomes & Performance** | 4 | `exit_reason`, `realized_pnl`, `realized_pnl_pct`, `is_win` |
| **Timing & Lifecycle** | 2 | `signal_time`, `confirmation_time` |
| **Fibonacci Excursion (BSL)** | 2 | `fib_bsl`, `fib_bsl_ambiguous` |
| **3-Candle State Patterns** | 8 | `epatt_1..4`, `entry_1..4` |
| **Candlestick Classifications** | 6 | `ecpatt_1..3`, `epcpatt_1..3` |
| **Total** | **34** | |

---

## 2. Detailed Column Specifications

### 2.1 Pivot & Reference Levels (5 Columns)
Calculated using a 20-period rolling window shifted by 1 bar:
- **`pivot`** (`float`): Core Floor Trader Pivot point:
  $$\text{pivot} = \frac{\text{High}_{20} + \text{Low}_{20} + \text{Close}_{-1}}{3}$$
- **`s1`** (`float`): First Floor Support:
  $$S_1 = (2 \times \text{pivot}) - \text{High}_{20}$$
- **`r1`** (`float`): First Floor Resistance (serves as the fixed Take-Profit target):
  $$R_1 = (2 \times \text{pivot}) - \text{Low}_{20}$$
- **`upper_pivot`** (`float`): Alias for `r1`.
- **`lower_pivot`** (`float`): Alias for `s1`.

---

### 2.2 Signal & Position State (4 Columns)
- **`entries`** (`bool`): `True` exclusively on the confirmation candle Open (Bar +3 from signal).
- **`exits`** (`bool`): `True` on the candle where either Take Profit ($R_1$) or Stop Loss is reached.
- **`in_trade`** (`bool`): `True` for every bar while the position remains active.
- **`trade_id`** (`int`): Unique sequential integer identifier assigned to each trade.

---

### 2.3 Execution & Order Levels (5 Columns)
- **`entry_price`** (`float`): Exact fill price at Bar +3 `open`.
- **`sl_price`** (`float`): Dynamic Stop Loss:
  $$\text{sl\_price} = \text{swing\_low} - 0.5 \times (R_1 - S_1)$$
- **`tp_price`** (`float`): Frozen target price at setup $R_1$.
- **`exit_price`** (`float`): Exit fill price (equals `tp_price` on TP hit, `sl_price` on SL hit).
- **`swing_low`** (`float`): Lowest candle body low ($\min(\text{open}, \text{close})$) across Bars 0 through 3 (from initial trigger bar through confirmation bar).

---

### 2.4 Outcomes & Performance (4 Columns)
Populated on the exit candle:
- **`exit_reason`** (`str`): Trigger that closed the trade (`'TP'` or `'SL'`).
- **`realized_pnl`** (`float`): Absolute point gain/loss:
  $$\text{realized\_pnl} = \text{exit\_price} - \text{entry\_price}$$
- **`realized_pnl_pct`** (`float`): Percentage return:
  $$\text{realized\_pnl\_pct} = \left(\frac{\text{realized\_pnl}}{\text{entry\_price}}\right) \times 100$$
- **`is_win`** (`int`): Binary outcome flag (`1` for win / TP, `-1` for loss / SL, `0` otherwise).

---

### 2.5 Timing & Lifecycle (2 Columns)
- **`signal_time`** (`datetime` / `object`): Timestamp of initial setup trigger (Bar 0 where $\text{close} \le S_1$).
- **`confirmation_time`** (`datetime` / `object`): Timestamp of scheduled entry bar (Bar +3).

---

### 2.6 Fibonacci Before Stop Loss (BSL) Excursion (2 Columns)
Measures the maximum upward excursion across Fibonacci ratios $(0.236, 0.382, 0.5, 0.618, 0.786)$ prior to trade closure:
- **`fib_bsl`** (`float`): Highest Fibonacci extension reached before an SL hit ($0.0$ to $0.786$). Automatically set to $0.786$ if the trade reached TP.
- **`fib_bsl_ambiguous`** (`bool`): `True` if the highest touch occurred on the exact same candle where the Stop Loss was triggered.

---

### 2.7 Confirmation-Anchored 3-Candle State Patterns (8 Columns)
Candle state is encoded as Direction (`U` / `D`) + Color (`G` / `R`), e.g., `UG`, `UR`, `DG`, `DR`.

#### Primary Format (`epatt_1..4`):
- **`epatt_1`** (`str`): 3 setup candles strictly preceding entry (`pos-3`, `pos-2`, `pos-1`).
- **`epatt_2`** (`str`): 2 candles prior + entry candle (`pos-2`, `pos-1`, `pos`).
- **`epatt_3`** (`str`): 1 candle before + entry + 1 candle after (`pos-1`, `pos`, `pos+1`).
- **`epatt_4`** (`str`): Entry bar + 3 forward confirmation candles (`pos`, `pos+1`, `pos+2`, `pos+3`).

#### Compatibility Aliases (`entry_1..4`):
- **`entry_1`** (`str`): Exact alias for `epatt_1` (for `loss-profile` CLI compatibility).
- **`entry_2`** (`str`): Exact alias for `epatt_2`.
- **`entry_3`** (`str`): Exact alias for `epatt_3`.
- **`entry_4`** (`str`): Exact alias for `epatt_4`.

---

### 2.8 Candlestick Pattern Recognition (6 Columns)
Extracted via `ta_patterns_book.loss_profile.candles`:
- **`ecpatt_1`** (`str`): 1st confirmation candlestick pattern name (e.g., `Hammer`, `Engulfing`).
- **`ecpatt_2`** (`str`): 2nd confirmation candlestick pattern name.
- **`ecpatt_3`** (`str`): 3rd confirmation candlestick pattern name.
- **`epcpatt_1`** (`str`): 1st preceding candlestick pattern name.
- **`epcpatt_2`** (`str`): 2nd preceding candlestick pattern name.
- **`epcpatt_3`** (`str`): 3rd preceding candlestick pattern name.

---

## 3. Architecture Proposal for Next Strategy Version

To establish a clean, strategy-agnostic architecture for the next strategy iteration, the following schema updates are proposed:

1. **Rename `r1` $\rightarrow$ `upper_pivot`**:
   - **Rationale**: Generalizes the upper boundary / target line across arbitrary channel algorithms (classic pivots, Woodie, Camarilla, Keltner/Bollinger envelopes), removing strategy-specific Floor Trader 'R1' coupling.
2. **Rename `s1` $\rightarrow$ `lower_pivot`**:
   - **Rationale**: Symmetrically generalizes the lower boundary / support trigger level for bounce and breakout strategies.
3. **Standardize on `epatt_1..4` (Deprecate `entry_1..4`)**:
   - **Rationale**: Standardizes all confirmation-anchored candle sequences under execution-pattern (`epatt`) taxonomy, eliminates redundant duplicate columns, and minimizes database payload.
