#!/usr/bin/env python3
"""
mt5_results_db.py — Ingest MT5 Backtest Telemetry & OHLCV into Institutional DuckDB Schema.

Maps raw MT5 deal-level telemetry into the canonical 1Ybt-2 DuckDB schema:
  1. ohlcv                — Clean OHLCV price series aligned to the test timeframe (with optional resampling)
  2. trades               — Reconstructed round-trip trades with entry/exit, SL mode, PnL, return %
  3. portfolio_metrics    — Executive summary with Sharpe, Sortino, Profit Factor, Drawdown
  4. monthly_performance  — Aggregated metrics per calendar month
  5. equity_curve         — Continuous trade-by-trade equity & cumulative drawdown progression
  6. drawdown_events      — Discrete peak-to-trough drawdown episodes

Usage:
  uv run python Utils/mt5_results_db.py --json outs/ClassicFloorModV6_1_results.json --db outs/mt5_backtests.duckdb
  uv run python Utils/mt5_results_db.py --run --from-date 2026-09-07 --to-date 2026-09-11
  uv run python Utils/mt5_results_db.py --resample 5T  # Resamples M1 OHLCV to 5-minute bars via Pandas
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_JSON = _REPO_ROOT / "outs" / "ClassicFloorModV6_1_results.json"
_DEFAULT_DB = _REPO_ROOT / "outs" / "mt5_backtests.duckdb"
_RUNNER_SCRIPT = _REPO_ROOT / "Core" / "mt5-wsl-tstSetup-01" / ".tmp" / "run_mt5_test.py"
_COMMON_FILES_DIR = Path("/mnt/c/Users/avijit/AppData/Roaming/MetaQuotes/Terminal/Common/Files")


def parse_mt5_json(json_path: Path) -> dict[str, Any]:
    if not json_path.exists():
        raise FileNotFoundError(f"MT5 results JSON not found at: {json_path}")
    return json.loads(json_path.read_text(encoding="utf-8"))


def load_and_prepare_ohlcv(
    data: dict[str, Any],
    custom_ohlcv_path: str | None = None,
    resample_tf: str | None = None,
    test_period: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> pd.DataFrame | None:
    """Load the tested OHLCV price series and optionally resample to target timeframe."""
    strategy = data.get("strategy", "ClassicFloorModV6_1")
    candidates = [
        Path(custom_ohlcv_path) if custom_ohlcv_path else None,
        Path(data.get("ohlcv_file")) if data.get("ohlcv_file") else None,
        _REPO_ROOT / "outs" / f"{strategy}_ohlcv.csv",
        _COMMON_FILES_DIR / f"{strategy}_ohlcv.csv",
    ]

    ohlcv_file = None
    for cand in candidates:
        if cand and cand.exists() and cand.stat().st_size > 50:
            ohlcv_file = cand
            break

    if not ohlcv_file:
        return None

    try:
        df = pd.read_csv(ohlcv_file)
        if "timestamp" not in df.columns:
            return None

        df["timestamp"] = pd.to_datetime(df["timestamp"].astype(str).str.replace(".", "-", regex=False), utc=True)
        df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)

        if from_date:
            start_dt = pd.to_datetime(from_date, utc=True)
            df = df[df["timestamp"] >= start_dt]
        if to_date:
            # Include entire end day
            end_dt = pd.to_datetime(to_date, utc=True) + pd.Timedelta(days=1)
            df = df[df["timestamp"] < end_dt]

        # Standardize columns
        numeric_cols = ["open", "high", "low", "close", "volume", "spread"]
        for c in numeric_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        # Handle Resampling if requested or needed by timeframe
        target_rule = None
        if resample_tf:
            target_rule = resample_tf
        elif test_period:
            period_clean = test_period.upper().replace("PERIOD_", "")
            if period_clean in ("M5", "5M"):
                target_rule = "5min"
            elif period_clean in ("M15", "15M"):
                target_rule = "15min"
            elif period_clean in ("M30", "30M"):
                target_rule = "30min"
            elif period_clean in ("H1", "1H"):
                target_rule = "1h"
            elif period_clean in ("H4", "4H"):
                target_rule = "4h"
            elif period_clean in ("D1", "1D"):
                target_rule = "1D"

        if target_rule and target_rule.upper().replace("PERIOD_", "") not in ("M1", "1M", "1T", "1MIN", "MIN", "T"):
            # Resample OHLCV via Pandas
            rule = target_rule.replace("T", "min").replace("t", "min")
            if rule.endswith("M") or rule.endswith("m"):
                rule = rule[:-1] + "min"
            resampled = df.resample(rule, on="timestamp").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
                "spread": "mean",
            }).dropna(subset=["open", "close"]).reset_index()
            return resampled

        return df.reset_index(drop=True)

    except Exception as exc:
        print(f"Warning: Failed to load OHLCV data from {ohlcv_file}: {exc}", file=sys.stderr)
        return None


def reconstruct_trades(data: dict[str, Any]) -> list[dict[str, Any]]:
    deals = data.get("deals", [])
    has_pos_id = any(d.get("position_id") for d in deals)

    strategy_name = data.get("strategy", "ClassicFloorModV6_1")
    symbol = data.get("symbol", "EURUSDm")
    period = data.get("period", "PERIOD_M1")

    if has_pos_id:
        pos_in: dict[int, dict[str, Any]] = {}
        pos_out: dict[int, dict[str, Any]] = {}
        for d in deals:
            entry_type = str(d.get("entry", "")).upper()
            dtype = str(d.get("type", "")).upper()
            if dtype not in ("BUY", "SELL"):
                continue
            pid = int(d.get("position_id", 0))
            if entry_type == "IN":
                pos_in[pid] = d
            elif entry_type == "OUT":
                pos_out[pid] = d

        common_pids = sorted(
            set(pos_in.keys()) & set(pos_out.keys()),
            key=lambda p: pd.to_datetime(pos_in[p]["time"].replace(".", "-")),
        )
        pairs = [(pos_in[p], pos_out[p]) for p in common_pids]
    else:
        in_deals = [d for d in deals if d.get("entry") == "IN" and d.get("type") in ("BUY", "SELL")]
        out_deals = [d for d in deals if d.get("entry") == "OUT" and d.get("type") in ("BUY", "SELL")]
        trade_count = min(len(in_deals), len(out_deals))
        pairs = [(in_deals[idx], out_deals[idx]) for idx in range(trade_count)]

    trades: list[dict[str, Any]] = []

    for idx, (tin, tout) in enumerate(pairs):

        entry_time = pd.to_datetime(tin["time"].replace(".", "-"), utc=True)
        exit_time = pd.to_datetime(tout["time"].replace(".", "-"), utc=True)
        holding_sec = float((exit_time - entry_time).total_seconds())

        entry_price = float(tin["price"])
        exit_price = float(tout["price"])
        pnl = float(tout["profit"])
        volume = float(tin["volume"])
        comm = float(tin.get("commission", 0.0) + tout.get("commission", 0.0))
        swap = float(tout.get("swap", 0.0))

        raw_ret = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0
        ret_pct = raw_ret * 100.0

        in_comment = str(tin.get("comment", "")).upper()
        out_comment = str(tout.get("comment", "")).lower()

        sl_mode = "PIVOT" if "PIVOT" in in_comment else "SAFE"
        if "tp" in out_comment:
            exit_reason = "TP"
        elif "sl" in out_comment:
            exit_reason = "SL"
        else:
            exit_reason = "CLOSE"

        is_win = 1 if pnl > 0 else -1

        trades.append({
            "uid": idx + 1,
            "trade_id": idx + 1,
            "strategy_name": strategy_name,
            "symbol": symbol,
            "period": period,
            "direction": "LONG",
            "entry_time": entry_time,
            "exit_time": exit_time,
            "holding_seconds": holding_sec,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "lot_size": volume,
            "pnl": pnl,
            "realized_pnl": exit_price - entry_price,
            "return_pct": ret_pct,
            "exit_reason": exit_reason,
            "sl_mode": sl_mode,
            "is_win": is_win,
            "commission": comm,
            "swap": swap,
            "ticket_in": int(tin.get("ticket", 0)),
            "ticket_out": int(tout.get("ticket", 0)),
        })

    return trades


def compute_metrics(
    trades: list[dict[str, Any]],
    initial_cash: float,
    strategy_name: str,
    symbol: str,
    period: str,
) -> dict[str, Any]:
    total_trades = len(trades)
    if total_trades == 0:
        return {
            "strategy_name": strategy_name,
            "symbol": symbol,
            "timeframe": period,
            "initial_cash": initial_cash,
            "ending_cash": initial_cash,
            "net_pnl": 0.0,
            "total_return_pct": 0.0,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "max_drawdown_usd": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "payoff_ratio": 0.0,
        }

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    net_pnl = sum(pnls)

    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / total_trades) * 100.0 if total_trades > 0 else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

    avg_win = (gross_profit / win_count) if win_count > 0 else 0.0
    avg_loss = (gross_loss / loss_count) if loss_count > 0 else 0.0
    payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0

    cum_cash = initial_cash
    peak_cash = initial_cash
    max_dd_usd = 0.0
    max_dd_pct = 0.0

    for p in pnls:
        cum_cash += p
        if cum_cash > peak_cash:
            peak_cash = cum_cash
        dd_usd = peak_cash - cum_cash
        dd_pct = (dd_usd / peak_cash * 100.0) if peak_cash > 0 else 0.0
        if dd_usd > max_dd_usd:
            max_dd_usd = dd_usd
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

    pnl_arr = np.array(pnls)
    mean_pnl = float(np.mean(pnl_arr))
    std_pnl = float(np.std(pnl_arr)) if len(pnl_arr) > 1 else 0.0
    sharpe = (mean_pnl / std_pnl * math.sqrt(252)) if std_pnl > 1e-6 else 0.0

    return {
        "strategy_name": strategy_name,
        "symbol": symbol,
        "timeframe": period,
        "initial_cash": float(initial_cash),
        "ending_cash": float(initial_cash + net_pnl),
        "net_pnl": float(net_pnl),
        "total_return_pct": float((net_pnl / initial_cash) * 100.0),
        "total_trades": int(total_trades),
        "wins": int(win_count),
        "losses": int(loss_count),
        "win_rate_pct": float(win_rate),
        "profit_factor": float(profit_factor),
        "sharpe_ratio": float(sharpe),
        "max_drawdown_pct": float(max_dd_pct),
        "max_drawdown_usd": float(max_dd_usd),
        "gross_profit": float(gross_profit),
        "gross_loss": float(gross_loss),
        "payoff_ratio": float(payoff_ratio),
        "created_at": datetime.now(timezone.utc),
    }


def compute_monthly_performance(trades: list[dict[str, Any]], strategy_name: str) -> list[dict[str, Any]]:
    if not trades:
        return []
    df = pd.DataFrame(trades)
    if "entry_time" in df.columns:
        df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
        df["year_month"] = df["entry_time"].dt.strftime("%Y-%m")
    else:
        df["year_month"] = "ALL"

    monthly: list[dict[str, Any]] = []
    for ym, group in df.groupby("year_month"):
        tot = len(group)
        pnl_series = pd.to_numeric(group.get("pnl", 0.0), errors="coerce").fillna(0.0)
        wins = int((pnl_series > 0).sum())
        losses = int((pnl_series <= 0).sum())
        net_pnl = float(pnl_series.sum())
        gp = float(pnl_series[pnl_series > 0].sum())
        gl = abs(float(pnl_series[pnl_series <= 0].sum()))
        pf = (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0)

        ret_sum = float(pd.to_numeric(group["return_pct"], errors="coerce").fillna(0.0).sum()) if "return_pct" in group.columns else 0.0

        monthly.append({
            "year_month": str(ym),
            "strategy_name": strategy_name,
            "trade_count": tot,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": float((wins / tot) * 100.0) if tot > 0 else 0.0,
            "realized_pnl": net_pnl,
            "return_pct": ret_sum,
            "profit_factor": float(pf),
        })

    return monthly


def compute_equity_curve_and_drawdowns(
    trades: list[dict[str, Any]],
    initial_cash: float,
    strategy_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    equity_rows: list[dict[str, Any]] = []
    dd_rows: list[dict[str, Any]] = []

    current_cash = initial_cash
    peak_cash = initial_cash
    in_dd = False
    cur_dd_start = None
    cur_dd_trough_time = None
    cur_dd_peak_val = initial_cash
    cur_dd_trough_val = initial_cash
    dd_counter = 1

    if trades:
        first_time = trades[0]["entry_time"]
        equity_rows.append({
            "timestamp": first_time,
            "trade_number": 0,
            "strategy_name": strategy_name,
            "balance": float(current_cash),
            "cumulative_pnl": 0.0,
            "drawdown_pct": 0.0,
            "cumulative_return_pct": 0.0,
        })

    for idx, t in enumerate(trades, 1):
        exit_t = t.get("exit_time")
        pnl = float(t.get("pnl", 0.0))
        trade_num = t.get("uid", t.get("trade_id", idx))

        current_cash += pnl
        cum_pnl = current_cash - initial_cash
        cum_ret = (cum_pnl / initial_cash) * 100.0

        if current_cash > peak_cash:
            if in_dd:
                dd_pct = (cur_dd_peak_val - cur_dd_trough_val) / cur_dd_peak_val * 100.0
                if dd_pct >= 0.1:
                    dd_rows.append({
                        "drawdown_id": dd_counter,
                        "strategy_name": strategy_name,
                        "start_time": cur_dd_start,
                        "trough_time": cur_dd_trough_time,
                        "recovery_time": exit_t,
                        "peak_value": float(cur_dd_peak_val),
                        "trough_value": float(cur_dd_trough_val),
                        "drawdown_pct": float(dd_pct),
                        "is_recovered": True,
                    })
                    dd_counter += 1
                in_dd = False
            peak_cash = current_cash
        elif current_cash < peak_cash:
            if not in_dd:
                in_dd = True
                cur_dd_start = exit_t
                cur_dd_peak_val = peak_cash
                cur_dd_trough_val = current_cash
                cur_dd_trough_time = exit_t
            else:
                if current_cash < cur_dd_trough_val:
                    cur_dd_trough_val = current_cash
                    cur_dd_trough_time = exit_t

        dd_pct = ((peak_cash - current_cash) / peak_cash * 100.0) if peak_cash > 0 else 0.0

        equity_rows.append({
            "timestamp": exit_t,
            "trade_number": trade_num,
            "strategy_name": strategy_name,
            "balance": float(current_cash),
            "cumulative_pnl": float(cum_pnl),
            "drawdown_pct": float(dd_pct),
            "cumulative_return_pct": float(cum_ret),
        })

    if in_dd:
        dd_pct = (cur_dd_peak_val - cur_dd_trough_val) / cur_dd_peak_val * 100.0
        if dd_pct >= 0.1:
            dd_rows.append({
                "drawdown_id": dd_counter,
                "strategy_name": strategy_name,
                "start_time": cur_dd_start,
                "trough_time": cur_dd_trough_time,
                "recovery_time": None,
                "peak_value": float(cur_dd_peak_val),
                "trough_value": float(cur_dd_trough_val),
                "drawdown_pct": float(dd_pct),
                "is_recovered": False,
            })

    return equity_rows, dd_rows


def persist_to_duckdb(
    trades: list[dict[str, Any]],
    metrics: dict[str, Any],
    monthly: list[dict[str, Any]],
    equity: list[dict[str, Any]],
    drawdowns: list[dict[str, Any]],
    df_ohlcv: pd.DataFrame | None,
    db_path: Path,
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))

    # 1. Table `ohlcv` (if available)
    if df_ohlcv is not None and not df_ohlcv.empty:
        con.register("df_ohlcv_tmp", df_ohlcv)
        con.execute("CREATE OR REPLACE TABLE ohlcv AS SELECT * FROM df_ohlcv_tmp")

    # 2. Table `trades`
    df_trades = pd.DataFrame(trades)
    con.register("df_trades_tmp", df_trades)
    con.execute("CREATE OR REPLACE TABLE trades AS SELECT * FROM df_trades_tmp")

    # 3. Table `portfolio_metrics`
    df_metrics = pd.DataFrame([metrics])
    con.register("df_metrics_tmp", df_metrics)
    con.execute("CREATE OR REPLACE TABLE portfolio_metrics AS SELECT * FROM df_metrics_tmp")

    # 4. Table `monthly_performance`
    df_monthly = pd.DataFrame(monthly)
    con.register("df_monthly_tmp", df_monthly)
    con.execute("CREATE OR REPLACE TABLE monthly_performance AS SELECT * FROM df_monthly_tmp")

    # 5. Table `equity_curve`
    df_equity = pd.DataFrame(equity)
    con.register("df_equity_tmp", df_equity)
    con.execute("CREATE OR REPLACE TABLE equity_curve AS SELECT * FROM df_equity_tmp")

    # 6. Table `drawdown_events`
    df_dd = pd.DataFrame(drawdowns) if drawdowns else pd.DataFrame([{
        "drawdown_id": 1, "strategy_name": metrics["strategy_name"], "start_time": None,
        "trough_time": None, "recovery_time": None, "peak_value": 0.0, "trough_value": 0.0,
        "drawdown_pct": 0.0, "is_recovered": True,
    }])
    con.register("df_dd_tmp", df_dd)
    con.execute("CREATE OR REPLACE TABLE drawdown_events AS SELECT * FROM df_dd_tmp")

    con.close()


def display_rich_summary(
    metrics: dict[str, Any],
    trades: list[dict[str, Any]],
    df_ohlcv: pd.DataFrame | None,
    db_path: Path,
) -> None:
    console = Console()

    table = Table(title=f"DuckDB Persistence Complete — {metrics['strategy_name']}", box=None)
    table.add_column("Metric", style="bold cyan")
    table.add_column("Value", justify="right")

    pnl = metrics["net_pnl"]
    pnl_style = "green" if pnl >= 0 else "red"
    sign = "+" if pnl >= 0 else ""

    ohlcv_count = len(df_ohlcv) if df_ohlcv is not None else 0

    table.add_row("Target Database", str(db_path))
    table.add_row("OHLCV Bars Persisted", f"{ohlcv_count:,} bars")
    table.add_row("Total Trades Persisted", str(metrics["total_trades"]))
    table.add_row("Net Profit (USD)", f"[{pnl_style}]{sign}${pnl:,.2f}[/{pnl_style}]")
    table.add_row("Profit Factor", f"{metrics['profit_factor']:.2f}")
    table.add_row("Win Rate", f"{metrics['win_rate_pct']:.2f}% ({metrics['wins']}W / {metrics['losses']}L)")
    table.add_row("Max Drawdown", f"${metrics['max_drawdown_usd']:,.2f} ({metrics['max_drawdown_pct']:.2f}%)")
    table.add_row("Payoff Ratio", f"{metrics['payoff_ratio']:.2f}")
    table.add_row("Sharpe Ratio", f"{metrics['sharpe_ratio']:.2f}")

    console.print()
    console.print(table)
    console.print()

    con = duckdb.connect(str(db_path), read_only=True)
    tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
    console.print(f"[bold green]✓ Verified Tables in DuckDB:[/bold green] {', '.join(tables)}\n")
    con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest MT5 JSON backtest results & OHLCV into DuckDB.")
    parser.add_argument("--strategy", "-s", type=str, default="CFMV0601B", help="Strategy EA name")
    parser.add_argument("--json", type=str, default=None, help="Path to MT5 results JSON")
    parser.add_argument("--db", type=str, default=str(_DEFAULT_DB), help="Target DuckDB file path")
    parser.add_argument("--ohlcv", type=str, default=None, help="Explicit path to OHLCV CSV")
    parser.add_argument("--tf", "--period", type=str, default=None, help="Test timeframe (M1, M5, H1)")
    parser.add_argument("--resample", type=str, default=None, help="Resampling rule (e.g. 5T, 15T, 1h)")
    parser.add_argument("--run", action="store_true", help="Trigger run_mt5_test.py before ingesting")
    parser.add_argument("--from-date", default="2026-09-07", help="Start date if --run is specified")
    parser.add_argument("--to-date", default="2026-09-11", help="End date if --run is specified")

    args = parser.parse_args()
    json_file = Path(args.json) if args.json else (_REPO_ROOT / "outs" / f"{args.strategy}_results.json")
    db_file = Path(args.db)

    if args.run:
        import subprocess
        cmd = [sys.executable, str(_RUNNER_SCRIPT), "--strategy", args.strategy, "--from", args.from_date, "--to", args.to_date]
        if args.tf:
            cmd.extend(["--period", args.tf])
        print(f"Executing: {' '.join(cmd)}")
        res = subprocess.run(cmd)
        if res.returncode != 0:
            print(f"Error running MT5 test: return code {res.returncode}", file=sys.stderr)
            sys.exit(res.returncode)

    raw_data = parse_mt5_json(json_file)
    strategy_name = raw_data.get("strategy", "ClassicFloorModV6_1")
    symbol = raw_data.get("symbol", "EURUSDm")
    period = args.tf or raw_data.get("period", "PERIOD_M1")
    init_cash = float(raw_data.get("summary", {}).get("initial_deposit", 10000.0))

    df_ohlcv = load_and_prepare_ohlcv(
        raw_data,
        custom_ohlcv_path=args.ohlcv,
        resample_tf=args.resample,
        test_period=period,
        from_date=args.from_date if args.run else None,
        to_date=args.to_date if args.run else None,
    )

    trades = reconstruct_trades(raw_data)
    metrics = compute_metrics(trades, init_cash, strategy_name, symbol, period)
    monthly = compute_monthly_performance(trades, strategy_name)
    equity, drawdowns = compute_equity_curve_and_drawdowns(trades, init_cash, strategy_name)

    persist_to_duckdb(trades, metrics, monthly, equity, drawdowns, df_ohlcv, db_file)
    display_rich_summary(metrics, trades, df_ohlcv, db_file)


if __name__ == "__main__":
    main()
