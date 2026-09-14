# Strategy Changelog: ClassicFloorMod v6.0 → ClassicFloorMod v6.1

**Document Version:** 1.0.0  
**Date:** 2026-09-14  
**Strategy Version:** `6.1.0` (`classic_floor_mod_v6_1`)  
**Reference Notes:** [`DOCs/NOTEs/classic_floor_v6/v6.1.txt`](file:///home/avijit/workSpace/Code/ta-patterns-book/DOCs/NOTEs/classic_floor_v6/v6.1.txt)

---

## 1. Executive Summary & Core Philosophy

`ClassicFloorModV6_1` introduces two key architectural enhancements to the pure canonical `v6` baseline:

1. **Dynamic Stop-Loss Adaptation on Sub-1.0 R:R (`projected_rr_safe < 1.0`)**:
   - In `v6.0`, every trade unconditionally executes with `safe_sl` as the operational stop loss, regardless of target distance. When price enters relatively close to `upper_pivot`, `projected_rr_safe` can fall below 1.0, creating negative-expectancy risk asymmetry.
   - `v6.1` dynamically adapts at execution (Bar +3 Open): if `projected_rr_safe < 1.0`, the operational stop loss is automatically tightened to **`pivot_sl`** (structural `lower_pivot` support level), risk distance updates to `risk_pivot`, and position sizing rescales to `risk_per_trade / risk_pivot`.
   - Trades with `projected_rr_safe >= 1.0` remain on `safe_sl`.

2. **Full Temporal Auditability for Stop Loss Breaches (`*_sl_hit_timestamp`)**:
   - `v6.0` recorded only boolean flags (`primary_sl_hit`, `pivot_sl_hit`, `safe_sl_hit`, `pfib15_sl_hit`, etc.).
   - `v6.1` introduces precise first-touch timestamp tracking for every stop loss breach level across both in-trade holding and post-trade forward excursion horizons:
     - `primary_sl_hit_timestamp`
     - `pivot_sl_hit_timestamp`
     - `safe_sl_hit_timestamp`
     - `pfib15_sl_hit_timestamp`
     - `pfib30_sl_hit_timestamp`
     - `pfib60_sl_hit_timestamp`

---

## 2. Detailed Feature Comparison: v6.0 vs. v6.1

| Feature / Metric | `classic_floor_mod_v6` (v6.0) | `classic_floor_mod_v6_1` (v6.1) | Rationale |
| :--- | :--- | :--- | :--- |
| **Operational Stop Loss** | Hardcoded to `safe_sl` for all trades. | **Dynamic**: `pivot_sl` if `projected_rr_safe < 1.0`, else `safe_sl`. | Eliminates sub-1.0 R:R asymmetry by tightening stop to structural support when target is compressed. |
| **Active Risk Basis** | Always `risk_safe`. | **`risk_pivot`** when adapted; **`risk_safe`** otherwise. | Maintains constant monetary risk budget (`risk_per_trade`) regardless of SL choice. |
| **Position Sizing** | `risk_per_trade / risk_safe`. | `risk_per_trade / active_risk`. | Ensures correct lot sizing when tightened to `pivot_sl`. |
| **In-Trade SL Breach Telemetry** | Boolean flags only (`primary_sl_hit`, `pivot_sl_hit`, `safe_sl_hit`). | Boolean flags **plus exact first-touch timestamps** (`*_sl_hit_timestamp`). | Enables time-to-breach analysis, intrabar hazard timing, and survival curve estimation. |
| **Post-Trade SL Excursion Telemetry** | Boolean flags (`pfib15_sl_hit`, `pfib30_sl_hit`, `pfib60_sl_hit`). | Boolean flags **plus post-exit first-touch timestamps** (`pfib*_sl_hit_timestamp`). | Unlocks exact forward candle timing for when runners would have been stopped out post-exit. |
| **Geometry Preservation** | Stored `pivot`, `lower_pivot`, `upper_pivot`, `safe_sl`, `pivot_sl`, `primary_sl`. | Stored identically, with additional `sl_mode` (`'SAFE'` or `'PIVOT'`). | 100% backward-compatible geometric reference data. |

---

## 3. Mathematical & Algorithmic Rules

### 3.1 Dynamic SL Selection Algorithm
```
At Bar i = Entry Bar (Confirmation Bar Open):
1. Compute setup levels:
   setup_upper = upper_pivot[orig_signal_bar]
   setup_lower = lower_pivot[orig_signal_bar]
   swing_low   = min(body_low[orig_signal_bar : entry_bar])
   safe_sl     = swing_low - 0.5 * (setup_upper - setup_lower)
   pivot_sl    = setup_lower
   primary_sl  = close[orig_signal_bar]

2. Compute risk distances:
   risk_safe    = max(entry_price - safe_sl, 1e-6)
   risk_pivot   = max(entry_price - pivot_sl, 1e-6)
   risk_primary = max(entry_price - primary_sl, 1e-6)

3. Evaluate Projected R:R:
   projected_rr_safe = (setup_upper - entry_price) / risk_safe

4. Dynamic Adaptation Branch:
   IF projected_rr_safe < 1.0:
       active_sl   = pivot_sl
       active_risk = risk_pivot
       sl_mode     = 'PIVOT'
   ELSE:
       active_sl   = safe_sl
       active_risk = risk_safe
       sl_mode     = 'SAFE'

5. Scale Position:
   size        = risk_per_trade / active_risk
   lot_size    = size / 100000.0
   risk_amount = active_risk * size
```

### 3.2 In-Trade Exit Trigger
```
For each bar while in trade:
  target_hit = High >= tp_price
  stop_hit   = Low <= active_sl

  IF target_hit OR stop_hit:
      exit_price = tp_price IF target_hit ELSE active_sl
      Close trade and compute pnl, r_multiple, holding_bars, holding_seconds.
```

### 3.3 SL Hit Timestamp Latching
```
For each bar i while in trade:
  IF Low <= primary_sl AND primary_sl_hit_timestamp IS NULL:
      primary_sl_hit           = True
      primary_sl_hit_timestamp = timestamp[i]

  IF Low <= pivot_sl AND pivot_sl_hit_timestamp IS NULL:
      pivot_sl_hit           = True
      pivot_sl_hit_timestamp = timestamp[i]

  IF Low <= safe_sl AND safe_sl_hit_timestamp IS NULL:
      safe_sl_hit           = True
      safe_sl_hit_timestamp = timestamp[i]
```

### 3.4 Post-Trade pfib SL Timestamp Latching
```
For forward bar k in 1..forward_len:
  IF Low[exit_bar + k] <= safe_sl + 1e-7:
      first_sl_hit_ts = timestamp[exit_bar + k]
      Assign first_sl_hit_ts to pfib15/30/60_sl_hit_timestamp for all pending horizons.
```

---

## 4. Canonical Column Additions in v6.1

The following 7 canonical columns are added in `v6.1`:

| Column Name | Type | Description |
| :--- | :---: | :--- |
| **`sl_mode`** | `str` | Active SL operational mode (`'SAFE'` or `'PIVOT'`). |
| **`primary_sl_hit_timestamp`** | `timestamp` | First timestamp when price Low touched or breached `primary_sl`. |
| **`pivot_sl_hit_timestamp`** | `timestamp` | First timestamp when price Low touched or breached `pivot_sl`. |
| **`safe_sl_hit_timestamp`** | `timestamp` | First timestamp when price Low touched or breached `safe_sl`. |
| **`pfib15_sl_hit_timestamp`** | `timestamp` | First timestamp when post-exit price touched `safe_sl` within 15 bars. |
| **`pfib30_sl_hit_timestamp`** | `timestamp` | First timestamp when post-exit price touched `safe_sl` within 30 bars. |
| **`pfib60_sl_hit_timestamp`** | `timestamp` | First timestamp when post-exit price touched `safe_sl` within 60 bars. |
