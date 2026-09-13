"""Unit tests for vbtspike CLI helpers and options."""

import unittest
from datetime import timedelta
from click.testing import CliRunner
import click

from vbtspike.cli import (
    _parse_duration,
    _resolve_window,
    cli,
)


class TestVbtSpikeCLI(unittest.TestCase):
    def test_parse_duration_valid(self):
        """_parse_duration parses valid strings into timedelta."""
        self.assertEqual(_parse_duration("0"), timedelta(0))
        self.assertEqual(_parse_duration("24h"), timedelta(hours=24))
        self.assertEqual(_parse_duration("30m"), timedelta(minutes=30))
        self.assertEqual(_parse_duration("7d"), timedelta(days=7))

    def test_parse_duration_invalid(self):
        """_parse_duration raises BadParameter on malformed strings."""
        with self.assertRaises(click.BadParameter):
            _parse_duration("abc")
        with self.assertRaises(click.BadParameter):
            _parse_duration("10x")

    def test_resolve_window(self):
        """_resolve_window returns datetime pair corresponding to timeframe."""
        w_start_1m, w_end_1m = _resolve_window("1m")
        diff_1m = w_end_1m - w_start_1m
        self.assertEqual(diff_1m.days, 7)

        w_start_1d, w_end_1d = _resolve_window("1d")
        diff_1d = w_end_1d - w_start_1d
        self.assertEqual(diff_1d.days, 730)

        w_start_1h, w_end_1h = _resolve_window("1h")
        diff_1h = w_end_1h - w_start_1h
        self.assertEqual(diff_1h.days, 90)

    def test_cli_help(self):
        """vbtspike --help should return exit code 0."""
        runner = CliRunner()
        res = runner.invoke(cli, ["--help"])
        self.assertEqual(res.exit_code, 0)
        self.assertIn("vbtSpike", res.output)

    def test_cli_version(self):
        """vbtspike --version should return exit code 0."""
        runner = CliRunner()
        res = runner.invoke(cli, ["--version"])
        self.assertEqual(res.exit_code, 0)
        self.assertIn("vbtspike", res.output)


if __name__ == "__main__":
    unittest.main()
