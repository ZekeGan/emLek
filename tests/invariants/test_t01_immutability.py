"""T01: stored versions can never be changed or deleted (purge excepted)."""

from __future__ import annotations

import sqlite3

import pytest

from emlek.core import service
from emlek.core.db import Database
from emlek.core.permissions import Caller


def _seed(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="原文はそのまま残る")


def test_revision_update_is_rejected(db: Database, caller: Caller) -> None:
    _seed(db, caller)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.conn.execute("UPDATE revisions SET body = '改ざん' WHERE record_id = 1")
    assert service.get(db, caller, ref="r1")["body"] == "原文はそのまま残る"


def test_revision_delete_is_rejected(db: Database, caller: Caller) -> None:
    _seed(db, caller)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.conn.execute("DELETE FROM revisions WHERE record_id = 1")


def test_record_delete_and_identity_change_are_rejected(db: Database, caller: Caller) -> None:
    _seed(db, caller)
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute("DELETE FROM records WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute("UPDATE records SET created_at = '2000-01-01T00:00:00.000Z' WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute("UPDATE records SET id = 99 WHERE id = 1")


def test_hide_flag_stays_mutable(db: Database, caller: Caller) -> None:
    _seed(db, caller)
    db.conn.execute("UPDATE records SET hidden = 1, hidden_at = 'now' WHERE id = 1")
    assert db.conn.execute("SELECT hidden FROM records WHERE id = 1").fetchone()[0] == 1


def test_duplicate_version_is_rejected(db: Database, caller: Caller) -> None:
    _seed(db, caller)
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute(
            "INSERT INTO revisions (record_id, version_no, body, body_norm, kind, created_at)"
            " VALUES (1, 1, 'x', 'x', 'original', 'now')"
        )


def test_other_sqlite_clients_fail_closed(db: Database, caller: Caller) -> None:
    """A client without emlek's function cannot modify history either."""
    _seed(db, caller)
    plain = sqlite3.connect(db.path)
    try:
        with pytest.raises(sqlite3.Error):
            plain.execute("UPDATE revisions SET body = 'x' WHERE record_id = 1")
        with pytest.raises(sqlite3.Error):
            plain.execute("DELETE FROM revisions")
    finally:
        plain.close()


def test_purge_mode_is_the_only_way_through(db: Database, caller: Caller) -> None:
    _seed(db, caller)
    with db.purge_mode(), db.transaction() as conn:
        conn.execute("DELETE FROM revisions WHERE record_id = 1")
        conn.execute("DELETE FROM records WHERE id = 1")
    assert db.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 0
    _seed(db, caller)
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute("DELETE FROM revisions")
