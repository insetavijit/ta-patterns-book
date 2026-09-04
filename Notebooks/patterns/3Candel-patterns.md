# 3-Candle Pattern Combination Problem

## Problem

We want to discover and analyze new **3-candle patterns** by representing each candle using two properties:

* **Direction:** `U` = Up, `D` = Down
* **Color:** `R` = Red, `G` = Green

This gives each candle four possible states:

`UR`, `UG`, `DR`, `DG`

The goal is to enumerate every possible combination of these states across three consecutive candles.

## Solution

For three candles, each candle has **4 possible states**:

`4 × 4 × 4 = 4³ = 64`

Therefore, there are **64 unique 3-candle combinations** when both direction and color are allowed to vary.

If the **color pattern is fixed**, for example `R-G-G`, only the direction can vary. Each of the three candles has 2 possible directions:

`2 × 2 × 2 = 2³ = 8`

Therefore, the `R-G-G` pattern produces **8 unique combinations**:

```text
UR-UG-UG
UR-UG-DG
UR-DG-UG
UR-DG-DG
DR-UG-UG
DR-UG-DG
DR-DG-UG
DR-DG-DG
```

### General Rule

For `N` candles:

* **Any color + direction:** `4^N` combinations
* **Fixed color sequence + variable direction:** `2^N` combinations

This provides a systematic way to generate and test candle-pattern combinations against historical market data.
