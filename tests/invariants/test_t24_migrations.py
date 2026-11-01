"""T24 (M1 part): migrations apply in order, back up first, and roll back on failure."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from emlek.core.db import Database, Migration, load_migrations
from emlek.core.errors import EmlekError, ErrorCode


def _tables(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def test_real_migrations_are_numbered_from_one() -> None:
    versions = [m.version for m in load_migrations()]
    assert versions == list(range(1, len(versions) + 1))


def test_fresh_database_gets_the_current_schema(tmp_path: Path) -> None:
    db = Database.open(tmp_path / "a.db", must_exist=False)
    try:
        assert db.user_version == len(load_migrations())
        assert {"meta", "records", "revisions", "revisions_fts"} <= _tables(db.path)
    finally:
        db.close()


def test_pending_migrations_run_in_order_and_set_the_version(tmp_path: Path) -> None:
    db = Database(tmp_path / "a.db")
    try:
        migrations = [
            Migration(1, "a", "CREATE TABLE a (x);"),
            Migration(2, "b", "CREATE TABLE b (x);"),
        ]
        assert db.apply_migrations(migrations, tmp_path / "bk") == [1, 2]
        assert db.user_version == 2
        assert db.apply_migrations(migrations, tmp_path / "bk") == []
        assert not (tmp_path / "bk").exists()  # nothing to back up on a brand-new database
    finally:
        db.close()


def test_a_backup_is_taken_before_upgrading_existing_data(tmp_path: Path) -> None:
    db = Database(tmp_path / "a.db")
    try:
        first = Migration(1, "a", "CREATE TABLE a (x); INSERT INTO a VALUES (7);")
        db.apply_migrations([first], tmp_path / "bk")
        db.apply_migrations([first, Migration(2, "b", "CREATE TABLE b (x);")], tmp_path / "bk")
    finally:
        db.close()
    backups = list((tmp_path / "bk").glob("pre-migration-v1-*.db"))
    assert len(backups) == 1
    assert _tables(backups[0]) == {"a"}


def test_a_failing_migration_changes_nothing(tmp_path: Path) -> None:
    db = Database(tmp_path / "a.db")
    try:
        good = Migration(1, "a", "CREATE TABLE a (x);")
        bad = Migration(2, "b", "CREATE TABLE b (x); INSERT INTO missing_table VALUES (1);")
        with pytest.raises(EmlekError) as info:
            db.apply_migrations([good, bad], tmp_path / "bk")
        assert info.value.code is ErrorCode.INTERNAL
        assert db.user_version == 1
        assert "b" not in _tables(db.path)
        assert not db.conn.in_transaction
    finally:
        db.close()


def test_upgrading_an_existing_vault_keeps_data_and_builds_the_index(tmp_path: Path) -> None:
    from emlek.core import search, service
    from emlek.core.permissions import Caller, Channel

    path = tmp_path / "old.db"
    first_only = load_migrations()[:1]
    old = Database.open(path, must_exist=False, migrations=first_only)
    cli = Caller(Channel.CLI)
    service.save(old, cli, body="アップグレード前の記録 京都", event_time="2026-03")
    old.close()

    upgraded = Database.open(path, backup_dir=tmp_path / "bk")
    try:
        assert upgraded.user_version == len(load_migrations())
        assert service.get(upgraded, cli, ref="r1")["body"] == "アップグレード前の記録 京都"
        found = search.search(upgraded, cli, query="アップグレード")
        assert found["total"] == 1
        in_march = search.search(upgraded, cli, date_from="2026-03-15", date_to="2026-03-16")
        assert in_march["total"] == 1  # derived date columns work for rows written before them
    finally:
        upgraded.close()
    backups = list((tmp_path / "bk").glob("pre-migration-v1-*.db"))
    assert len(backups) == 1
    assert "revisions_fts" not in _tables(backups[0])  # the backup is the old shape
