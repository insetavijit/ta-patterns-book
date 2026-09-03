"""Utility script to generate dummy OHLC candlestick data and plot

a 3x4 canvas of the 12 single-candle bullish patterns using Seaborn and Matplotlib.
- Prior candles: Ash (light gray/charcoal)
- Target pattern candle: Highlighted in Blue
- Gridlines disabled.
Saved to Shared/OUTs/single_candle_patterns.png.
"""

from pathlib import Path
import matplotlib

matplotlib.use("Agg")  # Non-interactive headless backend
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import duckdb

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "Shared" / "Data" / "memory.duckdb"
OUT_DIR = BASE_DIR / "Shared" / "OUTs"
OUT_FILE = OUT_DIR / "single_candle_patterns.png"


def fetch_single_candle_bullish_patterns():
    conn = duckdb.connect(str(DB_PATH))
    rows = conn.execute(
        """
        SELECT pattern_name 
        FROM pattern_catalog 
        WHERE family = '1-candle' AND direction_class = 'BULLISH'
        ORDER BY pattern_name;
    """
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def generate_dummy_ohlc(pattern_name, num_bars=15):
    np.random.seed(42)
    closes = 100.0 + np.cumsum(np.random.randn(num_bars) * 0.5)
    opens = closes + np.random.randn(num_bars) * 0.3
    highs = np.maximum(opens, closes) + np.abs(np.random.randn(num_bars) * 0.4)
    lows = np.minimum(opens, closes) - np.abs(np.random.randn(num_bars) * 0.4)

    # Shape the final target bar (index -1)
    if pattern_name == "hammer":
        lows[-1] = np.minimum(opens[-1], closes[-1]) - 3.5
        highs[-1] = np.maximum(opens[-1], closes[-1]) + 0.1
    elif pattern_name in ["marubozu_white", "closing_marubozu_white"]:
        opens[-1], closes[-1], highs[-1], lows[-1] = 98.0, 103.0, 103.0, 98.0
    elif pattern_name == "dragonfly_doji":
        opens[-1], closes[-1], highs[-1], lows[-1] = 100.0, 100.05, 100.1, 96.5
    elif pattern_name == "inverted_hammer":
        highs[-1] = np.maximum(opens[-1], closes[-1]) + 3.5
        lows[-1] = np.minimum(opens[-1], closes[-1]) - 0.1
    elif pattern_name == "takuri_line":
        lows[-1] = np.minimum(opens[-1], closes[-1]) - 4.5
        highs[-1] = np.maximum(opens[-1], closes[-1]) + 0.1
    elif pattern_name in ["white_candle", "long_white_day"]:
        opens[-1], closes[-1], highs[-1], lows[-1] = 99.0, 104.0, 104.2, 98.8
    else:
        opens[-1], closes[-1], highs[-1], lows[-1] = 99.5, 102.5, 102.8, 99.0

    return opens, highs, lows, closes


def draw_candlestick(ax, opens, highs, lows, closes, title):
    n = len(closes)
    x = np.arange(n)

    ax.grid(False)

    for i in range(n):
        if i == n - 1:
            # Target pattern candle: Bright Blue
            color = "#1e88e5"
            edge_color = "#1565c0"
            alpha = 1.0
            lw = 1.8
        else:
            # Prior candles: Ash (light ash for bullish / dark ash for bearish)
            if closes[i] >= opens[i]:
                color = "#b0bec5"  # Light ash
                edge_color = "#78909c"
            else:
                color = "#37474f"  # Dark ash
                edge_color = "#263238"
            alpha = 0.85
            lw = 1.2

        # Wick
        ax.plot(
            [x[i], x[i]],
            [lows[i], highs[i]],
            color=edge_color if i == n - 1 else color,
            linewidth=lw,
        )

        # Body
        body_bottom = min(opens[i], closes[i])
        body_height = max(abs(closes[i] - opens[i]), 0.05)
        ax.bar(
            x[i],
            body_height,
            bottom=body_bottom,
            width=0.6,
            color=color,
            edgecolor=edge_color,
            linewidth=1.0 if i == n - 1 else 0.8,
            alpha=alpha,
        )

    # Highlight line for target candle
    ax.axvline(
        n - 1, color="#1565c0", linestyle=":", linewidth=1.0, alpha=0.5
    )

    ax.set_title(title, fontsize=10, fontweight="bold", color="#1a237e")
    ax.tick_params(axis="both", which="both", labelsize=7)
    ax.set_xlim(-0.8, n - 0.2)

    # Clean borders
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)


def main():
    patterns = fetch_single_candle_bullish_patterns()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sns.set_theme(style="white")

    fig, axes = plt.subplots(3, 4, figsize=(14, 9))
    axes = axes.flatten()

    for idx, pattern in enumerate(patterns):
        if idx < 12:
            o, h, l, c = generate_dummy_ohlc(pattern)
            draw_candlestick(axes[idx], o, h, l, c, title=f"{idx+1}. {pattern}")

    plt.suptitle(
        "12 Single-Candle Bullish Patterns — Blue Target Highlights & Ash Context Bars",
        fontsize=14,
        fontweight="bold",
        y=0.98,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(OUT_FILE, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(
        f"[+] Output image saved with custom blue/ash palette: {OUT_FILE.resolve()}"
    )


if __name__ == "__main__":
    main()
