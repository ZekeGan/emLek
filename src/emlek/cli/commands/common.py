"""Helpers shared by command handlers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from emlek.config import load_config, resolve_data_dir
from emlek.core.db import Database
from emlek.core.permissions import Caller, Channel
from emlek.log import setup_logging


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
