"""Benchmark-only launcher: the emLek CLI with the MCP reference clock pinned to the bank's day.

The bank's answers are fixed to 2026-11-01. Without the pin the server hands the model the real
date, and runs on a later day measure the date mismatch instead of the product (W04, 2026-11-11).
Only the clock the model is shown changes; stored timestamps and the core are untouched.
"""

from __future__ import annotations

import sys

from emlek.cli import main
from emlek.mcp_server import server

BANK_NOW = "2026-11-01T12:00:00+09:00"


def _pinned(timezone: str) -> dict[str, str]:
    return {"reference_time": BANK_NOW, "timezone": timezone}


server._clock = _pinned

if __name__ == "__main__":
    sys.exit(main())
