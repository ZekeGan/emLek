"""T28: where the PIN lives, how it locks, how it recovers, and that backups never move it."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from emlek.config import load_config
from emlek.core import security, service
from emlek.core.backup import create_backup, restore_backup
from emlek.core.db import Database
from emlek.core.doctor import run_checks
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel

PIN = "correct horse"
CLI = Caller(Channel.CLI)
PERSON = Caller(Channel.CLI, interactive=True, pin_verified=True)


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "KDF_N", 16)  # the real cost is for people, not for tests


@pytest.fixture
def with_pin(db: Database, data_dir: Path) -> str:
    return security.set_pin(db, data_dir, PIN)


def _file(data_dir: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((data_dir / security.SECURITY_FILE).read_text("utf-8"))
    return loaded


def _denied(db: Database, data_dir: Path, pin: str) -> EmlekError:
    with pytest.raises(EmlekError) as info:
        security.verify_pin(db, data_dir, pin)
    assert info.value.code is ErrorCode.NOT_PERMITTED
    return info.value


def test_nothing_works_until_a_pin_is_set(db: Database, data_dir: Path) -> None:
    assert security.state(db.conn, data_dir) == security.UNSET
    assert "pin set" in _denied(db, data_dir, PIN).message
    with pytest.raises(EmlekError):
        security.ensure_available(db.conn, data_dir)


def test_setting_a_pin_stores_a_hash_outside_the_database(db: Database, data_dir: Path) -> None:
    code = security.set_pin(db, data_dir, PIN)
    stored = _file(data_dir)
    assert security.state(db.conn, data_dir) == security.SET
    assert PIN not in json.dumps(stored) and stored["pin_hash"]
    meta = json.dumps(db.conn.execute("SELECT key, value FROM meta").fetchall())
    assert stored["pin_hash"] not in meta and PIN not in meta  # not in the database
    assert code.count("-") == 4 and len(code.replace("-", "")) == 20
    with pytest.raises(EmlekError) as info:
        security.set_pin(db, data_dir, "another one")
    assert info.value.code is ErrorCode.CONFLICT


def test_short_pins_are_refused(db: Database, data_dir: Path) -> None:
    with pytest.raises(EmlekError) as info:
        security.set_pin(db, data_dir, "12345")
    assert info.value.code is ErrorCode.INVALID_INPUT
    assert security.state(db.conn, data_dir) == security.UNSET


def test_right_and_wrong_pins(db: Database, data_dir: Path, with_pin: str) -> None:
    security.verify_pin(db, data_dir, PIN)
    assert "再錯 4 次" in _denied(db, data_dir, "wrong one").message
    security.verify_pin(db, data_dir, PIN)  # a success clears the streak
    assert _file(data_dir)["failed_count"] == 0 and _file(data_dir)["failures_since_success"] == 0


def test_five_mistakes_lock_even_the_right_pin_until_the_time_passes(
    db: Database, data_dir: Path, with_pin: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    for _ in range(4):
        _denied(db, data_dir, "nope nope")
    assert "鎖定" in _denied(db, data_dir, "nope nope").message
    assert "鎖定" in _denied(db, data_dir, PIN).message  # correct, but locked
    with pytest.raises(EmlekError):
        security.ensure_available(db.conn, data_dir)

    later = security._now() + timedelta(seconds=security.LOCK_SECONDS + 1)
    monkeypatch.setattr(security, "_now", lambda: later)
    security.verify_pin(db, data_dir, PIN)
    assert _file(data_dir)["locked_until"] is None


def test_an_attempt_is_counted_before_it_is_judged(
    db: Database, data_dir: Path, with_pin: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def killed(*_: object, **__: object) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(security, "_scrypt", killed)
    with pytest.raises(KeyboardInterrupt):
        security.verify_pin(db, data_dir, PIN)
    assert _file(data_dir)["failures_since_success"] == 1  # the process died, the guess still cost


def test_changing_the_pin(db: Database, data_dir: Path, with_pin: str) -> None:
    security.change_pin(db, data_dir, PIN, "a brand new pin")
    _denied(db, data_dir, PIN)
    security.verify_pin(db, data_dir, "a brand new pin")
    with pytest.raises(EmlekError):
        security.change_pin(db, data_dir, "a brand new pin", "short")
    with pytest.raises(EmlekError):  # the old PIN is needed
        security.change_pin(db, data_dir, "not the pin", "yet another pin")


def test_the_recovery_code_resets_once_and_is_replaced(
    db: Database, data_dir: Path, with_pin: str
) -> None:
    new_code = security.reset_pin(db, data_dir, with_pin.lower(), "after the reset")
    assert new_code != with_pin
    security.verify_pin(db, data_dir, "after the reset")
    with pytest.raises(EmlekError):  # the used code is dead
        security.reset_pin(db, data_dir, with_pin, "once more please")
    security.reset_pin(db, data_dir, new_code, "and again fine")


def test_recovery_attempts_lock_too(db: Database, data_dir: Path, with_pin: str) -> None:
    for _ in range(security.MAX_FAILURES):
        with pytest.raises(EmlekError):
            security.reset_pin(db, data_dir, "AAAA-AAAA-AAAA-AAAA-AAAA", "a valid new pin")
    with pytest.raises(EmlekError) as info:
        security.reset_pin(db, data_dir, with_pin, "a valid new pin")
    assert "鎖定" in info.value.message


def test_a_missing_file_is_tampering_and_only_the_recovery_code_helps(
    db: Database, data_dir: Path, with_pin: str
) -> None:
    (data_dir / security.SECURITY_FILE).unlink()
    assert security.state(db.conn, data_dir) == security.TAMPERED
    assert "pin reset" in _denied(db, data_dir, PIN).message
    with pytest.raises(EmlekError) as info:
        security.set_pin(db, data_dir, "a sneaky new pin")  # cannot start over
    assert info.value.code is ErrorCode.CONFLICT
    security.reset_pin(db, data_dir, with_pin, "the real owner pin")
    assert security.state(db.conn, data_dir) == security.SET
    security.verify_pin(db, data_dir, "the real owner pin")


def test_a_damaged_file_is_also_tampering(db: Database, data_dir: Path, with_pin: str) -> None:
    (data_dir / security.SECURITY_FILE).write_text("{not json", encoding="utf-8")
    assert security.state(db.conn, data_dir) == security.TAMPERED


def test_backups_carry_no_pin_and_restores_keep_the_current_one(
    db: Database, data_dir: Path, tmp_path: Path, with_pin: str
) -> None:
    service.save(db, CLI, body="バックアップ前の記録")
    backup = Path(create_backup(db, CLI, tmp_path / "backups", data_dir)["file"])
    assert _file(data_dir)["pin_hash"].encode() not in backup.read_bytes()

    security.change_pin(db, data_dir, PIN, "the newer pin ok")
    service.save(db, CLI, body="バックアップ後の記録")
    db.close()
    restore_backup(PERSON, data_dir, backup)
    again = Database.open(load_config(data_dir).db_path)
    try:
        assert security.state(again.conn, data_dir) == security.SET
        security.verify_pin(again, data_dir, "the newer pin ok")  # not rolled back to the old one
        _denied(again, data_dir, PIN)
    finally:
        again.close()


def test_restoring_a_backup_from_before_the_pin_existed_keeps_this_machines_pin(
    db: Database, data_dir: Path, tmp_path: Path
) -> None:
    service.save(db, CLI, body="PIN より前の記録")
    backup = Path(create_backup(db, CLI, tmp_path / "backups", data_dir)["file"])
    security.set_pin(db, data_dir, PIN)
    db.close()
    restore_backup(PERSON, data_dir, backup)
    again = Database.open(load_config(data_dir).db_path)
    try:
        assert security.state(again.conn, data_dir) == security.SET
        security.verify_pin(again, data_dir, PIN)
    finally:
        again.close()


def test_status_and_doctor_show_attempts_without_secrets(
    db: Database, data_dir: Path, with_pin: str
) -> None:
    _denied(db, data_dir, "guess one")
    _denied(db, data_dir, "guess two")
    info = security.status(db.conn, data_dir)
    assert info["failures_since_success"] == 2 and info["locked"] is False
    checks = {c["name"]: c for c in run_checks(CLI, data_dir)["checks"]}
    assert checks["pin"]["status"] == "warn" and "2 次" in checks["pin"]["detail"]
    assert _file(data_dir)["pin_hash"] not in json.dumps(checks)
    security.verify_pin(db, data_dir, PIN)
    ok = {c["name"]: c for c in run_checks(CLI, data_dir)["checks"]}["pin"]
    assert ok["status"] == "ok"


def test_doctor_calls_a_missing_pin_a_warning_and_a_missing_file_a_failure(
    db: Database, data_dir: Path
) -> None:
    pin = {c["name"]: c for c in run_checks(CLI, data_dir)["checks"]}["pin"]
    assert pin["status"] == "warn"
    security.set_pin(db, data_dir, PIN)
    (data_dir / security.SECURITY_FILE).unlink()
    pin = {c["name"]: c for c in run_checks(CLI, data_dir)["checks"]}["pin"]
    assert pin["status"] == "fail"
