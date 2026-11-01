"""T11 (M1 subset): input limits and error codes. Tag limits arrive with M7."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from emlek.core import service
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller
from emlek.core.timeutil import infer_precision, is_valid_event_time

BAD_BODIES = ["", "   \n\t ", "a\x00b", "\ud800 lone surrogate", "x" * ((1 << 20) + 1)]


@pytest.mark.parametrize("body", BAD_BODIES)
def test_bad_bodies_are_rejected(db: Database, caller: Caller, body: str) -> None:
    with pytest.raises(EmlekError) as info:
        service.save(db, caller, body=body)
    assert info.value.code is ErrorCode.INVALID_INPUT
    assert db.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 0


def test_exactly_one_mebibyte_is_allowed(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="x" * (1 << 20))


def test_multibyte_size_is_counted_in_bytes(db: Database, caller: Caller) -> None:
    with pytest.raises(EmlekError):
        service.save(db, caller, body="日" * ((1 << 20) // 3 + 1))


def test_bad_metadata_is_rejected(db: Database, caller: Caller) -> None:
    for kwargs in (
        {"kind": "note"},
        {"source": "s" * 501},
        {"event_time": "2026-02-30"},
        {"event_time": "2026-01-15", "event_time_precision": "month"},
        {"event_time_precision": "day"},
        {"event_time": "2026-01-15T09:30"},
    ):
        with pytest.raises(EmlekError) as info:
            service.save(db, caller, body="ok", **kwargs)  # type: ignore[arg-type]
        assert info.value.code is ErrorCode.INVALID_INPUT


@pytest.mark.parametrize(
    ("value", "precision"),
    [
        ("2026", "year"),
        ("2026-11", "month"),
        ("2026-11-01", "day"),
        ("2026-01-15T09+09:00", "hour"),
        ("2026-01-15T09:30Z", "minute"),
        ("2026-01-15T09:30:45-05:00", "second"),
    ],
)
def test_valid_event_times_and_inference(value: str, precision: str) -> None:
    assert is_valid_event_time(value, precision)
    assert infer_precision(value) == precision


@pytest.mark.parametrize(
    ("value", "precision"),
    [
        ("2026-13", "month"),
        ("2026-02-30", "day"),
        ("2026-01-15T25:00Z", "minute"),
        ("2026-01-15T09:30", "minute"),
        ("26-01-15", "day"),
        ("2026-01-15T09:30+25:00", "minute"),
    ],
)
def test_invalid_event_times(value: str, precision: str) -> None:
    assert not is_valid_event_time(value, precision)


def test_event_time_roundtrips_with_precision(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="約束", event_time="2026-12-24T18:00+09:00")
    got = service.get(db, caller, ref="r1")
    assert (got["event_time"], got["event_time_precision"]) == ("2026-12-24T18:00+09:00", "minute")


def test_unknown_or_malformed_refs(db: Database, caller: Caller) -> None:
    with pytest.raises(EmlekError) as missing:
        service.get(db, caller, ref="r99")
    assert missing.value.code is ErrorCode.NOT_FOUND
    for bad in ("abc", "r", "r1.v", "1.2"):
        with pytest.raises(EmlekError) as info:
            service.get(db, caller, ref=bad)
        assert info.value.code is ErrorCode.INVALID_INPUT
    service.save(db, caller, body="一版")
    with pytest.raises(EmlekError) as info:
        service.get(db, caller, ref="r1.v2")
    assert info.value.code is ErrorCode.NOT_FOUND


def _run(data_dir: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    cmd = [sys.executable, "-m", "emlek", "--data-dir", str(data_dir), "--json", *args]
    return subprocess.run(cmd, capture_output=True, check=False)


def test_cli_exit_codes(data_dir: Path) -> None:
    assert _run(data_dir, "save", "--text", "").returncode == 2
    assert _run(data_dir, "get", "r99").returncode == 4
    assert _run(data_dir, "get", "nonsense").returncode == 2
    assert _run(data_dir, "no-such-command").returncode == 2
    ok = _run(data_dir, "save", "--text", "正常")
    assert ok.returncode == 0
    assert json.loads(ok.stdout.decode("utf-8"))["ok"] is True
    bad = json.loads(_run(data_dir, "get", "r99").stdout.decode("utf-8"))
    assert bad["ok"] is False
    assert bad["error"]["code"] == "NOT_FOUND"


def test_cli_without_initialised_vault_says_so(tmp_path: Path) -> None:
    result = _run(tmp_path / "nowhere", "get", "r1")
    assert result.returncode == 4
    assert "emlek init" in json.loads(result.stdout.decode("utf-8"))["error"]["message"]
