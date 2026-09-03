"""Script to create and populate the pattern_catalog table in memory.duckdb
with metadata for all 300 technical-analysis pattern detectors in ta-patterns.
"""

from pathlib import Path
import duckdb
import ta_patterns as tap
import ta_patterns.chart_patterns as cp

DB_PATH = Path(__file__).resolve().parent.parent / "Shared" / "Data" / "memory.duckdb"


def extract_metadata():
    patterns_meta = []

    # 1. Candlestick patterns (106)
    for name in tap.PATTERNS:
        fn = getattr(tap, name, None)
        doc = fn.__doc__.strip() if fn and fn.__doc__ else ""

        # Determine direction
        if name in tap.BULLISH:
            direction = "BULLISH"
        elif name in tap.BEARISH:
            direction = "BEARISH"
        elif name in tap.NON_DIRECTIONAL:
            direction = "NON_DIRECTIONAL"
        else:
            direction = "UNKNOWN"

        # Determine candle count family
        if (
            "1-candle" in doc.lower()
            or "1-bar" in doc.lower()
            or name
            in [
                "hammer",
                "shooting_star",
                "doji",
                "dragonfly_doji",
                "gravestone_doji",
                "spinning_top_white",
                "spinning_top_black",
                "marubozu_white",
                "marubozu_black",
                "closing_marubozu_white",
                "closing_marubozu_black",
                "opening_marubozu_white",
                "opening_marubozu_black",
                "white_candle",
                "black_candle",
                "long_white_day",
                "long_black_day",
                "takuri_line",
                "high_wave",
                "long_legged_doji",
                "rickshaw_man",
                "short_black_candle",
                "short_white_candle",
                "southern_doji",
                "northern_doji",
                "gapping_up_doji",
                "gapping_down_doji",
                "inverted_hammer",
                "hanging_man",
            ]
        ):
            family = "1-candle"
        elif (
            "2-candle" in doc.lower()
            or "2-bar" in doc.lower()
            or name
            in [
                "engulfing_bullish",
                "engulfing_bearish",
                "harami_bullish",
                "harami_bearish",
                "harami_cross_bullish",
                "harami_cross_bearish",
                "piercing_pattern",
                "dark_cloud_cover",
                "doji_star_bullish",
                "doji_star_bearish",
                "kicking_bullish",
                "kicking_bearish",
                "meeting_lines_bullish",
                "meeting_lines_bearish",
                "matching_low",
                "tweezer_bottoms",
                "tweezer_tops",
                "rising_window",
                "falling_window",
                "belt_hold_bullish",
                "belt_hold_bearish",
                "above_stomach",
                "below_stomach",
                "separating_lines_bullish",
                "separating_lines_bearish",
                "homing_pigeon",
                "in_neck",
                "on_neck",
                "thrusting",
                "last_engulfing_bottom",
                "last_engulfing_top",
                "shooting_star_two_line",
                "two_black_gapping",
            ]
        ):
            family = "2-candle"
        elif (
            "3-candle" in doc.lower()
            or "3-bar" in doc.lower()
            or name
            in [
                "morning_star",
                "evening_star",
                "morning_doji_star",
                "evening_doji_star",
                "three_white_soldiers",
                "three_black_crows",
                "three_inside_up",
                "three_inside_down",
                "three_outside_up",
                "three_outside_down",
                "abandoned_baby_bullish",
                "abandoned_baby_bearish",
                "tri_star_bullish",
                "tri_star_bearish",
                "unique_three_river_bottom",
                "stick_sandwich",
                "advance_block",
                "deliberation",
                "identical_three_crows",
                "two_crows",
                "upside_gap_two_crows",
                "downside_tasuki_gap",
                "upside_tasuki_gap",
                "collapse_doji_star",
                "side_by_side_white_lines_bullish",
                "side_by_side_white_lines_bearish",
                "three_stars_south",
            ]
        ):
            family = "3-candle"
        else:
            family = "4+ candle"

        patterns_meta.append(
            {
                "pattern_name": name,
                "category": "candlestick",
                "family": family,
                "direction_class": direction,
                "is_volume_dependent": False,
                "docstring": doc,
            }
        )

    # 2. Chart patterns (194)
    for name in cp.CHART_PATTERNS:
        fn = getattr(cp, name, None)
        doc = fn.__doc__.strip() if fn and fn.__doc__ else ""

        # Determine direction
        if name in cp.BULLISH:
            direction = "BULLISH"
        elif name in cp.BEARISH:
            direction = "BEARISH"
        elif name in cp.BIDIRECTIONAL:
            direction = "BIDIRECTIONAL"
        elif name in cp.NON_DIRECTIONAL:
            direction = "NON_DIRECTIONAL"
        else:
            direction = "UNKNOWN"

        # Determine structural family
        if "busted_" in name:
            family = "busted"
        elif any(
            h in name
            for h in ["bat_", "butterfly_", "crab_", "gartley_", "shark_", "abcd_"]
        ):
            family = "harmonic"
        elif any(
            t in name
            for t in ["triangle", "wedge", "pennant", "flag", "channel"]
        ):
            family = "triangles_wedges"
        elif any(
            c in name for c in ["head_and_shoulders", "hs_", "double_", "triple_"]
        ):
            family = "classic_reversal"
        elif any(v in name for v in ["volume", "obv", "vwap"]):
            family = "volume"
        elif any(r in name for r in ["reversal", "pivot", "carl_v", "hook_"]):
            family = "reversal_pivot"
        else:
            family = "chart_pattern"

        is_vol = (
            hasattr(fn, "__code__")
            and "v" in getattr(fn, "__code__").co_varnames[:5]
        )

        patterns_meta.append(
            {
                "pattern_name": name,
                "category": "chart_pattern",
                "family": family,
                "direction_class": direction,
                "is_volume_dependent": is_vol,
                "docstring": doc,
            }
        )

    return patterns_meta


def seed_database():
    conn = duckdb.connect(str(DB_PATH))

    # Create pattern_catalog table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pattern_catalog (
            pattern_name VARCHAR PRIMARY KEY,
            category VARCHAR NOT NULL,
            family VARCHAR NOT NULL,
            direction_class VARCHAR NOT NULL,
            is_volume_dependent BOOLEAN DEFAULT FALSE,
            docstring VARCHAR
        );
    """
    )

    records = extract_metadata()

    for item in records:
        conn.execute(
            """
            INSERT OR REPLACE INTO pattern_catalog (
                pattern_name, category, family, direction_class, is_volume_dependent, docstring
            ) VALUES (?, ?, ?, ?, ?, ?);
        """,
            (
                item["pattern_name"],
                item["category"],
                item["family"],
                item["direction_class"],
                item["is_volume_dependent"],
                item["docstring"],
            ),
        )

    print(
        f"[+] Successfully populated pattern_catalog with {len(records)} patterns!"
    )

    # Show grouping breakdown
    print("\n[=] Pattern counts by Category & Direction:")
    summary = conn.execute(
        """
        SELECT category, direction_class, COUNT(*) as count 
        FROM pattern_catalog 
        GROUP BY category, direction_class 
        ORDER BY category, direction_class;
    """
    ).fetchall()
    for row in summary:
        print(f"  - {row[0]} | {row[1]}: {row[2]} patterns")

    print("\n[=] Pattern counts by Family:")
    fam_summary = conn.execute(
        """
        SELECT family, COUNT(*) as count 
        FROM pattern_catalog 
        GROUP BY family 
        ORDER BY count DESC;
    """
    ).fetchall()
    for row in fam_summary:
        print(f"  - {row[0]}: {row[1]} patterns")

    conn.close()


if __name__ == "__main__":
    seed_database()
