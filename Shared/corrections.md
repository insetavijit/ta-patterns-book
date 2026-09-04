# Historical Corrections Log

This document records explicit user corrections and operational guidelines to prevent repeating mistakes in future tasks.

---

## 1. Directory Routing & Output Placement (`cnf.yaml`)
- **Correction**: Always strictly follow `Shared/cnf.yaml` and `DOCs/agents/dir-tree.md` for output file locations.
- **Rule**: All generated PNG charts and rendered visual outputs MUST be saved into `Shared/OUTs/png/` (`paths.shared.outputs.png`), never in temporary scratch directories or unmapped paths.

---

## 2. Suo-Moto Artifact & Markdown Creation
- **Correction**: Do not generate unsolicited artifacts or Markdown files.
- **Rule**: Never create `.md` files or workspace artifacts unless explicitly requested by the user. Ask for permission first if you feel the need to create one.

---

## 3. Database Column & Schema Verification
- **Correction**: Never guess table column names or table schemas in DuckDB SQL queries.
- **Rule**: Inspect schemas beforehand via `duckdb_explorer` (e.g., column `duration_candel` vs `duration_candles`).
