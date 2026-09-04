#!/usr/bin/env python3
"""Plot Duration 1 Trades Script (.tmp/plot_duration_1_trades.py)

Queries all trades with `duration_candel = 1` from `trades` in Shared/Data/eur_usd_trades_5m.duckdb
and uses the `trade_book_charts` package to render a SmartGrid trade playbook PNG canvas.

Output: Shared/OUTs/png/duration_1_trades_playbook/p1.png ...
"""

from pathlib import Path
import subprocess
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "Shared" / "Data" / "eur_usd_trades_5m.duckdb"
OUT_PATH = BASE_DIR / "Shared" / "OUTs" / "png" / "duration_1_trades_playbook.png"


def plot_duration_1_trades():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    sql_query = (
        "SELECT uid AS trade_id, entry_time, entry_price, sl_price, tp_price, "
        "exit_price, exit_reason, pnl FROM trades WHERE duration_candel = 1 ORDER BY uid ASC"
    )

    cmd = [
        sys.executable,
        "-m",
        "trade_book_charts",
        "tradebook",
        "--db",
        str(DB_PATH),
        "--sql",
        sql_query,
        "--ohlcv-table",
        "ohlcv",
        "--output",
        str(OUT_PATH),
        "--json",
    ]

    print(f"[+] Executing TradeBook Charts Package: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print("[+] TradeBook Charts rendering completed successfully!")
        print(f"[+] Output JSON: {result.stdout.strip()}")
    else:
        print(f"[-] TradeBook Charts rendering failed with exit code {result.returncode}")
        print(f"[-] Stderr: {result.stderr}")
        sys.exit(result.returncode)


def main():
    plot_duration_1_trades()


if __name__ == "__main__":
    main()
