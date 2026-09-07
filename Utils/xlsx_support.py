#!/usr/bin/env python3
"""
xlsx_support.py -- a single-file, agent-friendly CLI for CRUD operations on
Excel (.xlsx / .xlsm) workbooks.

See `xlsx_support.py describe` for the full, machine-readable command/flag
surface, or `xlsx_support.py <command> -h` for human help.

Design principles (see spec):
  1. Read-only by default -- any command that saves the workbook requires --write.
  2. Every response is a versioned JSON envelope:
     {tool, schema_version, command, success, data, meta, error}.
  3. No prompts, no interactive state -- one invocation, one result.
  4. Distinct exit codes so an agent can branch without parsing text.
  5. Global --limit caps rows returned anywhere.
  6. Prefers library built-ins: openpyxl for cell-level writes, pandas for
     bulk table-shaped reads.
  7. `read` is the escape hatch for anything not covered by a dedicated command.
  8. `describe` emits the full command/flag surface as JSON.
  9. Formula-writing commands trigger LibreOffice recalculation automatically.

Dependencies: openpyxl, pandas (both required). LibreOffice (`soffice` on
PATH) is required only for commands that write formulas.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

try:
    import openpyxl
    from openpyxl.utils import column_index_from_string, get_column_letter
    from openpyxl.utils.cell import coordinate_from_string
    from openpyxl.utils.exceptions import InvalidFileException
    from openpyxl.cell.cell import MergedCell
    from openpyxl.worksheet.formula import ArrayFormula
except ImportError as e:  # pragma: no cover
    print(json.dumps({
        "tool": "xlsx_support", "schema_version": "1.0", "command": None,
        "success": False, "data": None, "meta": {},
        "error": {"message": f"openpyxl is required but not importable: {e}",
                   "exit_code": 3, "details": {}},
    }))
    sys.exit(3)

try:
    import pandas as pd
except ImportError as e:  # pragma: no cover
    pd = None

TOOL_NAME = "xlsx_support"
SCHEMA_VERSION = "1.0"
TOOL_VERSION = "1.0.0"

# --------------------------------------------------------------------------
# Exit codes
# --------------------------------------------------------------------------
EXIT_OK = 0
EXIT_READ_ERROR = 1
EXIT_FILE_NOT_FOUND = 2
EXIT_ARG_ERROR = 3
EXIT_WRITE_NOT_ALLOWED = 4
EXIT_TIMEOUT = 5
EXIT_NOT_FOUND = 6
EXIT_CONFLICT = 7

SHEET_NAME_ILLEGAL = set(':\\/?*[]')
EXCEL_ERROR_LITERALS = ["#VALUE!", "#DIV/0!", "#REF!", "#NAME?", "#NULL!", "#NUM!", "#N/A"]
UNSAFE_SPILL_FUNCS = ["XLOOKUP", "XMATCH", "SORT(", "FILTER(", "UNIQUE(", "SEQUENCE("]
SAFE_PREFIXED_FUNCS = {
    "TEXTJOIN": "_xlfn.TEXTJOIN", "CONCAT": "_xlfn.CONCAT", "IFS": "_xlfn.IFS",
    "SWITCH": "_xlfn.SWITCH", "MAXIFS": "_xlfn.MAXIFS", "MINIFS": "_xlfn.MINIFS",
}
EXTERNAL_REF_RE = re.compile(r"""(?<![\w"\[])'?\[\d+\][^!"\[\]]*'?!""")


class ToolError(Exception):
    """Carries an exit code and structured details through to the envelope."""

    def __init__(self, message, exit_code, details=None):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.details = details or {}


# --------------------------------------------------------------------------
# Envelope + output rendering
# --------------------------------------------------------------------------

def make_envelope(command, success, data=None, meta=None, error=None):
    return {
        "tool": TOOL_NAME,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "success": success,
        "data": data,
        "meta": meta or {},
        "error": error,
    }


def error_envelope(command, err: ToolError):
    return make_envelope(
        command, False, data=None, meta={},
        error={"message": err.message, "exit_code": err.exit_code, "details": err.details},
    )


def _rows_to_table_lines(rows, columns=None, markdown=False):
    if not rows:
        return ["(no rows)"]
    if isinstance(rows[0], dict):
        cols = columns or list(rows[0].keys())
        matrix = [[("" if r.get(c) is None else str(r.get(c))) for c in cols] for r in rows]
    else:
        cols = columns or [f"col{i+1}" for i in range(len(rows[0]))]
        matrix = [[("" if v is None else str(v)) for v in r] for r in rows]
    widths = [max(len(str(c)), *(len(row[i]) for row in matrix)) for i, c in enumerate(cols)]
    lines = []
    header = " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(cols))
    lines.append(header)
    if markdown:
        lines.append(" | ".join("-" * widths[i] for i in range(len(cols))))
    else:
        lines.append("-+-".join("-" * w for w in widths))
    for row in matrix:
        lines.append(" | ".join(row[i].ljust(widths[i]) for i in range(len(cols))))
    return lines


def render(envelope, args):
    fmt = getattr(args, "output", "json")
    pretty = getattr(args, "pretty", False)
    nl = getattr(args, "nl", False)

    if nl or fmt == "ndjson":
        data = envelope["data"]
        if envelope["success"] and isinstance(data, list):
            for row in data:
                print(json.dumps(row, default=str))
        else:
            print(json.dumps(envelope, default=str))
        return

    if fmt in ("table", "markdown"):
        data = envelope["data"]
        if envelope["success"] and isinstance(data, list) and data:
            columns = envelope.get("meta", {}).get("columns")
            for line in _rows_to_table_lines(data, columns=columns, markdown=(fmt == "markdown")):
                print(line)
            return
        # fall through to JSON for non-tabular / empty / error payloads
        print(json.dumps(envelope, indent=2, default=str))
        return

    print(json.dumps(envelope, indent=2 if pretty else None, default=str))


# --------------------------------------------------------------------------
# Workbook / sheet helpers
# --------------------------------------------------------------------------

def open_workbook(path, keep_vba=None):
    if not path:
        raise ToolError("No file path given", EXIT_ARG_ERROR)
    p = Path(path)
    if not p.is_file():
        raise ToolError(f"File not found: {path}", EXIT_FILE_NOT_FOUND)
    if p.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ToolError(f"Not a .xlsx/.xlsm workbook: {path}", EXIT_FILE_NOT_FOUND)
    if keep_vba is None:
        keep_vba = p.suffix.lower() == ".xlsm"
    try:
        return openpyxl.load_workbook(str(p), data_only=False, keep_vba=keep_vba)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, OSError) as e:
        raise ToolError(f"Could not open workbook: {e}", EXIT_FILE_NOT_FOUND)
    except Exception as e:
        raise ToolError(f"Could not parse workbook: {e}", EXIT_READ_ERROR)


def get_sheet(wb, name):
    if name is None:
        return wb.active
    if name not in wb.sheetnames:
        raise ToolError(
            f"Sheet not found: {name}", EXIT_NOT_FOUND,
            {"available_sheets": wb.sheetnames},
        )
    return wb[name]


def sanitize_sheet_name(name, existing):
    if not name:
        raise ToolError("Sheet name cannot be empty", EXIT_ARG_ERROR)
    cleaned = "".join(ch for ch in name if ch not in SHEET_NAME_ILLEGAL)
    cleaned = cleaned.strip("'")[:31] or "Sheet"
    base = cleaned
    n = 1
    while cleaned in existing:
        suffix = f"_{n}"
        cleaned = (base[: 31 - len(suffix)] + suffix)
        n += 1
    return cleaned


def exact_max_row(ws):
    """A true scan for the last row containing a non-empty value, vs.
    openpyxl's ws.max_row which counts any cell ever touched (incl. cleared
    but formatted cells)."""
    last = 0
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None:
                last = max(last, cell.row)
    return last


def header_map(ws, header_row):
    headers = {}
    for cell in ws[header_row]:
        if cell.value is not None:
            headers[str(cell.value)] = cell.column
    if not headers:
        raise ToolError(
            f"No header values found on row {header_row}", EXIT_ARG_ERROR,
            {"header_row": header_row},
        )
    return headers


def row_as_dict(ws, row_num, headers):
    return {name: ws.cell(row=row_num, column=col).value for name, col in headers.items()}


def row_is_empty(row_dict):
    return all(v is None for v in row_dict.values())


# --------------------------------------------------------------------------
# Filter expression parsing:  "col == val" | "col != val" | "col > val" | ...
# --------------------------------------------------------------------------

_FILTER_RE = re.compile(r"^\s*(?P<col>[^=!<>~]+?)\s*(?P<op>==|!=|>=|<=|~=|=|>|<)\s*(?P<val>.*)$")


def parse_filter(expr):
    m = _FILTER_RE.match(expr)
    if not m:
        raise ToolError(f"Could not parse filter expression: {expr!r}", EXIT_ARG_ERROR)
    col = m.group("col").strip()
    op = m.group("op")
    val = m.group("val").strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
        val = val[1:-1]
    return col, ("==" if op == "=" else op), val


def _coerce(raw):
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    if raw.lower() in ("none", "null", ""):
        return None
    try:
        if re.fullmatch(r"-?\d+", raw):
            return int(raw)
        return float(raw)
    except ValueError:
        return raw


def row_matches(row, col, op, raw_val):
    if col not in row:
        return False
    cell_val = row[col]
    target = _coerce(raw_val)
    if op == "~=":
        return str(target).lower() in ("" if cell_val is None else str(cell_val).lower())
    if op == "==":
        if isinstance(cell_val, (int, float)) and isinstance(target, (int, float)):
            return cell_val == target
        return ("" if cell_val is None else str(cell_val)) == ("" if target is None else str(target))
    if op == "!=":
        return not row_matches(row, col, "==", raw_val)
    # ordering comparisons
    try:
        a, b = float(cell_val), float(target)
    except (TypeError, ValueError):
        a, b = ("" if cell_val is None else str(cell_val)), ("" if target is None else str(target))
    if op == ">":
        return a > b
    if op == "<":
        return a < b
    if op == ">=":
        return a >= b
    if op == "<=":
        return a <= b
    raise ToolError(f"Unsupported filter operator: {op}", EXIT_ARG_ERROR)


# --------------------------------------------------------------------------
# LibreOffice recalculation (principle 9 / spec section 7)
# --------------------------------------------------------------------------

RECALCULATE_MACRO = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">
<script:module xmlns:script="http://openoffice.org/2000/script" script:name="Module1" script:language="StarBasic">
    Sub RecalculateAndSave()
      ThisComponent.calculateAll()
      ThisComponent.store()
      ThisComponent.close(True)
    End Sub
</script:module>"""


def _soffice_env():
    env = os.environ.copy()
    env["SAL_USE_VCLPLUGIN"] = "svp"
    return env


def _stamp(path):
    st = os.stat(path)
    return st.st_mtime_ns, st.st_size


def external_links_at_risk(path):
    """Cells whose formula reaches into another workbook and whose cached
    value openpyxl already stripped -- recalculating would resolve these to
    #NAME? and delete the link for good."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except (zipfile.BadZipFile, OSError):
        return []
    if not any(n.startswith("xl/externalLinks/") for n in names):
        return []

    formulas = openpyxl.load_workbook(path, data_only=False)
    values = openpyxl.load_workbook(path, data_only=True)
    at_risk = []
    for sheet in formulas.sheetnames:
        ws, cached = formulas[sheet], values[sheet]
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if isinstance(v, ArrayFormula):
                    v = v.text
                if not (isinstance(v, str) and v.startswith("=")):
                    continue
                if EXTERNAL_REF_RE.search(v) and cached[cell.coordinate].value is None:
                    at_risk.append(f"{sheet}!{cell.coordinate}")
    formulas.close()
    values.close()
    return at_risk


def recalculate(path, timeout=30, force=False):
    """Recalculate every formula in `path` via headless LibreOffice, rewriting
    the file in place. Returns a meta dict on success; raises ToolError on
    failure to invoke LibreOffice itself (missing binary, timeout, crash)."""
    abs_path = str(Path(path).resolve())

    if not force:
        at_risk = external_links_at_risk(abs_path)
        if at_risk:
            raise ToolError(
                "Refusing to recalculate: this workbook links to another workbook and "
                f"{len(at_risk)} linked cell(s) already lost their cached value. "
                "Recalculating would resolve them to #NAME? and delete the external "
                "links permanently. Re-run with --force to accept the loss.",
                EXIT_ARG_ERROR,
                {"external_link_cells": at_risk[:100], "external_link_cells_truncated": max(0, len(at_risk) - 100)},
            )

    if shutil.which("soffice") is None and shutil.which("libreoffice") is None:
        raise ToolError(
            "soffice/libreoffice not found on PATH; it is required to recalculate "
            "formulas (openpyxl never caches formula results).",
            EXIT_READ_ERROR,
        )

    with tempfile.TemporaryDirectory(prefix="xlsx-support-lo-", ignore_cleanup_errors=True) as profile_dir:
        profile_url = Path(profile_dir).as_uri()
        try:
            subprocess.run(
                ["soffice", "--headless", "--terminate_after_init",
                 f"-env:UserInstallation={profile_url}"],
                capture_output=True, timeout=timeout, env=_soffice_env(), check=False,
            )
        except FileNotFoundError:
            raise ToolError("soffice not found on PATH", EXIT_READ_ERROR)
        except subprocess.TimeoutExpired:
            raise ToolError("LibreOffice timed out creating its profile", EXIT_TIMEOUT)

        macro_dir = Path(profile_dir) / "user" / "basic" / "Standard"
        if not macro_dir.exists():
            raise ToolError("LibreOffice did not create a usable profile", EXIT_READ_ERROR)
        (macro_dir / "Module1.xba").write_text(RECALCULATE_MACRO)

        before = _stamp(abs_path)
        cmd = ["soffice", "--headless", "--norestore", f"-env:UserInstallation={profile_url}",
               "vnd.sun.star.script:Standard.Module1.RecalculateAndSave?language=Basic&location=application",
               abs_path]
        if platform.system() == "Linux" and shutil.which("timeout"):
            cmd = ["timeout", str(timeout)] + cmd

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, env=_soffice_env(), timeout=timeout + 15)
        except subprocess.TimeoutExpired:
            raise ToolError(f"LibreOffice timed out after {timeout}s; formulas were NOT recalculated", EXIT_TIMEOUT)

        if result.returncode != 0:
            detail = (result.stderr or "").strip() or f"soffice exited {result.returncode}"
            raise ToolError(f"LibreOffice failed to recalculate: {detail}", EXIT_READ_ERROR)

        if _stamp(abs_path) == before:
            raise ToolError(
                "LibreOffice exited cleanly but never rewrote the file; nothing was recalculated. "
                "Check for another running LibreOffice instance and retry.",
                EXIT_READ_ERROR,
            )

    # Post-check for formula errors, matching validate's logic.
    wb = openpyxl.load_workbook(abs_path, data_only=True)
    total_formulas = 0
    error_locations = {}
    fwb = openpyxl.load_workbook(abs_path, data_only=False)
    for sheet_name in fwb.sheetnames:
        for row in fwb[sheet_name].iter_rows():
            for cell in row:
                v = cell.value
                if isinstance(v, ArrayFormula):
                    v = v.text
                if isinstance(v, str) and v.startswith("="):
                    total_formulas += 1
    for sheet_name in wb.sheetnames:
        for row in wb[sheet_name].iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    for err in EXCEL_ERROR_LITERALS:
                        if err in cell.value:
                            error_locations.setdefault(err, []).append(f"{sheet_name}!{cell.coordinate}")
    total_errors = sum(len(v) for v in error_locations.values())
    wb.close()
    fwb.close()
    return {
        "recalculated": True,
        "status": "errors_found" if total_errors else "success",
        "total_formulas": total_formulas,
        "total_errors": total_errors,
        "error_summary": {k: v[:100] for k, v in error_locations.items()},
    }


def formula_needs_recalc(value):
    return isinstance(value, str) and value.startswith("=")


def check_unsafe_formula(value):
    """Returns a warning string if `value` is a formula LibreOffice can't
    (safely) evaluate, else None."""
    if not isinstance(value, str) or not value.startswith("="):
        return None
    upper = value.upper()
    for fn in UNSAFE_SPILL_FUNCS:
        if fn in upper:
            return (f"{value!r} uses {fn.rstrip('(')}, a spilling array function with no spill "
                     "metadata in an openpyxl-written file; only the top-left cell will populate "
                     "and recalculation will report zero errors on the truncated result. Use "
                     "INDEX/MATCH instead.")
    for bare, prefixed in SAFE_PREFIXED_FUNCS.items():
        if re.search(rf"(?<![A-Za-z0-9_.]){bare}\s*\(", upper) and prefixed.upper() not in upper:
            return (f"{value!r} calls {bare}, a post-2007 function that must be written as "
                     f"{prefixed} (Excel hides this prefix in its UI but stores it in the file). "
                     "Written bare it will evaluate to #NAME?.")
    return None


def normalize_value(raw):
    """CLI values arrive as strings; coerce obvious ints/floats/bools so
    numeric cells don't get written as text. Leave formulas (leading '=')
    and everything else as-is."""
    if not isinstance(raw, str):
        return raw
    if raw.startswith("="):
        return raw
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)
    return raw


# --------------------------------------------------------------------------
# Command implementations. Each returns (data, meta) and raises ToolError.
# --------------------------------------------------------------------------

def cmd_version(args):
    data = {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "python_version": platform.python_version(),
        "openpyxl_version": getattr(openpyxl, "__version__", "unknown"),
        "pandas_version": getattr(pd, "__version__", None) if pd else None,
        "soffice_available": bool(shutil.which("soffice") or shutil.which("libreoffice")),
    }
    return data, {}


def cmd_describe(args):
    data = {
        "tool": TOOL_NAME,
        "schema_version": SCHEMA_VERSION,
        "exit_codes": {
            "0": "Success", "1": "Read/parse error", "2": "File not found / invalid workbook",
            "3": "Argument or validation error", "4": "Write attempted without --write",
            "5": "Operation timed out", "6": "Sheet, row, or cell not found",
            "7": "Concurrent write conflict (reserved, not wired up)",
        },
        "global_flags": [
            "--write", "--sheet NAME", "--header-row N", "--output {json,ndjson,table,markdown}",
            "--limit N", "--pretty", "--arrays", "--nl", "--quiet", "--exact",
        ],
        "commands": {
            "list-sheets": {"tier": "v1", "write": False, "args": []},
            "schema": {"tier": "v1", "write": False, "args": ["--sheet", "--sample-size"]},
            "read": {"tier": "v1", "write": False, "args": ["--sheet", "--filter", "--columns", "-n/--limit", "--offset"]},
            "stats": {"tier": "v1", "write": False, "args": []},
            "health-check": {"tier": "v1", "write": False, "args": []},
            "version": {"tier": "v1", "write": False, "args": []},
            "describe": {"tier": "v1", "write": False, "args": []},
            "write-row": {"tier": "v1", "write": True, "args": ["--sheet", "--values", "--at", "--where"]},
            "delete-row": {"tier": "v1", "write": True, "args": ["--sheet", "--at", "--where", "--all-matches"]},
            "set-cell": {"tier": "v1", "write": "conditional (write only when --value given)", "args": ["--sheet", "--cell", "--value"]},
            "add-sheet": {"tier": "v1", "write": True, "args": ["--sheet", "--after", "--index"]},
            "delete-sheet": {"tier": "v1", "write": True, "args": ["--sheet"]},
            "import": {"tier": "v1", "write": True, "args": ["--sheet", "--file", "--replace"]},
            "export": {"tier": "v1", "write": False, "args": ["--sheet", "--format", "--out", "--filter"]},
            "validate": {"tier": "v1.1", "write": False, "args": []},
            "convert": {"tier": "v1.1", "write": False, "args": [], "implemented": False},
            "detect-types": {"tier": "v1.1", "write": False, "args": [], "implemented": False},
            "dedupe": {"tier": "v2", "write": True, "args": [], "implemented": False},
            "rename-columns": {"tier": "v2", "write": True, "args": [], "implemented": False},
            "diff": {"tier": "v2", "write": False, "args": [], "implemented": False},
        },
        "known_constraints": [
            "openpyxl max_row/max_column overcounts cleared-but-formatted cells; use --exact for a true scan.",
            "Formula cells have no cached value until recalculated; write commands that add formulas auto-recalculate via LibreOffice.",
            "Only pre-2007 functions and six _xlfn.-prefixed ones survive LibreOffice recalculation; XLOOKUP/XMATCH/SORT/FILTER/UNIQUE/SEQUENCE are never safe.",
            "Merged cells accept a value only at the top-left anchor.",
            "Re-saving a workbook with external-workbook links can delete them on recalculation; refused by default, override with --force-recalc.",
            "Excel sheet names: 31 chars max, ':\\/?*[]' disallowed.",
            "Every save rewrites the whole workbook (no incremental write).",
            "No concurrency control (exit code 7 reserved, not wired up in v1).",
        ],
    }
    return data, {}


def cmd_health_check(args):
    try:
        wb = open_workbook(args.file)
    except ToolError as e:
        return {"valid": False, "reason": e.message}, {}
    data = {"valid": True, "sheet_count": len(wb.sheetnames), "sheets": wb.sheetnames}
    wb.close()
    return data, {}


def cmd_list_sheets(args):
    wb = open_workbook(args.file)
    out = []
    for name in wb.sheetnames:
        ws = wb[name]
        out.append({
            "name": name,
            "index": wb.sheetnames.index(name),
            "max_row": ws.max_row,
            "max_column": ws.max_column,
            "is_active": (ws is wb.active),
            "sheet_state": ws.sheet_state,  # visible | hidden | veryHidden
        })
    wb.close()
    return out, {"columns": ["name", "index", "max_row", "max_column", "is_active", "sheet_state"]}


def _infer_type(values):
    types_seen = set()
    for v in values:
        if v is None:
            continue
        if isinstance(v, bool):
            types_seen.add("bool")
        elif isinstance(v, int):
            types_seen.add("int")
        elif isinstance(v, float):
            types_seen.add("float")
        else:
            import datetime
            if isinstance(v, (datetime.date, datetime.datetime)):
                types_seen.add("datetime")
            else:
                types_seen.add("string")
    if not types_seen:
        return "empty"
    if types_seen <= {"int"}:
        return "int"
    if types_seen <= {"int", "float"}:
        return "float"
    if len(types_seen) == 1:
        return next(iter(types_seen))
    return "mixed"


def cmd_schema(args):
    wb = open_workbook(args.file)
    ws = get_sheet(wb, args.sheet)
    headers = header_map(ws, args.header_row)
    sample_size = args.sample_size or 100
    columns = []
    for name, col in headers.items():
        values = []
        for r in range(args.header_row + 1, min(ws.max_row, args.header_row + sample_size) + 1):
            values.append(ws.cell(row=r, column=col).value)
        non_null = sum(1 for v in values if v is not None)
        columns.append({
            "name": name, "column_letter": get_column_letter(col),
            "inferred_type": _infer_type(values),
            "sampled_rows": len(values), "non_null": non_null,
        })
    wb.close()
    return columns, {"sheet": ws.title, "header_row": args.header_row, "columns": ["name", "column_letter", "inferred_type", "sampled_rows", "non_null"]}


def cmd_read(args):
    wb = open_workbook(args.file)
    ws = get_sheet(wb, args.sheet)
    headers = header_map(ws, args.header_row)
    if args.columns:
        wanted = [c.strip() for c in args.columns.split(",")]
        missing = [c for c in wanted if c not in headers]
        if missing:
            raise ToolError(f"Unknown column(s): {missing}", EXIT_ARG_ERROR, {"available": list(headers)})
        headers = {k: headers[k] for k in wanted}

    filt = parse_filter(args.filter) if args.filter else None
    last_row = exact_max_row(ws) if args.exact else ws.max_row

    matched = []
    skipped = 0
    for r in range(args.header_row + 1, last_row + 1):
        row = row_as_dict(ws, r, headers)
        if row_is_empty(row):
            continue
        if filt and not row_matches(row, *filt):
            continue
        if skipped < args.offset:
            skipped += 1
            continue
        row["_row"] = r
        matched.append(row)
        if args.limit and len(matched) >= args.limit:
            break
    wb.close()

    total_matched_row_numbers = [r["_row"] for r in matched]
    columns = list(headers.keys())
    if args.arrays:
        out_rows = [[r.get(c) for c in columns] for r in matched]
    else:
        out_rows = matched
    return out_rows, {
        "sheet": ws.title, "header_row": args.header_row, "columns": columns,
        "row_count": len(out_rows), "offset": args.offset,
        "limit_applied": bool(args.limit), "row_numbers": total_matched_row_numbers,
    }


def cmd_stats(args):
    wb = open_workbook(args.file)
    p = Path(args.file)
    sheets = []
    total_rows = 0
    for name in wb.sheetnames:
        ws = wb[name]
        rows = exact_max_row(ws) if args.exact else ws.max_row
        total_rows += rows
        sheets.append({"name": name, "max_row": ws.max_row, "max_column": ws.max_column, "exact_max_row": (rows if args.exact else None)})
    has_macros = p.suffix.lower() == ".xlsm"
    has_external_links = False
    try:
        with zipfile.ZipFile(p) as z:
            has_external_links = any(n.startswith("xl/externalLinks/") for n in z.namelist())
    except (zipfile.BadZipFile, OSError):
        pass
    data = {
        "file_size_bytes": p.stat().st_size,
        "sheet_count": len(wb.sheetnames),
        "total_rows_estimate": total_rows,
        "has_macros": has_macros,
        "has_external_links": has_external_links,
        "sheets": sheets,
    }
    wb.close()
    return data, {}


def cmd_write_row(args):
    if not args.write:
        raise ToolError("write-row requires --write", EXIT_WRITE_NOT_ALLOWED)
    if not args.values:
        raise ToolError("--values is required", EXIT_ARG_ERROR)
    try:
        values = json.loads(args.values)
    except json.JSONDecodeError as e:
        raise ToolError(f"--values must be valid JSON: {e}", EXIT_ARG_ERROR)

    wb = open_workbook(args.file)
    ws = get_sheet(wb, args.sheet)
    headers = header_map(ws, args.header_row)
    unknown = [c for c in values if c not in headers]
    if unknown:
        raise ToolError(f"Unknown column(s): {unknown}", EXIT_ARG_ERROR, {"available": list(headers)})

    if args.at and args.where:
        raise ToolError("Use --at or --where, not both", EXIT_ARG_ERROR)

    target_row = None
    mode = "append"
    if args.at:
        target_row = args.at
        mode = "overwrite"
    elif args.where:
        col, op, val = parse_filter(args.where)
        last_row = exact_max_row(ws)
        for r in range(args.header_row + 1, last_row + 1):
            row = row_as_dict(ws, r, headers)
            if row_is_empty(row):
                continue
            if row_matches(row, col, op, val):
                target_row = r
                mode = "overwrite"
                break
        if target_row is None:
            raise ToolError(f"No row matched --where {args.where!r}", EXIT_NOT_FOUND)
    else:
        target_row = exact_max_row(ws) + 1
        mode = "append"

    has_formula = False
    warnings = []
    for name, col in headers.items():
        if name not in values:
            continue
        target_cell = ws.cell(row=target_row, column=col)
        if isinstance(target_cell, MergedCell):
            raise ToolError(
                f"{target_cell.coordinate} is part of a merged range and not the anchor cell; "
                "writes must target the top-left cell of the merge.",
                EXIT_ARG_ERROR,
            )
        v = normalize_value(values[name])
        w = check_unsafe_formula(v)
        if w:
            warnings.append(w)
        if formula_needs_recalc(v):
            has_formula = True
        target_cell.value = v

    wb.save(args.file)
    wb.close()

    meta = {"sheet": ws.title, "row": target_row, "mode": mode, "full_file_rewrite": True}
    if warnings:
        meta["warnings"] = warnings
    if has_formula:
        meta["recalc"] = recalculate(args.file, timeout=args.timeout, force=args.force_recalc)
    return {"row": target_row, "mode": mode, "values": values}, meta


def cmd_delete_row(args):
    if not args.write:
        raise ToolError("delete-row requires --write", EXIT_WRITE_NOT_ALLOWED)
    if bool(args.at) == bool(args.where):
        raise ToolError("Specify exactly one of --at or --where", EXIT_ARG_ERROR)

    wb = open_workbook(args.file)
    ws = get_sheet(wb, args.sheet)

    deleted = []
    if args.at:
        if args.at < 1 or args.at > ws.max_row:
            raise ToolError(f"Row {args.at} does not exist (sheet has {ws.max_row} rows)", EXIT_NOT_FOUND)
        ws.delete_rows(args.at, 1)
        deleted = [args.at]
    else:
        headers = header_map(ws, args.header_row)
        col, op, val = parse_filter(args.where)
        last_row = exact_max_row(ws)
        matches = []
        for r in range(args.header_row + 1, last_row + 1):
            row = row_as_dict(ws, r, headers)
            if row_is_empty(row):
                continue
            if row_matches(row, col, op, val):
                matches.append(r)
        if not matches:
            raise ToolError(f"No row matched --where {args.where!r}", EXIT_NOT_FOUND)
        if not args.all_matches and len(matches) > 1:
            raise ToolError(
                f"{len(matches)} rows matched --where {args.where!r}; pass --all-matches to delete all of them",
                EXIT_ARG_ERROR, {"matched_rows": matches},
            )
        # delete bottom-up so row numbers of earlier matches stay valid
        for r in sorted(matches, reverse=True):
            ws.delete_rows(r, 1)
        deleted = sorted(matches)

    wb.save(args.file)
    wb.close()
    return {"deleted_rows": deleted}, {"sheet": ws.title, "count": len(deleted), "full_file_rewrite": True}


def cmd_set_cell(args):
    wb = open_workbook(args.file)
    ws = get_sheet(wb, args.sheet)
    try:
        coordinate_from_string(args.cell)
    except ValueError:
        raise ToolError(f"Invalid cell reference: {args.cell}", EXIT_ARG_ERROR)

    cell = ws[args.cell]
    if args.value is None:
        data = {"cell": args.cell, "value": cell.value, "data_type": cell.data_type}
        wb.close()
        return data, {"sheet": ws.title, "mode": "read"}

    if not args.write:
        raise ToolError("Writing a cell requires --write", EXIT_WRITE_NOT_ALLOWED)
    if isinstance(cell, MergedCell):
        raise ToolError(
            f"{args.cell} is part of a merged range and not the anchor cell; "
            "writes must target the top-left cell of the merge.",
            EXIT_ARG_ERROR,
        )

    v = normalize_value(args.value)
    warning = check_unsafe_formula(v)
    old_value = cell.value
    cell.value = v
    wb.save(args.file)
    wb.close()

    meta = {"sheet": ws.title, "mode": "write", "full_file_rewrite": True}
    if warning:
        meta["warnings"] = [warning]
    if formula_needs_recalc(v):
        meta["recalc"] = recalculate(args.file, timeout=args.timeout, force=args.force_recalc)
    return {"cell": args.cell, "old_value": old_value, "new_value": v}, meta


def cmd_add_sheet(args):
    if not args.write:
        raise ToolError("add-sheet requires --write", EXIT_WRITE_NOT_ALLOWED)
    if not args.sheet:
        raise ToolError("--sheet NAME is required", EXIT_ARG_ERROR)
    wb = open_workbook(args.file)
    name = sanitize_sheet_name(args.sheet, wb.sheetnames)
    if args.index is not None:
        wb.create_sheet(title=name, index=args.index)
    elif args.after:
        if args.after not in wb.sheetnames:
            raise ToolError(f"--after sheet not found: {args.after}", EXIT_NOT_FOUND, {"available_sheets": wb.sheetnames})
        wb.create_sheet(title=name, index=wb.sheetnames.index(args.after) + 1)
    else:
        wb.create_sheet(title=name)
    wb.save(args.file)
    wb.close()
    return {"name": name, "requested_name": args.sheet, "renamed": name != args.sheet}, {"full_file_rewrite": True}


def cmd_delete_sheet(args):
    if not args.write:
        raise ToolError("delete-sheet requires --write", EXIT_WRITE_NOT_ALLOWED)
    wb = open_workbook(args.file)
    ws = get_sheet(wb, args.sheet)
    if len(wb.sheetnames) == 1:
        raise ToolError("Cannot delete the only sheet in a workbook", EXIT_ARG_ERROR)
    name = ws.title
    wb.remove(ws)
    wb.save(args.file)
    wb.close()
    return {"deleted": name}, {"full_file_rewrite": True}


def cmd_import(args):
    if not args.write:
        raise ToolError("import requires --write", EXIT_WRITE_NOT_ALLOWED)
    if pd is None:
        raise ToolError("pandas is required for import", EXIT_ARG_ERROR)
    src = Path(args.import_file)
    if not src.is_file():
        raise ToolError(f"Import source not found: {src}", EXIT_FILE_NOT_FOUND)

    if src.suffix.lower() == ".csv":
        df = pd.read_csv(src)
    elif src.suffix.lower() == ".json":
        df = pd.read_json(src)
    else:
        raise ToolError(f"Unsupported import format: {src.suffix}", EXIT_ARG_ERROR)

    wb = open_workbook(args.file)
    if args.sheet and args.sheet in wb.sheetnames:
        ws = wb[args.sheet]
        if args.replace:
            wb.remove(ws)
            ws = wb.create_sheet(title=args.sheet)
    else:
        ws = wb.create_sheet(title=sanitize_sheet_name(args.sheet or src.stem, wb.sheetnames))

    ws.append(list(df.columns))
    for row in df.itertuples(index=False):
        ws.append(list(row))

    wb.save(args.file)
    wb.close()
    return {"sheet": ws.title, "rows_written": len(df), "columns": list(df.columns)}, {"full_file_rewrite": True}


def cmd_export(args):
    if pd is None:
        raise ToolError("pandas is required for export", EXIT_ARG_ERROR)
    wb = open_workbook(args.file)
    ws = get_sheet(wb, args.sheet)
    headers = header_map(ws, args.header_row)
    filt = parse_filter(args.filter) if args.filter else None

    rows = []
    for r in range(args.header_row + 1, exact_max_row(ws) + 1):
        row = row_as_dict(ws, r, headers)
        if row_is_empty(row):
            continue
        if filt and not row_matches(row, *filt):
            continue
        rows.append(row)
    wb.close()

    df = pd.DataFrame(rows, columns=list(headers.keys()))
    out_path = Path(args.out) if args.out else None
    fmt = args.format or (out_path.suffix.lstrip(".") if out_path else "json")

    if out_path:
        if fmt == "csv":
            df.to_csv(out_path, index=False)
        elif fmt == "json":
            df.to_json(out_path, orient="records", indent=2)
        else:
            raise ToolError(f"Unsupported export format: {fmt}", EXIT_ARG_ERROR)
        return {"out": str(out_path), "rows_written": len(df)}, {"sheet": ws.title}
    else:
        return json.loads(df.to_json(orient="records")), {"sheet": ws.title, "row_count": len(df)}


def cmd_validate(args):
    wb_f = open_workbook(args.file)  # formulas
    wb_v = openpyxl.load_workbook(args.file, data_only=True)  # cached values

    issues = []
    total_formulas = 0
    for sheet_name in wb_f.sheetnames:
        ws_f, ws_v = wb_f[sheet_name], wb_v[sheet_name]
        for row in ws_f.iter_rows():
            for cell in row:
                v = cell.value
                if isinstance(v, ArrayFormula):
                    v = v.text
                if not (isinstance(v, str) and v.startswith("=")):
                    continue
                total_formulas += 1
                coord = f"{sheet_name}!{cell.coordinate}"
                warning = check_unsafe_formula(v)
                if warning:
                    issues.append({"cell": coord, "type": "unsafe_function", "detail": warning})
                cached = ws_v[cell.coordinate].value
                if isinstance(cached, str) and any(err in cached for err in EXCEL_ERROR_LITERALS):
                    issues.append({"cell": coord, "type": "formula_error", "detail": cached})
                elif cached is None:
                    issues.append({"cell": coord, "type": "uncached", "detail": "No cached value; run a write command (auto-recalculates) or recalculate the file."})
                if EXTERNAL_REF_RE.search(v):
                    issues.append({"cell": coord, "type": "external_link", "detail": "Formula references another workbook."})
    at_risk = external_links_at_risk(str(Path(args.file).resolve()))
    for coord in at_risk:
        issues.append({"cell": coord, "type": "external_link_at_risk", "detail": "Cached value already stripped; recalculating would delete this link."})
    wb_f.close()
    wb_v.close()
    return {"total_formulas": total_formulas, "issue_count": len(issues), "issues": issues}, {"clean": len(issues) == 0}


# --------------------------------------------------------------------------
# CLI wiring
# --------------------------------------------------------------------------

def add_common_args(p, needs_file=True, needs_write=False):
    if needs_file:
        p.add_argument("file", help="Path to the .xlsx/.xlsm workbook")
    if needs_write:
        pass  # --write is a global flag, already added on parent
    p.add_argument("--sheet", default=None, help="Target sheet name (default: active sheet)")
    p.add_argument("--header-row", type=int, default=1, dest="header_row", help="Row treated as the header (default 1)")


def build_global_parent():
    """Global flags, usable both before and after the subcommand name."""
    gp = argparse.ArgumentParser(add_help=False)
    gp.add_argument("--write", action="store_true", help="Allow save operations (off by default)")
    gp.add_argument("--output", choices=["json", "ndjson", "table", "markdown"], default="json")
    gp.add_argument("--limit", type=int, default=0, help="Cap on rows returned (0 = no cap)")
    gp.add_argument("--pretty", action="store_true", help="Indent JSON output")
    gp.add_argument("--arrays", action="store_true", help="Row data as arrays instead of objects")
    gp.add_argument("--nl", action="store_true", help="Newline-delimited JSON rows")
    gp.add_argument("--quiet", action="store_true", help="Suppress best-effort warnings on stderr")
    gp.add_argument("--exact", action="store_true", help="Use a true non-empty-row scan instead of openpyxl's max_row estimate")
    gp.add_argument("--timeout", type=int, default=30, help="Timeout (s) for LibreOffice recalculation")
    gp.add_argument("--force-recalc", action="store_true", dest="force_recalc", help="Recalculate even if external-workbook links would be lost")
    return gp


def build_parser():
    global_parent = build_global_parent()
    parser = argparse.ArgumentParser(
        prog="xlsx_support.py", description="CRUD CLI for .xlsx/.xlsm workbooks", parents=[global_parent],
    )
    parser.add_argument("-V", "--version", action="store_true", help="Print tool/library versions and exit")

    sub = parser.add_subparsers(dest="command")

    def add_sub(name):
        return sub.add_parser(name, parents=[global_parent])

    p = add_sub("list-sheets"); add_common_args(p, needs_file=True)
    p.set_defaults(func=cmd_list_sheets)

    p = add_sub("schema"); add_common_args(p)
    p.add_argument("--sample-size", type=int, default=100, dest="sample_size")
    p.set_defaults(func=cmd_schema)

    p = add_sub("read"); add_common_args(p)
    p.add_argument("--filter", default=None, help='e.g. "status == active"')
    p.add_argument("--columns", default=None, help="Comma-separated column subset")
    p.add_argument("-n", type=int, dest="limit_local", default=None, help="Per-call row cap (overrides global --limit)")
    p.add_argument("--offset", type=int, default=0)
    p.set_defaults(func=cmd_read)

    p = add_sub("stats"); add_common_args(p, needs_file=True)
    p.set_defaults(func=cmd_stats)

    p = add_sub("health-check"); add_common_args(p, needs_file=True)
    p.set_defaults(func=cmd_health_check)

    p = add_sub("version")
    p.set_defaults(func=cmd_version, requires_file=False)

    p = add_sub("describe")
    p.set_defaults(func=cmd_describe, requires_file=False)

    p = add_sub("write-row"); add_common_args(p)
    p.add_argument("--values", required=True, help='JSON object, e.g. \'{"name":"Ada","qty":3}\'')
    p.add_argument("--at", type=int, default=None, help="Overwrite this row number")
    p.add_argument("--where", default=None, help="Overwrite the row matching this filter")
    p.set_defaults(func=cmd_write_row)

    p = add_sub("delete-row"); add_common_args(p)
    p.add_argument("--at", type=int, default=None)
    p.add_argument("--where", default=None)
    p.add_argument("--all-matches", action="store_true", dest="all_matches")
    p.set_defaults(func=cmd_delete_row)

    p = add_sub("set-cell"); add_common_args(p)
    p.add_argument("--cell", required=True, help="Cell reference, e.g. B2")
    p.add_argument("--value", default=None, help="Value or formula to write; omit to read")
    p.set_defaults(func=cmd_set_cell)

    p = add_sub("add-sheet"); add_common_args(p)
    p.add_argument("--after", default=None, help="Insert after this existing sheet")
    p.add_argument("--index", type=int, default=None, help="Insert at this 0-based index")
    p.set_defaults(func=cmd_add_sheet)

    p = add_sub("delete-sheet"); add_common_args(p)
    p.set_defaults(func=cmd_delete_sheet)

    p = add_sub("import"); add_common_args(p)
    p.add_argument("--file-in", dest="import_file", required=True, help="CSV or JSON file to load")
    p.add_argument("--replace", action="store_true", help="Replace the sheet's contents instead of appending a new sheet")
    p.set_defaults(func=cmd_import)

    p = add_sub("export"); add_common_args(p)
    p.add_argument("--format", choices=["csv", "json"], default=None)
    p.add_argument("--out", default=None, help="Output path; omit to return data inline")
    p.add_argument("--filter", default=None)
    p.set_defaults(func=cmd_export)

    p = add_sub("validate"); add_common_args(p, needs_file=True)
    p.set_defaults(func=cmd_validate)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version and not args.command:
        args.command = "version"
        args.func = cmd_version

    if not args.command:
        parser.print_help()
        return EXIT_ARG_ERROR

    # reconcile read's local -n/--limit with the global --limit
    if args.command == "read":
        args.limit = args.limit_local if args.limit_local is not None else args.limit

    requires_file = getattr(args, "requires_file", True)
    command = args.command

    try:
        if requires_file and not hasattr(args, "file"):
            raise ToolError(f"{command} requires a file path", EXIT_ARG_ERROR)
        data, meta = args.func(args)
        env = make_envelope(command, True, data=data, meta=meta, error=None)
        render(env, args)
        return EXIT_OK
    except ToolError as e:
        env = error_envelope(command, e)
        render(env, args)
        return e.exit_code
    except Exception as e:  # last-resort catch so we always emit the envelope
        err = ToolError(f"Unexpected error: {e}", EXIT_READ_ERROR)
        env = error_envelope(command, err)
        render(env, args)
        return err.exit_code


if __name__ == "__main__":
    sys.exit(main())
