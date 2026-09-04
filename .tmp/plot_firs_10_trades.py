#!/usr/bin/env python3
"""Plot First 10 Trades Script.

Queries the first 10 trades from the `trades` table in Shared/Data/eur_usd_trades_5m.duckdb
and uses `trade_view` package (`python -m trade_view`) to render a SmartGrid trade playbook PNG canvas.

Output: Shared/OUTs/png/first_10_trades_playbook/first_10_trades_playbook.png
"""

from pathlib import Path
import subprocess
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "Shared" / "Data" / "eur_usd_trades_5m.duckdb"
OUT_PATH = BASE_DIR / "Shared" / "OUTs" / "png" / "first_10_trades_playbook.png"


def plot_first_10_trades():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    sql_query = (
        "SELECT uid AS trade_id, entry_time, entry_price, sl_price, tp_price, "
        "exit_price, exit_reason, pnl FROM trades ORDER BY uid ASC LIMIT 10"
    )

    cmd = [
        sys.executable,
        "-m",
        "trade_view",
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

    print(f"[+] Executing Tradebook Tool: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print("[+] Tradebook tool execution completed successfully!")
        print(f"[+] Output JSON: {result.stdout.strip()}")
    else:
        print(f"[-] Tradebook tool failed with exit code {result.returncode}")
        print(f"[-] Stderr: {result.stderr}")
        sys.exit(result.returncode)


def main():
    plot_first_10_trades()


if __name__ == "__main__":
    main()
