---
title: Post-Exit 15-Candle Fibonacci Excursion Analysis (pfib_bsl) — Architectural Specification
status: approved
version: 2
type: design-record
area: analytics
tags:
  - analytics
  - fibonacci
  - post-trade
  - runner-analysis
  - duckdb
  - architectural-decisions
created: 2026-09-09
author: Antigravity Agentic Pair
related:
  - "[[features-fibs.md]]"
  - "[[features-fibs-actual.md]]"
  - "Shared/straragYs/classic_floor_mod_v4c.py"
  - "Notebooks/1Ybt.py"
---

# Post-Exit 15-Candle Fibonacci Excursion Analysis (`pfib_bsl`)

> **Notice to New Developers:** This is an authoritative, completely self-contained specification. It details the trading problem, mathematical foundations, architectural decisions, technical trade-offs, and implementation contracts for the Post-Exit Fibonacci Excursion (`pfib_bsl`) analytics system. No prior verbal or chat context is needed to understand or implement this feature.

---

## 1. System Background & Context

The `ta-patterns-book` repository develops, backtests, and profiles quantitative trading strategies on foreign exchange and cryptocurrency data (primarily **EURUSD 5-minute candles**).

### Active Strategy Architecture (`classic_floor_mod_v4c`)
- **Signal Logic**: Triggered on daily pivot floor boundaries (S1/R1, 20-period lookback).
- **Confirmation**: Delayed entry via candlestick pattern rules (3 to 6 wait candles).
- **Stop-Loss (SL)**: Dynamic swing-anchor low minus half the pivot range:
  $$\text{SL} = \text{sl\_anchor} - \frac{\text{R1} - \text{S1}}{2}$$
- **Take-Profit (TP)**: Set rigidly at the frozen R1 pivot level:
  $$\text{TP} = \text{setup\_r1}$$
- **The In-Trade Baseline (`fib_bsl`)**:
  In version `v4c`, we established internal Fibonacci tracking across the **TP–SL structural block** ($\text{SL} \leftrightarrow \text{TP}$) using ratios `0.236`, `0.382`, `0.500`, `0.618`, `0.786`. That analysis proved that **50.4% of all stopped-out trades reached $\ge 61.8\%$ of the TP–SL span before reversing into the Stop-Loss**.

---

## 2. The Problem Situation: The "Blind Spot at 1.0"

In `classic_floor_mod_v4c`, when price hits `target_price = setup_r1` (Ratio **1.0**), the strategy **immediately closes the trade as a win (`TP`)**:

```python
target_hit = cur_high >= target_price  # target_price = Ratio 1.0
if target_hit:
    exits.iloc[i] = True
    in_trade = False                   # Position is closed immediately!
```

### The Blind Spots
1. **Unquantified Opportunity Cost (Money Left on the Table)**:
   - When a trade takes profit at 1.0, does the price momentum continue driving forward into extended Fibonacci ratios (e.g. 1.5, 2.0, 3.0)?
   - If price regularly doubles its run after our exit, our strict 1.0 exit is prematurely capping portfolio returns.
2. **Exhaustion Verification**:
   - Conversely, does price violently collapse immediately after hitting 1.0? If so, taking full profit at 1.0 is mathematically optimal, and greedy trailing stops would destroy profitability.
3. **In-Trade Monitoring Limitation**:
   - Because the position terminates at 1.0, the strategy loop stops monitoring the trade. We have zero telemetry on post-exit market behavior.

---

## 3. Key Decisions & Rationales (Decision Register)

| Decision | Chosen Direction | Rejected Alternative | Core Rationale |
|---|---|---|---|
| **D1: Execution Architecture** | **Standalone Post-Analysis Engine** (Option A) | In-Strategy Forward Telemetry (Option B) | **Zero state pollution.** If Trade #1 exits at bar 100 and Trade #2 enters at bar 104, an in-strategy tracker must juggle overlapping "ghost positions". A post-analysis engine slices `ohlcv[exit+1 : exit+16]` cleanly in $<1\text{s}$, and works **retroactively across any strategy** without code edits. |
| **D2: Observation Horizon** | **Fixed 15-Candle Window** | Dynamic / Indefinite Horizon | 15 bars on 5m data = **75 minutes** (1h 15m). This captures the immediate post-breakout impulse wave. Beyond 15 candles, market drift enters new intraday regimes and news cycles unrelated to the original setup. |
| **D3: Fibonacci Scale** | **0.0 to 3.0 Extension Grid (15 Ratios)** | Legacy 0.0 to 1.0 Range | We need to measure expansion *beyond* the target (1.0). Ratios include standard Fibonacci expansion milestones up to 3.0. |
| **D4: Dual Invalidation Rules** | Track both **Stop-Loss Hit** and **Breakeven (Entry) Hit** | Tracking Stop-Loss Hit only | In real trading, if a trader lets a runner ride past 1.0, they move their stop to **Breakeven (Entry)**. Tracking both tells us if the trade would have survived a breakeven runner stop or a loose original SL stop. |

---

## 4. Mathematical Definitions & Grid

### The Frozen Leg Formula
For every closed trade in DuckDB, the structural unit span is defined at entry:
$$\text{leg\_span} = \text{TP} - \text{SL}$$

The reference price for any Fibonacci ratio $r$ is direction-agnostic:
$$\text{level\_price}(r) = \text{SL} + r \times (\text{TP} - \text{SL})$$

### The 15 Standard Fibonacci Ratios (0.0 to 3.0)
```
[0.236, 0.382, 0.500, 0.618, 0.786, 1.000, 1.236, 1.382, 1.500, 1.618, 1.786, 2.000, 2.236, 2.500, 2.618, 3.000]
```

- **Base Zone (0.0 – 1.0)**: Where entry and base TP occur.
- **Secondary Runner Zone (1.0 – 2.0)**: First extension zone (`1.236` to `2.000`).
- **Extended Trend Zone (2.0 – 3.0)**: Extreme momentum runner zone (`2.236` to `3.000`).

---

## 5. Concrete Worked Example

Consider a Long trade produced by the strategy:
- **Entry Price**: `1.1000`
- **Stop-Loss (`SL`)**: `1.0950`
- **Take-Profit (`TP` / R1)**: `1.1050`
- **Structural Leg Span**: `1.1050 - 1.0950 = 0.0100` (100 pips)

### Computed Price Levels:
| Ratio ($r$) | Level Price Calculation | Level Price |
| :---: | :--- | :---: |
| `1.000` | $1.0950 + 1.000 \times 0.0100$ | `1.1050` *(Exit price)* |
| `1.236` | $1.0950 + 1.236 \times 0.0100$ | `1.10736` |
| `1.500` | $1.0950 + 1.500 \times 0.0100$ | `1.11000` |
| `1.618` | $1.0950 + 1.618 \times 0.0100$ | `1.11118` |
| `2.000` | $1.0950 + 2.000 \times 0.0100$ | `1.11500` |
| `2.618` | $1.0950 + 2.618 \times 0.0100$ | `1.12118` |
| `3.000` | $1.0950 + 3.000 \times 0.0100$ | `1.12500` |

### 15-Candle Post-Exit Forward Scan:
1. The trade hits `1.1050` at candle index $k = 42$ and closes.
2. The engine slices candles $k \in [43, 57]$ (15 candles).
3. On candle 45, `High = 1.1120` (touching `1.618` level).
4. On candle 48, `Low = 1.0990` (crosses below `Entry = 1.1000` $\rightarrow$ `pfib_be_hit = True`).
5. On candle 55, `Low = 1.0945` (crosses below `SL = 1.0950` $\rightarrow$ `pfib_sl_hit = True`).
6. **Result Recorded**:
   - `pfib_bsl = 1.618` (deepest ratio reached before SL hit).
   - `pfib_candles = 3` (occurred 3 candles after exit).
   - `pfib_be_hit = True`
   - `pfib_sl_hit = True`

---

## 6. DuckDB Schema & Output Columns

The post-trade analysis enriches `{strategy}_trades` table/view with 4 dedicated columns:

| Column Name | DuckDB Type | Description |
|---|---|---|
| `pfib_bsl` | `DOUBLE` | Deepest Fibonacci ratio (up to 3.0) reached in the 15 forward candles before hitting Stop-Loss. |
| `pfib_candles` | `INTEGER` | Candle offset from exit ($1 \dots 15$) where `pfib_bsl` occurred. |
| `pfib_be_hit` | `BOOLEAN` | `True` if price dropped below original entry price within the 15 candles. |
| `pfib_sl_hit` | `BOOLEAN` | `True` if price dropped below original Stop-Loss within the 15 candles. |

---

## 7. Actionable Decision Framework for Strategy Evolution

| Metric Finding from 1-Year Backtest | Quantitative Meaning | Implementation Next Step |
|---|---|---|
| **$\ge 35\%$ of TP trades reach `pfib_bsl >= 1.618` before Breakeven** | Major post-exit runner momentum exists. | **Implement v5 Scale-Out**: Bank 50% at 1.0, move SL to breakeven, and let remaining 50% target 1.618 or 2.0. |
| **$\ge 75\%$ of TP trades fail to reach `1.236` before dropping below Entry** | R1 is an exact local exhaustion ceiling. | **Retain 1.0 Full Exit**: Mathematically proves that letting trades run destroys equity. |
| **Peak `pfib_candles` clusters at candles 2 to 4** | Overextensions happen immediately after breakout. | **Short Time-Cap Trail**: Use a 4-candle trailing deadline for runners. |

---

## 8. CLI Command Integration
Once the module is deployed, developers and analysts can inspect post-exit behavior directly via `loss-profile`:

```bash
# View runner distribution across winning trades
uv run loss-profile --primary --view classic_floor_mod_v4c_trades --dist pfib_bsl --wins-only

# Dump full markdown report to Shared/OUTs/
uv run loss-profile --primary --view classic_floor_mod_v4c_trades --dist pfib_bsl -o md --dump
```
