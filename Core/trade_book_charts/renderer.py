"""Renderer for SmartGrid-packed Candlestick Trade Playbook PNG Canvases."""

from __future__ import annotations

import io
import logging
import os

from .db import (
    _check_table_exists,
    _to_naive_ts,
    _validate_identifier,
    _validate_select_sql,
    fetch_trade_window,
    normalize_trade_columns,
    resolve_exit_and_window,
)
from .engine import LayoutConfig, SmartGridEngine
from .models import _HLINE_COLOR_CYCLE, _TradebookDeps

logger = logging.getLogger("tradebook_tool")


def generate_trade_book(
    deps: _TradebookDeps,
    db_path: str,
    sql: str,
    sql_params: list,
    ohlcv_table: str,
    ohlcv_cols: dict,
    output_file: str,
    pad_candles: int = 15,
    exit_lookahead: int = 288,
    hline_cols: list[str] | None = None,
    row_capacity: int = 350,
    strategy: str = "optimal",
    max_charts: int = 18,
    run_name: str = "tradebook",
    dry_run: bool = False,
) -> dict:
    """Generates SmartGrid-packed candlestick trade playbook PNGs from DuckDB."""
    pd = deps.pd
    sql = _validate_select_sql(sql)
    _validate_identifier(ohlcv_table, "--ohlcv-table")
    hline_cols = [c.strip().lower() for c in (hline_cols or []) if c.strip()]

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DuckDB database file not found at '{db_path}'")

    with deps.duckdb.connect(db_path, read_only=True) as con:
        _check_table_exists(deps, con, ohlcv_table)

        df_trades = con.execute(sql, sql_params or []).df()

        if df_trades.empty:
            logger.info("No trades returned by --sql")
            return {
                "status": "ok",
                "trades_found": 0,
                "canvases_generated": 0,
                "output_files": [],
                "run_name": run_name,
                "dry_run": dry_run,
            }

        df_trades = normalize_trade_columns(df_trades)

        if dry_run:
            logger.info(f"[dry-run] {len(df_trades)} trade(s) would be plotted")
            return {
                "status": "ok",
                "trades_found": int(len(df_trades)),
                "canvases_generated": 0,
                "output_files": [],
                "run_name": run_name,
                "dry_run": True,
            }

        trade_windows = []
        candle_counts = []

        for i, row in enumerate(df_trades.to_dict("records")):
            t_id = row.get("trade_id", i + 1)
            entry_dt = _to_naive_ts(pd, row["entry_time"])
            entry_p = float(row["entry_price"])
            sl_p = row.get("sl_price")
            sl_p = float(sl_p) if sl_p is not None and pd.notna(sl_p) else None
            tp_p = row.get("tp_price")
            tp_p = float(tp_p) if tp_p is not None and pd.notna(tp_p) else None

            exit_time_given = row.get("exit_time")
            has_exit_time = exit_time_given is not None and pd.notna(exit_time_given)

            if has_exit_time:
                exit_dt = _to_naive_ts(pd, exit_time_given)
                exit_price_given = row.get("exit_price")
                exit_p = (
                    float(exit_price_given)
                    if exit_price_given is not None and pd.notna(exit_price_given)
                    else entry_p
                )
                exit_reason = row.get("exit_reason") or "PROVIDED"
                df_window = fetch_trade_window(
                    deps, con, ohlcv_table, ohlcv_cols, entry_dt, exit_dt, pad_candles
                )
            else:
                exit_dt, exit_p, exit_reason, df_window = resolve_exit_and_window(
                    deps,
                    con,
                    ohlcv_table,
                    ohlcv_cols,
                    entry_dt,
                    entry_p,
                    sl_p,
                    tp_p,
                    pad_candles,
                    exit_lookahead,
                )

            c_cnt = len(df_window) if not df_window.empty else max(pad_candles, 1)

            pnl = row.get("pnl")
            pnl = float(pnl) if pnl is not None and pd.notna(pnl) else None

            hline_values = {}
            for col in hline_cols:
                v = row.get(col)
                if v is not None and pd.notna(v):
                    try:
                        hline_values[col] = float(v)
                    except (TypeError, ValueError):
                        logger.debug(
                            f"--hline-cols: column '{col}' value {v!r} on trade "
                            f"#{t_id} is not numeric, skipping"
                        )

            candle_counts.append(c_cnt)
            trade_windows.append(
                {
                    "t_id": t_id,
                    "entry_dt": entry_dt,
                    "entry_p": entry_p,
                    "sl_p": sl_p,
                    "tp_p": tp_p,
                    "pnl": pnl,
                    "exit_dt": exit_dt,
                    "exit_p": exit_p,
                    "exit_reason": exit_reason,
                    "df_window": df_window,
                    "hline_values": hline_values,
                }
            )

    config = LayoutConfig(
        row_capacity_candles=row_capacity,
        packing_strategy=strategy,
        max_charts_per_canvas=max_charts,
    )
    layout_data = SmartGridEngine(candle_counts=candle_counts, config=config).run()
    canvases = layout_data["canvases"]
    total_canvases = len(canvases)

    deps.load_render_deps()
    mpf, mdates, gridspec, plt, Image = (
        deps.mpf,
        deps.mdates,
        deps.gridspec,
        deps.plt,
        deps.Image,
    )

    custom_style = mpf.make_mpf_style(
        base_mpf_style="charles",
        rc={
            "font.size": 6,
            "axes.labelsize": 6,
            "xtick.labelsize": 5.5,
            "ytick.labelsize": 5.5,
            "figure.facecolor": "#fafafa",
        },
    )

    generated_pngs = []

    for canvas_idx, canvas in enumerate(canvases):
        rows = canvas["rows"]
        num_rows = len(rows)

        fig = plt.figure(figsize=(16, 3.8 * num_rows), dpi=150)
        outer_gs = gridspec.GridSpec(num_rows, 1, figure=fig, hspace=0.35)

        for r_idx, row in enumerate(rows):
            charts_in_row = row["charts"]
            row_widths = [c["displayed_candles"] for c in charts_in_row]
            inner_gs = gridspec.GridSpecFromSubplotSpec(
                1,
                len(charts_in_row),
                subplot_spec=outer_gs[r_idx],
                width_ratios=row_widths,
                wspace=0.20,
            )

            for c_idx, chart_info in enumerate(charts_in_row):
                tw = trade_windows[chart_info["index"]]
                df_w = tw["df_window"]
                ax = fig.add_subplot(inner_gs[0, c_idx])

                if df_w.empty:
                    ax.text(0.5, 0.5, f"No Data\nTrade #{tw['t_id']}", ha="center", va="center")
                    continue

                mpf.plot(df_w, type="candle", ax=ax, style=custom_style)

                x_dates = df_w.index
                entry_dt = tw["entry_dt"]
                entry_idx_arr = x_dates.get_indexer([entry_dt])
                if entry_idx_arr[0] != -1:
                    entry_idx = entry_idx_arr[0]
                    ax.axvline(x=entry_idx, color="blue", linestyle="--", linewidth=1.2, alpha=0.8)
                    ax.axhline(y=tw["entry_p"], color="blue", linestyle=":", linewidth=1.0, alpha=0.7)

                if tw["sl_p"] is not None:
                    ax.axhline(
                        y=tw["sl_p"], color="red", linestyle="-", linewidth=0.9, alpha=0.75, label="SL"
                    )
                if tw["tp_p"] is not None:
                    ax.axhline(
                        y=tw["tp_p"], color="green", linestyle="-", linewidth=0.9, alpha=0.75, label="TP"
                    )
                for h_idx, (col_name, val) in enumerate(tw["hline_values"].items()):
                    color = _HLINE_COLOR_CYCLE[h_idx % len(_HLINE_COLOR_CYCLE)]
                    ax.axhline(
                        y=val, color=color, linestyle="-.", linewidth=0.7, alpha=0.6, label=col_name
                    )

                pnl_val = tw["pnl"]
                if pnl_val is None:
                    win_loss, color_edge = "N/A", "#555555"
                else:
                    win_loss = "WIN" if pnl_val >= 0 else "LOSS"
                    color_edge = "#2e7d32" if pnl_val >= 0 else "#c62828"

                title_str = f"Trade #{tw['t_id']} | {win_loss} | Exit: {tw['exit_reason']}"
                ax.set_title(title_str, fontsize=6.5, fontweight="bold", color=color_edge, pad=3)
                ax.tick_params(axis="both", which="major", labelsize=5.5)
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))

        page_str = f" (Page {canvas_idx + 1}/{total_canvases})" if total_canvases > 1 else ""
        plt.suptitle(
            f"Trade Playbook — {run_name}{page_str} — {len(df_trades)} Trades | SmartGrid {strategy.upper()}",
            fontsize=12,
            fontweight="bold",
            y=0.995,
        )
        fig.subplots_adjust(top=0.94, bottom=0.04, left=0.04, right=0.96)

        base_dir, file_name = os.path.split(output_file)
        name_no_ext, ext = os.path.splitext(file_name)
        sub_dir = os.path.join(base_dir, name_no_ext)
        os.makedirs(sub_dir, exist_ok=True)

        page_output = (
            os.path.join(sub_dir, f"p{canvas_idx + 1}{ext}")
            if total_canvases > 1
            else os.path.join(sub_dir, f"{name_no_ext}{ext}")
        )

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        with Image.open(buf) as img:
            img.save(page_output, format="PNG", optimize=True)

        file_size_kb = os.path.getsize(page_output) / 1024
        logger.info(f"SmartGrid PNG generated: {page_output} ({file_size_kb:.1f} KB)")
        generated_pngs.append(page_output)

    return {
        "status": "ok",
        "trades_found": int(len(df_trades)),
        "canvases_generated": total_canvases,
        "output_files": generated_pngs,
        "run_name": run_name,
        "dry_run": False,
    }
