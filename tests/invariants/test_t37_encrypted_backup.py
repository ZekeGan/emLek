"""T37: an encrypted backup is made only by a person at a terminal, leaves no plain copy behind,
restores with the right password, and a crash leaves nothing usable-looking."""

from __future__ import annotations

from pathlib import Path

import pytest

from emlek.core import backup, backup_crypto, service
from emlek.core.db import Database
from emlek.core.doctor import run_checks
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel

PERSON = Caller(Channel.CLI, interactive=True)
PASSWORD = "a long enough password"


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backup_crypto, "DEFAULT_LOG2N", 14)


@pytest.fixture
def filled(db: Database) -> Database:
    for i in range(5):
        service.save(db, PERSON, body=f"京都の記録{i}", event_time="2026-10-01")
    return db


def _made(db: Database, data_dir: Path, tmp_path: Path) -> dict[str, object]:
    return backup.create_backup(db, PERSON, tmp_path / "bk", data_dir, password=PASSWORD)


def test_only_a_person_at_a_terminal_can_encrypt(
    filled: Database, data_dir: Path, tmp_path: Path
) -> None:
    for blocked in (Caller(Channel.CLI), Caller(Channel.MCP, interactive=True)):
        with pytest.raises(EmlekError) as info:
            backup.create_backup(filled, blocked, tmp_path / "bk", data_dir, password=PASSWORD)
        assert info.value.code is ErrorCode.NOT_PERMITTED
    assert not (tmp_path / "bk").exists()


def test_an_encrypted_backup_leaves_no_plain_copy_and_says_so(
    filled: Database, data_dir: Path, tmp_path: Path
) -> None:
    made = _made(filled, data_dir, tmp_path)
    file = Path(str(made["file"]))
    assert file.name.endswith(".db.enc") and made["encrypted"] is True and made["records"] == 5
    assert backup_crypto.is_encrypted(file)
    assert b"SQLite format 3" not in file.read_bytes()[:64]
    assert list((data_dir / "tmp").iterdir()) == []
    assert list((tmp_path / "bk").glob("*.partial")) == []
    row = filled.conn.execute("SELECT value FROM meta WHERE key='last_backup_encrypted'").fetchone()
    assert row[0] == "1"
    checks = {c["name"]: c for c in run_checks(PERSON, data_dir)["checks"]}
    assert "已加密" in checks["backup"]["detail"]


def test_a_plain_backup_is_marked_plain(filled: Database, data_dir: Path, tmp_path: Path) -> None:
    made = backup.create_backup(filled, PERSON, tmp_path / "bk", data_dir)
    assert made["encrypted"] is False and made["file"].endswith(".db")
    row = filled.conn.execute("SELECT value FROM meta WHERE key='last_backup_encrypted'").fetchone()
    assert row[0] == "0"


def test_a_failed_encryption_leaves_nothing_behind(
    filled: Database, data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_a: object, **_k: object) -> str:
        raise EmlekError(ErrorCode.INTERNAL, "boom")

    monkeypatch.setattr(backup_crypto, "decrypt_file", broken)  # the verification step fails
    with pytest.raises(EmlekError):
        _made(filled, data_dir, tmp_path)
    assert list((tmp_path / "bk").iterdir()) == [] and list((data_dir / "tmp").iterdir()) == []


def test_a_crash_leftover_is_cleaned_at_the_next_backup(
    filled: Database, data_dir: Path, tmp_path: Path
) -> None:
    (tmp_path / "bk").mkdir()
    (tmp_path / "bk" / "emlek-old.db.enc.partial").write_bytes(b"half")
    (data_dir / "tmp").mkdir(exist_ok=True)
    (data_dir / "tmp" / "backup-old.db").write_bytes(b"plain")
    _made(filled, data_dir, tmp_path)
    assert list((tmp_path / "bk").glob("*.partial")) == []
    assert list((data_dir / "tmp").iterdir()) == []


def test_restore_from_an_encrypted_backup(filled: Database, data_dir: Path, tmp_path: Path) -> None:
    file = Path(str(_made(filled, data_dir, tmp_path)["file"]))
    service.save(filled, PERSON, body="後から足した記録")  # not in the backup
    filled.close()
    with pytest.raises(EmlekError):
        backup.open_backup(file, data_dir, None)  # a password is needed
    with pytest.raises(EmlekError) as wrong:
        backup.open_backup(file, data_dir, "the wrong password")
    assert wrong.value.code is ErrorCode.INVALID_INPUT
    assert not (data_dir / "emlek.db.decrypted").exists()
    plain, staged = backup.open_backup(file, data_dir, PASSWORD)
    assert staged and backup.inspect_database(plain)["records"] == 5
    person = Caller(Channel.CLI, interactive=True, pin_verified=True)
    result = backup.restore_backup(person, data_dir, plain, consume=True, restored_from=file)
    assert result["records"] == 5 and result["restored_from"] == str(file)
    assert not plain.exists()  # consumed, never copied twice
    assert not (data_dir / "emlek.db.restoring").exists()


def test_a_plain_file_passes_through_open_backup(
    filled: Database, data_dir: Path, tmp_path: Path
) -> None:
    made = backup.create_backup(filled, PERSON, tmp_path / "bk", data_dir)
    plain, staged = backup.open_backup(Path(str(made["file"])), data_dir, None)
    assert plain == Path(str(made["file"])) and staged is False
