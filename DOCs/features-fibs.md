---
title: Price-Level Touch Before Stop-Loss Analysis
status: draft
version: 5
type: proposal
area: backtesting
tags:
  - proposal
  - backtesting
  - vectorbt
  - numba
  - fibonacci
created: 2026-09-09
related:
  - "[[level_touch_analysis.py]]"
---

# Price-Level Touch Before Stop-Loss Analysis

## Definitions
Terms used throughout this document, defined so no external context is required.

| Term | Definition |
|---|---|
| **Trade** | One entry-to-exit position produced by the backtest, with a known entry price, stop-loss (SL) price, take-profit (TP) price, entry timestamp, and direction. |
| **SL (Stop Loss)** | The price at which a trade is closed for a loss if the market moves against it. |
| **TP (Take Profit)** | The price at which a trade is closed for a gain if the market moves in its favor. |
| **Direction** | `long` (profits if price rises, so `TP > SL`) or `short` (profits if price falls, so `TP < SL`). |
| **Candle** | One OHLC (Open/High/Low/Close) bar of price data at a fixed timeframe (e.g., 1 hour). `High`/`Low` are the max/min traded price within that bar. |
| **Fibonacci ratio / level** | One of a fixed set of ratios (0.236, 0.382, 0.5, 0.618, 0.786) projected across the SL↔TP leg (see below) to produce a reference price. Used purely as a price target to test for a touch — no claim about *why* price would react to it. |
| **Leg** | The SL↔TP range for a trade: `level_price = SL + ratio * (TP - SL)`. This formula is direction-agnostic — it works whether `TP > SL` (long) or `TP < SL` (short) without special-casing direction. Direction only matters later, in the touch condition. |
| **Touch** | A candle's High/Low range crosses a given price (a Fib level, SL, or TP). "Touched" does **not** mean closed beyond it — it only requires intersecting it within the candle's High-Low range. |
| **Before SL (`_bsl`)** | Shorthand used in this document and in column names for "touched before the stop-loss was touched" — i.e., the level's first touch happened on an earlier candle than the SL's first touch (or SL was never touched at all in the trade's window). |
| **Same-candle tie / ambiguous** | A level and the SL both had their first touch on the *same* candle. Plain OHLC data (High/Low only) cannot tell which happened first within that candle, so the order must be assumed via a policy (below) rather than known for certain. |
| **Not applicable** | A trade with no valid leg — i.e., no TP is defined for it (some strategy variants may use only a time-based or trailing exit with no fixed TP). Different from "no level was reached" — see [[#Requirements]]. |
| **`end_reason`** | Why the forward scan for a trade stopped: `sl_hit` (SL was touched first), `tp_hit` (TP was touched first), or `data_end` (historical data ran out before either fired — the trade may still be technically open). There is no `horizon_cap`: every trade is expected to eventually touch SL or TP, so scans are not artificially capped. |
| **Monotonicity** | The expectation that if a deeper Fibonacci ratio (e.g., 0.618) was reached before SL, the shallower ones (e.g., 0.382) almost always were too, since price generally has to pass through shallower levels to reach deeper ones. This is what allows the output to be collapsed to a single "deepest ratio reached" value instead of one flag per level (see [[#Output (collapsed schema)]]). |
| **Tolerance / epsilon** | A small numeric margin used when comparing prices (e.g., `High >= level`), to avoid floating-point rounding causing a real touch to be missed or a non-touch to be falsely counted. This proposal uses a **relative epsilon** (see [[#Requirements]]), not a per-symbol tick-size table. |
| **Trade window** | The candle range scanned for a trade: from `trade_start_idx` (entry + 1 candle) to `trade_end_idx` (inclusive — the last candle considered, per `end_reason`). |
| **Kernel** | The core computation function that does the forward scan and produces the touch result (planned as a Numba-compiled function — see [[#How to build it]]). |
| **Numba / `@njit`** | A Python compiler that turns a plain Python/NumPy function into fast machine code, used here so the per-trade scan runs at native speed instead of as a slow Python loop. |
| **`prange`** | Numba's parallel version of `range` — splits a loop (here, looping over trades) across multiple CPU cores. |
| **Differential test** | A test that runs two independent implementations of the same logic (a simple, obviously-correct one and the fast production one) on the same inputs and checks they produce identical results — used to catch bugs in the fast version. |

## What
For every trade (entry, SL, TP, direction, timestamp), determine the **deepest
Fibonacci level (of the SL↔TP leg) reached before SL**, using candle High/Low ranges.
This is a post-trade analytics step — it does not change how trades are generated.

## Output (collapsed schema)
Rather than one boolean column per level, the output uses monotonicity (see
[[#Definitions]]) to collapse the result to two columns per trade:

| Column | Type | Meaning |
|---|---|---|
| `fib_bsl` | float | The **highest Fibonacci ratio** (e.g. `0.618`) touched before SL. `0.0` = no level was touched before SL. `NaN` = trade has no valid leg (no TP defined — not applicable). |
| `fib_bsl_ambiguous` | bool | `True` only if the level reported in `fib_bsl` had its first touch on the *same candle* as SL (a same-candle tie) — i.e., whether the reported value itself depended on the tie-break policy below. |

> [!warning] `0.0` vs `NaN`
> These must never be confused downstream: `0.0` is a real result ("nothing was
> reached"), `NaN` means the trade cannot be scored at all. Any `groupby`/aggregation on
> `fib_bsl` must drop `NaN` rows explicitly rather than let them silently become `0` or
> get included in an average.

> [!note] `tp_hit` trades cluster at the top ratio by construction
> Since TP is the top of the leg (ratio = 1.0), a `tp_hit` trade will almost always
> report `fib_bsl = 0.786` (the highest defined ratio below TP itself) — reaching TP
> implies passing through 0.786 first in the vast majority of cases. This isn't a bug;
> it just means `fib_bsl` is only analytically interesting to break out by `end_reason`
> (see [[#Requirements]]) — the real signal is in **`sl_hit` trades**: how far into the
> reward zone price got before reversing and stopping out.

## Before building

> [!info] Check for an existing solution first
> Confirm whether vectorbt's existing MAE/MFE (Maximum Favorable/Adverse Excursion —
> built-in tracking of the best/worst price reached during a trade) tooling already
> covers this. It likely tracks running extremes, not "first touch of a specific
> ratio-based level," so it probably doesn't replace this feature — but once built,
> cross-check results against it (e.g., a trade with `fib_bsl = 0.618` must have an MFE
> distance at least as large as the distance to that level). Document this check either
> way before starting.

## Requirements

### Leg definition (resolved)
- The leg is **SL ↔ TP**, not a detected swing point. `level_price = SL + ratio * (TP - SL)`
  for each of the 5 standard ratios.
- **Open question to confirm:** does every trade have a fixed TP? If any strategy
  variant exits only by time or trailing stop with no fixed TP, those trades have no
  leg — they fall under "not applicable" (`fib_bsl = NaN`), the same as if no swing had
  been found in the earlier swing-based design.

### Touch definitions
- Long trade: level touched if `candle.High >= level`; SL touched if `candle.Low <= SL`.
- Short trade: level touched if `candle.Low <= level`; SL touched if `candle.High >= SL`.
- Use a tolerance in these comparisons — never exact float equality.

### Tolerance (resolved)
- Use a **relative epsilon scaled to price**, not a per-symbol tick-size lookup table:
  `tolerance = max(price * 1e-7, 1e-9)`.
- Rationale: a tick-size table requires maintaining per-instrument metadata this
  analytics layer doesn't otherwise need, and a missing/wrong tick size is a silent
  failure mode. A relative epsilon scales correctly across instruments of very different
  price magnitudes (e.g., BTC ~100,000 vs. an FX pair ~1.1) without any lookup, and
  `1e-7` relative is far tighter than any real tick size, so it only absorbs
  floating-point noise — it won't mask genuine near-misses.
- Make this a config constant so it can be swapped for a tick-size approach later if a
  specific instrument proves noisy in practice.

### Same-candle ambiguity (resolved: default `sl_first`)
- Ties are resolved per level internally using a configurable policy before the deepest
  reached ratio is determined:
  - **`sl_first` (default, confirmed):** SL assumed first at a tie → that level does
    **not** count as reached before SL.
  - `level_first`: level assumed first at a tie → that level **does** count as reached.
  - `simultaneous`: tied levels are excluded from `fib_bsl` entirely, but still recorded
    (see `fib_bsl_ambiguous`).
- `fib_bsl_ambiguous` is set based on whether the level that ended up being reported in
  `fib_bsl` was itself a tie — not whether *any* level for the trade had a tie.

### Not-applicable trades
- If a trade has no TP defined (no valid leg), `fib_bsl = NaN`, `fib_bsl_ambiguous = False`.
- Downstream statistics must explicitly exclude `NaN` trades rather than let them be
  silently dropped or zeroed by an aggregation function.

### Exit / `end_reason` (simplified: no horizon cap)
- Every trade is expected to eventually touch either SL or TP — there is no artificial
  scan cutoff (`horizon_cap` from earlier drafts is removed).
- `end_reason` has three values: `sl_hit`, `tp_hit`, `data_end` (historical data ran out
  before either fired). `data_end` is not a policy choice — it's an unavoidable
  consequence of finite historical data — but it still needs the same
  exclude-from-headline-stats treatment as `NaN` trades, since neither outcome is a
  genuine trade resolution.
- Reporting on `fib_bsl` must be broken out by `end_reason` (see the `tp_hit`-clustering
  note in [[#Output (collapsed schema)]] for why this matters).

### Scope
- One symbol/instrument per run. Multi-symbol portfolios (where trade indices would
  collide across instruments) are out of scope for this version.
- `trade_end_idx` is inclusive of the last candle in the trade window.

## How to build it

### Pipeline placement
```
OHLC candles → signal generation (pandas-ta-classic) → vectorbt trade records
  → Fibonacci level generation per trade (level = SL + ratio * (TP - SL))
  → touch-detection kernel (this feature, Numba-compiled)
  → fib_bsl / fib_bsl_ambiguous columns appended to the trade table
  → reporting (pandas / vectorbt), cross-checked against vbt MAE/MFE (see "Before building")
```

### Kernel design
- One `@njit(parallel=True)` function. Loop over trades using `prange` (parallel across
  CPU cores — see [[#Definitions]]).
- For each trade, do **one single forward pass** over its candle window that tracks the
  first-touch candle index for SL *and* every Fibonacci ratio at once, stopping early as
  soon as SL and all ratios are resolved. Do **not** scan the window separately per
  ratio — the kernel still evaluates all 5 ratios internally (it needs every one to find
  the deepest reached), but each candle in the window should only be visited once.
- Per trade: `sl_idx` = first candle index where SL condition is true (or -1 if never).
  `lvl_idx[j]` = same, per ratio `j`. Then, per ratio:
  - `lvl_idx[j] == -1` → not reached.
  - `sl_idx == -1` → reached (SL never touched, level was — i.e., trade ended in `tp_hit`
    or `data_end`).
  - `lvl_idx[j] < sl_idx` → reached.
  - `lvl_idx[j] > sl_idx` → not reached.
  - `lvl_idx[j] == sl_idx` → tie; resolved by policy.
  - After resolving all 5 ratios: `fib_bsl` = max ratio marked "reached" (or `0.0` if
    none), and `fib_bsl_ambiguous` = whether *that specific* ratio was a tie case.
- If trades have very uneven window lengths (some close in a few candles, some run for
  thousands), plain `prange` can load-balance poorly across cores. If benchmarking shows
  this, sort/bucket trades by window length before dispatching.

### Fibonacci level generation
- `build_fib_levels(sl, tp)` → `level_price = sl + ratio * (tp - sl)` for each of the 5
  standard ratios. No swing/leg detection needed — this replaces the earlier
  strategy-dependent swing logic entirely.
- If `tp` is undefined for a trade, all 5 levels are `NaN` for that trade (not applicable).

### Testing
- Write a plain Python (non-Numba) version of the same forward-scan logic. Run a
  differential test comparing it against the Numba kernel on randomized trades plus
  hand-picked edge cases: no level touched, SL never touched, single-candle window,
  entry price equal to SL, a level price equal to entry price, a tie occurring exactly
  on the level that turns out to be the deepest reached, and a trade with no TP defined.
- Track how often the reported `fib_bsl` ratio has a shallower ratio *not* marked as
  reached for the same trade (a monotonicity violation) as a data-quality metric — a
  high rate usually signals a bug in level generation or indexing.

## Open decisions
> [!question] Remaining items
> 1. ~~Leg definition~~ — **Resolved: SL ↔ TP.**
> 2. ~~Window capping~~ — **Resolved: none; every trade must exit via SL or TP.**
> 3. ~~Default tie policy~~ — **Resolved: `sl_first`.**
> 4. ~~Tolerance~~ — **Resolved: relative epsilon, `max(price * 1e-7, 1e-9)`.**
> 5. **New:** Does every trade in the dataset have a fixed TP? If not, confirm that
>    no-TP trades should be treated as "not applicable" (`fib_bsl = NaN`).

## Acceptance criteria
- [ ] Fibonacci levels are computed as `SL + ratio * (TP - SL)`, verified for both long
      (`TP > SL`) and short (`TP < SL`) trades.
- [ ] Touch definitions match the Requirements section exactly, verified against
      hand-built test candles, including the relative-epsilon tolerance.
- [ ] `fib_bsl` correctly reports the deepest reached ratio, and `0.0` vs. `NaN` are
      never confused in the kernel output or in downstream aggregation examples.
- [ ] `fib_bsl_ambiguous` reflects only ties on the reported ratio, not any tie anywhere
      in the trade's 5 ratios.
- [ ] Differential test (plain-Python reference vs. Numba kernel) passes on randomized
      trades and all listed edge cases, including no-TP trades.
- [ ] Kernel performs a single forward pass per trade with early exit — no independent
      per-ratio rescans.
- [ ] Benchmarked against a realistic, skewed trade-window-length distribution (not
      uniform synthetic data); load-balancing fix applied if imbalance is significant.
- [ ] Full trade set runs within an explicit time budget: **[fill in: N trades in
      < M minutes on K cores]**.
- [ ] Reporting on `fib_bsl` is broken out by `end_reason` (`sl_hit` / `tp_hit` /
      `data_end`) and excludes `NaN` trades — with the `tp_hit`-clustering behavior
      documented for report readers.
