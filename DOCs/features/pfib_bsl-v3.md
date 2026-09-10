---
title: Post-Exit 15-Candle Fibonacci Excursion Analysis (pfib_bsl) — Architectural Specification
status: approved
version: 3
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
updated: 2026-09-09
author: Antigravity Agentic Pair
changelog:
  - "v3: Added direction-agnostic (long/short) logic + short-side worked example,
     statistical validation methodology, data-quality/edge-case handling (partial
     windows, session gaps), schema/idempotency contract, look-ahead guardrail,
     cost-model caveat on v5 proposal, and a minimal testing strategy. Superseded v2."
  - "v2: Original standalone post-analysis engine spec."
related:
  - "[[features-fibs.md]]"
  - "[[features-fibs-actual.md]]"
  - "Shared/straragYs/classic_floor_mod_v4c.py"
  - "Notebooks/1Ybt.py"
---

# Post-Exit 15-Candle Fibonacci Excursion Analysis (`pfib_bsl`)

> **Notice to New Developers:** This is an authoritative, completely self-contained
> specification. It details the trading problem, mathematical foundations,
> architectural decisions, technical trade-offs, data-quality rules, and
> implementation contracts for the Post-Exit Fibonacci Excursion (`pfib_bsl`)
> analytics system. No prior verbal or chat context is needed to understand or
> implement this feature. **This is v3, which supersedes v2** — see the
> changelog above for what changed and why.

---

## 1. System Background & Context

The `ta-patterns-book` repository develops, backtests, and profiles quantitative
trading strategies on foreign exchange and cryptocurrency data (primarily
**EURUSD 5-minute candles**).

### Active Strategy Architecture (`classic_floor_mod_v4c`)
- **Signal Logic**: Triggered on daily pivot floor boundaries (S1/R1, 20-period
  lookback). The strategy trades **both directions** — longs off S1, shorts off
  R1 — which matters for Section 4 below.
- **Confirmation**: Delayed entry via candlestick pattern rules (3 to 6 wait
  candles).
- **Stop-Loss (SL)**: Dynamic swing-anchor low/high minus/plus half the pivot
  range:
  $$\text{SL}_{\text{long}} = \text{sl\_anchor} - \frac{\text{R1} - \text{S1}}{2}
  \qquad
  \text{SL}_{\text{short}} = \text{sl\_anchor} + \frac{\text{R1} - \text{S1}}{2}$$
- **Take-Profit (TP)**: Set rigidly at the frozen opposing pivot level
  (`R1` for longs, `S1` for shorts):
  $$\text{TP} = \text{setup\_r1} \text{ (long)} \quad / \quad \text{TP} =
  \text{setup\_s1} \text{ (short)}$$
- **The In-Trade Baseline (`fib_bsl`)**:
  In version `v4c`, we established internal Fibonacci tracking across the
  **TP–SL structural block** using ratios `0.236`, `0.382`, `0.500`, `0.618`,
  `0.786`. That analysis proved that **50.4% of all stopped-out trades reached
  ≥ 61.8% of the TP–SL span before reversing into the Stop-Loss**
  (n = *[TODO: insert sample size from that study]*, single-window result —
  see Section 8 for why this caveat now matters going forward).

  `pfib_bsl` **extends this same 0.0–1.0 baseline forward past the exit point**
  rather than duplicating it — see Section 4.1 on this de-duplication decision.

---

## 2. The Problem Situation: The "Blind Spot at 1.0"

In `classic_floor_mod_v4c`, when price hits `target_price = setup_r1` (Ratio
**1.0**) on a long trade, the strategy **immediately closes the trade as a
win (`TP`)**:

```python
target_hit = cur_high >= target_price  # long: target_price = Ratio 1.0
if target_hit:
    exits.iloc[i] = True
    in_trade = False                   # Position is closed immediately!
```

(The short-side equivalent checks `cur_low <= target_price`; see Section 4.2.)

### The Blind Spots
1. **Unquantified Opportunity Cost (Money Left on the Table)**: does price
   momentum continue driving forward into extended Fibonacci ratios
   (e.g. 1.5, 2.0, 3.0) after our exit?
2. **Exhaustion Verification**: does price violently collapse immediately
   after hitting 1.0? If so, a strict full-exit at 1.0 may already be optimal.
3. **In-Trade Monitoring Limitation**: because the position terminates at
   1.0, the strategy loop stops monitoring the trade — zero telemetry on
   post-exit market behavior.

> **Non-goal / guardrail:** `pfib_bsl` and its sibling columns are a
> **strictly retrospective, post-hoc research signal**. They must never be
> read by, or wired into, any live or backtested entry/exit decision. Because
> the window is computed using candles *after* the trade has already closed,
> any live use would be look-ahead bias by construction. Any future PR that
> references `pfib_*` columns from within strategy signal code should be
> rejected in review on that basis alone.

---

## 3. Key Decisions & Rationales (Decision Register)

| Decision | Chosen Direction | Rejected Alternative | Core Rationale |
|---|---|---|---|
| **D1: Execution Architecture** | **Standalone Post-Analysis Engine** (Option A) | In-Strategy Forward Telemetry (Option B) | **Zero state pollution.** If Trade #1 exits at bar 100 and Trade #2 enters at bar 104, an in-strategy tracker must juggle overlapping "ghost positions". A post-analysis engine slices `ohlcv[exit+1 : exit+16]` cleanly and works **retroactively across any strategy** without code edits. |
| **D2: Observation Horizon** | **Fixed 15-Candle Window** | Dynamic / Indefinite Horizon | 15 bars on 5m data = **75 minutes** (1h 15m). This captures the immediate post-breakout impulse wave. Beyond 15 candles, market drift enters new intraday regimes and news cycles unrelated to the original setup. |
| **D3: Fibonacci Scale** | **0.0 to 3.0 Extension Grid** | Legacy 0.0 to 1.0 Range | We need to measure expansion *beyond* the target (1.0). |
| **D4: Dual Invalidation Rules** | Track both **Stop-Loss Hit** and **Breakeven (Entry) Hit** | Tracking Stop-Loss Hit only | If a trader lets a runner ride past 1.0, they typically move their stop to **Breakeven**. Tracking both tells us if the trade would have survived a breakeven runner stop or the original loose SL. |
| **D5 (new): Direction-Aware Touch Logic** | Explicit `is_long` branch for level-touch checks (High-based for longs, Low-based for shorts) | Single "direction-agnostic" formula with no branching (v2 approach) | v2 asserted the price formula was direction-agnostic but only demonstrated long-side touch logic. Shorts require inverted comparisons (`Low <= level_price`), so the *formula* is direction-agnostic but the *touch detection* is not. Making this explicit prevents a silent short-side bug. |
| **D6 (new): Partial-Window Flagging** | Emit `pfib_window_candles` (actual count observed, 1–15) and exclude incomplete windows from aggregate stats by default | Silently truncating or zero-filling missing candles | Trades exiting near the end of the dataset would otherwise bias `pfib_bsl` downward without any way to detect it. |
| **D7 (new): Session-Gap Handling** | Flag windows that cross a weekend/session gap via `pfib_gap_crossed`; exclude from headline statistics by default (opt-in include flag) | Ignoring calendar gaps | A Friday-close exit's "15 candles" would otherwise span the weekend re-open, contaminating momentum measurement with a gap jump rather than genuine intraday continuation. |
| **D8 (new): Output as Joined Table, Not View Mutation** | Write to a separate `{strategy}_pfib` table keyed on `trade_id`, joined at query time | "Enriching" the `{strategy}_trades` view in place | DuckDB views are typically derived/read-only; mutating them in place is ambiguous and non-idempotent. A joinable side-table can be recomputed and re-run without touching the base trades table. |

---

## 4. Mathematical Definitions & Grid

### 4.1 Relationship to the Existing `fib_bsl` Baseline

`pfib_bsl` is **not** a re-derivation of the existing 0.236–0.786 in-trade
tracking from `fib_bsl` — it is a **forward continuation of the same
structural leg**, computed only after exit. Implementations must reuse the
already-computed `leg_span` and `level_price()` function from `fib_bsl` rather
than reimplementing ratio math, to avoid the two systems drifting out of sync.

### 4.2 The Frozen Leg Formula (Direction-Aware)

For every closed trade in DuckDB, the structural unit span is defined at entry:
$$\text{leg\_span} = |\text{TP} - \text{SL}|$$

The reference price for any Fibonacci ratio $r$ is:
$$\text{level\_price}(r) = \text{SL} + r \times (\text{TP} - \text{SL})$$

This formula is arithmetically direction-agnostic (it works whether `TP > SL`
or `TP < SL`), **but the touch-detection condition is not** and must branch
on trade direction:

```python
if is_long:
    level_price = sl + r * (tp - sl)          # tp > sl
    touched = candle_high >= level_price
else:  # short
    level_price = sl + r * (tp - sl)          # tp < sl, so ratios descend
    touched = candle_low <= level_price
```

`pfib_bsl` is recorded as the **deepest ratio touched** in the direction of
the trade before either invalidation condition (SL or nothing) fires — see
Section 6 for the exact precedence rules.

### 4.3 The Extension Ratio Grid

```
[0.236, 0.382, 0.500, 0.618, 0.786, 1.000, 1.272, 1.382, 1.618, 1.786, 2.000, 2.272, 2.618, 3.000]
```

**Deviation note:** v2 mirrored the retracement sequence past 1.0 (1.236,
1.382, 1.786 …). This version instead adopts the ratios most commonly used in
practitioner Fibonacci-**extension** analysis (1.272, 1.618, 2.0, 2.618),
kept alongside the retracement-style midpoints for continuity with `fib_bsl`.
If the team prefers strict continuity with v2's original grid for
backward-comparability with existing dashboards, that is a one-line config
change (`PFIB_RATIO_GRID`), not a structural change — flagging here as a
decision point rather than silently changing it underneath existing reports.

- **Base Zone (0.0 – 1.0)**: Entry and base TP.
- **Secondary Runner Zone (1.0 – 2.0)**: First extension zone.
- **Extended Trend Zone (2.0 – 3.0)**: Extreme momentum runner zone.

---

## 5. Worked Examples (Long and Short)

### 5.1 Long Trade

- **Entry Price**: `1.1000`
- **Stop-Loss (`SL`)**: `1.0950`
- **Take-Profit (`TP` / R1)**: `1.1050`
- **Structural Leg Span**: `0.0100` (100 pips)

| Ratio ($r$) | Level Price | Note |
| :---: | :---: | :--- |
| `1.000` | `1.1050` | Exit price |
| `1.272` | `1.10772` | |
| `1.618` | `1.11118` | |
| `2.000` | `1.11500` | |
| `2.618` | `1.12118` | |
| `3.000` | `1.12500` | |

**15-Candle Post-Exit Forward Scan:**
1. Trade hits `1.1050` at candle index $k = 42$, closes.
2. Engine slices candles $k \in [43, 57]$ (15 candles, all present — full
   window, `pfib_window_candles = 15`).
3. Candle 45: `High = 1.1120` → touches `1.618`.
4. Candle 48: `Low = 1.0990` → crosses below `Entry = 1.1000` →
   `pfib_be_hit = True`.
5. Candle 55: `Low = 1.0945` → crosses below `SL = 1.0950` →
   `pfib_sl_hit = True`.
6. **Result**: `pfib_bsl = 1.618`, `pfib_candles = 3`,
   `pfib_be_hit = True`, `pfib_sl_hit = True`, `pfib_gap_crossed = False`.

### 5.2 Short Trade (new in v3)

- **Entry Price**: `1.1000`
- **Stop-Loss (`SL`)**: `1.1050`
- **Take-Profit (`TP` / S1)**: `1.0950`
- **Structural Leg Span**: `0.0100` (100 pips, direction inverted vs. long)

| Ratio ($r$) | Level Price ($\text{SL} + r(\text{TP}-\text{SL})$) | Note |
| :---: | :---: | :--- |
| `1.000` | `1.0950` | Exit price |
| `1.272` | `1.09228` | |
| `1.618` | `1.08882` | |
| `2.000` | `1.08500` | |

**15-Candle Post-Exit Forward Scan (touch = `Low <= level_price`):**
1. Trade hits `1.0950` at candle index $k = 88$, closes.
2. Engine slices candles $k \in [89, 103]$. Only 11 candles exist before the
   dataset ends → `pfib_window_candles = 11`, `pfib_window_complete = False`.
   Per D6, this trade is **excluded from headline aggregate stats** by
   default but still recorded with its partial result.
3. Candle 90: `Low = 1.0885` → touches `2.000`.
4. Candle 92: `High = 1.1005` → crosses above `Entry = 1.1000` →
   `pfib_be_hit = True`.
5. No candle in the remaining (truncated) window crosses `SL = 1.1050` →
   `pfib_sl_hit = False`.
6. **Result**: `pfib_bsl = 2.000`, `pfib_candles = 2`,
   `pfib_be_hit = True`, `pfib_sl_hit = False`,
   `pfib_window_complete = False`.

---

## 6. DuckDB Schema & Output Contract

### 6.1 Storage Model (see D8)

Output is written to a **new table** `{strategy}_pfib`, one row per
`trade_id`, joined to `{strategy}_trades` at query time (`LEFT JOIN` on
`trade_id`). The base trades table/view is **never mutated in place**.

### 6.2 Columns

| Column Name | DuckDB Type | Description |
|---|---|---|
| `trade_id` | `BIGINT` | Foreign key to `{strategy}_trades`. |
| `pfib_bsl` | `DOUBLE` | Deepest Fibonacci ratio (up to 3.0) reached in the observed forward window, in the direction of the trade. `NULL` if zero forward candles were available. |
| `pfib_candles` | `INTEGER` | Candle offset from exit (1…15) where `pfib_bsl` occurred. |
| `pfib_be_hit` | `BOOLEAN` | `True` if price crossed back through the original entry price within the observed window. |
| `pfib_sl_hit` | `BOOLEAN` | `True` if price crossed the original Stop-Loss within the observed window. |
| `pfib_window_candles` | `INTEGER` | **(new)** Actual number of forward candles observed (1–15). |
| `pfib_window_complete` | `BOOLEAN` | **(new)** `True` iff `pfib_window_candles == 15`. Aggregate stats should filter on this by default. |
| `pfib_gap_crossed` | `BOOLEAN` | **(new)** `True` if the observed window spans a session/weekend gap (see D7). Aggregate stats should filter this out by default, or treat separately. |
| `pfib_direction` | `VARCHAR` | **(new)** `'long'` or `'short'` — makes the joined table self-describing without needing to re-join the strategy table just to interpret sign conventions. |

### 6.3 Precedence Rule for `pfib_bsl`

If both a deeper ratio touch and an SL/BE invalidation occur in the same
window, `pfib_bsl` records the **deepest ratio touched before or at the
candle where SL was hit** (a runner can touch 2.0 and then still stop out —
both facts are preserved via `pfib_bsl` and `pfib_sl_hit` independently,
rather than one overwriting the other).

### 6.4 Idempotency & Re-run Semantics (new in v3)

- Running the engine against a `{strategy}_pfib` table that already exists
  performs a full `DELETE + INSERT` keyed by `trade_id` for any trade present
  in the current `{strategy}_trades` snapshot — not an append, and not a
  silent no-op skip. This makes re-runs after new data arrives safe and
  deterministic.
- A `pfib_computed_at TIMESTAMP` column is included for auditability.

---

## 7. Data Quality & Edge Cases (new section in v3)

| Case | Rule |
|---|---|
| Trade exits within 15 candles of end-of-dataset | `pfib_window_candles < 15`; row is still written, `pfib_window_complete = False`. Excluded from default aggregates (Section 8). |
| Forward window spans a weekend/session gap | `pfib_gap_crossed = True`. Excluded from default aggregates; may be included via explicit opt-in flag for gap-specific studies. |
| Missing/NULL candles inside the window (data feed gap) | Treated as a break in continuity, same handling as a session gap — flagged, not interpolated. |
| Zero forward candles available (trade is literally the last row) | `pfib_bsl = NULL`, `pfib_window_candles = 0`, row still written for completeness/audit. |
| `leg_span == 0` (degenerate TP == SL) | Row excluded with a logged warning; this indicates a broken upstream trade record, not a valid input. |

---

## 8. Statistical Validation Methodology (new section in v3)

The percentage findings in Section 9 (e.g. "50.4%", "≥35%") are **point
estimates from a single backtest window** and must not be treated as
implementation triggers on their own. Before any finding drives a strategy
change:

1. **Report sample size** ($n$ trades) alongside every percentage.
2. **Report a confidence interval** (Wilson score interval is preferred over
   normal-approximation for binomial proportions, especially at smaller $n$
   or near 0%/100%).
3. **Require replication across ≥ 2 non-overlapping time windows**
   (e.g. two different years, or a walk-forward split) before a finding is
   treated as robust enough to act on — a single 1-year sample is one
   volatility regime, not a generalizable result.
4. Findings that fail replication are documented as "not robust — regime
   dependent" rather than discarded silently, since that's itself useful
   information about the underlying market structure.

---

## 9. Actionable Decision Framework for Strategy Evolution

> **Read this table together with Section 8.** None of the "Implementation
> Next Step" actions below should be taken on a single-window finding alone.

| Metric Finding from Backtest (validated per Section 8) | Quantitative Meaning | Implementation Next Step |
|---|---|---|
| **≥ 35% of TP trades reach `pfib_bsl >= 1.618` before Breakeven** (replicated across ≥2 windows) | Major post-exit runner momentum exists. | **Prototype v5 Scale-Out**: Bank 50% at 1.0, move SL to breakeven, target 1.618–2.0 on the remainder. **Must be re-evaluated net of spread + slippage on the partial close before any live consideration** — a partial-exit strategy adds a second round-trip cost that the raw ratio-touch statistic does not capture. |
| **≥ 75% of TP trades fail to reach `1.272` before dropping below Entry** (replicated) | R1 is close to a local exhaustion ceiling. | **Retain 1.0 Full Exit** as the default; scale-out variants are not expected to add value. |
| **Peak `pfib_candles` clusters at candles 2–4** (replicated) | Overextensions happen immediately after breakout. | Consider a short (4-candle) trailing deadline for any runner variant — but only after the cost-adjusted check above. |

---

## 10. Testing Strategy (new section in v3)

Minimum bar for merge:

1. **Unit test**: Section 5.1 and 5.2 worked examples encoded as fixtures —
   given the stated OHLC sequence, assert exact expected output row.
2. **Property test**: `leg_span != 0` assertion; reject/skip rows that
   violate it rather than dividing by zero.
3. **Direction test**: a short-side synthetic fixture explicitly asserting
   `Low <=` touch logic is used (guards against regression to the v2
   long-only pattern).
4. **Edge-of-dataset test**: fixture with fewer than 15 trailing candles
   confirms `pfib_window_complete = False` and correct partial `pfib_bsl`.
5. **Idempotency test**: running the engine twice on identical input
   produces identical output rows (no duplication, no drift).

---

## 11. CLI Command Integration

```bash
# View runner distribution across winning trades (complete windows only, default)
uv run loss-profile --primary --view classic_floor_mod_v4c_trades --dist pfib_bsl --wins-only

# Include partial/gap-crossed windows explicitly (opt-in)
uv run loss-profile --primary --view classic_floor_mod_v4c_trades --dist pfib_bsl --wins-only --include-partial --include-gap-crossed

# Dump full markdown report, with sample size + CI annotations, to Shared/OUTs/
uv run loss-profile --primary --view classic_floor_mod_v4c_trades --dist pfib_bsl -o md --dump --with-ci
```
