"""File logging. Records operation names and ids only, never content."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "emlek"


def setup_logging(data_dir: Path) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    log_dir = data_dir / "logs"
    target = log_dir / "emlek.log"
    already = any(
        isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == target.resolve()
        for h in logger.handlers
    )
    if already:
        return logger
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(
            target, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    except OSError as exc:
        # A read-only sandbox (W04: Codex) cannot write the log; logging is a convenience and
        # must never stop emLek from starting. Say so once on stderr (stdout belongs to MCP).
        if not any(isinstance(h, logging.NullHandler) for h in logger.handlers):
            logger.addHandler(logging.NullHandler())
            print(f"emLek：無法寫入日誌，本次不記錄（{type(exc).__name__}）", file=sys.stderr)
        return logger
    logger.addHandler(handler)
    return logger
