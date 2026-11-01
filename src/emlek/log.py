"""File logging. Records operation names and ids only, never content."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "emlek"


def setup_logging(data_dir: Path) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    target = log_dir / "emlek.log"
    already = any(
        isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == target.resolve()
        for h in logger.handlers
    )
    if not already:
        handler = RotatingFileHandler(target, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger
