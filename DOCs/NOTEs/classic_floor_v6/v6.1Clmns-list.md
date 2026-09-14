# ClassicFloorModV6 — Pure Canonical Column Specification (`v6Clmns-list.md`)

This document is the authoritative data dictionary and architecture specification for **`classic_floor_mod_v6`**, incorporating multi-tier stop losses, 4-phase timestamps, duration, MFE/MAE excursions, concurrent trade execution, and **strategy-level post-trade Fibonacci runner excursions (`pfib15`, `pfib30`, `pfib60`)**.

> [!NOTE]
> **Strictly Canonical Schema**: All 8 legacy duplicate aliases (`r1`, `s1`, `sl_price`, `projected_rr`, `entry_1..4`) have been completely purged from `v6`. Every column represents a unique, distinct metric.

---

## 1. Summary Overview (v6 Pure Canonical Columns)

| Category | Count | Canonical Columns Included |
| :--- | :---: | :--- |
| **Trade Identification & Metadata** | 10 | `uid`, `trade_id`, `vbt_trade_id`, `fingerprint`, `strategy_name`, `symbol`, `timeframe`, `direction`, `status`, `session` |
| **4-Phase Lifecycle Timestamps** | 4 | `signal_time`, `confirmation_time`, `entry_time`, `exit_time` |
| **Execution & Order Levels** | 4 | `entry_price`, `exit_price`, `tp_price`, `swing_low` |
| **Pivot & Channel Geometry** | 3 | `pivot`, `lower_pivot`, `upper_pivot` |
| **Multi-Tier Stop Loss Hierarchy** | 3 | `primary_sl`, `pivot_sl`, `safe_sl` |
| **Multi-Tier In-Trade SL Breaches** | 3 | `primary_sl_hit`, `pivot_sl_hit`, `safe_sl_hit` |
| **Risk Distances, Sizing & Fees** | 8 | `risk_primary`, `risk_pivot`, `risk_safe`, `size`, `lot_size`, `risk_amount`, `entry_fees`, `exit_fees` |
| **Risk:Reward & Realized Expectancy** | 8 | `projected_rr_safe`, `projected_rr_primary`, `r_multiple`, `pnl`, `realized_pnl`, `return_pct`, `realized_pnl_pct`, `is_win`, `exit_reason` |
| **Duration & Holding Telemetry** | 2 | `holding_bars`, `holding_seconds` |
| **In-Trade Excursions (MFE/MAE/BSL)** | 4 | `mfe`, `mae`, `fib_bsl`, `fib_bsl_ambiguous` |
| **Strategy-Level Post-Trade pfib** *(New in v6)* | **9** | **`pfib15_bsl`**, **`pfib15_be_hit`**, **`pfib15_sl_hit`**, **`pfib30_bsl`**, **`pfib30_be_hit`**, **`pfib30_sl_hit`**, **`pfib60_bsl`**, **`pfib60_be_hit`**, **`pfib60_sl_hit`** |
| **Execution Controls & Multi-Trade** | 2 | `allow_concurrent_trades`, `concurrent_trades_count` |
| **3-Candle State Patterns** | 4 | `epatt_1`, `epatt_2`, `epatt_3`, `epatt_4` |
| **TA Candlestick Classifications** | 6 | `ecpatt_1..3`, `epcpatt_1..3` |
| **Total Pure Canonical Metrics** | **69** | **100% distinct, zero aliases, zero duplicates** |

---

## 2. Removed Legacy Aliases (Purged in `v6`)

| Removed Legacy Column | Canonical Replacement | Reason for Removal |
| :--- | :--- | :--- |
| **`r1`** | `upper_pivot` | Redundant duplicate of generalized upper channel / resistance level. |
| **`s1`** | `lower_pivot` | Redundant duplicate of generalized lower channel / support level. |
| **`sl_price`** | `safe_sl` | Redundant duplicate of dynamic safe stop-loss. |
| **`projected_rr`** | `projected_rr_safe` | Redundant duplicate of dynamic safe Risk:Reward ratio. |
| **`entry_1`** | `epatt_1` | Redundant duplicate of 3-candle setup state pattern (`pos-3, pos-2, pos-1`). |
| **`entry_2`** | `epatt_2` | Redundant duplicate of 2 setup + entry candle pattern (`pos-2, pos-1, pos`). |
| **`entry_3`** | `epatt_3` | Redundant duplicate of straddle pattern (`pos-1, pos, pos+1`). |
| **`entry_4`** | `epatt_4` | Redundant duplicate of 4-candle forward follow-through pattern. |

---

## 3. Integrated Strategy-Level Post-Trade Fibonacci Excursions (New in `v6`)

Rather than requiring an external post-processing step (`post-trade-analysis` CLI), **`classic_floor_mod_v6`** natively computes post-exit runner excursions across 3 forward horizons upon trade termination:

### 3.1 The 9 Strategy-Level `pfib` Columns

| Column Name | Data Type | Horizon | Evaluated Window | Description & Invalidation Logic |
| :--- | :---: | :---: | :---: | :--- |
| **`pfib15_bsl`** | `float` | 15 bars | Exit + 1..15 bars | Highest Fibonacci extension ratio reached ($0.236$ to $3.000$) before touching Breakeven or Stop-Loss. |
| **`pfib15_be_hit`**| `bool` | 15 bars | Exit + 1..15 bars | `True` if forward price Low touches or crosses trade `entry_price` (Breakeven level) within 15 bars post-exit. |
| **`pfib15_sl_hit`**| `bool` | 15 bars | Exit + 1..15 bars | `True` if forward price Low touches or breaches trade `safe_sl` level within 15 bars post-exit. |
| **`pfib30_bsl`** | `float` | 30 bars | Exit + 1..30 bars | Highest Fibonacci extension ratio reached before touching BE or SL within 30 bars post-exit. |
| **`pfib30_be_hit`**| `bool` | 30 bars | Exit + 1..30 bars | `True` if forward price touches `entry_price` (Breakeven) within 30 bars post-exit. |
| **`pfib30_sl_hit`**| `bool` | 30 bars | Exit + 1..30 bars | `True` if forward price touches `safe_sl` within 30 bars post-exit. |
| **`pfib60_bsl`** | `float` | 60 bars | Exit + 1..60 bars | Highest Fibonacci extension ratio reached before touching BE or SL within 60 bars post-exit. |
| **`pfib60_be_hit`**| `bool` | 60 bars | Exit + 1..60 bars | `True` if forward price touches `entry_price` (Breakeven) within 60 bars post-exit. |
| **`pfib60_sl_hit`**| `bool` | 60 bars | Exit + 1..60 bars | `True` if forward price touches `safe_sl` within 60 bars post-exit. |

---

## 4. Detailed Pure Canonical Data Dictionary

### 4.1 Trade Identification & 4-Phase Timestamps (14 Columns)
- **`uid`** (`bigint`): Unique primary key integer assigned sequentially (`1..N`).
- **`trade_id`** (`bigint`): Strategy sequential trade counter.
- **`vbt_trade_id`** (`bigint`): VectorBT backtest engine trade index.
- **`fingerprint`** (`str`): SHA-256 parameter hash.
- **`strategy_name`** (`str`): `'classic_floor_mod_v6'`.
- **`symbol`** (`str`): Market ticker (e.g., `'EURUSD'`).
- **`timeframe`** (`str`): Execution resolution (e.g., `'5m'`).
- **`direction`** (`str`): Position side (`'LONG'`).
- **`status`** (`str`): Position lifecycle state (`'CLOSED'` or `'OPEN'`).
- **`session`** (`str`): Market trading session at trade entry (`Asian`, `London`, `New York`, `London/NY Overlap`).
- **`signal_time`** (`datetime`): Timestamp of initial trigger bar where condition $\text{Close} \le \text{lower\_pivot}$ first occurs (Bar 0).
- **`confirmation_time`** (`datetime`): Timestamp of setup confirmation candle (Bar +3 Open).
- **`entry_time`** (`datetime`): Exact order fill timestamp.
- **`exit_time`** (`datetime`): Exact order exit timestamp.

### 4.2 Levels, Hierarchy & SL Breach Telemetry (13 Columns)
- **`pivot`** (`float`): 20-period rolling Floor Pivot level shifted by 1 bar.
- **`lower_pivot`** (`float`): Support boundary ($S_1 = 2 \times \text{pivot} - \text{High}_{20}$).
- **`upper_pivot`** (`float`): Target boundary ($R_1 = 2 \times \text{pivot} - \text{Low}_{20}$).
- **`entry_price`** (`float`): Execution fill price (confirmation candle Open).
- **`exit_price`** (`float`): Fill price at trade termination (`tp_price` on win, `safe_sl` on loss).
- **`tp_price`** (`float`): Take profit target frozen at `upper_pivot`.
- **`swing_low`** (`float`): Lowest candle body low ($\min(\text{open}, \text{close})$) across Bars 0..3.
- **`primary_sl`** (`float`): Aggressive stop loss price anchored directly to setup signal candle Close (Bar 0 Close).
- **`pivot_sl`** (`float`): Structural stop loss price anchored to `lower_pivot` ($S_1$).
- **`safe_sl`** (`float`): Conservative dynamic stop loss: $\text{swing\_low} - 0.5 \times (\text{upper\_pivot} - \text{lower\_pivot})$.
- **`primary_sl_hit`** (`bool`): `True` if price Low touched or breached `primary_sl` ($\text{low} \le \text{primary\_sl}$) while in trade.
- **`pivot_sl_hit`** (`bool`): `True` if price Low touched or breached `pivot_sl` ($\text{low} \le \text{pivot\_sl}$) while in trade.
- **`safe_sl_hit`** (`bool`): `True` if price Low touched or breached `safe_sl` ($\text{low} \le \text{safe\_sl}$) while in trade.

### 4.3 Risk, Sizing, Fees & Expectancy (17 Columns)
- **`risk_primary`** (`float`): $\text{entry\_price} - \text{primary\_sl}$.
- **`risk_pivot`** (`float`): $\text{entry\_price} - \text{pivot\_sl}$.
- **`risk_safe`** (`float`): $\text{entry\_price} - \text{safe\_sl}$.
- **`size`** (`float`): Dynamic unit volume ($\text{risk\_per\_trade} / \text{risk\_safe}$).
- **`lot_size`** (`float`): Standard forex lots ($\text{size} / 100,000$).
- **`risk_amount`** (`float`): Total monetary risk in currency units ($\text{risk\_safe} \times \text{size}$).
- **`entry_fees`**, **`exit_fees`** (`float`): Commissions and transaction spread costs.
- **`projected_rr_primary`** (`float`): $\frac{\text{tp\_price} - \text{entry\_price}}{\text{risk\_primary}}$.
- **`projected_rr_safe`** (`float`): $\frac{\text{tp\_price} - \text{entry\_price}}{\text{risk\_safe}}$.
- **`r_multiple`** (`float`): Realized normalized return ($\text{pnl} / \text{risk\_amount}$).
- **`pnl`** (`float`): Net realized monetary profit/loss ($).
- **`realized_pnl`** (`float`): Absolute point gain/loss ($\text{exit\_price} - \text{entry\_price}$).
- **`return_pct`** (`float`): Net percentage return as decimal fraction.
- **`realized_pnl_pct`** (`float`): Percentage return on trade ($\text{return\_pct} \times 100$).
- **`is_win`** (`int`): `1` for TP win, `-1` for SL loss.
- **`exit_reason`** (`str`): `'TP'` or `'SL'`.

### 4.4 Duration & Excursion Extremes (6 Columns)
- **`holding_bars`** (`int`): Candle count between `entry_time` and `exit_time`.
- **`holding_seconds`** (`float`): Wall-clock elapsed duration in seconds.
- **`mfe`** (`float`): Maximum Favorable Excursion ($\max(\text{high}) - \text{entry\_price}$).
- **`mae`** (`float`): Maximum Adverse Excursion ($\text{entry\_price} - \min(\text{low})$).
- **`fib_bsl`** (`float`): Highest in-trade Fibonacci ratio reached before SL ($0.236..0.786$).
- **`fib_bsl_ambiguous`** (`bool`): `True` if in-trade highest touch coincided with exit bar.

### 4.5 Execution Controls (2 Columns)
- **`allow_concurrent_trades`** (`bool`, default: `False`): Permits or suppresses overlapping position entries.
- **`concurrent_trades_count`** (`int`): Simultaneous active trade count on current candle.

### 4.6 Candle Patterns & Classifications (10 Columns)
- **`epatt_1..4`** (`str`): Canonical 3-candle setup states (`epatt_1..3`) and follow-through (`epatt_4`).
- **`ecpatt_1..3`** (`str`): 1st, 2nd, and 3rd confirmation candlestick pattern names.
- **`epcpatt_1..3`** (`str`): 1st, 2nd, and 3rd preceding setup candlestick pattern names.
