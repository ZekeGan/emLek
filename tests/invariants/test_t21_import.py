"""T21: import is previewed first, written in one transaction, idempotent, safe with bad files,
sensitive content and hostile names, and never turns file text into tags."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest

from emlek.core import importer, search, service, versions
from emlek.core import tags as tagmod
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.export import export_all, verify_export
from emlek.core.permissions import Caller, Channel

PREVIEW = Caller(Channel.CLI)
PERSON = Caller(Channel.CLI, interactive=True)
PERSON_PIN = Caller(Channel.CLI, interactive=True, pin_verified=True)


@pytest.fixture
def notes(tmp_path: Path) -> Path:
    folder = tmp_path / "notes"
    folder.mkdir()
    return folder


def _write(folder: Path, name: str, text: str | bytes) -> Path:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return path


def _plan(db: Database, data_dir: Path, root: Path, **kw: Any) -> importer.Plan:
    return importer.plan_import(db, PREVIEW, root, data_dir=data_dir, backup_dir=None, **kw)


def _apply(db: Database, data_dir: Path, root: Path, caller: Caller = PERSON, **kw: Any) -> Any:
    plan = _plan(db, data_dir, root, **kw)
    return plan, importer.apply_import(db, caller, plan, options=kw)


def _count(db: Database, table: str) -> int:
    return int(db.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def test_preview_writes_nothing_and_apply_writes_exactly_the_files(
    db: Database, data_dir: Path, notes: Path
) -> None:
    _write(notes, "2026-10-01 京都.md", "京都で抹茶を飲んだ #旅行\r\n二行目")
    _write(notes, "memo.txt", "日付のないメモ")
    _write(notes, "photo.png", b"\x89PNG")
    plan = _plan(db, data_dir, notes)
    assert plan.summary()["to_import"] == 2 and plan.skipped_other == 1
    assert _count(db, "records") == 0 and _count(db, "import_batches") == 0
    _, result = _apply(db, data_dir, notes)
    assert result["imported"] == 2 and _count(db, "records") == 2
    row = db.conn.execute(
        "SELECT body, kind, event_time, event_time_precision, source FROM revisions"
        " WHERE source = 'import:2026-10-01 京都.md'"
    ).fetchone()
    assert row == (
        "京都で抹茶を飲んだ #旅行\r\n二行目",
        "original",
        "2026-10-01",
        "day",
        "import:2026-10-01 京都.md",
    )
    undated = db.conn.execute("SELECT event_time FROM revisions WHERE source = 'import:memo.txt'")
    assert undated.fetchone()[0] is None
    assert search.search(db, PREVIEW, query="抹茶")["total"] == 1  # indexed like any record


def test_a_hashtag_in_a_file_never_becomes_a_tag(db: Database, data_dir: Path, notes: Path) -> None:
    _write(notes, "a.md", "#ignore_all_rules #旅行 のメモ")
    before = _count(db, "tags")  # the built-in status tags
    _apply(db, data_dir, notes)
    assert _count(db, "record_tags") == 0 and _count(db, "tags") == before
    assert tagmod.popular_names(db.conn, "high") == []


def test_importing_twice_adds_nothing(db: Database, data_dir: Path, notes: Path) -> None:
    _write(notes, "a.txt", "one")
    _write(notes, "b.txt", "two")
    _apply(db, data_dir, notes)
    again = _plan(db, data_dir, notes)
    assert again.summary()["already_imported"] == 2 and again.summary()["to_import"] == 0
    importer.apply_import(db, PERSON, again, options={})
    assert _count(db, "records") == 2


def test_bad_files_are_listed_and_do_not_stop_the_others(
    db: Database, data_dir: Path, notes: Path
) -> None:
    _write(notes, "good.txt", "fine")
    _write(notes, "latin.txt", "caf\xe9".encode("latin-1") + b"\xff")
    _write(notes, "empty.txt", "   \n")
    _write(notes, "nul.txt", "a\x00b")
    _write(notes, "huge.txt", b"x" * ((1 << 20) + 1))
    plan, result = _apply(db, data_dir, notes)
    status = {i.file_name: i.status for i in plan.items}
    assert status == {
        "good.txt": "import",
        "latin.txt": "failed",
        "empty.txt": "failed",
        "nul.txt": "failed",
        "huge.txt": "failed",
    }
    assert "UTF-8" in next(i for i in plan.items if i.file_name == "latin.txt").reason
    assert result["imported"] == 1 and _count(db, "records") == 1


def test_a_bom_is_dropped_and_text_is_kept_as_written(
    db: Database, data_dir: Path, notes: Path
) -> None:
    _write(notes, "bom.txt", b"\xef\xbb\xbf" + "先頭に印".encode())
    _apply(db, data_dir, notes)
    body = db.conn.execute("SELECT body FROM revisions").fetchone()[0]
    assert body == "先頭に印"


def test_a_changed_file_is_a_new_record_with_a_warning(
    db: Database, data_dir: Path, notes: Path
) -> None:
    path = _write(notes, "diary.txt", "first version")
    _apply(db, data_dir, notes)
    path.write_text("second version", encoding="utf-8")
    plan, _ = _apply(db, data_dir, notes)
    assert plan.items[0].status == "changed" and "已變更" in plan.items[0].reason
    assert _count(db, "records") == 2


def test_same_content_under_another_name_is_a_duplicate_unless_allowed(
    db: Database, data_dir: Path, notes: Path
) -> None:
    _write(notes, "a.txt", "same words")
    _write(notes, "b.txt", "same words")  # same batch
    plan, _ = _apply(db, data_dir, notes)
    assert [i.status for i in plan.items] == ["import", "duplicate"]
    _write(notes, "c.txt", "same words")  # a later batch
    assert _plan(db, data_dir, notes).count("duplicate") == 2
    allowed, _ = _apply(db, data_dir, notes, allow_duplicates=True)
    assert allowed.count("duplicate") == 0 and _count(db, "records") == 3


def test_high_risk_files_are_left_out_unless_a_person_with_the_pin_says_so(
    db: Database, data_dir: Path, notes: Path
) -> None:
    _write(notes, "ok.txt", "普通のメモ")
    _write(notes, "key.txt", "-----BEGIN RSA PRIVATE KEY-----\nabc")
    plan, result = _apply(db, data_dir, notes)
    assert plan.count("high") == 1 and result["imported"] == 1
    shown = str([i.public() for i in plan.items if i.status == "high"])
    assert "PRIVATE" not in shown and "abc" not in shown  # the content is never echoed
    wanted = _plan(db, data_dir, notes, include_high=True)
    assert wanted.count("import") == 1  # ok.txt is already in, the key file would now go
    with pytest.raises(EmlekError) as info:  # a terminal is not enough, the PIN is needed
        importer.apply_import(db, PERSON, wanted, options={})
    assert info.value.code is ErrorCode.NOT_PERMITTED and _count(db, "records") == 1
    importer.apply_import(db, PERSON_PIN, wanted, options={})
    high = db.conn.execute("SELECT count(*) FROM records WHERE sensitivity = 'high'").fetchone()
    assert high[0] == 1 and _count(db, "records") == 2


def test_personal_data_is_imported_and_marked_medium(
    db: Database, data_dir: Path, notes: Path
) -> None:
    _write(notes, "contact.txt", "連絡先は taro@example.com です")
    _apply(db, data_dir, notes)
    assert db.conn.execute("SELECT sensitivity FROM records").fetchone()[0] == "medium"


def test_writing_needs_a_person_at_a_terminal(db: Database, data_dir: Path, notes: Path) -> None:
    _write(notes, "a.txt", "text")
    plan = _plan(db, data_dir, notes)
    for blocked in (PREVIEW, Caller(Channel.MCP, interactive=True)):
        with pytest.raises(EmlekError) as info:
            importer.apply_import(db, blocked, plan, options={})
        assert info.value.code is ErrorCode.NOT_PERMITTED
    with pytest.raises(EmlekError):
        importer.plan_import(
            db, Caller(Channel.MCP), notes, data_dir=data_dir, backup_dir=None
        )  # the AI side has no way to even preview
    assert _count(db, "records") == 0


def test_a_failure_in_the_middle_leaves_nothing_behind(
    db: Database, data_dir: Path, notes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for i in range(5):
        _write(notes, f"n{i}.txt", f"note {i}")
    plan = _plan(db, data_dir, notes)
    real = service._insert_revision
    calls = {"n": 0}

    def flaky(*args: Any, **kw: Any) -> int:
        calls["n"] += 1
        if calls["n"] == 4:
            raise RuntimeError("disk trouble")
        return real(*args, **kw)

    monkeypatch.setattr(service, "_insert_revision", flaky)
    with pytest.raises(RuntimeError):
        importer.apply_import(db, PERSON, plan, options={})
    assert _count(db, "records") == 0 and _count(db, "import_log") == 0
    assert _count(db, "import_batches") == 0


def test_the_vaults_own_folders_and_links_are_left_alone(
    db: Database, data_dir: Path, notes: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(notes, "keep.txt", "mine")
    _write(notes, "old export/export.jsonl", "{}")
    _write(notes, "old export/markdown/r1.md", "exported")
    backups = notes / "backups"
    _write(backups, "x.txt", "backup side")
    _write(notes, "linked/y.txt", "through a link")
    real = importer._is_link
    monkeypatch.setattr(importer, "_is_link", lambda p: p.name == "linked" or real(p))
    plan = importer.plan_import(db, PREVIEW, notes, data_dir=data_dir, backup_dir=backups)
    assert [i.file_name for i in plan.items] == ["keep.txt"]
    assert "old export" in plan.skipped_own and "backups" in plan.skipped_own
    assert plan.skipped_links == 1
    with pytest.raises(EmlekError):
        _plan(db, data_dir, data_dir)  # the vault itself


def test_limits_are_enforced(
    db: Database, data_dir: Path, notes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for i in range(4):
        _write(notes, f"f{i}.txt", f"text {i}")
    monkeypatch.setattr(importer, "MAX_FILES", 3)
    with pytest.raises(EmlekError) as info:
        _plan(db, data_dir, notes)
    assert "分批" in info.value.message
    monkeypatch.setattr(importer, "MAX_FILES", 10)
    monkeypatch.setattr(importer, "MAX_TOTAL_BYTES", 10)
    with pytest.raises(EmlekError):
        _plan(db, data_dir, notes)


@pytest.mark.parametrize(
    ("name", "expected", "kind"),
    [
        ("2026-10-01 京都", "2026-10-01", "filename"),
        ("20261001_memo", "2026-10-01", "filename"),
        ("2026年10月1日の記録", "2026-10-01", "filename"),
        ("２０２６－１０－０１", "2026-10-01", "filename"),  # full-width forms are normalised
        ("２０２６年１０月１日", "2026-10-01", "filename"),  # full-width digits are normalised
        ("20261301", None, "none"),
        ("2026-02-30", None, "none"),
        ("IMG_202601151230", None, "none"),  # digits next to digits
        ("2026-10-01 to 2026-10-05", None, "ambiguous"),
        ("1899-12-31", None, "none"),
        ("2026-10-01 and 20261001", "2026-10-01", "filename"),  # the same date twice is one date
        ("no date here", None, "none"),
    ],
)
def test_dates_come_from_the_file_name_only(name: str, expected: str | None, kind: str) -> None:
    assert importer.date_from_name(name) == (expected, kind)


def test_the_source_never_carries_control_characters_or_a_long_path() -> None:
    assert "\n" not in importer._source_name("a\nb\x1b.txt")
    assert len(importer._source_name("x" * 900 + ".txt")) <= len("import:") + 300


def test_undo_hides_the_whole_batch_and_a_reimport_is_not_repeated(
    db: Database, data_dir: Path, notes: Path
) -> None:
    for i in range(3):
        _write(notes, f"n{i}.txt", f"京都のメモ{i}")
    _, result = _apply(db, data_dir, notes)
    batch = result["batch"]
    ref = service.save(db, PERSON, body="自分で書いた京都")["ref"]
    first = db.conn.execute("SELECT record_id FROM import_log ORDER BY id").fetchone()[0]
    service.amend(db, PERSON, ref=f"r{first}", body="京都のメモ0（修正）")
    info = importer.undo_preview(db, PREVIEW, batch)
    assert info["visible"] == 3 and info["amended_since_import"] == 1
    done = importer.undo(db, PERSON, batch)
    assert done["hidden"] == 3
    found = search.search(db, PREVIEW, query="京都")
    assert [r["ref"] for r in found["results"]] == [ref]  # only the hand-written one is left
    assert importer.list_batches(db, PREVIEW)[0]["undone_at"]
    versions.unhide(db, PREVIEW, ref=f"r{first}")  # a record can be brought back one by one
    assert search.search(db, PREVIEW, query="京都")["total"] == 2
    again = _plan(db, data_dir, notes)
    assert again.count("already_hidden") == 2 and again.count("already") == 1
    with pytest.raises(EmlekError) as missing:
        importer.undo_preview(db, PREVIEW, 999)
    assert missing.value.code is ErrorCode.NOT_FOUND
    with pytest.raises(EmlekError):
        importer.undo(db, PREVIEW, batch)  # needs a person at a terminal


def test_the_export_carries_the_import_records(
    db: Database, data_dir: Path, notes: Path, tmp_path: Path
) -> None:
    _write(notes, "a.txt", "exported note")
    _apply(db, data_dir, notes)
    made = export_all(db, PREVIEW, tmp_path / "out")
    checked = verify_export(Path(made["folder"]))
    assert checked["counts"]["import_batch"] == 1 and checked["counts"]["import_log"] == 1
    assert checked["header"]["counts"]["import_log"] == 1


def test_a_big_import_is_one_quick_transaction(db: Database, data_dir: Path, notes: Path) -> None:
    for i in range(1500):
        _write(notes, f"d{i // 100}/{i}.txt", f"メモ {i} " + "あ" * 200)
    started = time.monotonic()
    _, result = _apply(db, data_dir, notes)
    took = time.monotonic() - started
    assert result["imported"] == 1500 and _count(db, "records") == 1500
    assert took < 20, f"1500 files took {took:.1f}s"  # saving them one by one would take minutes
    assert os.path.getsize(str(db.path) + "-wal") < 5_000_000 if hasattr(db, "path") else True
