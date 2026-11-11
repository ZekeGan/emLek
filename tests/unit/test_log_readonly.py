"""W04: emLek must start where the log cannot be written (a read-only sandbox)."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from emlek import log


def test_an_unwritable_log_falls_back_to_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Refusing(RotatingFileHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise PermissionError("read-only sandbox")

    monkeypatch.setattr(log, "RotatingFileHandler", Refusing)
    logger = logging.getLogger(log.LOGGER_NAME)
    before = list(logger.handlers)
    try:
        log.setup_logging(tmp_path / "vault")
        log.setup_logging(tmp_path / "vault")  # twice: still one fallback handler
        added = [h for h in logger.handlers if h not in before]
        assert [type(h) for h in added] == [logging.NullHandler]
        logger.info("still fine")
        said = capsys.readouterr()
        assert said.out == ""  # stdout belongs to the MCP protocol
        assert said.err.count("無法寫入日誌") == 1  # said once, not on every call
    finally:
        for handler in logger.handlers[:]:
            if handler not in before:
                logger.removeHandler(handler)
