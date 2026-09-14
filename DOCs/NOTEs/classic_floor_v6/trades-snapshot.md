# Strategy Backtest & Trade Diagnostics Snapshot

**Document Generated:** `2026-09-14 11:55:55 UTC`  
**Target Database:** [`classic_floor_mod_v6_1.duckdb`](file:///home/avijit/workSpace/Code/ta-patterns-book/Shared/OUTs/duckdb/classic_floor_mod_v6_1.duckdb)  
**Strategy:** `classic_floor_mod_v6_1`  
**Evaluated Period:** `2025-01-02 to 2025-12-31`  

---

## 1. Executive Performance Comparison (Concurrent: FALSE vs Concurrent: TRUE)

| Performance Metric | Concurrent: `FALSE` (Single Position) | Concurrent: `TRUE` (Overlapping Positions) | Variance (True - False) |
| :--- | :---: | :---: | :---: |
| **Total Executed Trades** | **585** | **720** | `+135` |
| **Overall Win Rate** | **36.9%** | **37.4%** | `+0.4%` |
| **Net Realized PnL** | **+107,224.21 pts** | **+109,019.37 pts** | `+1,795.16 pts` |
| **Profit Factor** | **3.93** | **3.43** | `-0.50` |
| **Average Trade PnL** | **+183.29 pts** | **+151.42 pts** | `-31.87 pts` |
| **Average Win / Average Loss** | `665.8 / 99.1` | `571.7 / 99.3` | — |
| **Payoff Ratio (W/L)** | **6.72** | **5.76** | `-0.96` |
| **Max Drawdown (Points)** | **2,322.8 pts** | **2,419.5 pts** | `+96.6 pts` |
| **Max Consecutive Losses** | **12** | **13** | `+1` |
| **Avg Holding Duration** | **22.9 bars** | **23.2 bars** | `+0.3 bars` |
| **Long Trades (Win Rate)** | 585 (36.9%) | 720 (37.4%) | — |
| **Short Trades (Win Rate)** | 0 (0.0%) | 0 (0.0%) | — |

---

## 2. Monthly Performance Breakdown (`Concurrent: TRUE`)

| Month | Trades | Wins | Losses | Win Rate % | Net Realized PnL (pts) | Profit Factor |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2025-01** | 64 | 23 | 41 | **35.9%** | +26,973.4 | 7.58 |
| **2025-02** | 48 | 16 | 32 | **33.3%** | +38,467.3 | 13.02 |
| **2025-03** | 58 | 22 | 36 | **37.9%** | +496.0 | 1.14 |
| **2025-04** | 58 | 18 | 40 | **31.0%** | +63.3 | 1.02 |
| **2025-05** | 55 | 22 | 33 | **40.0%** | +1,153.2 | 1.36 |
| **2025-06** | 41 | 15 | 26 | **36.6%** | -4.5 | 1.00 |
| **2025-07** | 81 | 26 | 55 | **32.1%** | -221.4 | 0.96 |
| **2025-08** | 59 | 17 | 42 | **28.8%** | +15,307.5 | 4.71 |
| **2025-09** | 67 | 28 | 39 | **41.8%** | +20,347.6 | 6.22 |
| **2025-10** | 61 | 25 | 36 | **41.0%** | +872.6 | 1.24 |
| **2025-11** | 67 | 33 | 34 | **49.3%** | +3,706.2 | 2.11 |
| **2025-12** | 61 | 24 | 37 | **39.3%** | +1,858.4 | 1.50 |

---

## 3. Dynamic Stop-Loss Architecture & Breach Diagnostics

### 3.1 SL Switching Mode (`sl_mode`: `PIVOT` vs `SAFE`)

| SL Mode | Trade Count | Share % | Win Rate % | Realized PnL (pts) | Avg Trade PnL |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **`PIVOT`** | 136 | 23.2% | **38.2%** | +101,450.3 | +745.96 |
| **`SAFE`** | 449 | 76.8% | **36.5%** | +5,773.9 | +12.86 |

### 3.2 First-Touch Breach Frequency

| Breach Signal Column | Breached Trades Count | Breach Frequency % | Description |
| :--- | :---: | :---: | :--- |
| **`base_sl_hit_timestamp`** | 0 | 0.0% | First-touch breach of baseline swing SL |
| **`be_hit_timestamp`** | 0 | 0.0% | First-touch breach of Break-Even level |
| **`pivot_sl_hit_timestamp`** | 516 | 88.2% | First-touch breach of tight pivot SL |
| **`primary_sl_hit_timestamp`** | 464 | 79.3% | First-touch breach of active execution SL (`safe` or `pivot`) |
| **`safe_sl_hit_timestamp`** | 288 | 49.2% | First-touch breach of safe structural SL |

---

## 4. 3-Candle Setup Pattern Distribution (`epatt_1`)

| Setup Pattern | Total Trades | Wins | Losses | Win Rate % | Realized PnL (pts) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **`DR-UG-DR`** | 148 | 53 | 95 | **35.8%** | +22,851.5 |
| **`DR-UG-UG`** | 146 | 61 | 85 | **41.8%** | +52,566.6 |
| **`DR-DR-DR`** | 123 | 38 | 85 | **30.9%** | +28,953.4 |
| **`DR-DR-UG`** | 121 | 44 | 77 | **36.4%** | +1,139.2 |
| **`DR-UR-UG`** | 10 | 3 | 7 | **30.0%** | -131.1 |
| **`DR-UG-UR`** | 8 | 5 | 3 | **62.5%** | +305.3 |
| **`DR-UR-DR`** | 7 | 3 | 4 | **42.9%** | +358.0 |
| **`DR-DR-UR`** | 6 | 3 | 3 | **50.0%** | +572.6 |
| **`DR-UG-DG`** | 6 | 4 | 2 | **66.7%** | +640.3 |
| **`DR-DG-UG`** | 4 | 0 | 4 | **0.0%** | -400.0 |
| **`DG-DR-DR`** | 1 | 1 | 0 | **100.0%** | +527.0 |
| **`DG-DR-UG`** | 1 | 0 | 1 | **0.0%** | -100.0 |

---

## 5. DuckDB Database Relations Profiling (`classic_floor_mod_v6_1.duckdb`)

| # | Table / View Name | Row Count | Column Count | Relation Purpose |
| :---: | :--- | :---: | :---: | :--- |
| 1 | **`candel_patters_5m`** | 76,403 | 11 | 62-pattern Technical Analysis reference table / view |
| 2 | **`candel_patters_tf`** | 76,403 | 11 | 62-pattern Technical Analysis reference table / view |
| 3 | **`drawdown_events`** | 69 | 11 | Peak-to-trough drawdown episodes and recovery metrics |
| 4 | **`equity_curve`** | 152,806 | 6 | Continuous bar-by-bar portfolio value and drawdown timeseries |
| 5 | **`monthly_performance`** | 24 | 12 | Aggregated month-by-month performance records |
| 6 | **`ohlcv`** | 76,403 | 6 | Resampled market OHLCV price history |
| 7 | **`portfolio_metrics`** | 2 | 24 | Overall portfolio risk and performance metrics |
| 8 | **`sl_risk_summary`** | 4 | 9 | Dynamic SL architecture risk distribution (v6.1) |
| 9 | **`trades_concurrent_false`** | 585 | 79 | Single active position trade simulations & telemetry |
| 10 | **`trades_concurrent_true`** | 720 | 79 | Overlapping / concurrent trade simulations & telemetry |
