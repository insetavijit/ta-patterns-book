"""Unit tests for CLI parsers, logging formatters, and exit codes in trade_book_charts."""

import json
import logging
import unittest
from unittest.mock import patch

from trade_book_charts.cli import (
    _JsonLogFormatter,
    _configure_logging,
    _JsonAwareArgumentParser,
    main,
)
from trade_book_charts.models import EXIT_OK, EXIT_BAD_INPUT


class TestTradeBookCLI(unittest.TestCase):
    def test_json_log_formatter(self):
        """_JsonLogFormatter must format record as JSON payload."""
        formatter = _JsonLogFormatter()
        record = logging.LogRecord("test", logging.INFO, "path", 1, "test message", (), None)
        out = formatter.format(record)
        data = json.loads(out)
        self.assertEqual(data["level"], "info")
        self.assertEqual(data["message"], "test message")

    def test_configure_logging(self):
        """_configure_logging must set logger handler without error."""
        _configure_logging(quiet=True, json_logs=True)
        _configure_logging(quiet=False, json_logs=False)

    def test_json_aware_argument_parser_error(self):
        """_JsonAwareArgumentParser should exit with EXIT_BAD_INPUT on error."""
        parser = _JsonAwareArgumentParser(prog="test_parser")
        with self.assertRaises(SystemExit) as ctx:
            parser.error("test error")
        self.assertEqual(ctx.exception.code, EXIT_BAD_INPUT)

    def test_main_help(self):
        """trade_book_charts main --help should exit with code 0."""
        with patch("sys.argv", ["trade-book-charts", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, EXIT_OK)


if __name__ == "__main__":
    unittest.main()
