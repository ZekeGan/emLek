"""T19: a backup restores to an identical vault; bad backups and busy databases change nothing."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from emlek.config import load_config
from emlek.core import search, service
from emlek.core.backup import create_backup, inspect_database, restore_backup
from emlek.core.db import Database, load_migrations
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel
from emlek.core.stats import stats
from emlek.core.vault import init_vault

Saver = Callable[..., dict[str, Any]]
PERSON = Caller(Channel.CLI, interactive=True, pin_verified=True)

TEXTS = [
    "京都で抹茶を飲んだ 😀",
    "Ｒａｍｅｎ ＴＯＫＹＯ\r\n改行あり",
    "école 學習日文",
    "line1\nline2\n",
    "x" * 5000,
]


@pytest.fixture
def populated(db: Database, save_at: Saver) -> Database:
    for i, text in enumerate(TEXTS):
        save_at(text, created_at=f"2026-0{i + 1}-15T10:00:00.000Z", event_time=f"2026-0{i + 1}-15")
    save_at("事件時間なし")
    return db


def _rows(path: Path) -> dict[str, list[tuple[Any, ...]]]:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return {
            "records": conn.execute("SELECT * FROM records ORDER BY id").fetchall(),
            "revisions": conn.execute("SELECT * FROM revisions ORDER BY id").fetchall(),
            "meta": conn.execute(
                "SELECT * FROM meta WHERE key NOT LIKE 'last_backup%' ORDER BY key"
            ).fetchall(),
        }
    finally:
        conn.close()


def _make_backup(db: Database, tmp_path: Path, data_dir: Path) -> Path:
    result = create_backup(db, Caller(Channel.CLI), tmp_path / "backups", data_dir)
    return Path(result["file"])


def test_backup_then_restore_into_a_clean_folder_is_identical(
    populated: Database, data_dir: Path, tmp_path: Path
) -> None:
    backup = _make_backup(populated, tmp_path, data_dir)
    clean = tmp_path / "new-computer"
    init_vault(PERSON, clean)
    result = restore_backup(PERSON, clean, backup)
    assert (result["records"], result["revisions"]) == (6, 6)

    original, restored = _rows(populated.path), _rows(load_config(clean).db_path)
    assert restored["records"] == original["records"]
    assert restored["revisions"] == original["revisions"]
    assert [m for m in restored["meta"] if m[0] != "created_at"] == [
        m for m in original["meta"] if m[0] != "created_at"
    ]

    db = Database.open(load_config(clean).db_path)
    try:
        assert db.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert search.index_status(db)["ok"]
        assert search.search(db, Caller(Channel.CLI), query="京都")["total"] == 1
        assert service.get(db, Caller(Channel.CLI), ref="r2")["body"] == TEXTS[1]
    finally:
        db.close()


def test_backup_is_recorded_and_visible(
    populated: Database, data_dir: Path, tmp_path: Path
) -> None:
    assert stats(populated, Caller(Channel.CLI))["last_backup_at"] is None
    backup = _make_backup(populated, tmp_path, data_dir)
    after = stats(populated, Caller(Channel.CLI))
    assert after["last_backup_at"] and after["last_backup_file"] == backup.name
    info = inspect_database(backup)
    assert (info["records"], info["revisions"]) == (6, 6)


def test_backup_refuses_a_folder_inside_the_data_folder(
    populated: Database, data_dir: Path
) -> None:
    for inside in (data_dir, data_dir / "sub"):
        with pytest.raises(EmlekError) as info:
            create_backup(populated, Caller(Channel.CLI), inside, data_dir)
        assert info.value.code is ErrorCode.INVALID_INPUT


def test_mcp_cannot_back_up_or_restore(populated: Database, data_dir: Path, tmp_path: Path) -> None:
    for channel in (Channel.MCP, Channel.MCP_READONLY):
        with pytest.raises(EmlekError) as info:
            create_backup(populated, Caller(channel, interactive=True), tmp_path / "b", data_dir)
        assert info.value.code is ErrorCode.NOT_PERMITTED
        with pytest.raises(EmlekError):
            restore_backup(Caller(channel, interactive=True), data_dir, tmp_path / "x.db")


def test_restore_needs_a_person_at_a_terminal(
    populated: Database, data_dir: Path, tmp_path: Path
) -> None:
    backup = _make_backup(populated, tmp_path, data_dir)
    populated.close()
    with pytest.raises(EmlekError) as info:
        restore_backup(Caller(Channel.CLI, interactive=False), data_dir, backup)
    assert info.value.code is ErrorCode.NOT_PERMITTED
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "emlek",
            "--data-dir",
            str(data_dir),
            "restore",
            str(backup),
        ],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert run.returncode == 3  # refused before touching anything
    # All three streams on the null device look like a tty on Windows; they must still be refused.
    nul = subprocess.run(
        [sys.executable, "-m", "emlek", "--data-dir", str(data_dir), "restore", str(backup)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    assert nul.returncode == 3


def test_a_null_device_is_not_a_terminal() -> None:
    from emlek.cli.commands.common import is_real_terminal

    with open(os.devnull, "w", encoding="utf-8") as null:
        assert not is_real_terminal(null)
    assert not is_real_terminal(None)


def test_old_schema_backups_are_upgraded_on_restore(tmp_path: Path) -> None:
    old = Database.open(tmp_path / "old.db", must_exist=False, migrations=load_migrations()[:1])
    service.save(old, Caller(Channel.CLI), body="古い版の備份 京都", event_time="2026-03")
    backup = tmp_path / "v1-backup.db"
    old.backup_to(backup)
    old.close()
    assert inspect_database(backup)["schema_version"] == 1

    target = tmp_path / "vault"
    init_vault(PERSON, target)
    restore_backup(PERSON, target, backup)
    db = Database.open(load_config(target).db_path)
    try:
        assert db.user_version == len(load_migrations())
        found = search.search(db, Caller(Channel.CLI), query="古い版", date_from="2026-03")
        assert found["total"] == 1
    finally:
        db.close()


def test_bad_backups_are_rejected_and_nothing_changes(
    populated: Database, data_dir: Path, tmp_path: Path
) -> None:
    good = _make_backup(populated, tmp_path, data_dir)
    populated.close()
    before = _rows(load_config(data_dir).db_path)

    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"this is not a database" * 100)
    foreign = tmp_path / "foreign.db"
    conn = sqlite3.connect(foreign)
    conn.execute("CREATE TABLE unrelated (x)")
    conn.commit()
    conn.close()
    newer = tmp_path / "newer.db"
    newer.write_bytes(good.read_bytes())
    conn = sqlite3.connect(newer)
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    conn.close()
    truncated = tmp_path / "truncated.db"
    truncated.write_bytes(good.read_bytes()[: good.stat().st_size // 2])

    for bad in (garbage, foreign, newer, truncated, tmp_path / "missing.db"):
        with pytest.raises(EmlekError):
            restore_backup(PERSON, data_dir, bad)
    with pytest.raises(EmlekError):
        restore_backup(PERSON, data_dir, load_config(data_dir).db_path)  # the live file itself

    assert _rows(load_config(data_dir).db_path) == before
    assert not (data_dir / "emlek.db.restoring").exists()


def test_restore_keeps_the_previous_database(
    populated: Database, data_dir: Path, tmp_path: Path
) -> None:
    backup = _make_backup(populated, tmp_path, data_dir)
    service.save(populated, Caller(Channel.CLI), body="バックアップ後に増えた記録")
    populated.close()
    result = restore_backup(PERSON, data_dir, backup)
    assert result["records"] == 6
    kept = Path(result["previous_database_kept_as"])
    assert (
        inspect_database(kept)["records"] == 7
    )  # the record saved after the backup survives there
    db = Database.open(load_config(data_dir).db_path)
    try:
        assert db.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 6
    finally:
        db.close()


def test_restore_is_refused_while_the_database_is_in_use(
    populated: Database, data_dir: Path, tmp_path: Path
) -> None:
    backup = _make_backup(populated, tmp_path, data_dir)
    service.save(populated, Caller(Channel.CLI), body="使用中に増えた記録")
    with pytest.raises(EmlekError) as info:  # `populated` still holds the file open
        restore_backup(PERSON, data_dir, backup)
    assert info.value.code is ErrorCode.BUSY
    assert populated.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 7
    assert not (data_dir / "emlek.db.restoring").exists()
