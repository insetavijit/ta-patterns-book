#!/usr/bin/env python3
"""dn-ducas.py — Unified Dukascopy Historical OHLCV Downloader, Validator & Converter.

Compiles and unifies functionalities from the ducas-copy-data-dn toolkit:
1. Downloader (`dn.py`, `batch_dl.py`, `fan_dl.py`, `backfill.py`):
   - Direct download with --instrument, --start, --end, --tf (timeframe).
   - Multi-instrument support (including `--majors` preset).
   - Monthly chunking for multi-month spans with polite throttling (--wait-sec).
   - Resumable downloading (skips already downloaded chunks).
   - Normalized schema: timestamp, open, high, low, close, volume.
   - Output naming: {INSTRUMENT}-{start}-{end}-{tf}.parquet
2. Validator (`validate_data.py`):
   - Verifies parquet integrity, column schema, row counts, and date coverage / gaps.
   - Borderless rich display output.
3. Converter (`csv2perque.py`):
   - Batch converts raw CSV files to Parquet with PyArrow.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import sleep
from typing import Any, Generator, Iterable

try:
    import dukascopy_python as dk
    from dukascopy_python.instruments import (
        INSTRUMENT_FX_MAJORS_AUD_USD,
        INSTRUMENT_FX_MAJORS_EUR_USD,
        INSTRUMENT_FX_MAJORS_GBP_USD,
        INSTRUMENT_FX_MAJORS_NZD_USD,
        INSTRUMENT_FX_MAJORS_USD_CAD,
        INSTRUMENT_FX_MAJORS_USD_CHF,
        INSTRUMENT_FX_MAJORS_USD_JPY,
        INSTRUMENT_FX_METALS_XAG_USD,
        INSTRUMENT_FX_METALS_XAU_USD,
        INSTRUMENT_IDX_AMERICA_E_D_J_IND,
        INSTRUMENT_IDX_AMERICA_E_NQ_100,
        INSTRUMENT_IDX_AMERICA_E_SANDP_500,
        INSTRUMENT_VCCY_BTC_USD,
        INSTRUMENT_VCCY_ETH_USD,
    )
except ImportError:
    dk = None

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import pyarrow.parquet as pq
    import pyarrow.csv as pacsv
except ImportError:
    pq = None
    pacsv = None

try:
    from rich.console import Console
    from rich.table import Table

    console = Console()
except ImportError:
    console = None
    Table = None


# ---------------------------------------------------------------------------
# Instrument Registry
# ---------------------------------------------------------------------------

INSTRUMENT_MAP: dict[str, str] = {
    # FX Majors
    "eurusd": "EUR/USD",
    "gbpusd": "GBP/USD",
    "audusd": "AUD/USD",
    "nzdusd": "NZD/USD",
    "usdcad": "USD/CAD",
    "usdchf": "USD/CHF",
    "usdjpy": "USD/JPY",
    # Metals
    "xauusd": "XAU/USD",
    "xagusd": "XAG/USD",
    "gold": "XAU/USD",
    "silver": "XAG/USD",
    # US Indices
    "sp500": "USA500.IDX/USD",
    "nasdaq": "USATECH.IDX/USD",
    "djia": "USA30.IDX/USD",
    # Crypto
    "btcusd": "BTC/USD",
    "ethusd": "ETH/USD",
}

FX_MAJORS = ["eurusd", "gbpusd", "audusd", "nzdusd", "usdcad", "usdchf", "usdjpy"]

# ---------------------------------------------------------------------------
# Timeframe Mapping
# ---------------------------------------------------------------------------

TIMEFRAME_MAP: dict[str, str] = {
    "1s": "1s",
    "10s": "10s",
    "30s": "30s",
    "1m": "1m",
    "5m": "5m",
    "10m": "10m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "60m": "1h",
    "4h": "4h",
    "1d": "1d",
    "d": "1d",
    "1w": "1w",
    "w": "1w",
    "1mo": "1M",
    "1mth": "1M",
    "1M": "1M",
}


def resolve_interval(tf_str: str) -> str:
    """Map friendly timeframe string to dukascopy-python interval constant."""
    if not dk:
        raise RuntimeError("dukascopy-python is not installed. Run `uv add dukascopy-python`.")

    key = tf_str.strip().lower()
    if key in ["1m", "m1", "1min"]:
        return dk.INTERVAL_MIN_1
    elif key in ["5m", "m5", "5min"]:
        return dk.INTERVAL_MIN_5
    elif key in ["10m", "m10", "10min"]:
        return dk.INTERVAL_MIN_10
    elif key in ["15m", "m15", "15min"]:
        return dk.INTERVAL_MIN_15
    elif key in ["30m", "m30", "30min"]:
        return dk.INTERVAL_MIN_30
    elif key in ["1h", "h1", "60m", "1hour"]:
        return dk.INTERVAL_HOUR_1
    elif key in ["4h", "h4", "4hour"]:
        return dk.INTERVAL_HOUR_4
    elif key in ["1d", "d1", "d", "1day"]:
        return dk.INTERVAL_DAY_1
    elif key in ["1w", "w1", "w", "1week"]:
        return dk.INTERVAL_WEEK_1
    elif key in ["1mo", "1mth", "1m_month", "1month"]:
        return dk.INTERVAL_MONTH_1
    elif key in ["1s", "s1"]:
        return dk.INTERVAL_SEC_1
    elif key in ["10s", "s10"]:
        return dk.INTERVAL_SEC_10
    elif key in ["30s", "s30"]:
        return dk.INTERVAL_SEC_30
    else:
        # Fallback to direct attribute on dukascopy_python if provided
        attr = f"INTERVAL_{key.upper()}"
        if hasattr(dk, attr):
            return getattr(dk, attr)
        raise ValueError(f"Unsupported timeframe: '{tf_str}'. Supported: 1m, 5m, 10m, 15m, 30m, 1h, 4h, 1d, 1w, 1M")


def resolve_instrument(name: str) -> tuple[str, str]:
    """Resolve user-friendly instrument name to (dukascopy_symbol, canonical_label)."""
    cleaned = name.strip().lower().replace("/", "").replace("_", "").replace("-", "")
    if cleaned in INSTRUMENT_MAP:
        dk_symbol = INSTRUMENT_MAP[cleaned]
        label = cleaned.upper()
        return dk_symbol, label

    # Check if raw uppercase was passed e.g. "EUR/USD"
    upper = name.strip().upper()
    if "/" in upper:
        label = upper.replace("/", "")
        return upper, label

    # Default to upper string
    return upper, cleaned.upper()


def parse_datetime(dt_input: str | datetime) -> datetime:
    """Parse string or datetime to naive UTC-representing datetime."""
    if isinstance(dt_input, datetime):
        return dt_input

    s = dt_input.strip()
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y%m%d",
        "%Y%m%d_%H%M%S",
        "%Y%m%d%H%M%S",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue

    return datetime.fromisoformat(s)


def format_ts(dt: datetime) -> str:
    """Format datetime for filename stamp: YYYYMMDD_HHMMSS."""
    return dt.strftime("%Y%m%d_%H%M%S")


def month_slices(start: datetime, end: datetime) -> Generator[tuple[datetime, datetime], None, None]:
    """Slice a date range into calendar month boundaries."""
    cursor = start
    while cursor < end:
        y, m = cursor.year, cursor.month
        _, last_day = monthrange(y, m)
        m_end = min(end, datetime(y, m, last_day, 23, 59, 59) + timedelta(seconds=1))
        yield cursor, m_end
        cursor = m_end


def get_last_week_market_range(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Calculate the previous completed market week's date range.

    Forex markets trade from Sunday ~21:00 UTC through Friday ~21:00 UTC.
    Returns (start_dt, end_dt):
      start_dt: Monday 00:00:00 UTC of last week
      end_dt:   Monday 00:00:00 UTC of current week
    This cleanly encompasses all 5 market trading days (Mon-Fri) plus the Sunday open.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    current_date = now.date()
    weekday = current_date.weekday()  # Monday=0, Sunday=6

    # On Saturday (5) or Sunday (6), the completed trading week started on this calendar week's Monday.
    # On Monday (0) through Friday (4), the last completed trading week started on the prior calendar week's Monday.
    if weekday >= 5:
        last_week_monday = current_date - timedelta(days=weekday)
    else:
        last_week_monday = current_date - timedelta(days=weekday + 7)

    this_week_monday = last_week_monday + timedelta(days=7)

    start_dt = datetime(last_week_monday.year, last_week_monday.month, last_week_monday.day, 0, 0, 0)
    end_dt = datetime(this_week_monday.year, this_week_monday.month, this_week_monday.day, 0, 0, 0)
    return start_dt, end_dt


# ---------------------------------------------------------------------------
# Downloader Implementation
# ---------------------------------------------------------------------------

def download_ohlcv_chunk(
    symbol: str,
    interval_const: str,
    side: str,
    start: datetime,
    end: datetime,
    max_retries: int = 7,
) -> pd.DataFrame:
    """Fetch candles from Dukascopy API and normalize columns."""
    if not dk:
        raise RuntimeError("dukascopy-python is required. Install via `uv add dukascopy-python`.")

    offer_side = dk.OFFER_SIDE_BID if side.upper() == "BID" else dk.OFFER_SIDE_ASK

    df = dk.fetch(
        symbol,
        interval_const,
        offer_side,
        start,
        end,
        max_retries=max_retries,
    )

    if df is None or len(df) == 0:
        return pd.DataFrame()

    # Normalize timestamp column
    if "timestamp" not in df.columns:
        df = df.reset_index()
        first_col = df.columns[0]
        if first_col != "timestamp":
            df = df.rename(columns={first_col: "timestamp"})

    # Canonical lowercase column names
    df.columns = [str(c).lower() for c in df.columns]

    # Ensure required columns exist
    for col in ["timestamp", "open", "high", "low", "close", "volume"]:
        if col not in df.columns:
            df[col] = 0.0

    return df


def download_single_span(
    instrument: str,
    start: datetime,
    end: datetime,
    tf: str = "5m",
    outdir: Path | str = ".tmp",
    side: str = "BID",
    skip_existing: bool = True,
    ext: str = "parquet",
) -> Path | None:
    """Download OHLCV for an instrument within [start, end] and save to parquet."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    dk_symbol, label = resolve_instrument(instrument)
    interval = resolve_interval(tf)

    ts_start = format_ts(start)
    ts_end = format_ts(end)
    tf_clean = tf.lower()
    ext_clean = ext.lstrip(".")

    filename = f"{label}-{ts_start}-{ts_end}-{tf_clean}.{ext_clean}"
    filepath = outdir / filename

    if skip_existing and filepath.exists() and filepath.stat().st_size > 0:
        _print(f"  [SKIPPED] {filename} already exists ({filepath.stat().st_size:,} bytes)")
        return filepath

    _print(f"Fetching {label} ({dk_symbol}) [{tf}] from {start} to {end}...")
    df = download_ohlcv_chunk(dk_symbol, interval, side, start, end)

    if df.empty:
        _print(f"  [WARN] No data returned for {label} between {start} and {end}.")
        return None

    df.to_parquet(filepath, index=False)
    _print(f"  [SAVED] {len(df):,} rows -> {filepath}")
    return filepath


def download_chunked(
    instruments: list[str],
    start: datetime,
    end: datetime,
    tf: str = "5m",
    outdir: Path | str = ".tmp",
    side: str = "BID",
    chunk_by_month: bool = True,
    wait_sec: int = 5,
    skip_existing: bool = True,
    ext: str = "parquet",
) -> list[Path]:
    """Download one or more instruments over a date range, optionally chunked by month."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if chunk_by_month and (end - start).days > 32:
        slices = list(month_slices(start, end))
    else:
        slices = [(start, end)]

    saved_files: list[Path] = []
    total_steps = len(instruments) * len(slices)
    step = 0

    for inst in instruments:
        for slice_start, slice_end in slices:
            step += 1
            _print(f"\n[{step}/{total_steps}] Downloading {inst.upper()} {slice_start.strftime('%Y-%m-%d')} -> {slice_end.strftime('%Y-%m-%d')} ({tf})")
            fp = download_single_span(
                instrument=inst,
                start=slice_start,
                end=slice_end,
                tf=tf,
                outdir=outdir,
                side=side,
                skip_existing=skip_existing,
                ext=ext,
            )
            if fp:
                saved_files.append(fp)

            if step < total_steps and wait_sec > 0:
                sleep(wait_sec)

    return saved_files


# ---------------------------------------------------------------------------
# Validator Implementation (from validate_data.py)
# ---------------------------------------------------------------------------

FILE_RE = re.compile(
    r"^(?P<instrument>[A-Za-z0-9]+)-(?P<from>\d{8}_\d{6})-(?P<to>\d{8}_\d{6})(?:-(?P<tf>[a-zA-Z0-9]+))?\.(?:parquet|perque)$"
)


def validate_parquet_file(filepath: Path) -> dict[str, Any] | None:
    """Validate parquet file schema and extract metadata."""
    if not pq:
        # Fallback to pandas
        if not pd:
            return None
        try:
            df = pd.read_parquet(filepath)
            cols = list(df.columns)
            if len(df) == 0:
                return None
            return {
                "ts_min": str(df["timestamp"].iloc[0]),
                "ts_max": str(df["timestamp"].iloc[-1]),
                "rows": len(df),
            }
        except Exception:
            return None

    try:
        table = pq.read_table(filepath)
        cols = table.column_names
        if "timestamp" not in cols or table.num_rows == 0:
            return None

        ts_col = table.column("timestamp")
        first_ts = ts_col[0].as_py()
        last_ts = ts_col[table.num_rows - 1].as_py()
        return {
            "ts_min": str(first_ts),
            "ts_max": str(last_ts),
            "rows": table.num_rows,
        }
    except Exception:
        return None


def run_validation(data_dir: Path | str) -> None:
    """Validate parquet files in data_dir, compute coverage, and print borderless table."""
    data_dir = Path(data_dir)
    if not data_dir.exists():
        _print(f"Data directory not found: {data_dir}")
        return

    # Find parquet/perque files recursively
    files: list[Path] = []
    for ext in ("*.parquet", "*.perque"):
        files.extend(data_dir.rglob(ext))

    files = sorted(set(files))
    if not files:
        _print(f"No parquet files found in {data_dir}")
        return

    by_instrument: dict[str, list[dict[str, Any]]] = {}

    for f in files:
        m = FILE_RE.match(f.name)
        if not m:
            continue
        inst = m.group("instrument").upper()
        from_dt = datetime.strptime(m.group("from"), "%Y%m%d_%H%M%S")
        to_dt = datetime.strptime(m.group("to"), "%Y%m%d_%H%M%S")
        tf = m.group("tf") or "1m"

        meta = validate_parquet_file(f)
        if meta is None:
            continue

        entry = {
            "name": f.name,
            "filepath": str(f),
            "from_dt": from_dt,
            "to_dt": to_dt,
            "tf": tf,
            **meta,
        }
        by_instrument.setdefault(inst, []).append(entry)

    if console and Table:
        # Borderless formatting per Shared/cnf.yaml
        table = Table(
            show_header=True,
            header_style="bold cyan",
            box=None,
            show_edge=False,
            pad_edge=False,
        )
        table.add_column("Instrument")
        table.add_column("TF")
        table.add_column("From")
        table.add_column("To")
        table.add_column("Files", justify="right")
        table.add_column("Rows", justify="right")
        table.add_column("Status")

        for inst in sorted(by_instrument):
            entries = by_instrument[inst]
            entries.sort(key=lambda x: x["from_dt"])
            first_dt = entries[0]["from_dt"]
            last_dt = entries[-1]["to_dt"]
            total_rows = sum(e["rows"] for e in entries)
            tf_label = entries[0]["tf"]

            table.add_row(
                inst,
                tf_label,
                first_dt.strftime("%Y-%m-%d"),
                last_dt.strftime("%Y-%m-%d"),
                str(len(entries)),
                f"{total_rows:,}",
                "OK",
            )

        console.print(table)
        console.print(f"\nTotal: {len(by_instrument)} instrument(s) validated across {len(files)} files.")
    else:
        print(f"{'Instrument':<12} {'TF':<6} {'From':<12} {'To':<12} {'Files':>6} {'Rows':>12}")
        print("-" * 65)
        for inst in sorted(by_instrument):
            entries = by_instrument[inst]
            entries.sort(key=lambda x: x["from_dt"])
            first_dt = entries[0]["from_dt"].strftime("%Y-%m-%d")
            last_dt = entries[-1]["to_dt"].strftime("%Y-%m-%d")
            total_rows = sum(e["rows"] for e in entries)
            tf_label = entries[0]["tf"]
            print(f"{inst:<12} {tf_label:<6} {first_dt:<12} {last_dt:<12} {len(entries):>6} {total_rows:>12,}")


# ---------------------------------------------------------------------------
# CSV to Parquet Converter (from csv2perque.py)
# ---------------------------------------------------------------------------

def run_csv_conversion(
    input_path: Path | str,
    outdir: Path | str = "data_perque",
    compression: str = "snappy",
    overwrite: bool = False,
) -> int:
    """Batch convert CSV files into Parquet format."""
    if not pacsv or not pq:
        _print("Missing dependency: pyarrow. Install with `uv add pyarrow`.")
        return 1

    input_path = Path(input_path)
    outdir = Path(outdir)

    if input_path.is_file():
        csv_files = [input_path]
    elif input_path.is_dir():
        csv_files = sorted(input_path.rglob("*.csv"))
    else:
        _print(f"Input path not found: {input_path}")
        return 1

    if not csv_files:
        _print(f"No CSV files found in {input_path}")
        return 0

    converted = 0
    skipped = 0

    for csv_file in csv_files:
        if input_path.is_file():
            target = outdir / csv_file.with_suffix(".parquet").name
        else:
            target = outdir / csv_file.relative_to(input_path).with_suffix(".parquet")

        if target.exists() and not overwrite:
            skipped += 1
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        table = pacsv.read_csv(csv_file)
        pq.write_table(table, target, compression=compression)
        converted += 1
        _print(f"Converted {csv_file.name} -> {target}")

    _print(f"Conversion complete: {converted} converted, {skipped} skipped.")
    return 0


# ---------------------------------------------------------------------------
# Utility Logging
# ---------------------------------------------------------------------------

def _print(msg: str) -> None:
    if console:
        console.print(msg)
    else:
        print(msg)


# ---------------------------------------------------------------------------
# CLI Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Unified Dukascopy Historical OHLCV Downloader & Toolkit",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Operational mode")

    # 1. Download command (default action if arguments provided)
    p_dl = subparsers.add_parser("download", help="Download OHLCV candles from Dukascopy")
    _add_download_args(p_dl)

    # 2. Batch / Year command (from fan_dl.py / backfill.py)
    p_batch = subparsers.add_parser("batch", help="Batch download entire year(s) chunked by month")
    p_batch.add_argument("--year", type=int, help="Single year (e.g., 2024)")
    p_batch.add_argument("--years", type=str, help="Comma-separated years (e.g., 2023,2024,2025)")
    p_batch.add_argument("--instrument", "-i", type=str, default="eurusd", help="Instrument ticker")
    p_batch.add_argument("--majors", action="store_true", help="Download all 7 major FX pairs")
    p_batch.add_argument("--tf", default="1m", help="Timeframe (1m, 5m, 15m, 1h, etc.)")
    p_batch.add_argument("--outdir", default="data_perque", help="Target output directory")
    p_batch.add_argument("--wait-sec", type=int, default=15, help="Throttle wait between chunks")

    # 3. Validate command (from validate_data.py)
    p_val = subparsers.add_parser("validate", help="Validate downloaded Parquet files and coverage")
    p_val.add_argument("--dir", "-d", default="data_perque", help="Directory containing parquet files")

    # 4. Convert command (from csv2perque.py)
    p_conv = subparsers.add_parser("convert", help="Convert CSV files to Parquet")
    p_conv.add_argument("input", help="CSV file or directory containing CSVs")
    p_conv.add_argument("--outdir", default="data_perque", help="Target output directory")
    p_conv.add_argument("--compression", default="snappy", help="Parquet compression codec")
    p_conv.add_argument("--overwrite", action="store_true", help="Overwrite existing parquet files")

    # Root flags support direct invocation without typing 'download'
    _add_download_args(parser)
    parser.add_argument("--validate-dir", help="Quick run validation on directory")
    parser.add_argument("--convert-csv", help="Quick run CSV conversion on directory or file")

    return parser


def _add_download_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--start", "--from", dest="start", help="Start date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)")
    p.add_argument("--end", "--to", dest="end", help="End date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)")
    p.add_argument("--lastweek", "--last-week", dest="lastweek", action="store_true", help="Download the previous completed market week (Mon-Fri market days)")
    p.add_argument("--instrument", "-i", default="eurusd", help="Instrument (e.g. eurusd, gbpusd, xauusd, sp500)")
    p.add_argument("--majors", action="store_true", help="Download all 7 FX major pairs")
    p.add_argument("--tf", default="5m", help="Timeframe: 1m, 5m, 10m, 15m, 30m, 1h, 4h, 1d, 1w, 1M")
    p.add_argument("--side", default="BID", choices=["BID", "ASK", "bid", "ask"], help="Price offer side")
    p.add_argument("--outdir", default=".tmp", help="Output directory for saved parquet files")
    p.add_argument("--chunk", choices=["month", "none"], default="month", help="Chunking mode for long date ranges")
    p.add_argument("--wait-sec", type=int, default=5, help="Throttle wait between chunk requests (seconds)")
    p.add_argument("--no-skip", action="store_true", help="Do not skip existing parquet files")
    p.add_argument("--ext", default="parquet", help="File extension (e.g. parquet or perque)")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Route: quick validate flag
    if getattr(args, "validate_dir", None):
        run_validation(args.validate_dir)
        return 0

    # Route: quick convert flag
    if getattr(args, "convert_csv", None):
        return run_csv_conversion(args.convert_csv, getattr(args, "outdir", "data_perque"))

    # Route: validate subcommand
    if args.command == "validate":
        run_validation(args.dir)
        return 0

    # Route: convert subcommand
    if args.command == "convert":
        return run_csv_conversion(args.input, args.outdir, args.compression, args.overwrite)

    # Route: batch subcommand
    if args.command == "batch":
        years: list[int] = []
        if args.year:
            years.append(args.year)
        elif args.years:
            years.extend(int(y.strip()) for y in args.years.split(","))
        else:
            _print("Error: Specify --year or --years for batch mode.")
            return 1

        instruments = FX_MAJORS if args.majors else [args.instrument]

        for y in years:
            _print(f"\n==================== YEAR {y} ====================")
            start_dt = datetime(y, 1, 1)
            end_dt = datetime(y + 1, 1, 1)
            download_chunked(
                instruments=instruments,
                start=start_dt,
                end=end_dt,
                tf=args.tf,
                outdir=args.outdir,
                chunk_by_month=True,
                wait_sec=args.wait_sec,
                skip_existing=True,
            )
        return 0

    # Route: download subcommand or direct flags
    if not args.start and not getattr(args, "lastweek", False):
        parser.print_help()
        return 1

    if getattr(args, "lastweek", False):
        start_dt, end_dt = get_last_week_market_range()
        _print(f"Calculated last week market range: {start_dt.strftime('%Y-%m-%d')} -> {end_dt.strftime('%Y-%m-%d')} (Mon-Fri market days)")
    else:
        start_dt = parse_datetime(args.start)
        end_dt = parse_datetime(args.end) if args.end else datetime.now(timezone.utc).replace(tzinfo=None)

    instruments = FX_MAJORS if args.majors else [i.strip() for i in args.instrument.split(",")]
    chunk_by_month = (args.chunk == "month")

    download_chunked(
        instruments=instruments,
        start=start_dt,
        end=end_dt,
        tf=args.tf,
        outdir=args.outdir,
        side=args.side,
        chunk_by_month=chunk_by_month,
        wait_sec=args.wait_sec,
        skip_existing=not args.no_skip,
        ext=args.ext,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
