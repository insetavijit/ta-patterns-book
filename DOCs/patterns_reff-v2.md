# Pattern Reference — v2

Second-generation reference for the `ta_patterns` library (pinned to **v1.1.1**, PyPI `ta-patterns`, source `github.com/AdventuresInDataScience/ta_patterns`).

**What changed from v1:** v1 only listed pattern *names* grouped by direction/family. This version pulls the actual definitions straight from the installed package's docstrings (`pip install ta-patterns` → introspected via Python), verifies every direction assignment against the library's own `BULLISH`/`BEARISH`/`BIDIRECTIONAL`/`NON_DIRECTIONAL` frozensets rather than the catalog text, and flags known documentation issues and cross-module redundancy found during review.

## How to read this file

- **Definition** — the pattern's own docstring, lightly cleaned (whitespace collapsed only; wording is the library author's, not rewritten).
- **Family** — a navigational tag (candle-count for candlesticks; structural family for chart patterns), same scheme as v1, kept for browsing.
- Counts and direction splits below are pulled live from `tap.BULLISH`, `tap.BEARISH`, `cp.BULLISH`, `cp.BIDIRECTIONAL`, etc. — not retyped from the catalog doc.

## Known issues found during review (v2 additions)

### 1. Documentation/classification drift — `cloud_bank`
> **Docstring says:** “**BULLISH** (+1 / 0). Recent closes cluster in a tight band...”
> **Actual runtime classification:** registered in `cp.NON_DIRECTIONAL`, **not** in `cp.BULLISH`. Verified: `'cloud_bank' in cp.NON_DIRECTIONAL` → `True`; `'cloud_bank' in cp.BULLISH` → `False`. Behaviorally it only ever emits `{0, 1}` — never `-1` — so the *code* is internally consistent, but the docstring text is stale/wrong. The catalog's classification (non-directional) is correct; the docstring wording is the bug.

### 2. Undocumented patterns — the four "new price lines" detectors

`eight_new_price_lines`, `ten_new_price_lines`, `twelve_new_price_lines`, `thirteen_new_price_lines` have **no docstring at all** (`__doc__ is None`) in v1.1.1 — verified by direct introspection. Their behavior can only be inferred from the name and from testing against synthetic data; this file marks them clearly below rather than guessing at a definition.

### 3. Cross-module redundancy (self-disclosed in docstrings)

| Chart pattern | Overlaps with | Note |
|---|---|---|
| `double_key_reversal_bullish / bearish` | `candlestick key-reversal concept (multi-bar variant)` | Docstring: “Reimports from candlestick module. 3-bar: D1 down, D2 key-reversal up, D3 confirms by closing above D2 close.” Only the bullish half's docstring states this explicitly. |
| `fakey_bullish / fakey_bearish` | `hikkake_bullish / hikkake_bearish (candlestick)` | Docstrings state they 'reimport semantics' from the candlestick hikkake detectors. The bidirectional `fakey()` most likely unions both halves. |
| `hook_reversal_bottom / hook_reversal_top` | `harami + confirmation bar (candlestick)` | Docstring states 'semantically equivalent to the candlestick harami + confirm.' |
| `roof` | `rounding_top` | Docstring: 'Similar to rounding top but over a shorter timeframe' — a parameter/timeframe variant of an existing pattern given a new name, not a hard duplicate. |
| `turn_key_bullish / turn_key_bearish` | `three_line_strike_bullish / bearish (candlestick)` | Docstring: 'Reimports from candlestick multi_bar.three_line_strike_bullish semantics.' |
| `two_step_bullish / two_step_bearish` | `breakaway_bullish / bearish (candlestick)` | Docstring: 'Similar to breakaway_bullish from candlestick module.' |

These six pairs are not confirmed to be numerically identical (a synthetic-data check on `turn_key_bullish` vs `three_line_strike_bullish` showed non-identical outputs), but the *authors' own docstrings* describe them as reimplementations or close variants of existing candlestick detectors. Treat these as **correlated, not independent, signals** when summing scores across the 300-pattern catalog — `net_score_all` will implicitly weight these ideas roughly 2x versus a single-representation pattern.

### 4. Naming clarity

Several names give no hint of what they detect without reading source: `two_did`, `two_tall`, `carl_v`, `turn_key`, `shark_32` (name collides with the unrelated, well-known Shark harmonic pattern — this library's `shark_32` is actually a triple-inside-bar compression pattern, unrelated to Fibonacci harmonics). The Definition column below exists specifically to close this gap.

### 5. Version pin

This file reflects `ta-patterns==1.1.1` (2026-06-09). The library is early-stage (single maintainer, no CHANGELOG.md, no documented stability policy for detector *logic*). If you depend on this file's definitions matching runtime behavior, pin the version.

---

## 1. Candlesticks (106)

Verified live: 51 bullish, 49 bearish, 6 non-directional.

### Bullish (51)

| Pattern | Family | Definition |
|---|---|---|
| `abandoned_baby_bullish` | 3-candle | D1 black; D2 doji gaps down (no overlap with D1); D3 white gaps up (no overlap with D2).  Strongest bullish reversal in the star family. |
| `above_stomach` | 2-candle | D1 black; D2 white opens within D1 body and closes above D1 midpoint. Bullish reversal. |
| `belt_hold_bullish` | 2-candle | **BULLISH** (+1 / 0). White candle opening at/near the session low; closes strongly. |
| `breakaway_bullish` | 4+ candle | D1 long black; D2 black (gap down from D1); D3 & D4 small/indecisive; D5 long white closing back into the gap (above D2 open, below D1 close). Bullish reversal. |
| `closing_marubozu_white` | 1-candle | **BULLISH** (+1 / 0). White candle closing at the high. |
| `concealing_baby_swallow` | 4+ candle | D1 & D2 black marubozus; D3 black with a gap-down open and upper shadow that reaches back into D2; D4 black that fully engulfs D3. Bullish reversal. |
| `doji_star_bullish` | 2-candle | D1 black; D2 is a doji that gaps DOWN below D1's body. Bullish reversal warning (two-bar version). |
| `dragonfly_doji` | 1-candle | **BULLISH** (+1 / 0). Doji with a long lower shadow and no/tiny upper shadow (T-shape). |
| `eight_new_price_lines` | 4+ candle | _[No docstring in source — undocumented at v1.1.1. Name implies an N-consecutive-higher-closes count-up variant of the 'three new price lines' concept; behavior not independently verified.]_ |
| `engulfing_bullish` | 2-candle | D1 black; D2 white whose body fully engulfs D1's body. Bullish reversal. |
| `gapping_up_doji` | 1-candle | Doji that gaps UP from the prior bar (bearish warning in uptrend). |
| `hammer` | 1-candle | **BULLISH** (+1 / 0). Small body in the upper portion; lower shadow ≥ shadow_factor × body; tiny upper shadow; typically in a downtrend. |
| `harami_bullish` | 2-candle | D1 long black; D2 small white body *inside* D1 body. Bullish reversal: sellers losing conviction. |
| `harami_cross_bullish` | 2-candle | D1 long black; D2 is a doji whose body is inside D1's body. |
| `hikkake_bullish` | 4+ candle | D1 any; D2 inside bar (high < D1 high, low > D1 low); D3 closes ABOVE D1 high – false downside breakout resolves bullishly. |
| `homing_pigeon` | 2-candle | Two black candles; D2 body is entirely inside D1 body. Bullish reversal (sellers stalling). |
| `inverted_hammer` | 1-candle | D1 black (bearish move); D2 has a small body at the bottom of its range with a long upper shadow and tiny/no lower shadow.  Bullish reversal. |
| `kicking_bullish` | 2-candle | D1 black marubozu followed by a gap-UP white marubozu. Very strong bullish signal. |
| `ladder_bottom` | 4+ candle | D1-D3 three successively lower black candles; D4 black with upper shadow (buyers trying); D5 white opening above D4 close.  Bullish reversal. |
| `last_engulfing_bottom` | 2-candle | Bullish engulfing in a downtrend (capitulation / bottom reversal). |
| `long_white_day` | 1-candle | **BULLISH** (+1 / 0). |
| `marubozu_white` | 1-candle | **BULLISH** (+1 / 0). White candle with no/negligible shadows. |
| `mat_hold` | 4+ candle | D1 long white; D2 small black (gap up); D3 & D4 small, staying above D1's close; D5 long white closing at a new high vs D2-D4. Bullish continuation. |
| `matching_low` | 2-candle | Two consecutive black candles with the same close (within *tol*). Bullish support signal. |
| `meeting_lines_bullish` | 2-candle | D1 black; D2 white opens with a gap down but closes at D1's close level. Bullish reversal. |
| `morning_doji_star` | 3-candle | Like morning_star but D2 is specifically a doji. |
| `morning_star` | 3-candle | D1 long black; D2 small body (any colour) below D1; D3 white closing above D1 midpoint.  Bullish reversal. |
| `opening_marubozu_white` | 1-candle | **BULLISH** (+1 / 0). White candle opening at the low. |
| `piercing_pattern` | 2-candle | D1 long black; D2 white opens below D1 low then closes *penetration* fraction into D1's body (measured upward from D1's close). Bullish reversal.  Mirror image of dark_cloud_cover. Parameters ---------- penetration : float, default 0.50 0.50 → D2 closes above the midpoint (classic definition). 0.30 → looser; 0.70 → stricter. d1_body_thr : float, default 0.50 Minimum body/range ratio for D1. |
| `rising_three_methods` | 4+ candle | D1 long white; D2-D4 three small blacks staying within D1's range; D5 long white closing above D1's high.  Bullish continuation. |
| `rising_window` | 2-candle | Gap UP: current low > prior high.  Bullish continuation. |
| `separating_lines_bullish` | 2-candle | D1 black; D2 white opens at the same price as D1 (within *tol*). Bullish continuation – buyers defended the open. |
| `side_by_side_white_lines_bullish` | 3-candle | D1 white; D2 & D3 are similar-sized white candles both opening with a gap up above D1.  Bullish continuation. |
| `southern_doji` | 1-candle | **BULLISH** (+1 / 0). Doji in a downtrend. |
| `spinning_top_white` | 1-candle | **BULLISH** (+1 / 0). White candle with small body and bilateral shadows. |
| `stick_sandwich` | 3-candle | D1 black; D2 white (higher close); D3 black with same close as D1. Bullish reversal (price found support at the matching closes). |
| `takuri_line` | 1-candle | **BULLISH** (+1 / 0). Like a hammer but with an unusually long lower shadow (≥ 3× body). |
| `ten_new_price_lines` | 4+ candle | _[No docstring in source — undocumented at v1.1.1. Name implies an N-consecutive-higher-closes count-up variant of the 'three new price lines' concept; behavior not independently verified.]_ |
| `thirteen_new_price_lines` | 4+ candle | _[No docstring in source — undocumented at v1.1.1. Name implies an N-consecutive-higher-closes count-up variant of the 'three new price lines' concept; behavior not independently verified.]_ |
| `three_inside_up` | 3-candle | D1 black; D2 white harami inside D1; D3 white closing above D1 open. Bullish reversal confirmed. |
| `three_line_strike_bullish` | 4+ candle | Three white soldiers (D1-D3) followed by a single black candle (D4) that opens above D3 and closes at-or-below D1's open. Textbook says this is paradoxically a *bullish continuation* signal. |
| `three_outside_up` | 3-candle | D1 black; D2 white bullish engulfing; D3 white closing above D2. Bullish reversal confirmed. |
| `three_stars_south` | 3-candle | Three black candles: each with a lower high and lower low; the third is a small near-marubozu.  Bullish reversal. |
| `three_white_soldiers` | 3-candle | Three consecutive white candles; each opens inside the prior body and closes progressively higher.  Bullish continuation / reversal. |
| `tri_star_bullish` | 3-candle | Three consecutive dojis in a downtrend.  Bullish reversal. |
| `tweezer_bottoms` | 2-candle | D1 and D2 share the same low (within *tol* of price). Bullish. |
| `twelve_new_price_lines` | 4+ candle | _[No docstring in source — undocumented at v1.1.1. Name implies an N-consecutive-higher-closes count-up variant of the 'three new price lines' concept; behavior not independently verified.]_ |
| `unique_three_river_bottom` | 3-candle | D1 long black; D2 black with lower low and long lower shadow; D3 small white closing inside D2 body.  Bullish reversal. |
| `upside_gap_three_methods` | 4+ candle | D1 white; D2 white (gap up); D3 black closes inside D1 body. Bullish continuation. |
| `upside_tasuki_gap` | 3-candle | D1 & D2 white with a gap up; D3 black opens inside D2 and closes in the gap but does NOT close it.  Bullish continuation. |
| `white_candle` | 1-candle | **BULLISH** (+1 / 0). Any close > open candle. |


### Bearish (49)

| Pattern | Family | Definition |
|---|---|---|
| `abandoned_baby_bearish` | 3-candle | D1 white; D2 doji gaps up; D3 black gaps down. Strongest bearish reversal in the star family. |
| `advance_block` | 3-candle | Three white candles with progressively smaller bodies and/or larger upper shadows – buyers exhausting.  Bearish warning. |
| `below_stomach` | 2-candle | D1 white; D2 black opens within D1 body and closes below D1 midpoint. Bearish reversal. |
| `belt_hold_bearish` | 2-candle | **BEARISH** (-1 / 0). Black candle opening at/near the session high; closes weakly. |
| `black_candle` | 1-candle | **BEARISH** (-1 / 0). Any close < open candle. |
| `breakaway_bearish` | 4+ candle | D1 long white; D2 white (gap up); D3 & D4 small; D5 long black closing back into the gap.  Bearish reversal. |
| `closing_marubozu_black` | 1-candle | **BEARISH** (-1 / 0). Black candle closing at the low. |
| `collapse_doji_star` | 3-candle | D1 black; D2 doji near D1 close level; D3 black closes below D1 close. Bearish continuation. |
| `dark_cloud_cover` | 2-candle | D1 long white; D2 black opens above D1 high then closes *penetration* fraction into D1's body (measured downward from D1's close). Parameters ---------- penetration : float, default 0.50 Fraction of D1's body that D2 must close through. 0.50 → D2 closes below the midpoint (classic textbook definition). 0.30 → looser; 0.70 → stricter (more bearish conviction required). d1_body_thr : float, default 0.50 Minimum body/range ratio for D1 to qualify as a 'substantial' candle. |
| `deliberation` | 3-candle | Three white candles; first two strong, third is small/doji-like. Bearish hesitation signal. |
| `doji_star_bearish` | 2-candle | D1 white; D2 is a doji that gaps UP above D1's body. Bearish reversal warning (two-bar version). |
| `downside_gap_three_methods` | 4+ candle | D1 black; D2 black (gap down); D3 white closes inside D1 body. Bearish continuation. |
| `downside_tasuki_gap` | 3-candle | D1 & D2 black with a gap down; D3 white opens inside D2 and closes in the gap but does NOT close it.  Bearish continuation. |
| `engulfing_bearish` | 2-candle | D1 white; D2 black whose body fully engulfs D1's body. Bearish reversal. |
| `evening_doji_star` | 3-candle | Like evening_star but D2 is specifically a doji. |
| `evening_star` | 3-candle | D1 long white; D2 small body above D1; D3 black closing below D1 midpoint. Bearish reversal. |
| `falling_three_methods` | 4+ candle | D1 long black; D2-D4 three small whites within D1's range; D5 long black closing below D1's low.  Bearish continuation. |
| `falling_window` | 2-candle | Gap DOWN: current high < prior low.  Bearish continuation. |
| `gapping_down_doji` | 1-candle | Doji that gaps DOWN from the prior bar (bullish warning in downtrend). |
| `gravestone_doji` | 1-candle | **BEARISH** (-1 / 0). Doji with a long upper shadow and no/tiny lower shadow (inverted T). |
| `hanging_man` | 1-candle | **BEARISH** (-1 / 0). Same shape as hammer but in an uptrend. |
| `harami_bearish` | 2-candle | D1 long white; D2 small black body *inside* D1 body. Bearish reversal: buyers losing conviction. |
| `harami_cross_bearish` | 2-candle | D1 long white; D2 is a doji whose body is inside D1's body. |
| `hikkake_bearish` | 4+ candle | D1 any; D2 inside bar; D3 closes BELOW D1 low – false upside breakout resolves bearishly. |
| `identical_three_crows` | 3-candle | Three black crows where each opens at (within *tol* of) the prior close. More bearish than standard three black crows. |
| `in_neck` | 2-candle | D1 black; D2 white opens below D1 low and closes very close to D1 close. Bearish continuation – buyers barely made it back. |
| `kicking_bearish` | 2-candle | D1 white marubozu followed by a gap-DOWN black marubozu. Very strong bearish signal. |
| `last_engulfing_top` | 2-candle | Bearish engulfing in an uptrend (final gasp / top reversal). |
| `long_black_day` | 1-candle | **BEARISH** (-1 / 0). |
| `marubozu_black` | 1-candle | **BEARISH** (-1 / 0). Black candle with no/negligible shadows. |
| `meeting_lines_bearish` | 2-candle | D1 white; D2 black opens with a gap up but closes at D1's close level. Bearish reversal. |
| `northern_doji` | 1-candle | **BEARISH** (-1 / 0). Doji in an uptrend. |
| `on_neck` | 2-candle | D1 black; D2 white opens below D1 low and closes at (within tol of) D1 low. Bearish continuation. |
| `opening_marubozu_black` | 1-candle | **BEARISH** (-1 / 0). Black candle opening at the high. |
| `separating_lines_bearish` | 2-candle | D1 white; D2 black opens at the same price as D1 (within *tol*). Bearish continuation. |
| `shooting_star` | 1-candle | **BEARISH** (-1 / 0). Small body near the bottom; long upper shadow ≥ shadow_factor × body; tiny lower shadow; typically in an uptrend. |
| `shooting_star_two_line` | 2-candle | D1 white (uptrend context); D2 gaps UP then forms a small body near the bottom with a long upper shadow.  Bearish reversal. |
| `side_by_side_white_lines_bearish` | 3-candle | D1 black; D2 & D3 are similar-sized white candles with a gap down from D1.  Bearish continuation (counter-intuitive). |
| `spinning_top_black` | 1-candle | **BEARISH** (-1 / 0). Black candle with small body and bilateral shadows. |
| `three_black_crows` | 3-candle | Three consecutive black candles; each opens inside the prior body and closes progressively lower.  Bearish continuation / reversal. |
| `three_inside_down` | 3-candle | D1 white; D2 black harami inside D1; D3 black closing below D1 open. Bearish reversal confirmed. |
| `three_line_strike_bearish` | 4+ candle | Three black crows (D1-D3) followed by a white candle (D4) that closes at-or-above D1's open.  Bearish continuation signal. |
| `three_outside_down` | 3-candle | D1 white; D2 black bearish engulfing; D3 black closing below D2. Bearish reversal confirmed. |
| `thrusting` | 2-candle | D1 black; D2 white opens below D1 low and closes between D1 low and D1 midpoint.  Weaker than piercing; bearish continuation. |
| `tri_star_bearish` | 3-candle | Three consecutive dojis in an uptrend.  Bearish reversal. |
| `tweezer_tops` | 2-candle | D1 and D2 share the same high (within *tol* of price). Bearish. |
| `two_black_gapping` | 2-candle | Two consecutive black candles with a gap DOWN between them. Bearish continuation. |
| `two_crows` | 3-candle | D1 long white; D2 black gaps up into 'star' position; D3 black opens inside D2 body and closes inside D1 body.  Bearish reversal. |
| `upside_gap_two_crows` | 3-candle | D1 long white; D2 black gaps up above D1 body; D3 black engulfs D2 but stays above D1 close.  Bearish reversal. |


### Non-directional (6)

| Pattern | Family | Definition |
|---|---|---|
| `doji` | 1-candle | **NON-DIRECTIONAL** — returns +1 for shape, 0 otherwise. Body < *threshold* × total range (default 10 %). |
| `high_wave` | 1-candle | **NON-DIRECTIONAL** — returns +1 for shape, 0 otherwise. Small real body with very long upper AND lower shadows. |
| `long_legged_doji` | 1-candle | **NON-DIRECTIONAL** — returns +1 for shape, 0 otherwise. Doji with significant shadows on BOTH sides. |
| `rickshaw_man` | 1-candle | **NON-DIRECTIONAL** — returns +1 for shape, 0 otherwise. Long-legged doji with the body near the midpoint of the range. |
| `short_black_candle` | 1-candle | **NON-DIRECTIONAL** — returns +1 for shape, 0 otherwise. Black candle with a small body (< body_thr of range). |
| `short_white_candle` | 1-candle | **NON-DIRECTIONAL** — returns +1 for shape, 0 otherwise. White candle with a small body (< body_thr of range). |

---

## 2. Chart patterns (194)

Verified live: 79 bullish, 76 bearish, 30 bidirectional, 9 non-directional.

### Bullish (79)

| Pattern | Family | Definition |
|---|---|---|
| `abc_correction` | Wave/correction | **BULLISH** (+1 / 0). Three-leg pullback within an uptrend: A (high) → B (low) → C (partial bounce below A) → D (entry, higher low than B).  Detected using recent pivot extremes. |
| `abcd_bull` | Harmonic | **BULLISH** (+1 / 0). AB=CD bullish: ABCD structure where CD ≈ AB in length. Entry at D (price expected to rise). |
| `ascending_triangle` | Triangles & wedges | **BULLISH** (+1 / 0). Flat upper resistance + rising lower support. Confirmed on close above resistance. |
| `bat_bull` | Harmonic | **BULLISH** (+1 / 0). Bat: AB/XA∈[0.382,0.50], BC/AB∈[0.382,0.886], CD/BC∈[1.618,2.618], AD/XA≈0.886. |
| `big_w` | Classic reversal | **BULLISH** (+1 / 0). Like a double bottom but larger in scale — two major troughs with a significant peak between them. |
| `broadening_bottom` | Triangles & wedges | **BULLISH** (+1 / 0). Expanding price action at a low — broader range with a bullish bias. Confirmed when price closes above the upper trendline. |
| `broadening_wedge_desc` | Triangles & wedges | **BULLISH** (+1 / 0). Both trendlines falling but diverging (upper falling faster). |
| `bump_and_run_bottom` | Specialty | **BULLISH** (+1 / 0). Downward lead-in, steep downward bump, then recovery through lead-in. |
| `busted_desc_triangle` | Triangles & wedges | **BULLISH** (+1 / 0). Descending triangle breaks down but reverses upward — bear trap. |
| `busted_double_top` | Busted | **BULLISH** (+1 / 0). Double top breaks down then reverses upward — bear trap. |
| `busted_hs_top` | Busted | **BULLISH** (+1 / 0). H&S top breaks below neckline then reverses — bear trap. |
| `busted_triple_top` | Busted | **BULLISH** (+1 / 0). Triple top breaks down then reverses. |
| `butterfly_bull` | Harmonic | **BULLISH** (+1 / 0). Butterfly: AB/XA≈0.786, BC/AB∈[0.382,0.886], CD/BC∈[1.618,2.240], AD/XA∈[1.272,1.618]. D extends beyond X. |
| `carl_v_bullish` | Reversal-day / pivot | **BULLISH** (+1 / 0). Price drops sharply, then recovers to (or above) the starting level within *window* bars — a completed V recovery. |
| `channel_desc` | Continuation | **BULLISH** (+1 / 0). Price trends downward in a parallel channel; bullish breakout above the upper channel line. |
| `closing_price_reversal_bottom` | Reversal-day / pivot | **BULLISH** (+1 / 0). Downtrend (new *n*-bar low), but closes higher than it opened. |
| `complex_hs_bottom` | Classic reversal | **BULLISH** (+1 / 0). Complex inverse H&S: multiple shoulders, looser symmetry requirement. |
| `crab_bull` | Harmonic | **BULLISH** (+1 / 0). Crab: AB/XA∈[0.382,0.618], BC/AB∈[0.382,0.886], CD/BC∈[2.240,3.618], AD/XA≈1.618. |
| `cup_with_handle` | Continuation | **BULLISH** (+1 / 0). U-shaped base (cup) followed by a brief pullback (handle). Confirmed when price closes above the cup rim. |
| `dead_cat_bounce_inv` | Specialty | **BULLISH** (+1 / 0). Sharp rise + shallow pullback — continuation rally expected. |
| `diamond_bottom` | Classic reversal | **BULLISH** (+1 / 0). Diamond bottom: broadening then contracting at a price low. |
| `diving_board` | Specialty | **BULLISH** (+1 / 0). Price dips sharply for 1-3 bars (diving board shape), then recovers. Signal fires on the recovery bar. |
| `double_bottom` | Classic reversal | **BULLISH** (+1 / 0).  Generic double bottom — any trough shapes. Two pivot lows at approximately the same level (*tol* fraction), separated by at least *min_separation* bars. Parameters ---------- mode : 'forming' \| 'confirmed' confirmed — shape + close above the peak between the two troughs. |
| `double_bottom_adam_adam` | Classic reversal | **BULLISH** (+1 / 0). Double bottom where both troughs are sharp Adam spikes. |
| `double_bottom_adam_eve` | Classic reversal | **BULLISH** (+1 / 0). Double bottom: first trough Adam (sharp), second Eve (rounded). |
| `double_bottom_eve_adam` | Classic reversal | **BULLISH** (+1 / 0). Double bottom: first trough Eve, second Adam. |
| `double_bottom_eve_eve` | Classic reversal | **BULLISH** (+1 / 0). Double bottom where both troughs are rounded Eve formations. |
| `double_bottom_ugly` | Classic reversal | MISSING |
| `double_key_reversal_bullish` | Reversal-day / pivot | **BULLISH** (+1 / 0). Reimports from candlestick module.  3-bar: D1 down, D2 key-reversal up, D3 confirms by closing above D2 close. |
| `fakey_bullish` | Specialty | **BULLISH** (+1 / 0).  Reimports semantics from candlestick hikkake_bullish. Inside bar followed by false downside break that reverses upward. |
| `falling_wedge` | Triangles & wedges | **BULLISH** (+1 / 0). Both trendlines falling but converging (upper falls faster). |
| `flag_bull` | Continuation | **BULLISH** (+1 / 0). Sharp upward move (flagpole) followed by a shallow downward parallel channel (flag).  Confirmed on breakout above the flag's upper trendline. |
| `flag_high_tight` | Continuation | **BULLISH** (+1 / 0). Very sharp rise (≥ 40 % in ~10 bars) then a tight consolidation (< 20 % retracement).  One of Bulkowski's best-performing patterns. |
| `flat_base` | Continuation | **BULLISH** (+1 / 0). Price consolidates in a narrow range (< *max_range_pct* of mean) over *window* bars while in an uptrend — bullish continuation setup. |
| `gap2h` | Gap-based | **BULLISH** (+1 / 0). Current bar opens with a gap up above the prior two bars' highs. Signals strong momentum continuation. |
| `gartley_bull` | Harmonic | **BULLISH** (+1 / 0). Gartley 222: AB/XA≈0.618, BC/AB∈[0.382,0.886], CD/BC∈[1.272,1.618], AD/XA≈0.786. |
| `hook_reversal_bottom` | Reversal-day / pivot | **BULLISH** (+1 / 0). D1: down bar (c1 < c0_prior).  D2: opens inside D1 range, closes above D1 open. Reimplemented here; semantically equivalent to the candlestick harami + confirm. |
| `horn_bottom` | Classic reversal | **BULLISH** (+1 / 0). Two spike-lows of similar depth separated by a higher middle bar. |
| `hs_bottom` | Classic reversal | **BULLISH** (+1 / 0). Inverse head-and-shoulders: two shoulders above the head (lowest trough). Confirmed when price closes above the neckline. |
| `inverted_roof` | Specialty | **BULLISH** (+1 / 0). Inverted arch: dips to a trough then curves back up. |
| `island_bottom` | Gap-based | **BULLISH** (+1 / 0). Price gaps down into island, then gaps up out — bullish reversal. |
| `key_reversal_bottom` | Reversal-day / pivot | **BULLISH** (+1 / 0). Bar makes a new *n*-bar low intraday but closes above the prior close. Classic upside key reversal. |
| `key_reversal_v2_bullish` | Reversal-day / pivot | **BULLISH** (+1 / 0). V2: new *n*-bar low AND closes above prior bar's high (stronger). |
| `measured_move_up` | Continuation | **BULLISH** (+1 / 0). Two upward legs of approximately equal length separated by a correction. Signal at the start of the second leg (or at completion). |
| `one_day_reversal_bottom` | Reversal-day / pivot | **BULLISH** (+1 / 0). Single bar that makes a new *n*-bar low but closes above the midpoint of its own range (strong recovery within the session). |
| `one_two_three_bottom` | Specialty | **BULLISH** (+1 / 0). Downtrend followed by: point-1 (low), point-2 (bounce high), point-3 (higher low > point-1), then price breaks above point-2. Signal fires at the point-2 breakout bar. |
| `open_close_reversal_bottom` | Reversal-day / pivot | **BULLISH** (+1 / 0). D1 closes near its low; D2 opens lower but closes above D1 close. |
| `outside_day_bullish` | Reversal-day / pivot | **BULLISH** (+1 / 0). Outside day (range engulfs prior) with a bullish close (c > prior high). |
| `partial_decline` | Specialty | **BULLISH** (+1 / 0). Within a consolidation, price dips toward support but fails to reach it — often precedes an upside breakout. |
| `pennant_bull` | Continuation | **BULLISH** (+1 / 0). Like a bull flag but the consolidation forms a symmetrical triangle (converging trendlines rather than parallel). |
| `pipe_bottom` | Specialty | **BULLISH** (+1 / 0). Two adjacent candles with similar deep lows — capitulation at the bottom. |
| `pivot_point_reversal_bottom` | Reversal-day / pivot | **BULLISH** (+1 / 0). D1 is a down bar; D2 gaps up (opens above D1 high) and closes higher. |
| `pothole` | Specialty | **BULLISH** (+1 / 0). A pothole is a brief downward retrace (a "pothole in the road") that digs below a recent flat base of support for 1-3 bars and then recovers, with price closing back at or above the base.  Per Bulkowski it is a bullish continuation pattern within an upward trend, not a bearish one.  The signal fires on the recovery bar. Parameters ---------- lookback : bars of flat base used as the reference level. drop_pct : minimum depth of the dip below the base, as a fraction. |
| `rectangle_bottom` | Continuation | **BULLISH** (+1 / 0). Flat support and resistance; upside breakout after an uptrend context. |
| `right_angle_broadening_desc` | Triangles & wedges | **BULLISH** (+1 / 0). Flat lower support + rising upper resistance. |
| `rising_volume_trend` | Volume-based | **BULLISH** (+1 / 0). Volume has been rising consistently over *window* bars. A rising volume trend confirms upward price moves. *min_slope_pct* is the minimum slope as a fraction of mean volume. |
| `rounding_bottom` | Classic reversal | **BULLISH** (+1 / 0). Gradual U-shaped price curve over *window* bars.  Detected by checking that the middle third of the window has lower closes than the outer thirds. |
| `scallop_asc` | Specialty | **BULLISH** (+1 / 0). Repeated J-shaped recovery (scallop) in a rising trend. |
| `scallop_desc_inv` | Specialty | **BULLISH** (+1 / 0). J-shaped recovery in a falling trend — potential bottom reversal. |
| `three_bar_bullish` | Specialty | **BULLISH** (+1 / 0). Three-bar pattern: down bar, inside or narrow bar, up bar closing above D1 open. |
| `three_lr_bullish` | Continuation | **BULLISH** (+1 / 0). Three consecutive lower lows (3 legs down) followed by a higher close. |
| `three_lr_inverted_bullish` | Continuation | **BULLISH** (+1 / 0). Inverted 3L-R: three higher lows (hammering the floor) + up close. |
| `three_valleys` | Specialty | **BULLISH** (+1 / 0). Three successive pivot lows each higher than the last — a stair-step accumulation pattern with bullish bias. |
| `triple_bottom` | Classic reversal | **BULLISH** (+1 / 0). Three pivot lows at approximately equal prices, confirmed by a close above the highest peak between the three troughs. |
| `turn_key_bullish` | Specialty | **BULLISH** (+1 / 0). 3 black candles (lower lows) then a wide white bar closing above D1 open. Reimports from candlestick multi_bar.three_line_strike_bullish semantics. |
| `two_b_bottom` | Specialty | **BULLISH** (+1 / 0). Price makes a new low, then the very next close recovers above the prior swing low, signalling a failed breakdown. |
| `two_close_bullish` | Specialty | **BULLISH** (+1 / 0). D1 is a down bar (c1 < o1).  D2 closes above D1's open. |
| `two_dance_bullish` | Specialty | **BULLISH** (+1 / 0). Two bars with similar closes (within tol), second bar white. Price consolidates at support before continuing up. |
| `two_did_bullish` | Specialty | **BULLISH** (+1 / 0). D2 closes above D1 close (D1 was a down bar) — buyers absorb selling. |
| `two_step_bullish` | Specialty | **BULLISH** (+1 / 0). 5-bar pattern: big down move (D1), partial bounce (D2-D4), resumption up (D5). Similar to breakaway_bullish from candlestick module. |
| `two_tall_bullish` | Specialty | **BULLISH** (+1 / 0). D2 is a tall (large body) white bar, significantly larger than D1 body. |
| `u_shaped_volume` | Volume-based | **BULLISH** (+1 / 0). Volume forms a U over *window* bars: declines to a trough then recovers. Signals a base-building / accumulation phase. |
| `v_bottom` | Classic reversal | **BULLISH** (+1 / 0). Sharp decline then equally sharp recovery — a V-shape. |
| `v_bottom_extended` | Classic reversal | **BULLISH** (+1 / 0). Like a V-bottom but the right side overshoots the starting price — extended recovery signals continued buying. |
| `v_pivot` | Reversal-day / pivot | **BULLISH** (+1 / 0). Bar makes a sharp new low (new *lookback*-bar low) with a small body — a V-reversal spike. High recovery from intraday low. |
| `vertical_run_up` | Volume-based | **BULLISH** (+1 / 0). *n* consecutive bars each closing in the upper *close_pct* fraction of their range — nearly vertical price climb. |
| `weekly_reversal_upside` | Reversal-day / pivot | **BULLISH** (+1 / 0). Bar makes a new *lookback*-bar low intraday but closes above the prior bar's close AND above the current open.  Applied on any timeframe. |
| `wide_ranging_day_up` | Reversal-day / pivot | **BULLISH** (+1 / 0). Bar with a very wide range (> factor × average) closing in its upper half. |
| `wolfe_wave_bull` | Harmonic | **BULLISH** (+1 / 0). Bullish Wolfe Wave: 5-pivot pattern where points 1,3,5 are lows and 2,4 are highs.  Point 5 undershoots the 1-3 trendline; entry at point 5 when price crosses above it. |


### Bearish (76)

| Pattern | Family | Definition |
|---|---|---|
| `abcd_bear` | Harmonic | **BEARISH** (-1 / 0). AB=CD bearish: entry at D (price expected to fall). |
| `bat_bear` | Harmonic | **BEARISH** (-1 / 0). Bearish bat. |
| `big_m` | Classic reversal | **BEARISH** (-1 / 0). Like a double top but larger in scale — two major peaks separated by a significant valley, with extra breadth requirements. |
| `broadening_top` | Triangles & wedges | **BEARISH** (-1 / 0). Expanding price action: both trendlines diverging (upper rising, lower falling).  Bearish bias. |
| `broadening_wedge_asc` | Triangles & wedges | **BEARISH** (-1 / 0). Both trendlines rising but diverging (lower rising faster than upper). |
| `bump_and_run_top` | Specialty | **BEARISH** (-1 / 0). Gradual lead-in trendline followed by a steep 'bump' (manic buying), then price collapses back through the lead-in line. |
| `busted_asc_triangle` | Triangles & wedges | **BEARISH** (-1 / 0). Ascending triangle breaks out upward but quickly reverses back below resistance — bears trapped the bulls. |
| `busted_double_bottom` | Busted | **BEARISH** (-1 / 0). Double bottom breaks out bullishly then collapses — bull trap. |
| `busted_hs_bottom` | Busted | **BEARISH** (-1 / 0). Inverse H&S breaks above neckline then collapses — bull trap. |
| `busted_triple_bottom` | Busted | **BEARISH** (-1 / 0). Triple bottom breaks out then collapses. |
| `butterfly_bear` | Harmonic | **BEARISH** (-1 / 0). Bearish butterfly. |
| `carl_v_bearish` | Reversal-day / pivot | **BEARISH** (-1 / 0). Price rises sharply, then collapses back to (or below) the starting level within *window* bars — an inverted V. |
| `cat_ears` | Specialty | **BEARISH** (-1 / 0). Two sharp, closely spaced peaks of similar height — like a cat's ears. A tighter, faster version of the double top. |
| `channel_asc` | Continuation | **BEARISH** (-1 / 0). Price trends upward in a parallel channel; bearish when it breaks below the lower channel line (support failure). |
| `closing_price_reversal_top` | Reversal-day / pivot | **BEARISH** (-1 / 0). Uptrend (new *n*-bar high), but closes lower than it opened. |
| `complex_hs_top` | Classic reversal | **BEARISH** (-1 / 0). Complex H&S top: multiple shoulders on one or both sides. Detected as two or more H&S patterns sharing the same head. |
| `crab_bear` | Harmonic | **BEARISH** (-1 / 0). Bearish crab. |
| `dead_cat_bounce` | Specialty | **BEARISH** (-1 / 0). After a sharp decline (≥ *drop_pct* over *window* bars), a weak bounce retraces ≤ *bounce_pct* of the drop — expect resumption of the decline. |
| `descending_triangle` | Triangles & wedges | **BEARISH** (-1 / 0). Flat lower support + descending upper resistance. Confirmed on close below support. |
| `diamond_top` | Classic reversal | **BEARISH** (-1 / 0). Broadening formation followed by a symmetrical triangle — creates a diamond shape.  First half expands, second half contracts. |
| `dome_shaped_volume` | Volume-based | **BEARISH** (-1 / 0). Volume forms an inverted U over *window* bars: rises to a climax peak, then declines.  The peak must be at least *peak_pct* of the window from either end (i.e. not at the edges).  Signals a distribution / topping phase. |
| `double_key_reversal_bearish` | Reversal-day / pivot | **BEARISH** (-1 / 0). 3-bar: D1 up, D2 key reversal down (new high + close < D1 low), D3 confirms. |
| `double_top` | Classic reversal | **BEARISH** (-1 / 0).  Generic double top — any peak shapes. Two pivot highs at approximately the same level (*tol* fraction), separated by at least *min_separation* bars. Parameters ---------- mode : 'forming' \| 'confirmed' forming   — shape complete, signal fires continuously. confirmed — shape + close below the valley between the two peaks. tol : float Max fractional difference between the two peak prices (default 3 %). min_separation : int Minimum bars between the two peaks. |
| `double_top_adam_adam` | Classic reversal | **BEARISH** (-1 / 0). Double top where both peaks are sharp Adam spikes. |
| `double_top_adam_eve` | Classic reversal | **BEARISH** (-1 / 0). Double top: first peak Adam (sharp), second Eve (rounded). |
| `double_top_eve_adam` | Classic reversal | **BEARISH** (-1 / 0). Double top: first peak Eve (rounded), second Adam (sharp). |
| `double_top_eve_eve` | Classic reversal | **BEARISH** (-1 / 0). Double top where both peaks are rounded Eve formations. |
| `fakey_bearish` | Specialty | **BEARISH** (-1 / 0).  Reimports semantics from candlestick hikkake_bearish. Inside bar followed by false upside break that reverses downward. |
| `falling_volume_trend` | Volume-based | **BEARISH** (-1 / 0). Volume has been declining consistently over *window* bars. Falling volume during a rally warns of weak buying conviction. |
| `flag_bear` | Continuation | **BEARISH** (-1 / 0). Sharp downward move followed by a shallow upward channel. |
| `gap2h_inverted` | Gap-based | **BEARISH** (-1 / 0). Current bar opens with a gap down below the prior two bars' lows. |
| `gartley_bear` | Harmonic | **BEARISH** (-1 / 0). Bearish Gartley: same ratios, inverted structure. |
| `hook_reversal_top` | Reversal-day / pivot | **BEARISH** (-1 / 0). D1 up bar; D2 opens inside D1 range and closes below D1 open. |
| `horn_top` | Classic reversal | **BEARISH** (-1 / 0). Two spike-highs of similar height separated by a smaller middle bar. |
| `hs_top` | Classic reversal | **BEARISH** (-1 / 0). Classic head-and-shoulders top: left shoulder (LS), head (H, highest), right shoulder (RS ≈ LS height), neckline through the two troughs. Confirmed when price closes below the neckline. |
| `inverted_cup_with_handle` | Continuation | **BEARISH** (-1 / 0). Inverted U-shaped top followed by a brief bounce (handle). Confirmed when price breaks below the cup base level. |
| `inverted_v_pivot` | Reversal-day / pivot | **BEARISH** (-1 / 0). Bar makes a sharp new high (new *lookback*-bar high) then collapses — a V-top spike with strong rejection from intraday high. |
| `island_top` | Gap-based | **BEARISH** (-1 / 0). Price gaps up into an island, trades there, then gaps down below the entry gap — leaving an isolated price island. |
| `key_reversal_top` | Reversal-day / pivot | **BEARISH** (-1 / 0). Bar makes a new *n*-bar high intraday but closes below the prior close. Classic downside key reversal. |
| `key_reversal_v2_bearish` | Reversal-day / pivot | **BEARISH** (-1 / 0). V2: new *n*-bar high AND closes below prior bar's low (stronger). |
| `measured_move_down` | Continuation | **BEARISH** (-1 / 0). Two downward legs of approximately equal size separated by a bounce. |
| `mountain` | Specialty | **BEARISH** (-1 / 0). Price forms a mountain: rises sharply then falls sharply back to (or below) the starting level. |
| `one_day_reversal_top` | Reversal-day / pivot | **BEARISH** (-1 / 0). Single bar: new *n*-bar high but closes below the midpoint of its range. |
| `one_two_three_top` | Specialty | **BEARISH** (-1 / 0). Uptrend followed by: point-1 (high), point-2 (pullback low), point-3 (lower high < point-1), then price breaks below point-2. |
| `open_close_reversal_top` | Reversal-day / pivot | **BEARISH** (-1 / 0). D1 closes near its high; D2 opens higher but closes below D1 close. |
| `outside_day_bearish` | Reversal-day / pivot | **BEARISH** (-1 / 0). Outside day with a bearish close (c < prior low). |
| `partial_rise` | Specialty | **BEARISH** (-1 / 0). Within a consolidation pattern (triangle/rectangle), price makes a partial rise toward resistance but fails to reach it — often precedes a downside breakout. |
| `pennant_bear` | Continuation | **BEARISH** (-1 / 0). Bear pennant: sharp drop then converging triangle. |
| `pipe_top` | Specialty | **BEARISH** (-1 / 0). Two adjacent candles with similar tall highs — exhaustion at the top. |
| `pivot_point_reversal_top` | Reversal-day / pivot | **BEARISH** (-1 / 0). D1 is an up bar; D2 gaps down (opens below D1 low) and closes lower. |
| `rectangle_top` | Continuation | **BEARISH** (-1 / 0). Price oscillates between flat support and flat resistance; breakout expected downward (bearish context = downtrend before the rectangle). |
| `right_angle_broadening_asc` | Triangles & wedges | **BEARISH** (-1 / 0). Flat upper resistance + falling lower support (right-angled, ascending bias from lows while highs are flat → bearish resolution). |
| `rising_wedge` | Triangles & wedges | **BEARISH** (-1 / 0). Both trendlines rising but converging (lower rises faster → support approaching resistance). |
| `roof` | Specialty | **BEARISH** (-1 / 0). Arched price action: rises to a peak then curves back down. Similar to rounding top but over a shorter timeframe. |
| `rounding_top` | Classic reversal | **BEARISH** (-1 / 0). Gradual inverted-U price curve. |
| `scallop_asc_inv` | Specialty | **BEARISH** (-1 / 0). Inverted ascending scallop — ∩-shape in a rising trend signals a top. |
| `scallop_desc` | Specialty | **BEARISH** (-1 / 0). Inverted J-shape (decay) in a falling trend. |
| `three_bar_bearish` | Specialty | **BEARISH** (-1 / 0). Three-bar pattern: up bar, inside bar, down bar closing below D1 open. |
| `three_lr_bearish` | Continuation | **BEARISH** (-1 / 0). Three consecutive higher highs (3 legs up) followed by a lower close. |
| `three_lr_inverted_bearish` | Continuation | **BEARISH** (-1 / 0). Inverted 3L-R: three lower highs (ceiling pressing down) + down close. |
| `three_peaks` | Specialty | **BEARISH** (-1 / 0). Three successive pivot highs each lower than the last — a stair-step distribution pattern with bearish bias. |
| `three_peaks_domed_house` | Specialty | **BEARISH** (-1 / 0). Bulkowski's 'three peaks and a domed house': three peaks followed by a broad rounded dome top before a major decline.  Approximated here as three rising peaks (the 'house' stage) then a rounded reversal. .. note:: Full Bulkowski pattern spans months; this implementation detects the completed rounding top after three prior peaks. |
| `triple_top` | Classic reversal | **BEARISH** (-1 / 0). Three pivot highs at approximately equal prices, each separated by at least *min_separation* bars, confirmed by a close below the lowest valley between the three peaks. |
| `turn_key_bearish` | Specialty | **BEARISH** (-1 / 0). 3 white candles then a wide black bar closing below D1 open. |
| `two_b_top` | Specialty | **BEARISH** (-1 / 0). Price makes a new high, then the very next close is below the prior swing high within *lookback* bars, signalling a failed breakout. |
| `two_close_bearish` | Specialty | **BEARISH** (-1 / 0). D1 is an up bar (c1 > o1).  D2 closes below D1's open. |
| `two_dance_bearish` | Specialty | **BEARISH** (-1 / 0). Two bars with similar closes, second bar black — consolidation at resistance. |
| `two_did_bearish` | Specialty | **BEARISH** (-1 / 0). D2 closes below D1 close (D1 was an up bar) — sellers absorb buying. |
| `two_step_bearish` | Specialty | **BEARISH** (-1 / 0). 5-bar pattern: big up move (D1), partial pullback (D2-D4), resumption down (D5). |
| `two_tall_bearish` | Specialty | **BEARISH** (-1 / 0). D2 is a tall black bar, significantly larger than D1 body. |
| `v_top` | Classic reversal | **BEARISH** (-1 / 0). Sharp rise then sharp fall — inverted V. |
| `v_top_extended` | Classic reversal | **BEARISH** (-1 / 0). Extended inverted V: recovery from initial top extends to new lows. |
| `vertical_run_down` | Volume-based | **BEARISH** (-1 / 0). *n* consecutive bars each closing in the lower *close_pct* of their range. |
| `weekly_reversal_downside` | Reversal-day / pivot | **BEARISH** (-1 / 0). New *lookback*-bar high intraday but closes below prior close and open. |
| `wide_ranging_day_down` | Reversal-day / pivot | **BEARISH** (-1 / 0). Wide-range bar closing in its lower half. |
| `wolfe_wave_bear` | Harmonic | **BEARISH** (-1 / 0). Bearish Wolfe Wave: 1,3,5 are highs and 2,4 are lows.  Point 5 overshoots the 1-3 trendline; entry when price falls back below it. |


### Bidirectional (30)

Direction resolves at runtime from the breakout; these are mostly the 'combined' detectors that merge their own `*_bullish`/`*_bearish` halves (per the library's own `concepts.md`).

| Pattern | Family | Definition |
|---|---|---|
| `busted_rectangle` | Busted | **BIDIRECTIONAL** (+1 or -1). Rectangle breakout fails and reverses — direction depends on which way the original breakout went. |
| `busted_sym_triangle` | Triangles & wedges | **BIDIRECTIONAL** (+1 or -1). Symmetrical triangle breakout reverses — direction is opposite to the initial breakout. |
| `carl_v` | Reversal-day / pivot | **BIDIRECTIONAL**: +1 bullish V, -1 bearish inverted-V. |
| `closing_price_reversal` | Reversal-day / pivot | **BIDIRECTIONAL**: +1 bottom, -1 top. |
| `double_key_reversal` | Reversal-day / pivot | **BIDIRECTIONAL**: +1 bullish, -1 bearish. |
| `failure_swing` | Reversal-day / pivot | **BIDIRECTIONAL** (+1 bullish / -1 bearish / 0 none). New intrabar extreme but close reverses through bar midpoint — a price-level approximation of the RSI failure swing. |
| `fakey` | Specialty | **BIDIRECTIONAL**: +1 bullish, -1 bearish. |
| `gap2h_combined` | Gap-based | **BIDIRECTIONAL**: +1 bullish gap2h, -1 bearish inverted. |
| `hook_reversal` | Reversal-day / pivot | **BIDIRECTIONAL**: +1 bottom, -1 top. |
| `key_reversal` | Reversal-day / pivot | **BIDIRECTIONAL**: +1 bottom, -1 top. |
| `key_reversal_v2` | Reversal-day / pivot | **BIDIRECTIONAL**: +1 bullish v2, -1 bearish v2. |
| `long_island` | Gap-based | **BIDIRECTIONAL** (+1 or -1). Like island reversal but spanning several days.  Direction depends on whether price exited via a gap up (+1) or gap down (-1). |
| `one_day_reversal` | Reversal-day / pivot | **BIDIRECTIONAL**: +1 bottom, -1 top. |
| `one_two_three` | Specialty | **BIDIRECTIONAL**: +1 bottom, -1 top. |
| `open_close_reversal` | Reversal-day / pivot | **BIDIRECTIONAL**: +1 bottom, -1 top. |
| `outside_day` | Reversal-day / pivot | **BIDIRECTIONAL**: +1 bullish outside day, -1 bearish. |
| `pivot_point_reversal` | Reversal-day / pivot | **BIDIRECTIONAL**: +1 bottom, -1 top. |
| `spikes` | Reversal-day / pivot | **BIDIRECTIONAL** (+1 lower spike / -1 upper spike / 0 none). Upper spike (bearish): upper wick ≥ shadow_factor × body. Lower spike (bullish): lower wick ≥ shadow_factor × body. |
| `symmetrical_triangle` | Triangles & wedges | **BIDIRECTIONAL** (+1 bullish breakout / -1 bearish / 0 none). Both trendlines converging; direction determined by confirmed breakout. |
| `three_bar` | Specialty | **BIDIRECTIONAL**: +1 bullish, -1 bearish. |
| `three_lr` | Continuation | **BIDIRECTIONAL**: +1 bullish, -1 bearish. |
| `turn_key` | Specialty | **BIDIRECTIONAL**: +1 bullish, -1 bearish. |
| `two_b` | Specialty | **BIDIRECTIONAL**: +1 bottom, -1 top. |
| `two_close` | Specialty | **BIDIRECTIONAL**: +1 bullish, -1 bearish. |
| `two_dance` | Specialty | **BIDIRECTIONAL**: +1 bullish setup, -1 bearish setup. |
| `two_did` | Specialty | **BIDIRECTIONAL**: +1 bullish, -1 bearish. |
| `two_step` | Specialty | **BIDIRECTIONAL**: +1 bullish, -1 bearish. |
| `two_tall` | Specialty | **BIDIRECTIONAL**: +1 bullish, -1 bearish. |
| `weekly_reversal` | Reversal-day / pivot | **BIDIRECTIONAL**: +1 upside, -1 downside. |
| `wide_ranging_day` | Reversal-day / pivot | **BIDIRECTIONAL**: +1 upside reversal, -1 downside reversal. |


### Non-directional (9)

| Pattern | Family | Definition |
|---|---|---|
| `cloud_bank` | Non-directional shape | **BULLISH** (+1 / 0). Recent closes cluster in a tight band (< *tol* range/mean) — a dense support zone that price is bouncing from. |
| `elevator_stop` | Non-directional shape | **NON-DIRECTIONAL** (+1 when shape fires). Last *window* closes all within *tol* of each other — temporary equilibrium at a support/resistance level. |
| `inside_day` | Non-directional shape | **NON-DIRECTIONAL** (+1 / 0). Current bar's high-low range is entirely inside the prior bar's range. NON-DIRECTIONAL WARNING: returns +1 for the shape only. |
| `narrow_range_4` | Non-directional shape | **NON-DIRECTIONAL** (+1 / 0). Current bar has the narrowest high-low range of the last 4 bars. Signals a volatility contraction — breakout expected. NON-DIRECTIONAL WARNING: returns +1 for the shape only. |
| `narrow_range_7` | Non-directional shape | **NON-DIRECTIONAL** (+1 / 0). Current bar has the narrowest range of the last 7 bars. Stronger squeeze signal than NR4. NON-DIRECTIONAL WARNING: returns +1 for the shape only. |
| `shark_32` | Non-directional shape | **NON-DIRECTIONAL** (+1 / 0). Bar 3 is an inside bar of bar 2, which is an inside bar of bar 1. Three consecutive inside bars signal extreme compression. NON-DIRECTIONAL WARNING: direction of breakout is not predicted. |
| `three_day_compression` | Non-directional shape | **NON-DIRECTIONAL** (+1 / 0). Each of the three bars has a total range less than *factor* × the range of the bar 3 bars prior.  Signals a volatility squeeze. NON-DIRECTIONAL WARNING: returns +1 for the shape — provides no inherent price direction.  Use with other context. |
| `three_dc` | Non-directional shape | Alias for :func:`three_day_compression`. |
| `volume_breakout_day` | Volume-based | **NON-DIRECTIONAL** (+1 / 0). Current bar's volume exceeds *vol_factor* × the average volume of the prior *lookback* bars, AND the bar closes more than 1 % above or below its open.  Signals a high-conviction directional move. NON-DIRECTIONAL WARNING: the +1 flag fires regardless of which direction the breakout goes.  Check the individual candle (white/black) for direction. |

---

## Summary

| Section | Count (verified live) |
|---|---|
| Candlestick — bullish | 51 |
| Candlestick — bearish | 49 |
| Candlestick — non-directional | 6 |
| **Candlestick subtotal** | **106** |
| Chart — bullish | 79 |
| Chart — bearish | 76 |
| Chart — bidirectional | 30 |
| Chart — non-directional | 9 |
| **Chart subtotal** | **194** |
| **Grand total** | **300** |

_4 of the 300 detectors above (`eight/ten/twelve/thirteen_new_price_lines`) carry no source docstring and are flagged rather than described._