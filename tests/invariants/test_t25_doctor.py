"""T25: `doctor` and startup checks report real problems clearly."""

from __future__ import annotations

from pathlib import Path

import pytest

from emlek.core.db import Database, wal_safe
from emlek.core.doctor import run_checks
from emlek.core.permissions import Caller, Channel
from emlek.core.vault import init_vault


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ((3, 53, 1), True),
        ((3, 51, 3), True),
        ((3, 51, 2), False),
        ((3, 50, 7), True),
        ((3, 50, 6), False),
        ((3, 44, 6), True),
        ((3, 44, 5), False),
        ((3, 45, 0), False),
        ((3, 40, 0), False),
    ],
)
def test_wal_fix_detection(version: tuple[int, ...], expected: bool) -> None:
    assert wal_safe(version) is expected


def test_old_sqlite_falls_back_to_the_delete_journal(tmp_path: Path) -> None:
    db = Database(tmp_path / "old.db", sqlite_version=(3, 45, 0))
    try:
        assert db.journal_mode == "delete"
    finally:
        db.close()


def _by_name(result: dict[str, object]) -> dict[str, str]:
    checks = result["checks"]
    assert isinstance(checks, list)
    return {c["name"]: c["status"] for c in checks}


def test_fresh_vault_is_healthy(data_dir: Path, caller: Caller) -> None:
    result = run_checks(caller, data_dir)
    statuses = _by_name(result)
    assert result["status"] == "warn"  # the only warning: no backup has been made yet
    assert statuses["backup"] == "warn"
    assert {n for n, s in statuses.items() if s == "warn"} == {"backup"}
    assert statuses["database"] == "ok"
    assert statuses["permissions"] == "ok"
    assert statuses["disk_encryption"] == "info"


def test_missing_vault_is_a_warning(tmp_path: Path, caller: Caller) -> None:
    result = run_checks(caller, tmp_path / "nowhere")
    assert result["status"] == "warn"
    assert _by_name(result)["data_dir"] == "warn"


def test_vault_inside_a_sync_folder_is_flagged(tmp_path: Path, caller: Caller) -> None:
    path = tmp_path / "OneDrive" / "emlek"
    init_vault(Caller(Channel.CLI), path)
    assert _by_name(run_checks(caller, path))["data_dir"] == "warn"


def test_old_sqlite_is_flagged(data_dir: Path, caller: Caller) -> None:
    result = run_checks(caller, data_dir, sqlite_version=(3, 45, 0))
    assert _by_name(result)["sqlite"] == "warn"


def test_doctor_does_not_change_the_vault(data_dir: Path, caller: Caller) -> None:
    before = sorted(p.name for p in data_dir.iterdir())
    run_checks(caller, data_dir)
    assert sorted(p.name for p in data_dir.iterdir()) == before


def test_loosened_permissions_are_flagged(data_dir: Path, caller: Caller) -> None:
    import subprocess
    import sys

    if sys.platform != "win32":
        pytest.skip("Windows ACL check")
    subprocess.run(
        ["icacls", str(data_dir), "/grant", "*S-1-1-0:(OI)(CI)R"], check=True, capture_output=True
    )
    assert _by_name(run_checks(caller, data_dir))["permissions"] == "warn"
