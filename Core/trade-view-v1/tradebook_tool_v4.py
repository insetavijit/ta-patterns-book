#!/usr/bin/env python3
"""tradebook_tool v4 CLI Executable Entrypoint.

Delegates execution to the modular `trade_view` package (`trade_view.cli.main`).
"""

import sys
from trade_view.cli import main

if __name__ == "__main__":
    sys.exit(main())
