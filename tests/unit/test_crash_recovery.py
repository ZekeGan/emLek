"""Only the reproduced Windows truncation race gets a bounded recovery window."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_spec = importlib.util.spec_from_file_location(
    "crash_case", Path(__file__).parents[1] / "invariants/test_t06_crash.py"
)
assert _spec is not None and _spec.loader is not None
crash_case = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crash_case)


@pytest.mark.parametrize(
    ("platform", "code", "recovers"),
    [
        ("win32", sqlite3.SQLITE_IOERR_TRUNCATE, True),
        ("linux", sqlite3.SQLITE_IOERR_TRUNCATE, False),
        ("win32", sqlite3.SQLITE_CORRUPT, False),
    ],
)
def test_only_windows_truncate_is_retried(
    monkeypatch: pytest.MonkeyPatch, platform: str, code: int, recovers: bool
) -> None:
    error = sqlite3.OperationalError("synthetic error")
    error.sqlite_errorcode = code
    first, second = MagicMock(), MagicMock()
    first.execute.side_effect = error
    second.execute.return_value.fetchone.return_value = ("ok",)
    connect = MagicMock(side_effect=[first, second])
    monkeypatch.setattr(crash_case.sqlite3, "connect", connect)
    monkeypatch.setattr(crash_case.sys, "platform", platform)
    monkeypatch.setattr(crash_case.time, "sleep", lambda _: None)
    if recovers:
        conn, integrity = crash_case._recover_after_kill(Path("synthetic.db"))
        assert conn is second and integrity == "ok" and connect.call_count == 2
    else:
        with pytest.raises(sqlite3.OperationalError):
            crash_case._recover_after_kill(Path("synthetic.db"))
        assert connect.call_count == 1
    first.close.assert_called_once()


def test_persistent_truncate_error_still_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    error = sqlite3.OperationalError("synthetic error")
    error.sqlite_errorcode = sqlite3.SQLITE_IOERR_TRUNCATE
    conn = MagicMock()
    conn.execute.side_effect = error
    monkeypatch.setattr(crash_case.sqlite3, "connect", lambda _: conn)
    monkeypatch.setattr(crash_case.sys, "platform", "win32")
    monkeypatch.setattr(crash_case.time, "monotonic", MagicMock(side_effect=[0, 2]))
    with pytest.raises(sqlite3.OperationalError):
        crash_case._recover_after_kill(Path("synthetic.db"))
    conn.close.assert_called_once()
