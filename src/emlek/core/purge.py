"""Permanent purge (M9): remove a record, everything that only exists because of it, and then
scrub the database files so the text is physically gone.

The logical delete is one transaction. The physical scrub (checkpoint, VACUUM, a raw byte scan)
comes after it and is repeatable: a purge whose scrub did not finish stays 'pending' in
`purge_log` until `finish` completes it. Text and fragments live in memory only; nothing here
prints or logs record content.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel, require, sees_hidden
from emlek.core.refs import parse_ref
from emlek.core.timeutil import utc_now_iso

_log = logging.getLogger("emlek")

MAX_REFS = 20
MIN_FRAGMENT = 8
MIN_TAG_FRAGMENT = 2
MAX_FRAGMENTS = 60
EXCERPT_CHARS = 40
_CHUNK = 4 * 1024 * 1024
_SIDECARS = ("-wal", "-shm")

LIMITS = (
    "清除只是從 emLek 的資料庫檔案移除。它到不了的地方：SSD 與檔案系統的殘留、Windows 還原點與"
    "陰影複本、防毒隔離區、本機 AI 的對話記錄（例如 Claude Code、Codex）、PowerShell 歷史、"
    "終端機捲動緩衝、既有的備份與匯出，以及已經傳給第三方 AI 的內容。"
)


@dataclass
class Plan:
    requested: list[int]
    derived: list[int]
    kept: list[int]
    revisions: list[int]
    links: list[int]
    tags: list[tuple[int, str]]
    orphaned_other: list[str]
    fingerprint: str

    @property
    def records(self) -> list[int]:
        return sorted({*self.requested, *self.derived})


def _ids(values: Any) -> str:
    return ",".join(str(int(v)) for v in values) or "NULL"


def parse_refs(refs: list[str]) -> list[int]:
    if not refs:
        raise EmlekError(ErrorCode.INVALID_INPUT, "請指定要清除的記錄，例如 r12")
    ids: list[int] = []
    for ref in refs:
        record_id, version = parse_ref(ref)
        if version is not None:
            raise EmlekError(
                ErrorCode.INVALID_INPUT, "清除以整筆記錄為單位，請用 r12 而不是 r12.v3"
            )
        if record_id not in ids:
            ids.append(record_id)
    if len(ids) > MAX_REFS:
        raise EmlekError(ErrorCode.INVALID_INPUT, f"一次最多清除 {MAX_REFS} 筆記錄")
    return ids


def purge_enabled(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM phrases WHERE kind = 'purge' AND enabled = 1 LIMIT 1"
        ).fetchone()
        is not None
    )


def build_plan(conn: sqlite3.Connection, ids: list[int]) -> Plan:
    missing = [
        i
        for i in ids
        if conn.execute("SELECT 1 FROM records WHERE id = ?", (i,)).fetchone() is None
    ]
    if missing:
        raise EmlekError(ErrorCode.NOT_FOUND, "找不到記錄：" + "、".join(f"r{i}" for i in missing))
    everything = set(ids)
    derived: set[int] = set()
    frontier = set(ids)
    while frontier:  # AI summaries and inferences that link to a purged version, by any relation
        revs = _revisions(conn, frontier)
        found = {
            int(row[0])
            for row in conn.execute(
                "SELECT DISTINCT rev.record_id FROM links l"
                " JOIN revisions rev ON rev.id = l.revision_id"
                f" WHERE l.derived_from_revision_id IN ({_ids(revs)})"
                " AND rev.kind IN ('ai_summary', 'inference')"
            )
        }
        frontier = found - everything
        derived |= frontier
        everything |= frontier
    revs = _revisions(conn, everything)
    kept = sorted(
        int(row[0])
        for row in conn.execute(
            "SELECT DISTINCT rev.record_id FROM links l"
            " JOIN revisions rev ON rev.id = l.revision_id"
            f" WHERE l.derived_from_revision_id IN ({_ids(revs)})"
            f" AND rev.record_id NOT IN ({_ids(everything)})"
        )
    )
    links = sorted(
        int(row[0])
        for row in conn.execute(
            f"SELECT id FROM links WHERE revision_id IN ({_ids(revs)})"
            f" OR derived_from_revision_id IN ({_ids(revs)})"
        )
    )
    removable: list[tuple[int, str]] = []
    orphaned: list[str] = []
    for tag_id, name, made_by in conn.execute(
        "SELECT DISTINCT t.id, t.name, t.created_by FROM record_tags rt"
        f" JOIN tags t ON t.id = rt.tag_id WHERE rt.record_id IN ({_ids(everything)})"
    ).fetchall():
        outside = conn.execute(
            "SELECT 1 FROM record_tags WHERE tag_id = ?"
            f" AND record_id NOT IN ({_ids(everything)}) LIMIT 1",
            (tag_id,),
        ).fetchone()
        if outside is not None:
            continue
        created_here = conn.execute(
            "SELECT 1 FROM tag_events WHERE action = 'tag_create' AND detail = ?"
            f" AND record_id IN ({_ids(everything)}) LIMIT 1",
            (name,),
        ).fetchone()
        if created_here is not None and made_by != "system":
            removable.append((int(tag_id), str(name)))
        else:
            orphaned.append(str(name))
    # Tags created by this record but never attached to anything are removed too.
    for tag_id, name in conn.execute(
        "SELECT t.id, t.name FROM tag_events e JOIN tags t ON t.name = e.detail"
        f" WHERE e.action = 'tag_create' AND e.record_id IN ({_ids(everything)})"
        " AND t.created_by <> 'system'"
        " AND NOT EXISTS (SELECT 1 FROM record_tags rt WHERE rt.tag_id = t.id)"
    ).fetchall():
        if (int(tag_id), str(name)) not in removable:
            removable.append((int(tag_id), str(name)))
    removable.sort()
    material = json.dumps(
        [sorted(everything), revs, links, [t[0] for t in removable], kept], separators=(",", ":")
    )
    return Plan(
        requested=sorted(ids),
        derived=sorted(derived),
        kept=kept,
        revisions=revs,
        links=links,
        tags=removable,
        orphaned_other=sorted(orphaned),
        fingerprint=hashlib.sha256(material.encode()).hexdigest(),
    )


def _revisions(conn: sqlite3.Connection, records: Any) -> list[int]:
    return sorted(
        int(r[0])
        for r in conn.execute(f"SELECT id FROM revisions WHERE record_id IN ({_ids(records)})")
    )


def preview(
    db: Database, caller: Caller, refs: list[str], *, with_text: bool = False
) -> dict[str, Any]:
    """What a purge would remove. The text of a record is shown only to the command line: the
    MCP preview is metadata, so asking for a preview never sends the content to an AI."""
    require(caller, "purge_preview")
    text = with_text and caller.channel is Channel.CLI
    conn = db.conn
    asked = parse_refs(refs)
    if not sees_hidden(caller):  # D103: to an AI a hidden note is gone, worded like a missing one
        gone = [
            i
            for i in asked
            if (row := conn.execute("SELECT hidden FROM records WHERE id = ?", (i,)).fetchone())
            is None
            or row[0]
        ]
        if gone:
            raise EmlekError(ErrorCode.NOT_FOUND, "找不到記錄：" + "、".join(f"r{i}" for i in gone))
    plan = build_plan(conn, asked)
    items = []
    for record_id in plan.records:
        created, hidden = conn.execute(
            "SELECT created_at, hidden FROM records WHERE id = ?", (record_id,)
        ).fetchone()
        if hidden and not sees_hidden(caller):
            continue
        versions, kind = conn.execute(
            "SELECT count(*), max(kind) FROM revisions WHERE record_id = ?", (record_id,)
        ).fetchone()
        item: dict[str, Any] = {
            "ref": f"r{record_id}",
            "versions": versions,
            "kind": kind,
            "created_at": created,
            "hidden": bool(hidden),
            "derived": record_id in plan.derived,
        }
        if text:
            body = conn.execute(
                "SELECT body FROM revisions WHERE record_id = ? ORDER BY version_no DESC LIMIT 1",
                (record_id,),
            ).fetchone()[0]
            item["excerpt"] = body[:EXCERPT_CHARS].replace("\n", " ")
        items.append(item)
    if not sees_hidden(caller):
        # The plan may include hidden derivatives; an AI gets only what it can already see, so
        # whole-plan counts (links, tags) stay in the terminal preview (D103).
        return {
            "records": items,
            "revisions": sum(int(item["versions"]) for item in items),
            "kept_originals_that_may_mention_this": [
                f"r{i}"
                for i in plan.kept
                if not conn.execute("SELECT hidden FROM records WHERE id = ?", (i,)).fetchone()[0]
            ],
            "purge_enabled": purge_enabled(conn),
        }
    result: dict[str, Any] = {
        "records": items,
        "revisions": len(plan.revisions),
        "links": len(plan.links),
        "tags_removed": len(plan.tags),
        "tags_unused_afterwards": len(plan.orphaned_other),
        "kept_originals_that_may_mention_this": [f"r{i}" for i in plan.kept],
        "purge_enabled": purge_enabled(conn),
    }
    if text:
        result["tag_names"] = [name for _, name in plan.tags]
        result["unused_tag_names"] = plan.orphaned_other
        result["fingerprint"] = plan.fingerprint
    return result


# --- the purge itself ------------------------------------------------------------------------


def _candidates(text: str) -> list[str]:
    found: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if len(line) < MIN_FRAGMENT or any(c in line for c in '"\\\r\t'):
            continue
        width = min(len(line), 16)
        middle = max(0, len(line) // 2 - width // 2)
        for piece in (line[:width], line[middle : middle + width], line[-width:]):
            if len(piece) >= MIN_FRAGMENT and piece not in found:
                found.append(piece)
    return found


def _fragments(conn: sqlite3.Connection, texts: list[str], tag_names: list[str]) -> list[bytes]:
    """Distinct pieces of the purged text to look for afterwards. A piece that still occurs in
    surviving content is useless as evidence and is dropped."""
    wanted: list[str] = []
    for text in texts:
        for piece in _candidates(text):
            if piece not in wanted:
                wanted.append(piece)
    for name in tag_names:
        if len(name) >= MIN_TAG_FRAGMENT and name not in wanted:
            wanted.append(name)
    chosen: list[bytes] = []
    for piece in wanted:
        survives = conn.execute(
            "SELECT 1 FROM revisions WHERE instr(body, ?) > 0 OR instr(body_norm, ?) > 0 LIMIT 1",
            (piece, piece),
        ).fetchone()
        if survives is None:
            survives = conn.execute(
                "SELECT 1 FROM tags WHERE instr(name, ?) > 0 OR instr(description, ?) > 0 LIMIT 1",
                (piece, piece),
            ).fetchone()
        if survives is None:
            chosen.append(piece.encode("utf-8"))
        if len(chosen) >= MAX_FRAGMENTS:
            break
    return chosen


def _optimize(conn: sqlite3.Connection, table: str) -> None:
    try:
        conn.execute(f"INSERT INTO {table} ({table}, rank) VALUES ('integrity-check', 1)")
    except sqlite3.DatabaseError:
        conn.execute(f"INSERT INTO {table} ({table}) VALUES ('rebuild')")
        return
    conn.execute(f"INSERT INTO {table} ({table}) VALUES ('optimize')")


def purge(
    db: Database,
    caller: Caller,
    refs: list[str],
    *,
    fingerprint: str,
    data_dir: Path,
    backup_dir: Path | None,
) -> dict[str, Any]:
    require(caller, "purge")
    ids = parse_refs(refs)
    conn = db.conn
    if not purge_enabled(conn):
        raise EmlekError(ErrorCode.NOT_PERMITTED, "徹底清除目前是關閉的（沒有啟用中的 purge 語句）")
    conn.execute("PRAGMA secure_delete = ON")
    conn.execute("PRAGMA temp_store = MEMORY")
    now = utc_now_iso()
    with db.transaction():
        plan = build_plan(conn, ids)
        if plan.fingerprint != fingerprint:
            raise EmlekError(ErrorCode.CONFLICT, "預覽之後內容有變動，沒有刪除任何東西，請重新執行")
        everything = plan.records
        texts = [
            str(value)
            for row in conn.execute(
                f"SELECT body, body_norm FROM revisions WHERE record_id IN ({_ids(everything)})"
            )
            for value in row
        ]
        tag_ids = [t[0] for t in plan.tags]
        words = [name for _, name in plan.tags]
        words += [
            str(value)
            for row in conn.execute(
                f"SELECT alias, alias_key FROM tag_aliases WHERE tag_id IN ({_ids(tag_ids)})"
            )
            for value in row
        ]
        with db.purge_mode():
            conn.execute(f"DELETE FROM links WHERE id IN ({_ids(plan.links)})")
            conn.execute(f"DELETE FROM record_tags WHERE record_id IN ({_ids(everything)})")
            conn.execute(
                f"DELETE FROM tag_links WHERE parent_tag_id IN ({_ids(tag_ids)})"
                f" OR child_tag_id IN ({_ids(tag_ids)})"
            )
            conn.execute(f"DELETE FROM tag_aliases WHERE tag_id IN ({_ids(tag_ids)})")
            conn.execute(f"DELETE FROM tags_fts WHERE rowid IN ({_ids(tag_ids)})")
            conn.execute(f"DELETE FROM tags WHERE id IN ({_ids(tag_ids)})")
            conn.execute(f"DELETE FROM tag_events WHERE record_id IN ({_ids(everything)})")
            for word in words:
                if word:
                    conn.execute("DELETE FROM tag_events WHERE instr(detail, ?) > 0", (word,))
            conn.execute(
                "UPDATE import_log SET file_name = 'purged:' || id, record_id = NULL, purged = 1"
                f" WHERE record_id IN ({_ids(everything)})"
            )
            conn.execute("DELETE FROM confirm_tokens")
            removed_revisions = conn.execute(
                f"DELETE FROM revisions WHERE record_id IN ({_ids(everything)})"
            ).rowcount
            removed_records = conn.execute(
                f"DELETE FROM records WHERE id IN ({_ids(everything)})"
            ).rowcount
        if removed_revisions != len(plan.revisions) or removed_records != len(everything):
            raise EmlekError(ErrorCode.INTERNAL, "刪除筆數與預覽不一致，已全部復原")
        _optimize(conn, "revisions_fts")
        _optimize(conn, "tags_fts")
        floor = conn.execute("SELECT value FROM meta WHERE key = 'record_id_floor'").fetchone()
        new_floor = max(int(floor[0]) if floor else 0, max(everything))
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('record_id_floor', ?)",
            (str(new_floor),),
        )
        log_id = conn.execute(
            "INSERT INTO purge_log (at, record_ids, revision_count, derived_count, scrub_status)"
            " VALUES (?, ?, ?, ?, 'pending')",
            (
                now,
                ",".join(str(i) for i in everything),
                removed_revisions,
                len(plan.derived),
            ),
        ).lastrowid
    _log.info(
        "purge records=%d revisions=%d derived=%d",
        len(everything),
        removed_revisions,
        len(plan.derived),
    )
    fragments = _fragments(conn, texts, words)
    del texts
    scrub = _scrub(db, fragments)
    residue = residue_scan(data_dir, backup_dir, fragments)
    if scrub["finished"]:
        conn.execute(
            "UPDATE purge_log SET scrub_status = ? WHERE id = ?",
            ("done" if fragments else "unverified", log_id),
        )
    return {
        "purged": [f"r{i}" for i in everything],
        "revisions": removed_revisions,
        "derived": [f"r{i}" for i in plan.derived],
        "tags_removed": len(plan.tags),
        "kept_originals_that_may_mention_this": [f"r{i}" for i in plan.kept],
        "scrub": {**scrub, "verified": bool(fragments) and scrub["finished"]},
        "residue": residue,
        "limits": LIMITS,
    }


def _hits(paths: list[Path], needles: list[bytes]) -> list[Path]:
    if not needles:
        return []
    overlap = max(len(n) for n in needles) - 1
    found: list[Path] = []
    for path in paths:
        tail = b""
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(_CHUNK):
                    data = tail + chunk
                    if any(n in data for n in needles):
                        found.append(path)
                        break
                    tail = data[-overlap:] if overlap else b""
        except OSError:
            continue
    return found


def _database_files(db: Database) -> list[Path]:
    return [p for p in (db.path, *(Path(str(db.path) + s) for s in _SIDECARS)) if p.exists()]


def _scrub(db: Database, fragments: list[bytes]) -> dict[str, Any]:
    """Checkpoint, VACUUM, checkpoint, then look at the raw bytes. Every step's outcome is
    checked: a busy checkpoint means another process still holds the old pages."""
    conn = db.conn
    notes: list[str] = []
    busy = False
    for step in range(2):
        try:
            result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if result is not None and int(result[0]) != 0:
                busy = True
        except sqlite3.Error:
            busy = True
        if step == 0:
            try:
                conn.execute("VACUUM")
            except sqlite3.Error:
                busy = True
    if busy:
        notes.append("資料庫正被其他程式使用，實體擦除未完成")
    leaked = _hits(_database_files(db), fragments)
    if leaked:
        notes.append("資料庫檔案裡仍找得到被清除內容的片段")
    return {"finished": not busy and not leaked, "notes": notes}


def pending(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute("SELECT count(*) FROM purge_log WHERE scrub_status = 'pending'").fetchone()[0]
    )


def finish(db: Database, caller: Caller) -> dict[str, Any]:
    """Redo the physical scrub of purges that did not finish. The text is gone from memory by
    now, so this step cannot byte-scan; it reports that honestly as 'unverified'."""
    require(caller, "purge_finish")
    conn = db.conn
    waiting = pending(conn)
    if not waiting:
        return {"pending": 0, "finished": True, "notes": []}
    conn.execute("PRAGMA secure_delete = ON")
    conn.execute("PRAGMA temp_store = MEMORY")
    scrub = _scrub(db, [])
    if scrub["finished"]:
        conn.execute(
            "UPDATE purge_log SET scrub_status = 'unverified' WHERE scrub_status = 'pending'"
        )
    return {"pending": waiting, **scrub, "verified": False}


# --- leftovers outside the live database -----------------------------------------------------


def leftover_files(data_dir: Path, backup_dir: Path | None) -> tuple[list[Path], list[Path]]:
    """Plain files that may hold a copy of the data, and encrypted backups that cannot be read."""
    readable: list[Path] = []
    sealed: list[Path] = []

    def walk(folder: Path) -> None:
        if not folder.is_dir():
            return
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            (sealed if path.name.endswith(".enc") else readable).append(path)

    for name in ("pre-migration", "exports", "tmp", "logs"):
        walk(data_dir / name)
    for path in sorted(data_dir.iterdir()) if data_dir.is_dir() else []:
        if path.is_file() and path.name.startswith("emlek.db.") and path.name != "emlek.db":
            readable.append(path)
    if backup_dir is not None:
        walk(backup_dir)
    return readable, sealed


def residue_scan(data_dir: Path, backup_dir: Path | None, fragments: list[bytes]) -> dict[str, Any]:
    """Names of copies that still contain the purged text. Raw bytes only: opening these files
    with SQLite could replay or create journal files. Fragments are never printed."""
    readable, sealed = leftover_files(data_dir, backup_dir)
    if not fragments:
        return {"checked": False, "reason": "沒有足夠獨特的片段可供比對", "files": [], "sealed": []}
    return {
        "checked": True,
        "scanned": len(readable),
        "files": [str(p) for p in _hits(readable, fragments)],
        "sealed": [str(p) for p in sealed],
    }
