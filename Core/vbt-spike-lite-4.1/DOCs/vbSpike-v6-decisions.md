---
title: vbSpike — Decision Index & Risk Register (v6)
aliases:
  - vbSpike decisions
  - vbt-tst-6-decisions
tags:
  - pipeline/backtesting
  - vectorbt
  - duckdb
  - persistence-layer
doc_type:
  - decision-index
  - risk-register
status: v6 (accepted — hardens v5's single-file design against review findings)
date: 2026-09-05
supersedes: "v5 (2026-09-05, single-file DuckDB, all forks resolved) — this revision closes gaps found in review: backup/recovery, config validation, stringly-typed columns, an undefined batch concept, and version pinning. No architectural fork reopened."
related:
  - "[[vbSpike-v6-spec]]"
  - "[[vbSpike-brif]]"
  - "[[vbSpike-v4-duckdb-brief]]"
  - "[[proposal]]"
cssclasses:
  - wide-page
---

# vbSpike — v6 decisions, scope & risk (companion to the spec)

This is the rationale half of the v6 doc: why each hardening item exists, what's explicitly out of scope, accepted trade-offs, and the risk register. For architecture, data model, config, backup mechanics, CLI, and runbook, see [[vbSpike-v6-spec]].

> [!note] v6 doesn't reopen any v5 fork. It answers the follow-up questions v5 left implicit.
> v5 correctly centralized all I/O into one DuckDB file for simplicity. A review of that design flagged five things it never stated out loud: what happens when that one file corrupts, what `config/cnf.yaml` is actually allowed to contain, why `status`/`side` are freely typeable strings, why `batch_id` exists with no `batches` table behind it, and what happens across a DuckDB version bump. None of these change the v5 architecture — they close gaps in it.

---

## 0. Decision index

Decisions are never deleted. v2's log, v4's log, and v5's log are carried forward unchanged — see prior briefs for full history. Only new v6 items appear below; each one closes a specific gap raised in review, not a reopened fork.

### New in v6

| ID | Decision | Status | Closes | Last verified |
|---|---|---|---|---|
| DL-V6-01 | Adopt a periodic backup routine: `COPY FROM DATABASE` snapshot on a schedule and always before schema changes | **Accepted** | corruption/no-backup gap | 2026-09-05 |
| DL-V6-02 | `config/cnf.yaml` gets an explicit, validated schema; the app fails loud at startup on a missing or malformed key rather than silently defaulting | **Accepted** | unvalidated config gap | 2026-09-05 |
| DL-V6-03 | `test_runs.status` and `trades[].side` become DuckDB `ENUM` types (or `CHECK` constraints if enum churn is expected) instead of free `TEXT` | **Accepted** | stringly-typed column gap | 2026-09-05 |
| DL-V6-04 | `test_runs.params` (JSON) gets a documented minimal shape, since it feeds the canonical fingerprint tuple directly | **Accepted** | undocumented fingerprint input gap | 2026-09-05 |
| DL-V6-05 | Introduce a `batches` table; `test_runs.batch_id` and `ohlcv` ingestion both reference it via foreign key instead of a dangling ID | **Accepted** | undefined "batch" concept gap | 2026-09-05 |
| DL-V6-06 | Pin the DuckDB version in `pyproject.toml`; document the upgrade procedure (snapshot, open with new version, verify, then retire the old pin) | **Accepted** | storage-format compatibility gap | 2026-09-05 |
| DL-V6-07 | Minimal structured logging to stdout (level configurable via `config/cnf.yaml`) — no framework, just consistent log lines | **Accepted** | observability gap | 2026-09-05 |
| DL-V6-08 | CLI gets `--help` and `--version`; exit codes are documented (`0` success, `1` error, `2` dedup-skip) | **Accepted** | CLI-polish gap | 2026-09-05 |
| DL-V6-09 | Concurrent access is stated explicitly: one writer at a time; read-only connections to `comparative`/`coverage` are safe while no write is in progress, unsafe mid-write | **Accepted** | concurrency-ambiguity gap | 2026-09-05 |

v2's DL-N1–N9, v4's DL-V4-01/07, and v5's DL-V5-01…07 remain Accepted and untouched. The table above **is** the v5→v6 changelog — each row already states what changed and what gap it closes, so no separate changelog is kept.

---

## 1. Why these additions

v5 made the right call collapsing everything into one file for a solo MVP — that call stands. But "one file is simpler" and "one file has no failure plan" are different claims, and v5 only justified the first one. Every item in §0 above is something a reviewer would ask about within the first week of running this in anger: what if the file corrupts, what if `cnf.yaml` gets a typo from an edit, what if `status` gets a typo, what actually is a "batch." None of these needed a new component — they needed the existing components to state their contracts explicitly instead of leaving them implicit. No component was added, removed, or re-forked; this is a hardening pass, not an architecture change.

---

## 2. Explicitly out of scope (v6)

Unchanged from v5, plus:

- **A real migration framework.** Still hand-written `ALTER`/rebuild (v5 DL-V5-07) — the backup routine ([[vbSpike-v6-spec#6. Backup and recovery|spec §6]]) is what makes that acceptable, not a replacement for it.
- **Multi-writer / distributed backup targets** (e.g. syncing to cloud storage). The backup routine writes a local snapshot file only; off-machine backup is a future decision if this ever leaves "personal project" scale.
- **A full logging/metrics stack.** DL-V6-07 is stdout lines, not structured telemetry, dashboards, or alerting.

---

## 3. Accepted trade-offs (updated from v5)

| Trade-off | What's given up | Mitigation |
|---|---|---|
| ASM-005 boundary no longer enforced | Nothing stops accidental writes to `ohlcv` from vbSpike code | Discipline only; unchanged from v5 |
| No migration framework | Manual `ALTER`/rebuild for schema changes | Backup routine (spec §6) makes a bad `ALTER` recoverable, not risk-free |
| Views instead of modules | Easier to change silently | View definitions versioned in source control, unchanged from v5 |
| Nested trades vs. relational table | Awkward if queried standalone often | `UNNEST` covers this, unchanged from v5 |
| Local-only backup | No off-machine copy if the whole disk is lost | Acceptable at personal-project scale; revisit if that changes |

Note what's **no longer** in this table versus v5: the single-file corruption risk and the unvalidated config risk both moved from "accepted trade-off" to "mitigated" (spec §6, spec §5) — they're not gone, but they're no longer unmitigated.

---

## Appendix A: Risk register

| Item | Accepted | Closed | Resolution |
|---|---|---|---|
| *(all v2/v4/v5 risks carried forward — see prior briefs)* | | | |
| **RISK-V5-A:** No migration framework | 2026-09-05 | Not closed | Unchanged from v5; backup routine (spec §6) lowers impact, doesn't close it |
| **RISK-V5-B:** ASM-005 boundary unenforced | 2026-09-05 | Not closed | Unchanged from v5 — accepted trade-off |
| **RISK-V5-C:** Views changeable silently | 2026-09-05 | Not closed | Unchanged from v5 — mitigated by source control + CI test |
| **RISK-V6-D (new):** Single DuckDB file has a documented real-world corruption mode (interrupted writes) | 2026-09-05 | **Mitigated** | Backup routine spec §6 — not eliminated, but recoverable |
| **RISK-V6-E (new):** `config/cnf.yaml` is missing required keys or malformed | 2026-09-05 | **Mitigated** | Config loader validates `config/cnf.yaml` explicitly under `vbtspike:` key at startup (spec §5) |
| **RISK-V6-F (new):** DuckDB storage format may not be forward/backward compatible across versions | 2026-09-05 | Not closed | Version pinned (DL-V6-06); upgrade procedure documented but not yet exercised |

---

**v5 and earlier** — see `proposal.md` (v5), `vbSpike-v4-duckdb-brief.md` (v4), and `vbSpike-brif.md` (v2) for full decision index and changelog history.
