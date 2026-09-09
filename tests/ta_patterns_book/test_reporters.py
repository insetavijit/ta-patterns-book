"""Unit tests for reporters, stream capture, and table modifiers in loss_profile."""

import io
import unittest
import pandas as pd
from pathlib import Path

from ta_patterns_book.loss_profile.reporters import (
    AXIS_ALIASES,
    TeeStream,
    apply_table_modifiers,
    save_dump_file,
)


class TestLossProfileReporters(unittest.TestCase):
    def test_tee_stream_capture_and_strip_ansi(self):
        """TeeStream should pass output to original stream and capture clean text."""
        buf = io.StringIO()
        tee = TeeStream(buf)
        colored_text = "\x1b[31mRed Alert\x1b[0m and Normal Text\n"
        tee.write(colored_text)
        tee.flush()

        self.assertEqual(buf.getvalue(), colored_text)
        clean = tee.get_clean_text()
        self.assertEqual(clean, "Red Alert and Normal Text\n")

    def test_apply_table_modifiers_min_trades(self):
        """Table modifiers should filter rows by min_trades."""
        df = pd.DataFrame({
            "pattern": ["A", "B", "C"],
            "number of trades": [10, 3, 25],
            "win%": [50.0, 33.3, 80.0],
            "raw_pnl": [100.0, -50.0, 500.0],
        })
        mod = apply_table_modifiers(df, min_trades=10)
        self.assertEqual(len(mod), 2)
        self.assertNotIn("B", mod["pattern"].values)

    def test_apply_table_modifiers_sort_and_top(self):
        """Table modifiers should sort by win% and slice top N."""
        df = pd.DataFrame({
            "pattern": ["A", "B", "C"],
            "number of trades": [10, 3, 25],
            "win%": [50.0, 90.0, 80.0],
            "raw_pnl": [100.0, -50.0, 500.0],
        })
        mod = apply_table_modifiers(df, sort="win%", top=2)
        self.assertEqual(len(mod), 2)
        self.assertEqual(mod.iloc[0]["pattern"], "B")
        self.assertEqual(mod.iloc[1]["pattern"], "C")

    def test_save_dump_file(self):
        """save_dump_file should write content cleanly to specified file."""
        content = "Line 1\nLine 2\n"
        out_path = save_dump_file(content, view_name="test_view", axis_name="test_axis")
        self.assertTrue(out_path.exists())
        self.assertEqual(out_path.read_text(encoding="utf-8"), content)
        out_path.unlink(missing_ok=True)

    def test_axis_aliases_resolution(self):
        """Verify standard aliases resolution dictionary."""
        self.assertEqual(AXIS_ALIASES["prr"], "prr")
        self.assertEqual(AXIS_ALIASES["duration"], "duration")
        self.assertEqual(AXIS_ALIASES["wk"], "weekly")
        self.assertEqual(AXIS_ALIASES["month"], "monthly")


if __name__ == "__main__":
    unittest.main()
