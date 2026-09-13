# Strategy Column Specification & Next-Version Architecture (`v5Clmns-list.md`)

This document is the authoritative data dictionary and architecture specification covering:
1. **Current `classic_floor_mod_v5` Computed Columns** (28 unique metrics)
2. **Identified Duplicate Aliases** (6 legacy aliases)
3. **Next-Version Strategy Architecture Specification** (19 proposed enhancements)

---

## 1. Current `classic_floor_mod_v5` Computed Columns (28 Unique Metrics)

| # | Column Name | Data Type | Brief Description | Detailed Formula & Logic |
| :-: | :--- | :---: | :--- | :--- |
| 1 | `pivot` | `float` | 20-period rolling Floor Trader Pivot level | $\frac{\text{High}_{20} + \text{Low}_{20} + \text{Close}_{-1}}{3}$ (shifted 1 bar) |
| 2 | `s1` | `float` | First Floor Support line | $(2 \times \text{pivot}) - \text{High}_{20}$ |
| 3 | `r1` | `float` | First Floor Resistance line (Frozen Take Profit) | $(2 \times \text{pivot}) - \text{Low}_{20}$ |
| 4 | `entries` | `bool` | Entry signal execution flag | `True` exclusively on confirmation candle Open (Bar +3) |
| 5 | `exits` | `bool` | Exit execution flag | `True` when price high reaches `tp_price` or low breaches `sl_price` |
| 6 | `in_trade` | `bool` | Active position state | `True` for every bar while in position |
| 7 | `trade_id` | `int` | Sequential trade counter | Incremental integer assigned per executed trade (`1, 2, 3...`) |
| 8 | `entry_price` | `float` | Execution fill price | Open price of the confirmation candle (Bar +3 Open) |
| 9 | `sl_price` | `float` | Dynamic Stop Loss level | $\text{swing\_low} - 0.5 \times (R_1 - S_1)$ |
| 10 | `tp_price` | `float` | Take Profit target level | Frozen $R_1$ value captured from setup signal candle |
| 11 | `exit_price` | `float` | Trade exit execution fill price | Equals `tp_price` on win, `sl_price` on loss |
| 12 | `exit_reason` | `str` | Trade exit trigger classification | `'TP'` (Take Profit win) or `'SL'` (Stop Loss hit) |
| 13 | `realized_pnl` | `float` | Absolute trade price point gain/loss | $\text{exit\_price} - \text{entry\_price}$ |
| 14 | `realized_pnl_pct`| `float` | Percentage return on trade | $\left(\frac{\text{realized\_pnl}}{\text{entry\_price}}\right) \times 100$ |
| 15 | `is_win` | `int` | Binary outcome indicator | `1` for TP win, `-1` for SL loss, `0` otherwise |
| 16 | `signal_time` | `datetime` | Setup trigger bar timestamp | Bar 0 timestamp where condition $\text{close} \le S_1$ first triggered |
| 17 | `confirmation_time`| `datetime`| Setup confirmation bar timestamp | Bar +3 timestamp (4th candle from signal) |
| 18 | `swing_low` | `float` | Body swing low boundary | $\min(\text{open}, \text{close})$ across Bars 0..3 (Signal through Entry) |
| 19 | `fib_bsl` | `float` | Max Fibonacci ratio before SL hit | Highest ratio $(0.236, 0.382, 0.5, 0.618, 0.786)$ reached before SL hit; $0.786$ on TP |
| 20 | `fib_bsl_ambiguous`| `bool` | Same-bar Fibonacci ambiguity flag | `True` if highest Fibonacci level touch coincided with the exact SL exit bar |
| 21 | `epatt_1` | `str` | Setup pattern prior to entry | 3 setup candles strictly before entry bar: $(pos_{-3}, pos_{-2}, pos_{-1})$ |
| 22 | `epatt_2` | `str` | Setup pattern including entry bar | 2 setup candles before entry + entry bar: $(pos_{-2}, pos_{-1}, pos)$ |
| 23 | `epatt_3` | `str` | Straddle pattern around entry | 1 candle before + entry + 1 candle after: $(pos_{-1}, pos, pos_{+1})$ |
| 24 | `epatt_4` | `str` | 4-candle forward follow-through | Entry bar + 3 forward confirmation candles: $(pos, pos_{+1}, pos_{+2}, pos_{+3})$ |
| 25 | `ecpatt_1` | `str` | 1st confirmation candlestick pattern | Detected TA pattern on confirmation bar |
| 26 | `ecpatt_2` | `str` | 2nd confirmation candlestick pattern | 2nd detected TA pattern on confirmation bar |
| 27 | `ecpatt_3` | `str` | 3rd confirmation candlestick pattern | 3rd detected TA pattern on confirmation bar |
| 28 | `epcpatt_1` | `str` | 1st preceding candlestick pattern | Detected TA pattern on preceding setup bar |
| 29 | `epcpatt_2` | `str` | 2nd preceding candlestick pattern | 2nd detected TA pattern on preceding setup bar |
| 30 | `epcpatt_3` | `str` | 3rd preceding candlestick pattern | 3rd detected TA pattern on preceding setup bar |

---

## 2. Removed Duplicate Aliases in `v5` (6 Columns)

These columns exist in `classic_floor_mod_v5.py` solely as duplicate aliases of canonical columns:

| Duplicate Column | Exact Equivalent | Rationale for Removal |
| :--- | :--- | :--- |
| `upper_pivot` | `r1` | Semantic duplicate of Floor Resistance $R_1$ |
| `lower_pivot` | `s1` | Semantic duplicate of Floor Support $S_1$ |
| `entry_1` | `epatt_1` | Retained in v5 code for backwards compatibility with `loss-profile --dist entry_1` |
| `entry_2` | `epatt_2` | Retained in v5 code for backwards compatibility with `loss-profile --dist entry_2` |
| `entry_3` | `epatt_3` | Retained in v5 code for backwards compatibility with `loss-profile --dist entry_3` |
| `entry_4` | `epatt_4` | Retained in v5 code for backwards compatibility with `loss-profile --dist entry_4` |

---

## 3. Next Strategy Version Architecture Specification

The next strategy iteration establishes an engine-agnostic, multi-tier risk and telemetry framework:

### 3.1 Generalized Nomenclature
- **`upper_pivot`**: Replaces `r1`. Generalizes the upper channel boundary / target line across arbitrary algorithms (Floor Pivots, Camarilla, Keltner/Bollinger bands).
- **`lower_pivot`**: Replaces `s1`. Symmetrically generalizes the lower boundary / support setup trigger.
- **`epatt_1..4`**: Standardized as the sole canonical pattern format, deprecating `entry_1..4` to eliminate redundant database storage.

### 3.2 4-Phase Lifecycle Timestamps
Separates pattern detection, rule validation, broker execution fill, and trade termination:
- **`signal_time`** (`datetime`): Timestamp of initial trigger bar where condition is detected (Bar 0).
- **`confirmation_time`** (`datetime`): Timestamp of setup confirmation candle (Bar +3).
- **`entry_time`** (`datetime`): Exact timestamp when order fill occurs (separated to support delayed or pending limit/stop orders).
- **`exit_time`** (`datetime`): Exact timestamp when position closes (TP, SL, or session cutoff).

### 3.3 Duration & Holding Telemetry
- **`holding_bars`** (`int`): Total candles elapsed from `entry_time` to `exit_time` (standardizes `holding_bars` and `duration_candel` across `loss-profile`).
- **`holding_seconds`** (`float`): Total wall-clock duration of active trade in seconds ($\text{exit\_time} - \text{entry\_time}$).

### 3.4 Multi-Tier Stop Loss Hierarchy
Provides 3 concurrent risk models per trade to benchmark stop-loss efficiency:
- **`primary_sl`** (`float`): Aggressive stop loss price anchored directly to the Close of the setup signal candle (Bar 0 Close).
- **`pivot_sl`** (`float`): Structural stop loss price anchored to `lower_pivot` ($S_1$).
- **`safe_sl`** (`float`): Conservative dynamic stop loss set at $\text{swing\_low} - 0.5 \times (\text{upper\_pivot} - \text{lower\_pivot})$.

### 3.5 Multi-Tier Trade-Level SL Breach Telemetry
Cumulative breach flags evaluated across the entire lifecycle of each trade:
- **`primary_sl_hit`** (`bool`): `True` if price low touched or breached `primary_sl` ($\text{low} \le \text{primary\_sl}$) at any point while in trade.
- **`pivot_sl_hit`** (`bool`): `True` if price low touched or breached `pivot_sl` ($\text{low} \le \text{pivot\_sl}$) at any point while in trade.
- **`safe_sl_hit`** (`bool`): `True` if price low touched or breached `safe_sl` ($\text{low} \le \text{safe\_sl}$) at any point while in trade.

#### Analytical Diagnostic Value:
1. **Premature Stop-out Detection**:
   $$\text{primary\_sl\_hit} == \text{True} \quad \land \quad \text{safe\_sl\_hit} == \text{False} \quad \land \quad \text{is\_win} == 1$$
   Proves trades where tight stops were shaken out by market noise, whereas safe stops allowed the setup to reach Take Profit.
2. **High-Efficiency Setup Discovery**:
   $$\text{primary\_sl\_hit} == \text{False} \quad \land \quad \text{is\_win} == 1$$
   Identifies pristine setups where price never looked back. Using `primary_sl` on these setups yields significantly tighter risk and higher R-multiples.
3. **Runaway Loss Mitigation**:
   $$\text{primary\_sl\_hit} == \text{True} \quad \land \quad \text{pivot\_sl\_hit} == \text{True} \quad \land \quad \text{safe\_sl\_hit} == \text{True}$$
   Identifies catastrophic setup failures where an aggressive `primary_sl` would have preserved capital by cutting losses immediately.

### 3.6 Risk Distances, Sizing & Fees
- **`risk_primary`** (`float`): Point distance to primary SL ($\text{entry\_price} - \text{primary\_sl}$).
- **`risk_pivot`** (`float`): Point distance to structural SL ($\text{entry\_price} - \text{pivot\_sl}$).
- **`risk_safe`** (`float`): Point distance to dynamic safe SL ($\text{entry\_price} - \text{safe\_sl}$).
- **`size`** (`float`): Executed contract/unit volume.
- **`lot_size`** (`float`): Standardized FX lots (e.g., $0.01$ micro, $0.10$ mini, $1.00$ standard lot $= \text{size} / 100,000$).
- **`risk_amount`** (`float`): Monetary capital risked ($\text{risk\_distance} \times \text{size}$).
- **`entry_fees`** / **`exit_fees`** (`float`): Commission and spread transaction costs.

### 3.7 Risk:Reward & Realized Expectancy
- **`projected_rr_primary`** (`float`): Projected R:R using primary SL:
  $$\text{prr\_primary} = \frac{\text{tp\_price} - \text{entry\_price}}{\text{risk\_primary}}$$
- **`projected_rr_safe`** (`float`): Projected R:R using safe SL:
  $$\text{prr\_safe} = \frac{\text{tp\_price} - \text{entry\_price}}{\text{risk\_safe}}$$
- **`r_multiple`** (`float`): Realized return normalized by active risk distance:
  $$\text{r\_multiple} = \frac{\text{pnl}}{\text{risk\_amount}}$$
- **`pnl`** (`float`): Net realized monetary gain/loss.
- **`return_pct`** (`float`): Net percentage return on capital.

### 3.8 In-Trade Excursion Extremes
- **`mfe`** (`float`): Maximum Favorable Excursion ($\max(\text{high}_{\text{entry}..\text{exit}}) - \text{entry\_price}$). Reveals "near-miss winners" that approached TP before reversing, enabling optimal Break-Even (BE) thresholds.
- **`mae`** (`float`): Maximum Adverse Excursion ($\text{entry\_price} - \min(\text{low}_{\text{entry}..\text{exit}})$). Identifies drawdown thresholds required for winning trades.

### 3.9 Direction, Status & Market Regime
- **`direction`** (`str`): `'LONG'` or `'SHORT'`.
- **`status`** (`str`): `'CLOSED'` or `'OPEN'`.
- **`session`** (`str`): Market trading session at trade entry (`Asian`, `London`, `New York`, `London/NY Overlap`).

### 3.10 Execution Control Toggles
- **`allow_concurrent_trades`** (`bool`, default: `False`):
  - `False`: Single-position execution (suppresses new setup triggers while in an open trade).
  - `True`: Multi-position execution (allows concurrent trade entries with independent `trade_id` tracking).
- **`concurrent_trades_count`** (`int`): Bar telemetry tracking simultaneous active positions open on the current bar.
