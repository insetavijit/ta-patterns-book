# Strategy Changelog: ClassicFloorMod v4c → ClassicFloorMod v5

**Document Version:** 1.0.0  
**Date:** 2026-09-10  
**Status:** Approved Architecture Specification  
**Reference Notes:** [`DOCs/NOTEs/v5updates.md`](file:///home/avijit/workSpace/Code/ta-patterns-book/DOCs/NOTEs/v5updates.md)

---

## 1. Executive Summary & Core Philosophy

`ClassicFloorModV5` streamlines and formalizes the strategy architecture:

1. **Elimination of Heuristic Delay & Cancellation Filters**:
   - `v4c` applied complex multi-branch conditional delay rules (`DR-DR-DR` +3 bars, `DR-UG-DR` +1-2 bars, `DR-DR-UG` +1 bar, `UG-DR-UG` +3 bars) and setup cancellation on `Bull_Spinning_Top`.
   - `v5` **removes all conditional delay and cancellation filters**. It re-establishes a clean, deterministic baseline where every valid signal enters directly at the **Confirmation Candle's Open**.

2. **Strict 4-Candle Lifecycle**:
   - Every trade tracks 4 canonical lifecycle timestamps: `signal_time`, `confirmation_time`, `entry_time`, and `exit_time`.
   - The **Confirmation Candle** is strictly defined as the **4th candle from the Signal Candle** (Sequence: `Signal [0] → Wait 1 [1] → Wait 2 [2] → Confirmation / Entry [3]`).

3. **Pattern Renaming & Anchoring**:
   - 3-candle state patterns are renamed from `entry_1..4` to **`epatt_1..4`**.
   - They are formally anchored to the **Confirmation Candle** (`pos = signal + 3`).

4. **Self-Contained Database Deployment**:
   - `v5` transitions from monolithic shared database mutation to isolated, portable backtest artifacts: `Shared/Data/classic_floor_mod_v5_{tf}_{symbol}.duckdb` containing canonical `ohlcv` (sliced to exact test window) and canonical `trades`.

---

## 2. Detailed Comparison: v4c vs. v5

| Feature / Metric | `classic_floor_mod_v4c` (Previous) | `classic_floor_mod_v5` (New) | Rationale |
| :--- | :--- | :--- | :--- |
| **Entry Timing** | Dynamic (`signal + 3`, `+4`, `+5`, `+6`) depending on candle patterns. | **Deterministic: Always `signal + 3` Open** (Confirmation Candle Open). | Eliminates curve-fitting, removes filter latency, provides a pure structural baseline. |
| **Delay Filters** | 4 nested pattern delay rules (`DR-DR-DR`, `DR-UG-DR`, `DR-DR-UG`, `UG-DR-UG`). | **None (Avoided entirely)**. | Maximizes sample size and transparency of the core floor trader edge. |
| **Setup Cancellation** | Cancelled entry if `entry_1 == 'DR-UG-UG'` and `epcpatt_1 == 'Bull_Spinning_Top'`. | **None (No cancellations)**. | Every signal executes cleanly. |
| **Pattern Group Name** | `entry_1`, `entry_2`, `entry_3`, `entry_4` | **`epatt_1`, `epatt_2`, `epatt_3`, `epatt_4`** | Aligns with spec in [`v5updates.md`](file:///home/avijit/workSpace/Code/ta-patterns-book/DOCs/NOTEs/v5updates.md). |
| **Pattern Anchor** | Anchored to actual entry candle (which varied if delayed). | **Anchored strictly to Confirmation Candle (`pos = signal + 3`)**. | Consistent pre-entry and post-confirmation anatomical comparison across all trades. |
| **Lifecycle Timestamps** | `signal_time`, `entry_time`, `exit_time` (3 timestamps). | **`signal_time`, `confirmation_time`, `entry_time`, `exit_time`** (4 timestamps). | Full auditability of setup vs. confirmation vs. execution vs. exit. |
| **Swing Low Storage** | Evaluated in memory for SL, but **not saved** to database. | **Explicitly saved as `swing_low` column**. | Allows risk-per-candle and swing depth analysis. |
| **Pivot Columns** | Stored as `pivot`, `s1`, `r1`. | Stored as **`upper_pivot` ($R_1$), `lower_pivot` ($S_1$), and `pivot`**. | Clear semantic naming reflecting upper target and lower trigger. |
| **In-Trade Fibonacci** | `fib_bsl`, `fib_bsl_ambiguous` | **`fib_bsl`, `fib_bsl_ambiguous`** | Retained identically. |
| **Post-Trade Excursion** | Joined via view `_trades_pfib` in primary DB. | Populated directly into the isolated DB as table **`trades_pfib`** and view. | Self-contained backtest file portability. |
| **Target DuckDB** | `Shared/INPs/Ohlcv_2325Eurusd.duckdb` (Monolithic table `classic_floor_mod_v4c_trades`). | **`Shared/Data/classic_floor_mod_v5_{tf}_{symbol}.duckdb`** (Canonical `ohlcv` + `trades`). | Zero risk of collateral data corruption. |

---

## 3. Mathematical & Anatomical Definitions

### 3.1 Confirmation Sequence & Timestamps
```
Bar 0: Signal Bar (Close <= S1)
  │    signal_time = timestamp[0]
  ▼
Bar 1: Wait Candle 1
  ▼
Bar 2: Wait Candle 2
  ▼
Bar 3: Confirmation Candle (4th Candle from Signal)
       confirmation_time = timestamp[3]
       entry_time        = timestamp[3] (Entry executed at Open[3])
       entry_price       = Open[3]
```

### 3.2 Swing Low & Stop Loss Formula
- **`swing_low`**: Evaluated across bars $0..3$ inclusive:
  $$\text{swing\_low} = \min_{i \in [0, 3]} (\min(\text{open}_i, \text{close}_i))$$
- **Stop Loss (`sl_price`)**:
  $$\text{sl\_price} = \text{swing\_low} - 0.5 \times (R_1 - S_1)$$
- **Take Profit (`tp_price`)**:
  $$\text{tp\_price} = R_1 \quad (\text{frozen from setup bar } 0)$$

### 3.3 Confirmation-Anchored `epatt_*` Definitions ($pos = 3$)
- **`epatt_1`** ($pos-3, pos-2, pos-1$): 3 setup candles strictly before confirmation (Bar 0, Bar 1, Bar 2).
- **`epatt_2`** ($pos-2, pos-1, pos$): 2 setup candles before confirmation + confirmation candle (Bar 1, Bar 2, Bar 3).
- **`epatt_3`** ($pos-1, pos, pos+1$): 1 candle before confirmation + confirmation candle + 1 candle after (Bar 2, Bar 3, Bar 4).
- **`epatt_4`** ($pos, pos+1, pos+2, pos+3$): Confirmation candle + 3 candles after (Bar 3, Bar 4, Bar 5, Bar 6).

---

## 4. DuckDB Schema for `classic_floor_mod_v5`

The dedicated backtest database (`Shared/Data/classic_floor_mod_v5_{tf}_{symbol}.duckdb`) contains:

### Table: `ohlcv`
- `timestamp`: `TIMESTAMP WITH TIME ZONE PRIMARY KEY`
- `open`, `high`, `low`, `close`: `DOUBLE`
- `volume`: `DOUBLE`

### Table: `trades`
- `uid`: `BIGINT PRIMARY KEY` (integers `1..N`)
- `trade_id`: `BIGINT`
- `signal_time`: `TIMESTAMP WITH TIME ZONE`
- `confirmation_time`: `TIMESTAMP WITH TIME ZONE`
- `entry_time`: `TIMESTAMP WITH TIME ZONE`
- `exit_time`: `TIMESTAMP WITH TIME ZONE`
- `entry_price`: `DOUBLE`
- `exit_price`: `DOUBLE`
- `sl_price`: `DOUBLE`
- `tp_price`: `DOUBLE`
- `swing_low`: `DOUBLE`
- `upper_pivot`: `DOUBLE` ($R_1$)
- `lower_pivot`: `DOUBLE` ($S_1$)
- `pivot`: `DOUBLE`
- `exit_reason`: `VARCHAR` (`'TP'` or `'SL'`)
- `pnl`: `DOUBLE`
- `return_pct`: `DOUBLE`
- `holding_bars`: `BIGINT`
- `is_win`: `BOOLEAN`
- `epatt_1`, `epatt_2`, `epatt_3`, `epatt_4`: `VARCHAR`
- `fib_bsl`: `DOUBLE`
- `fib_bsl_ambiguous`: `BOOLEAN`
