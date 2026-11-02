"""Helpers shared by command handlers."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from pathlib import Path
from typing import Any

from emlek.config import load_config, resolve_data_dir
from emlek.core import security
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel, require
from emlek.log import setup_logging

_log = logging.getLogger("emlek")


def is_real_terminal(stream: object) -> bool:
    """True only for a console/tty. On Windows `isatty()` is also true for the NUL device, so
    an agent could redirect all three streams to NUL and pass; GetConsoleMode tells them apart."""
    if stream is None or not getattr(stream, "isatty", lambda: False)():
        return False
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        handle = msvcrt.get_osfhandle(stream.fileno())  # type: ignore[attr-defined]
        mode = wintypes.DWORD()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        return bool(kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    except OSError, ValueError, AttributeError:
        return False  # cannot prove it is a console: fail closed


def cli_caller() -> Caller:
    interactive = all(is_real_terminal(s) for s in (sys.stdin, sys.stdout, sys.stderr))
    return Caller(Channel.CLI, interactive=interactive)


def data_dir_of(args: argparse.Namespace) -> Path:
    return resolve_data_dir(args.data_dir)


def open_vault(args: argparse.Namespace) -> Database:
    data_dir = data_dir_of(args)
    config = load_config(data_dir)
    if data_dir.exists():
        setup_logging(data_dir)
    return Database.open(config.db_path)


def parse_links(values: list[str] | None) -> list[dict[str, Any]]:
    """`r12` or `r12:supersedes` -> {"ref": "r12", "relation": "supersedes"}."""
    links: list[dict[str, Any]] = []
    for value in values or []:
        ref, _, relation = value.partition(":")
        links.append({"ref": ref, "relation": relation or None})
    return links


def read_secret(prompt: str = "PIN：") -> str:
    """Read a secret from the console. getpass talks to the console device, so a PIN can never be
    supplied through arguments, environment variables or a pipe."""
    return getpass.getpass(prompt)


def read_new_pin(prompt: str = "設定新的 PIN（至少 6 個字元）：") -> str:
    first = read_secret(prompt)
    if read_secret("再輸入一次：") != first:
        raise EmlekError(ErrorCode.INVALID_INPUT, "兩次輸入的 PIN 不一致")
    return first


def authorize(args: argparse.Namespace, operation: str, *, pin: bool = True) -> Caller:
    """The gate for commands that change what the AI may do: a real terminal first, then the PIN.

    Order matters: nothing is asked of a non-terminal caller, and a locked or missing PIN is
    reported before any prompt. Outcomes go to the log without content."""
    person = cli_caller()
    if not pin:  # operations that need a person at a terminal but not the PIN
        require(Caller(Channel.CLI, interactive=person.interactive), operation)
        _log.info("gate operation=%s result=ok", operation)
        return Caller(Channel.CLI, interactive=True)
    require(Caller(Channel.CLI, interactive=person.interactive, pin_verified=True), operation)
    data_dir = data_dir_of(args)
    db = open_vault(args)
    try:
        try:
            security.ensure_available(db.conn, data_dir)
            security.verify_pin(db, data_dir, read_secret("PIN："))
        except EmlekError:
            _log.warning("gate operation=%s result=denied", operation)
            raise
    finally:
        db.close()
    _log.info("gate operation=%s result=ok", operation)
    return Caller(Channel.CLI, interactive=True, pin_verified=True)
