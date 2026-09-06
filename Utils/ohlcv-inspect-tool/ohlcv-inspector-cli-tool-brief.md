# `ohlcv-inspector` — CLI Tool Brief (for agent use)

**Purpose of this document:** give a coding agent everything it needs to decide *when* to call this tool, *how* to call it, and *how to interpret* what comes back — without needing to read source code first.

**What this tool is:** a read-only, standalone CLI (Python, `uv` project) that inspects an OHLCV candle table in DuckDB and reports data-quality problems and statistical abnormalities. It never modifies data. It is safe to call at any time.

---

## 1. When to use this tool

| Situation | Command to reach for |
|---|---|
| "Is this OHLCV table safe to use for backtesting/training?" | `run` |
| "I just ingested new data, did anything break?" | `run --incremental` |
| "Does this table even have the columns I expect, before I do anything else?" | `schema check` |
| "What checks does this tool even support?" | `checks list` |
| "What does check X actually do / why did it fire?" | `checks describe <name>` |
| "I want to see the exact SQL/logic without running it" | `run --dry-run` |
| "Is the data stale / has ingestion stopped?" | `run --checks freshness` (or full `run`, freshness is included by default) |
| "Something looks off with symbol X only" | `run --symbol X` |
| "I only care about hard errors, not statistical flags" | `run --tier quality` |
| "I want to know if there's anything statistically weird, even if technically valid" | `run --tier anomaly` |

**Rule of thumb for the agent:** call `schema check` first on a table you haven't seen before (cheap, fast, fails clearly if columns are wrong). Then call `run` for the real inspection. Use `--format json` always when consuming output programmatically — `text` output is for humans only.

---

## 2. Command reference

All commands follow a `noun → verb` / `verb` pattern and are non-interactive by default (never prompts, safe for unattended agent use).

### `ohlcv-inspector run`
Runs the inspection and produces a report.

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--db PATH` | string | required | Path to DuckDB file, or `:memory:` with `--attach` |
| `--table NAME` | string | required | Table name, or use `--query` for an arbitrary SQL source |
| `--query SQL` | string | — | Alternative to `--table` for ad hoc/derived sources |
| `--symbol SYM[,SYM...]` | string | all | Restrict to one or more symbols |
| `--start DATE` / `--end DATE` | ISO date | all | Restrict time range |
| `--tier {quality,anomaly,all}` | enum | `all` | Which check tier(s) to run |
| `--checks NAME[,NAME...]` | string | all enabled | Run only named checks (see `checks list`) |
| `--exclude-checks NAME[,...]` | string | none | Disable specific checks |
| `--config PATH` | string | built-in defaults | YAML config for thresholds/column mapping |
| `--column-map open=o,high=h,...` | string | identity | Inline column mapping override |
| `--incremental` | flag | off | Only inspect rows newer than last checkpoint |
| `--full` | flag | off | Force full rescan, ignoring checkpoint |
| `--dry-run` | flag | off | Print the SQL/logic that would run; do not execute |
| `--format {text,json,csv}` | enum | `text` | Output format |
| `--output PATH` | string | stdout | Write report to file instead of stdout |
| `--verbose` / `--quiet` | flag | normal | Adjust output verbosity |
| `--yes` | flag | off | Suppress any confirmation (reserved; `run` never prompts today) |

**Exit codes:** see §4.

### `ohlcv-inspector schema check`
Fast, upfront validation that the table exists and columns match the expected types/mapping — before running full checks.

| Flag | Notes |
|---|---|
| `--db`, `--table`, `--column-map` | same as `run` |
| `--format {text,json}` | default `text` |

Exit codes: `0` schema OK, `3` schema mismatch (missing/wrong-typed column), `4` cannot connect to DB.

### `ohlcv-inspector checks list`
Enumerates every available check.

| Flag | Notes |
|---|---|
| `--tier {quality,anomaly,all}` | filter by tier |
| `--format {text,json}` | JSON returns `[{name, tier, severity, description}]` |

### `ohlcv-inspector checks describe <name>`
Prints what a specific check does, its default threshold(s), and an example of a row that would trigger it.

### `ohlcv-inspector config validate`
Validates a config file (thresholds, column mapping, enabled checks) without running anything. Useful for an agent to sanity-check a generated config before a real run.

| Flag | Notes |
|---|---|
| `--config PATH` | required |
| `--format {text,json}` | default `text` |

### `ohlcv-inspector version`
Prints tool version, check-registry version, and default config version — all three matter for reproducibility (see §6).

---

## 3. Check tiers (what gets run)

| Tier | Nature | Examples | Result semantics |
|---|---|---|---|
| **quality** | Deterministic, provably-wrong rules | null OHLCV, `high < low`, duplicate `(symbol, timestamp)`, negative volume, schema/type mismatch, calendar gaps, staleness/freshness | `error` (hard) or `warning` (soft) — pass/fail |
| **anomaly** | Statistical/behavioral, probabilistic | price spike + reversion, frozen/stale repeated bars, volume z-score spike, volume-price divergence, regime/volatility shift, multivariate outlier (Isolation Forest) | `flagged` with a numeric anomaly score — never a hard failure by itself |

Quality-tier violations can fail a pipeline (see exit codes). Anomaly-tier results are **for review**, not failure, unless the agent's calling context explicitly treats them as blocking.

**Not covered by this tool:** order-book-level manipulation patterns (spoofing, layering, wash trading) — these require tick/order data this tool does not have access to. If asked to detect those, say so rather than attempting it via OHLCV alone.

---

## 4. Exit codes (authoritative — branch on these, not on text)

| Code | Meaning | Agent action |
|---|---|---|
| `0` | Clean — no errors, no warnings, no flags | Proceed normally |
| `1` | Soft warnings and/or anomaly flags present, no hard errors | Data usable but worth surfacing to the user; safe to proceed with caution |
| `2` | Hard (quality-tier) errors found | Data should **not** be used as-is; do not proceed silently |
| `3` | Usage or config error (bad flags, invalid config, schema mismatch) | Fix the invocation/config, don't retry as-is |
| `4` | Runtime/connection error (can't open DB, table not found, transient failure) | Safe to retry; may be transient |

---

## 5. JSON output shape (for `--format json`)

```json
{
  "meta": {
    "tool_version": "0.1.0",
    "check_registry_version": "2026-09-01",
    "config_source": "config.yaml",
    "db": "candles.duckdb",
    "table": "ohlcv_1m",
    "symbols": ["AAPL"],
    "start": "2026-01-01",
    "end": "2026-09-01",
    "run_at": "2026-09-06T10:15:00Z"
  },
  "summary": [
    {"check": "high_ge_low", "tier": "quality", "severity": "error", "violations": 3, "pct_rows": 0.001},
    {"check": "volume_zscore_spike", "tier": "anomaly", "severity": "flagged", "violations": 12, "pct_rows": 0.004}
  ],
  "details": [
    {
      "check": "high_ge_low",
      "tier": "quality",
      "severity": "error",
      "symbol": "AAPL",
      "timestamp": "2026-03-14T09:31:00Z",
      "values": {"open": 172.1, "high": 171.9, "low": 172.3, "close": 172.0},
      "message": "high < low",
      "score": null
    },
    {
      "check": "volume_zscore_spike",
      "tier": "anomaly",
      "severity": "flagged",
      "symbol": "AAPL",
      "timestamp": "2026-03-14T14:02:00Z",
      "values": {"volume": 985000, "rolling_median_volume": 42000},
      "message": "volume 12.3x rolling median (robust z-score 8.7)",
      "score": 8.7
    }
  ],
  "exit_code": 2
}
```

**Error responses** (schema/config/connection failures) use a distinct shape so the agent can branch without parsing prose:

```json
{
  "error_type": "column_not_found",
  "input": "close_price",
  "available_columns": ["open", "high", "low", "close", "volume", "ts"],
  "suggestion": "pass --column-map close=close_price or fix the source table",
  "exit_code": 3
}
```

---

## 6. Reproducibility contract

Every run — text or JSON — includes `tool_version`, `check_registry_version`, and `config_source` in its output. If an agent re-runs the same command later and gets a different result, it should check whether any of those three changed before assuming the underlying data changed. Thresholds are never silently updated between runs; a config file is required to change them, and the file path/hash is echoed back in `meta`.

---

## 7. Example agent workflows

**A. First contact with an unfamiliar table**
```
ohlcv-inspector schema check --db candles.duckdb --table ohlcv_1m --format json
ohlcv-inspector run --db candles.duckdb --table ohlcv_1m --format json
```
Branch on exit code: `0`/`1` → proceed; `2` → surface hard errors to user before using the data; `3` → fix schema/column-map first.

**B. Post-ingestion sanity check in a pipeline**
```
ohlcv-inspector run --db candles.duckdb --table ohlcv_1m --incremental --format json --output last_run.json
```
Exit code gates the next pipeline step; `last_run.json` is the audit trail.

**C. Investigating a specific symbol a user flagged as "looks wrong"**
```
ohlcv-inspector run --db candles.duckdb --table ohlcv_1m --symbol TSLA --tier all --format json
```

**D. Explaining a result to the user**
```
ohlcv-inspector checks describe volume_zscore_spike --format text
```
Use this to translate a check name from a report into a plain-language explanation before showing the user.

**E. Dry-run before trusting a new config**
```
ohlcv-inspector config validate --config custom.yaml
ohlcv-inspector run --db candles.duckdb --table ohlcv_1m --config custom.yaml --dry-run
```

---

## 8. Things the agent should NOT do

- Don't retry on exit code `2` or `3` without changing something — the data or the invocation is genuinely wrong, retrying identically will not help.
- Don't treat `anomaly` tier flags as failures by default — they require judgment (real event vs. bad data); surface them, don't auto-reject.
- Don't parse `text`-format output programmatically — always use `--format json` for anything the agent will branch on.
- Don't assume this tool detects order-flow manipulation (spoofing/wash trading) — it only sees OHLCV bars.
