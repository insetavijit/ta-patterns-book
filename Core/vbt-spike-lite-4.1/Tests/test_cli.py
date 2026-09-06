"""Tests for the CLI entry point (spec §8, DL-V6-08)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["uv", "run", "vbtspike", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )


class TestCliSmoke:
    def test_help_exits_0(self):
        assert run_cli("--help").returncode == 0

    def test_help_contains_vbtspike(self):
        result = run_cli("--help")
        assert "vbtspike" in (result.stdout + result.stderr).lower()

    def test_version_exits_0(self):
        assert run_cli("--version").returncode == 0

    def test_version_shows_0_6_0(self):
        result = run_cli("--version")
        assert "0.6.0" in result.stdout + result.stderr

    def test_run_help_exits_0(self):
        assert run_cli("run", "--help").returncode == 0

    def test_backup_help_exits_0(self):
        assert run_cli("backup", "--help").returncode == 0


class TestCliValidation:
    def test_bad_config_exits_1(self, tmp_path):
        result = run_cli(
            "run",
            "--strategy", "sma_cross",
            "--symbol", "EURUSD",
            "--timeframe", "1m",
            "--config", str(tmp_path / "missing.yaml"),
        )
        assert result.returncode == 1

    def test_unknown_strategy_exits_nonzero(self):
        result = run_cli(
            "run",
            "--strategy", "totally_fake_strategy",
            "--symbol", "EURUSD",
            "--timeframe", "1m",
        )
        assert result.returncode != 0
