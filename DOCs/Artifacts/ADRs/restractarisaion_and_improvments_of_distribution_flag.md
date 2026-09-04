# ADR: Restructuring & Improvements of the `--distribution` Flag

**Status**: Proposed  
**Date**: 2026-09-04  
**Location**: `Core/ta_patterns_book/loss_profile/`

---

## Context

The `loss-profile` CLI currently exposes several independent flags that all perform
the same conceptual operation — grouping trades along a dimension and reporting
win/loss distribution statistics:

| Current Flag | Dimension |
|---|---|
| `--distribution entry_1` | 3-candle pattern column |
| `--duration-group` | Candle duration brackets |
| `--loss-group` | Dollar loss severity brackets |
| `--projected-rr / -prr` | Projected R:R brackets |
| `--monthly` | Monthly time buckets |
| `--weekly` | Weekly time buckets |

As more distribution axes get added, this design leads to flag sprawl — each
new axis requires its own flag, its own `elif` branch in `cli.py`, and its own
reporter call. There is no unified mental model for the user.

---

## Decision

Unify all distribution-type operations under a single `--distribution` / `--dist`
flag that accepts an **axis name** as its argument. Additionally, introduce a set
of composable modifier flags to enhance analytical power across all axes.

---

## Proposed CLI Contract

### Unified Flag

```bash
uv run loss-profile --dist <axis> [modifiers]
```

`--dist` with no value defaults to `entry_1` (backward compatible).

### Supported Axes

| Axis Value(s) | Dimension Grouped |
|---|---|
| `entry_1`, `entry_2`, `entry_3`, `entry_4` | 3-candle pattern columns |
| `prr`, `rr`, `projected_rr` | Projected R:R brackets |
| `duration`, `dur`, `candles` | Candle duration brackets |
| `loss`, `pnl`, `loss_group` | Dollar loss severity brackets |
| `monthly`, `month` | Monthly time buckets |
| `weekly`, `week` | Weekly time buckets |

### Composable Modifier Flags (All Axes)

| Flag | Description |
|---|---|
| `--filter "entry_1 = DR-DR-DR"` | Filter trades by any pattern expression |
| `--losses-only` | Restrict distribution to losing trades only (pnl <= 0) |
| `--wins-only` | Restrict distribution to winning trades only (pnl > 0) |
| `--sort <field>` | Sort output by: `win%`, `trades`, `pnl` (default: natural bracket order) |
| `--top N` | Show only top N rows by the sort field |
| `--bottom N` | Show only bottom N rows by the sort field |
| `--min-trades N` | Hide rows with fewer than N trades (noise filter) |
| `--output markdown` | Render as markdown table instead of rich terminal |

---

## Example Usage After Refactor

```bash
# Pattern distribution (existing, unchanged behaviour)
uv run loss-profile --dist entry_1
uv run loss-profile --dist entry_2 --filter "entry_1 = DR-DR-DR"

# Projected R:R distribution (replaces -prr)
uv run loss-profile --dist prr
uv run loss-profile --dist prr --filter "entry_1 = DR-DR-DR"

# Candle duration (replaces --duration-group)
uv run loss-profile --dist duration
uv run loss-profile --dist duration --filter "entry_1 = DR-DR-DR"

# Dollar loss severity (replaces --loss-group)
uv run loss-profile --dist loss

# Time-based (replaces --monthly / --weekly)
uv run loss-profile --dist monthly
uv run loss-profile --dist weekly

# Composable modifiers
uv run loss-profile --dist entry_1 --sort win% --top 5
uv run loss-profile --dist prr --min-trades 10 --losses-only
uv run loss-profile --dist duration --sort pnl --bottom 3
uv run loss-profile --dist entry_1 --wins-only --min-trades 5
```

---

## Architecture Changes

### 1. `cli.py` — Simplification

**Remove** all separate distribution flags:
- `--duration-group` / `--dur-group`
- `--loss-group` / `--loss-grp`
- `--projected-rr` / `-prr`
- `--weekly` / `--wk`
- `--monthly` / `--month`

**Keep** and extend:
- `--dist` / `--distribution` as the single unified entry point

**Add** new modifier flags:
- `--wins-only`
- `--sort <field>` (choices: `win%`, `trades`, `pnl`)
- `--top N`
- `--bottom N`
- `--min-trades N`

### 2. `reporters.py` — Single Dispatch Function

Replace individual reporter calls in `main()` with a unified dispatcher:

```python
AXIS_ALIASES = {
    "prr": "prr", "rr": "prr", "projected_rr": "prr",
    "duration": "duration", "dur": "duration", "candles": "duration",
    "loss": "loss", "pnl": "loss", "loss_group": "loss",
    "monthly": "monthly", "month": "monthly",
    "weekly": "weekly", "week": "weekly",
}

def generate_distribution(axis, *, filter, losses_only, wins_only,
                          sort, top, bottom, min_trades, output_fmt):
    resolved = AXIS_ALIASES.get(axis, axis)   # default: treat as pattern col
    if resolved == "prr":        → _run_prr_distribution(...)
    elif resolved == "duration": → _run_duration_distribution(...)
    elif resolved == "loss":     → _run_loss_distribution(...)
    elif resolved == "monthly":  → _run_monthly_distribution(...)
    elif resolved == "weekly":   → _run_weekly_distribution(...)
    else:                        → _run_pattern_distribution(axis, ...)
```

Post-query modifiers (`--sort`, `--top`, `--bottom`, `--min-trades`,
`--wins-only`) are applied as **DataFrame transforms** uniformly inside
`generate_distribution()` after any axis query returns, so no SQL-layer
changes are needed.

### 3. `sql.py` — No Breaking Changes

All existing query builder functions remain as pure functions:
- `build_distribution_query` → pattern axes
- `build_duration_query` → duration axis
- `build_loss_group_query` → loss axis
- `build_projected_rr_group_query` → prr axis
- `build_monthly_query` → monthly axis
- `build_weekly_query` → weekly axis

No modifications required to `sql.py`.

---

## Future Enhancements (Phase 2)

### `--compare <axis>` — Cross-Axis Comparison

```bash
uv run loss-profile --dist prr --compare entry_1
```

Shows how projected R:R performance varies *across* each `entry_1` pattern
value, rendered as a wide pivot-style table. Answers: "does `DR-DR-DR`
outperform in the `4.0-5.0 RR` bracket compared to `UG-DR-DR`?"

### `--stack <axis>` — Nested Sub-Distribution

```bash
uv run loss-profile --dist duration --stack prr
```

Within each duration bracket row, sub-groups by R:R bracket. Effectively a
pivot table. High implementation effort but provides the deepest analytical
insight for multi-dimensional trade profiling.

---

## Migration / Backward Compatibility

| Old Command | New Equivalent |
|---|---|
| `uv run loss-profile --duration-group` | `uv run loss-profile --dist duration` |
| `uv run loss-profile --loss-group` | `uv run loss-profile --dist loss` |
| `uv run loss-profile -prr` | `uv run loss-profile --dist prr` |
| `uv run loss-profile --monthly` | `uv run loss-profile --dist monthly` |
| `uv run loss-profile --weekly` | `uv run loss-profile --dist weekly` |
| `uv run loss-profile --distribution entry_1` | `uv run loss-profile --dist entry_1` ✅ unchanged |

Old flags can be kept as hidden deprecated aliases during a transition period.

---

## Flags NOT Affected

These flags are out of scope for this refactor and remain unchanged:

| Flag | Reason |
|---|---|
| `--head` | Trade row viewer — not a distribution |
| `--loss <N>` | Renders trade playbook PNGs — not a distribution |
| `--filter` | Composable modifier — stays as-is |
| `--output` | Composable modifier — stays as-is |
| `--db` / `--view` | Infrastructure — stays as-is |
| `--duration` / `--dur` | Exact candle filter for `--head` — stays as-is |
| `--duration-till` | Upper duration bound for `--head` — stays as-is |

---

## Implementation Order

1. **Phase 1 — Unified `--dist` + Deprecation of old flags**
   - Implement axis dispatcher in `reporters.py`
   - Update `cli.py` with new flag contract
   - Keep old flags as hidden aliases (no removal yet)

2. **Phase 2 — Modifier Flags**
   - `--wins-only` (low effort, high symmetry value)
   - `--min-trades N` (low effort, noise reduction)
   - `--top N` / `--bottom N` (low effort, high insight value)
   - `--sort <field>` (medium effort)

3. **Phase 3 — Cross-Axis Features**
   - `--compare <axis>`
   - `--stack <axis>`
