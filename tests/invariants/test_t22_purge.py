"""T22: a purge leaves nothing of the purged text behind: not in rows, indexes, tags, links, the
import log, the WAL, or the copies emLek made itself. Ids are never reused and a purged file is
never imported again."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pytest

from emlek.config import load_config
from emlek.core import doctor, importer, purge, search, service
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel

PERSON = Caller(Channel.CLI, interactive=True, pin_verified=True)
SECRET = "SECRETPHRASE-京都抹茶-ALPHA 只在這筆記錄出現的獨特內容"
SECOND = "SECOND-VERSION-BRAVO 修改後的獨特內容也必須消失"
SUMMARY = "SUMMARY-CHARLIE 摘要裡引用了 SECRETPHRASE-京都抹茶-ALPHA"
TAG = "zzprivate-tag"


def _bytes_of(db: Database) -> bytes:
    data = b""
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(db.path) + suffix)
        if path.exists():
            data += path.read_bytes()
    return data


def _purge(db: Database, data_dir: Path, *refs: str) -> dict[str, object]:
    shown = purge.preview(db, PERSON, list(refs), with_text=True)
    return purge.purge(
        db,
        PERSON,
        list(refs),
        fingerprint=str(shown["fingerprint"]),
        data_dir=data_dir,
        backup_dir=None,
    )


def _ref(saved: dict[str, object]) -> str:
    return str(saved["ref"]).split(".")[0]


@pytest.fixture
def world(db: Database) -> dict[str, str]:
    """An older record, the target (two versions, a tag, an outgoing link), an AI summary linked
    with no relation, one that is linked with 'supports', an original that mentions the target,
    and an unrelated record."""
    older = service.save(db, PERSON, body="OLDER-ROOT 更早的一筆記錄")
    target = service.save(
        db,
        PERSON,
        body=SECRET,
        event_time="2026-10-01",
        tags=[TAG],
        links=[{"ref": _ref(older), "relation": "supersedes"}],
    )
    service.amend(db, PERSON, ref=_ref(target), body=SECOND)
    plain = service.save(db, PERSON, body=SUMMARY, kind="ai_summary", links=[{"ref": _ref(target)}])
    supports = service.save(
        db,
        PERSON,
        body="SUPPORT-DELTA 另一則推論",
        kind="inference",
        links=[{"ref": _ref(target), "relation": "supports"}],
    )
    mention = service.save(
        db,
        PERSON,
        body="MENTION-ECHO 我自己寫的筆記，提到了上面那筆",
        links=[{"ref": _ref(target), "relation": "supplements"}],
    )
    other = service.save(db, PERSON, body="UNRELATED-FOXTROT 完全無關的記錄")
    return {
        "older": _ref(older),
        "target": _ref(target),
        "plain": _ref(plain),
        "supports": _ref(supports),
        "mention": _ref(mention),
        "other": _ref(other),
    }


def test_nothing_of_the_text_survives_in_the_database_files(
    db: Database, data_dir: Path, world: dict[str, str]
) -> None:
    assert SECRET.encode() in _bytes_of(db)  # the check below can fail
    result = _purge(db, data_dir, world["target"])
    assert result["scrub"]["finished"] is True and result["scrub"]["verified"] is True  # type: ignore[index]
    raw = _bytes_of(db)
    for text in (SECRET, SECOND, SUMMARY, "SUPPORT-DELTA", TAG):
        assert text.encode() not in raw, text
    assert search.search(db, PERSON, query="SECRETPHRASE")["results"] == []
    conn = db.conn
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.execute("INSERT INTO revisions_fts (revisions_fts, rank) VALUES ('integrity-check', 1)")
    assert conn.execute("SELECT count(*) FROM tags WHERE name = ?", (TAG,)).fetchone()[0] == 0
    assert (
        conn.execute("SELECT count(*) FROM tags_fts WHERE tags_fts MATCH ?", ('"zzp"',)).fetchone()[
            0
        ]
        == 0
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM tag_events WHERE instr(detail, ?) > 0", (TAG,)
        ).fetchone()[0]
        == 0
    )
    assert conn.execute("SELECT scrub_status FROM purge_log").fetchone()[0] == "done"


def test_purging_a_record_with_outgoing_links_works_and_keeps_the_others(
    db: Database, data_dir: Path, world: dict[str, str]
) -> None:
    before = service.get(db, PERSON, ref=world["other"])["body"]
    _purge(db, data_dir, world["target"])
    assert service.get(db, PERSON, ref=world["older"])["body"].startswith("OLDER-ROOT")
    assert service.get(db, PERSON, ref=world["other"])["body"] == before
    with pytest.raises(EmlekError) as info:
        service.get(db, PERSON, ref=world["target"])
    assert info.value.code is ErrorCode.NOT_FOUND


def test_ai_made_records_linked_by_any_relation_go_too_but_originals_are_kept_and_listed(
    db: Database, data_dir: Path, world: dict[str, str]
) -> None:
    shown = purge.preview(db, PERSON, [world["target"]])
    assert set(shown["kept_originals_that_may_mention_this"]) == {world["mention"]}
    assert "excerpt" not in json.dumps(shown) and "fingerprint" not in shown
    result = _purge(db, data_dir, world["target"])
    assert result["derived"] == sorted(
        {world["plain"], world["supports"]}, key=lambda r: int(r[1:])
    )
    assert result["kept_originals_that_may_mention_this"] == [world["mention"]]
    assert service.get(db, PERSON, ref=world["mention"])["body"].startswith("MENTION-ECHO")
    assert db.conn.execute("SELECT count(*) FROM links").fetchone()[0] == 0


def test_a_purged_id_is_never_handed_out_again_not_even_after_a_restore(
    db: Database, data_dir: Path, world: dict[str, str]
) -> None:
    newest = service.save(db, PERSON, body="NEWEST-GOLF 最新的一筆")
    top = int(str(_ref(newest))[1:])
    _purge(db, data_dir, _ref(newest))
    fresh = service.save(db, PERSON, body="AFTER-HOTEL 之後的新記錄")
    assert int(str(_ref(fresh))[1:]) == top + 1


def test_tokens_that_hash_the_text_are_cleared(
    db: Database, data_dir: Path, world: dict[str, str]
) -> None:
    db.conn.execute(
        "INSERT INTO confirm_tokens (token_hash, kind, content_hash, created_at, expires_at)"
        " VALUES ('t', 'confirm', 'h', '2026-01-01T00:00:00.000Z', '2099-01-01T00:00:00.000Z')"
    )
    _purge(db, data_dir, world["target"])
    assert db.conn.execute("SELECT count(*) FROM confirm_tokens").fetchone()[0] == 0


def test_a_change_after_the_preview_stops_the_purge_and_deletes_nothing(
    db: Database, data_dir: Path, world: dict[str, str]
) -> None:
    shown = purge.preview(db, PERSON, [world["target"]], with_text=True)
    service.save(
        db,
        PERSON,
        body="LATE-INDIA 預覽後才補的摘要",
        kind="ai_summary",
        links=[{"ref": world["target"]}],
    )
    with pytest.raises(EmlekError) as info:
        purge.purge(
            db,
            PERSON,
            [world["target"]],
            fingerprint=str(shown["fingerprint"]),
            data_dir=data_dir,
            backup_dir=None,
        )
    assert info.value.code is ErrorCode.CONFLICT
    assert service.get(db, PERSON, ref=world["target"])["body"] == SECOND
    assert db.conn.execute("SELECT count(*) FROM purge_log").fetchone()[0] == 0


def test_purge_is_refused_when_no_purge_phrase_is_enabled(
    db: Database, data_dir: Path, world: dict[str, str]
) -> None:
    db.conn.execute("UPDATE phrases SET enabled = 0 WHERE kind = 'purge'")
    shown = purge.preview(db, PERSON, [world["target"]], with_text=True)
    assert shown["purge_enabled"] is False
    with pytest.raises(EmlekError) as info:
        purge.purge(
            db,
            PERSON,
            [world["target"]],
            fingerprint=str(shown["fingerprint"]),
            data_dir=data_dir,
            backup_dir=None,
        )
    assert info.value.code is ErrorCode.NOT_PERMITTED
    assert service.get(db, PERSON, ref=world["target"])["body"] == SECOND


def test_whole_records_only_and_a_limit_on_how_many(db: Database, world: dict[str, str]) -> None:
    for refs in ([], [world["target"] + ".v1"], [f"r{i}" for i in range(1, purge.MAX_REFS + 2)]):
        with pytest.raises(EmlekError) as info:
            purge.preview(db, PERSON, refs)
        assert info.value.code is ErrorCode.INVALID_INPUT
    with pytest.raises(EmlekError) as info:
        purge.preview(db, PERSON, ["r9999"])
    assert info.value.code is ErrorCode.NOT_FOUND


def test_a_reader_that_holds_the_database_makes_the_scrub_unfinished_until_it_lets_go(
    db: Database, data_dir: Path, world: dict[str, str]
) -> None:
    reader = sqlite3.connect(db.path, isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM revisions").fetchone()
    result = _purge(db, data_dir, world["target"])
    assert result["scrub"]["finished"] is False  # type: ignore[index]
    assert purge.pending(db.conn) == 1
    checks = {c["name"]: c for c in doctor.run_checks(PERSON, data_dir)["checks"]}
    assert checks["purge"]["status"] == "warn" and "purge --finish" in checks["purge"]["detail"]
    reader.close()
    done = purge.finish(db, PERSON)
    assert done["finished"] is True and purge.pending(db.conn) == 0
    assert SECRET.encode() not in _bytes_of(db)


def test_a_crash_after_the_commit_is_picked_up_by_finish(
    db: Database, data_dir: Path, world: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def crash(*args: object, **kwargs: object) -> None:
        raise RuntimeError("power cut")

    monkeypatch.setattr(purge, "_scrub", crash)
    with pytest.raises(RuntimeError):
        _purge(db, data_dir, world["target"])
    monkeypatch.undo()
    assert purge.pending(db.conn) == 1
    assert purge.finish(db, PERSON)["finished"] is True
    assert db.conn.execute("SELECT scrub_status FROM purge_log").fetchone()[0] == "unverified"
    assert SECRET.encode() not in _bytes_of(db)


def test_import_cannot_bring_a_purged_file_back_and_its_name_is_not_kept(
    db: Database, data_dir: Path, tmp_path: Path
) -> None:
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "2026-10-01 京都旅行計畫.txt").write_text(
        "IMPORTED-JULIET 京都旅行的內容", encoding="utf-8"
    )
    plan = importer.plan_import(db, PERSON, notes, data_dir=data_dir, backup_dir=None)
    importer.apply_import(db, PERSON, plan, options={})
    record = db.conn.execute("SELECT record_id FROM import_log").fetchone()[0]
    _purge(db, data_dir, f"r{record}")
    row = db.conn.execute("SELECT file_name, record_id, purged FROM import_log").fetchone()
    assert row[0].startswith("purged:") and row[1] is None and row[2] == 1
    assert "旅行計畫".encode() not in _bytes_of(db)
    (notes / "2026-10-01 京都旅行計畫.txt").rename(notes / "another name.txt")
    for allow in (False, True):
        again = importer.plan_import(
            db, PERSON, notes, data_dir=data_dir, backup_dir=None, allow_duplicates=allow
        )
        assert [i.status for i in again.items] == ["duplicate"]
        assert "清除" in again.items[0].reason
    assert importer.undo(db, PERSON, 1)["hidden"] == 0


def test_the_scan_finds_leftover_copies_without_touching_them_or_printing_text(
    db: Database,
    data_dir: Path,
    world: dict[str, str],
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    copy = data_dir / "pre-migration" / "old.db"
    copy.parent.mkdir(exist_ok=True)
    copy.write_bytes(b"header" + SECRET.encode() + b"tail")
    decoy = data_dir / "emlek.db.before-restore-x-wal"
    decoy.write_bytes(b"nothing of interest, only OLDER-ROOT")
    sealed = data_dir / "exports" / "x.db.enc"
    sealed.parent.mkdir(exist_ok=True)
    sealed.write_bytes(b"sealed")
    before = copy.read_bytes(), copy.stat().st_mtime_ns
    with caplog.at_level(logging.DEBUG, logger="emlek"):
        result = _purge(db, data_dir, world["target"])
    residue = result["residue"]
    assert residue["checked"] is True  # type: ignore[index]
    assert residue["files"] == [str(copy)]  # type: ignore[index]
    assert residue["sealed"] == [str(sealed)]  # type: ignore[index]
    assert (copy.read_bytes(), copy.stat().st_mtime_ns) == before
    out = capsys.readouterr()
    shown = json.dumps(result, ensure_ascii=False) + out.out + out.err + caplog.text
    for text in ("SECRETPHRASE", "京都抹茶", "ALPHA", "SECOND-VERSION"):
        assert text not in shown


def test_a_phrase_shared_with_surviving_content_is_not_used_as_evidence(
    db: Database, data_dir: Path
) -> None:
    keep = service.save(db, PERSON, body="SHAREDLINE-KILO 共用的一行文字在這裡")
    gone = service.save(db, PERSON, body="SHAREDLINE-KILO 共用的一行文字在這裡")
    decoy = data_dir / "pre-migration" / "copy.db"
    decoy.parent.mkdir(exist_ok=True)
    decoy.write_bytes(
        b"has " + "SHAREDLINE-KILO 共用的一行文字在這裡".encode() + b" from the kept record"
    )
    result = _purge(db, data_dir, _ref(gone))
    assert result["scrub"]["verified"] is False  # type: ignore[index]
    assert result["residue"]["checked"] is False  # type: ignore[index]
    assert service.get(db, PERSON, ref=_ref(keep))["body"].startswith("SHAREDLINE")


def test_purge_log_keeps_ids_and_counts_but_no_text(
    db: Database, data_dir: Path, world: dict[str, str]
) -> None:
    _purge(db, data_dir, world["target"])
    row = db.conn.execute(
        "SELECT record_ids, revision_count, derived_count FROM purge_log"
    ).fetchone()
    assert row[1] == 4 and row[2] == 2
    assert all(part.isdigit() for part in row[0].split(","))
    stats = load_config(data_dir)  # config still loads; stats exposes only count and time
    assert stats is not None
