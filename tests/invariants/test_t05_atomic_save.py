"""T05: a save either happens completely or not at all."""

from __future__ import annotations

from typing import Any

import pytest

from emlek.core import service
from emlek.core.db import Database
from emlek.core.permissions import Caller


def _counts(db: Database) -> tuple[int, int]:
    records = db.conn.execute("SELECT count(*) FROM records").fetchone()[0]
    revisions = db.conn.execute("SELECT count(*) FROM revisions").fetchone()[0]
    return records, revisions


def test_failure_after_all_writes_rolls_everything_back(
    db: Database, caller: Caller, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> None:
        raise RuntimeError("injected before commit")

    monkeypatch.setattr(service, "_before_commit", boom)
    with pytest.raises(RuntimeError):
        service.save(db, caller, body="途中で失敗する")
    assert _counts(db) == (0, 0)
    assert not db.conn.in_transaction


def test_failure_while_writing_the_version_leaves_no_orphan_record(
    db: Database, caller: Caller, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> int:
        raise RuntimeError("injected while inserting revision")

    monkeypatch.setattr(service, "_insert_revision", boom)
    with pytest.raises(RuntimeError):
        service.save(db, caller, body="途中で失敗する")
    assert _counts(db) == (0, 0)


def test_next_save_works_after_a_failure(
    db: Database, caller: Caller, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(service, "_before_commit", lambda: (_ for _ in ()).throw(RuntimeError("x")))
        with pytest.raises(RuntimeError):
            service.save(db, caller, body="失敗")
    saved = service.save(db, caller, body="成功")
    assert saved["ref"] == "r1" or saved["record_id"] >= 1
    assert _counts(db) == (1, 1)
