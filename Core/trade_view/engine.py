"""SmartGrid Layout Engine for Candlestick Chart Grid Layouts."""

from __future__ import annotations

import json
import os

from .models import LayoutConfig, _DEFAULT_DUMMY_CANDLES


def validate_input(candle_counts: list[int], config: LayoutConfig) -> None:
    """Validates input candle counts and layout configuration parameters."""
    if not candle_counts:
        raise ValueError("candle_counts must not be empty")
    if any((not isinstance(c, int)) or c <= 0 for c in candle_counts):
        raise ValueError("candle_counts must all be positive integers")
    if config.row_capacity_candles <= 0:
        raise ValueError("row_capacity_candles must be positive")
    if config.gap_candles < 0:
        raise ValueError("gap_candles must be >= 0")
    if config.max_extension_ratio < 1.0:
        raise ValueError("max_extension_ratio must be >= 1.0")
    if config.packing_strategy not in ("wordwrap", "bestfit", "optimal"):
        raise ValueError(f"unknown packing_strategy: {config.packing_strategy}")
    if config.max_charts_per_canvas < 1:
        raise ValueError("max_charts_per_canvas must be >= 1")
    if config.min_candles < 0:
        raise ValueError("min_candles must be >= 0")
    if config.px_per_candle <= 0:
        raise ValueError("px_per_candle must be > 0")


def pack_wordwrap(candle_counts: list[int], capacity: int, gap: int) -> list[list[int]]:
    """Greedy, order-preserving Stage A packing strategy."""
    rows: list[list[int]] = []
    current: list[int] = []
    current_total = 0
    for i, c in enumerate(candle_counts):
        if c > capacity:
            if current:
                rows.append(current)
                current, current_total = [], 0
            rows.append([i])  # Overflow row alone
            continue
        needed = c + (gap if current else 0)
        if current and current_total + needed > capacity:
            rows.append(current)
            current, current_total = [], 0
            needed = c
        current.append(i)
        current_total += needed
    if current:
        rows.append(current)
    return rows


def pack_bestfit(candle_counts: list[int], capacity: int, gap: int) -> list[list[int]]:
    """Best-Fit-Decreasing bin packing Stage A strategy (reorders charts)."""
    order = sorted(range(len(candle_counts)), key=lambda i: candle_counts[i], reverse=True)
    rows: list[dict] = []
    for i in order:
        c = candle_counts[i]
        if c > capacity:
            rows.append({"indices": [i], "total": c, "overflow": True})
            continue
        best_r, best_leftover = None, None
        for r_idx, row in enumerate(rows):
            if row["overflow"]:
                continue
            addl = c if not row["indices"] else gap + c
            new_total = row["total"] + addl
            if new_total <= capacity:
                leftover = capacity - new_total
                if best_leftover is None or leftover < best_leftover:
                    best_leftover, best_r = leftover, r_idx
        if best_r is not None:
            row = rows[best_r]
            addl = c if not row["indices"] else gap + c
            row["total"] += addl
            row["indices"].append(i)
        else:
            rows.append({"indices": [i], "total": c, "overflow": False})
    for row in rows:
        row["indices"].sort()
    rows.sort(key=lambda r: min(r["indices"]))
    return [r["indices"] for r in rows]


def pack_optimal(candle_counts: list[int], capacity: int, gap: int) -> list[list[int]]:
    """Order-preserving DP (Knuth-Plass style) Stage A strategy."""
    n = len(candle_counts)
    INF = float("inf")
    dp = [INF] * (n + 1)
    dp[0] = 0.0
    back = [-1] * (n + 1)

    for i in range(1, n + 1):
        running_total = 0
        for j in range(i - 1, -1, -1):
            c = candle_counts[j]
            if j == i - 1:
                running_total = c
            else:
                running_total += gap + c
            if running_total > capacity:
                if j == i - 1:
                    if dp[j] + 0.0 < dp[i]:
                        dp[i] = dp[j] + 0.0
                        back[i] = j
                break
            leftover = capacity - running_total
            badness = leftover**3
            if dp[j] + badness < dp[i]:
                dp[i] = dp[j] + badness
                back[i] = j

    rows = []
    i = n
    while i > 0:
        j = back[i]
        rows.append(list(range(j, i)))
        i = j
    rows.reverse()
    return rows


PACKERS = {
    "wordwrap": pack_wordwrap,
    "bestfit": pack_bestfit,
    "optimal": pack_optimal,
}


def fill_row(indices: list[int], candle_counts: list[int], config: LayoutConfig) -> list[dict]:
    """Stage B: bounded proportional fill of leftover row space."""
    capacity = config.row_capacity_candles
    gap = config.gap_candles
    n = len(indices)
    is_overflow = n == 1 and candle_counts[indices[0]] > capacity

    if is_overflow:
        c = candle_counts[indices[0]]
        return [
            {
                "index": indices[0],
                "original_candles": c,
                "displayed_candles": c,
                "extra_candles_added": 0,
                "capped": False,
                "overflow": True,
            }
        ]

    gap_total = gap * max(0, n - 1)
    available = capacity - gap_total
    natural_total = sum(candle_counts[i] for i in indices)
    scale = available / natural_total if natural_total > 0 else 1.0
    scale_capped = min(scale, config.max_extension_ratio)
    capped = scale > config.max_extension_ratio

    results = []
    for i in indices:
        c = candle_counts[i]
        displayed = max(config.min_candles, round(c * scale_capped))
        results.append(
            {
                "index": i,
                "original_candles": c,
                "displayed_candles": displayed,
                "extra_candles_added": displayed - c,
                "capped": capped,
                "overflow": False,
            }
        )

    if not capped:
        residual = available - sum(r["displayed_candles"] for r in results)
        results[-1]["displayed_candles"] += residual
        results[-1]["extra_candles_added"] += residual

    return results


def paginate(rows_filled: list[list[dict]], max_charts_per_canvas: int) -> list[list[list[dict]]]:
    """Paginates rows into canvas pages bounded by max_charts_per_canvas."""
    canvases = []
    current_canvas_rows = []
    current_chart_count = 0

    for row in rows_filled:
        row_size = len(row)
        if current_canvas_rows and current_chart_count + row_size > max_charts_per_canvas:
            canvases.append(current_canvas_rows)
            current_canvas_rows, current_chart_count = [], 0
        current_canvas_rows.append(row)
        current_chart_count += row_size

    if current_canvas_rows:
        canvases.append(current_canvas_rows)
    return canvases


def compute_layout(candle_counts: list[int] = None, config: LayoutConfig = None) -> dict:
    """Computes the full SmartGrid layout solution dictionary."""
    if candle_counts is None:
        candle_counts = list(_DEFAULT_DUMMY_CANDLES)
    config = config or LayoutConfig()
    validate_input(candle_counts, config)

    packer = PACKERS[config.packing_strategy]
    row_indices = packer(candle_counts, config.row_capacity_candles, config.gap_candles)

    rows_filled = [fill_row(row, candle_counts, config) for row in row_indices]
    canvases_rows = paginate(rows_filled, config.max_charts_per_canvas)

    canvases_out = []
    for canvas_idx, canvas_rows in enumerate(canvases_rows):
        rows_out = []
        for row_idx, row in enumerate(canvas_rows):
            x_candles = 0
            charts_out = []
            for item in row:
                x_px = round(x_candles * config.px_per_candle, 1)
                width_px = round(item["displayed_candles"] * config.px_per_candle, 1)
                charts_out.append(
                    {
                        "index": item["index"],
                        "original_candles": item["original_candles"],
                        "displayed_candles": item["displayed_candles"],
                        "extra_candles_added": item["extra_candles_added"],
                        "x_px": x_px,
                        "width_px": width_px,
                        "capped": item["capped"],
                        "overflow": item["overflow"],
                    }
                )
                x_candles += item["displayed_candles"] + config.gap_candles
            rows_out.append({"row": row_idx, "charts": charts_out})
        canvases_out.append({"canvas_index": canvas_idx, "rows": rows_out})

    return {
        "config": {
            "row_capacity_candles": config.row_capacity_candles,
            "px_per_candle": config.px_per_candle,
            "gap_candles": config.gap_candles,
            "max_charts_per_canvas": config.max_charts_per_canvas,
            "max_extension_ratio": config.max_extension_ratio,
            "min_candles": config.min_candles,
            "packing_strategy": config.packing_strategy,
        },
        "canvas_width_px": round(config.row_capacity_candles * config.px_per_candle, 1),
        "total_charts": len(candle_counts),
        "canvases": canvases_out,
    }


class SmartGridEngine:
    """Object-Oriented API for the SmartGrid Chart Grid Layout System."""

    def __init__(self, candle_counts: list[int] = None, config: LayoutConfig = None):
        self.candle_counts = candle_counts if candle_counts is not None else list(_DEFAULT_DUMMY_CANDLES)
        self.config = config or LayoutConfig()

    def run(self) -> dict:
        return compute_layout(self.candle_counts, self.config)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.run(), indent=indent)

    def save_json(self, filepath: str) -> str:
        res = self.run()
        filepath = os.path.normpath(filepath)
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(res, f, indent=2)
        return filepath

    @classmethod
    def dry_run(cls, config: LayoutConfig = None) -> dict:
        engine = cls(candle_counts=list(_DEFAULT_DUMMY_CANDLES), config=config)
        return engine.run()
