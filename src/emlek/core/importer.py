"""Import plain-text notes (.txt, .md): one record per file, previewed first, written in one go.

Imported text is outside material: it never creates tags (hashtags stay plain text), a file with
top-secret content is left out unless a person at a terminal says otherwise, and the whole batch
is one transaction so a failure leaves nothing behind.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from emlek.core import sensitivity as scanner
from emlek.core import service
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, require
from emlek.core.timeutil import utc_now_iso

MAX_FILES = 20_000
MAX_FILE_BYTES = 1 << 20
MAX_TOTAL_BYTES = 512 << 20
MAX_SOURCE_NAME = 300
EXTENSIONS = (".txt", ".md")
_REPARSE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: symlinks, junctions, cloud placeholders
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

_DATE_FORMS = (
    re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(\d{4})年(\d{1,2})月(\d{1,2})日"),
)

IMPORTABLE = ("import", "changed")


@dataclass
class Item:
    file_name: str
    status: str  # import | changed | already | already_hidden | duplicate | high | failed
    reason: str = ""
    event_time: str | None = None
    level: str = "none"
    categories: list[str] = field(default_factory=list)
    content_hash: str = ""
    body: str = ""
    dated: str = "none"  # none | filename | ambiguous

    def public(self) -> dict[str, Any]:
        return {
            "file": self.file_name,
            "status": self.status,
            **({"reason": self.reason} if self.reason else {}),
            **({"event_time": self.event_time} if self.event_time else {}),
            **({"sensitivity": self.level} if self.level != "none" else {}),
            **({"categories": self.categories} if self.categories else {}),
            **({"date": self.dated} if self.dated == "ambiguous" else {}),
        }


@dataclass
class Plan:
    root: str
    items: list[Item]
    skipped_other: int = 0
    skipped_own: list[str] = field(default_factory=list)
    skipped_links: int = 0

    def count(self, *statuses: str) -> int:
        return sum(1 for i in self.items if i.status in statuses)

    def summary(self) -> dict[str, Any]:
        return {
            "to_import": self.count("import"),
            "changed_since_last_import": self.count("changed"),
            "already_imported": self.count("already"),
            "already_imported_but_hidden": self.count("already_hidden"),
            "duplicates": self.count("duplicate"),
            "high_left_out": self.count("high"),
            "failed": self.count("failed"),
            "medium": sum(1 for i in self.items if i.status in IMPORTABLE and i.level == "medium"),
            "undated": sum(1 for i in self.items if i.status in IMPORTABLE and not i.event_time),
            "ambiguous_dates": sum(1 for i in self.items if i.dated == "ambiguous"),
            "skipped_other_files": self.skipped_other,
            "skipped_links": self.skipped_links,
            "skipped_own_folders": self.skipped_own,
        }


def _is_link(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
        return bool(attributes & _REPARSE)
    except OSError:
        return True  # cannot tell: leave it alone


def date_from_name(name: str) -> tuple[str | None, str]:
    """A calendar date written in the file name: ("2026-10-01", "filename"), (None, "ambiguous")
    when two different dates appear, (None, "none") when there is none. Digits next to digits,
    years outside 1900-2100 and dates that do not exist are not dates."""
    text = unicodedata.normalize("NFKC", name)
    found: set[str] = set()
    for form in _DATE_FORMS:
        for year, month, day in form.findall(text):
            try:
                valid = date(int(year), int(month), int(day))
            except ValueError:
                continue
            if 1900 <= valid.year <= 2100:
                found.add(valid.isoformat())
    if len(found) == 1:
        return next(iter(found)), "filename"
    if len(found) > 1:
        return None, "ambiguous"
    return None, "none"


def _source_name(file_name: str) -> str:
    cleaned = _CONTROL.sub("", file_name)
    if len(cleaned) > MAX_SOURCE_NAME:
        cleaned = cleaned[: MAX_SOURCE_NAME - 1] + "…"
    return f"import:{cleaned}"


def _walk(root: Path, skip: list[Path]) -> tuple[list[Path], int, list[str], int]:
    """Files to read (sorted), count of other files, own folders left out, links left out."""
    if root.is_file():
        return (
            ([root] if root.suffix.lower() in EXTENSIONS else []),
            (0 if root.suffix.lower() in EXTENSIONS else 1),
            [],
            0,
        )
    files: list[Path] = []
    other = links = 0
    own: list[str] = []
    for current, dirs, names in os.walk(root, followlinks=False):
        here = Path(current)
        kept: list[str] = []
        for name in sorted(dirs):
            path = here / name
            if _is_link(path):
                links += 1
            elif (
                any(path.resolve() == s or s in path.resolve().parents for s in skip)
                or (path / "export.jsonl").exists()
            ):
                own.append(name)
            else:
                kept.append(name)
        dirs[:] = kept
        for name in sorted(names):
            path = here / name
            if _is_link(path):
                links += 1
            elif path.suffix.lower() in EXTENSIONS:
                files.append(path)
            else:
                other += 1
    return files, other, own, links


def plan_import(
    db: Database,
    caller: Caller,
    root: Path,
    *,
    data_dir: Path,
    backup_dir: Path | None,
    include_high: bool = False,
    allow_duplicates: bool = False,
) -> Plan:
    """Read every candidate file once and decide what would happen to it. Writes nothing."""
    require(caller, "import_preview")
    if not root.exists():
        raise EmlekError(ErrorCode.NOT_FOUND, "找不到要匯入的檔案或資料夾")
    skip = [data_dir.resolve()] + ([backup_dir.resolve()] if backup_dir else [])
    if any(root.resolve() == s or s in root.resolve().parents for s in skip):
        raise EmlekError(ErrorCode.INVALID_INPUT, "不能匯入 emLek 自己的資料夾或備份資料夾")
    files, other, own, links = _walk(root, skip)
    if len(files) > MAX_FILES:
        raise EmlekError(ErrorCode.INVALID_INPUT, f"檔案超過 {MAX_FILES} 個，請分批匯入")
    base = root if root.is_dir() else root.parent
    plan = Plan(root=root.name, items=[], skipped_other=other, skipped_own=own, skipped_links=links)
    seen: dict[str, str] = {}
    total = 0
    for path in files:
        name = unicodedata.normalize("NFC", path.relative_to(base).as_posix())
        item = _read_one(path, name)
        plan.items.append(item)
        if item.status != "import":
            continue
        total += len(item.body.encode("utf-8"))
        if total > MAX_TOTAL_BYTES:
            raise EmlekError(ErrorCode.INVALID_INPUT, "一次匯入的內容超過 512 MiB，請分批匯入")
        _classify(db, item, seen, include_high=include_high, allow_duplicates=allow_duplicates)
    return plan


def _read_one(path: Path, name: str) -> Item:
    item = Item(file_name=name, status="import")
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        item.status, item.reason = "failed", f"讀取失敗（{type(exc).__name__}）"
        return item
    if len(raw) > MAX_FILE_BYTES:
        item.status, item.reason = "failed", "檔案超過 1 MiB"
        return item
    try:
        body = raw.decode("utf-8-sig")  # strict: a bad byte is a failure, never a replacement
    except UnicodeDecodeError:
        item.status, item.reason = "failed", "不是有效的 UTF-8（本版只收 UTF-8）"
        return item
    try:
        service._check_body(body)
    except EmlekError as exc:
        item.status, item.reason = "failed", exc.message
        return item
    item.body = body
    item.content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    item.event_time, item.dated = date_from_name(Path(name).stem)
    item.level, item.categories = scanner.assess(body)
    return item


def _classify(
    db: Database,
    item: Item,
    seen: dict[str, str],
    *,
    include_high: bool,
    allow_duplicates: bool,
) -> None:
    conn = db.conn
    same = conn.execute(
        "SELECT l.record_id, rec.hidden FROM import_log l"
        " LEFT JOIN records rec ON rec.id = l.record_id"
        " WHERE l.file_name = ? AND l.content_hash = ?",
        (item.file_name, item.content_hash),
    ).fetchone()
    if same is not None:
        if same[1]:
            item.status, item.reason = "already_hidden", "已匯入過但被隱藏，要恢復請用 unhide"
        else:
            item.status = "already"
        return
    if conn.execute(
        "SELECT 1 FROM import_log WHERE purged = 1 AND content_hash = ? LIMIT 1",
        (item.content_hash,),
    ).fetchone():  # purged on purpose: never brought back, whatever the file is called
        item.status = "duplicate"
        item.reason = "這個內容曾被徹底清除，不會再匯入"
        return
    elsewhere = conn.execute(
        "SELECT file_name FROM import_log WHERE content_hash = ? LIMIT 1", (item.content_hash,)
    ).fetchone()
    twin = seen.get(item.content_hash)
    if (elsewhere is not None or twin is not None) and not allow_duplicates:
        item.status = "duplicate"
        item.reason = "內容與已匯入的另一個檔案相同（加 --allow-duplicates 才會匯入）"
        return
    if item.level == "high":
        item.status = "high"
        item.reason = "含密碼、金鑰等最高風險內容，不予匯入"
        return
    seen.setdefault(item.content_hash, item.file_name)
    changed = conn.execute(
        "SELECT 1 FROM import_log WHERE file_name = ? LIMIT 1", (item.file_name,)
    ).fetchone()
    if changed is not None:
        item.status, item.reason = "changed", "檔案自上次匯入後已變更，將另存為新記錄"


def apply_import(
    db: Database,
    caller: Caller,
    plan: Plan,
    *,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Write every importable item of an already-read plan in one transaction."""
    require(caller, "import_apply")
    todo = [i for i in plan.items if i.status in IMPORTABLE]
    if any(scanner.assess(i.body, i.level)[0] == "high" for i in todo):
        raise EmlekError(ErrorCode.NOT_PERMITTED, "密碼、金鑰等最高風險內容不予匯入")
    now = utc_now_iso()
    refs: list[str] = []
    with db.transaction() as conn:
        batch = conn.execute(
            "INSERT INTO import_batches (created_at, file_count, options_json) VALUES (?, ?, ?)",
            (now, len(todo), json.dumps(options, ensure_ascii=False, sort_keys=True)),
        ).lastrowid
        for item in todo:
            event_time, precision = service._check_meta(
                "original", _source_name(item.file_name), item.event_time, None
            )
            record_id = service._insert_record(conn, now, item.level)
            service._insert_revision(
                conn,
                record_id,
                1,
                item.body,
                "original",
                now,
                event_time,
                precision,
                _source_name(item.file_name),
            )
            conn.execute(
                "INSERT INTO import_log (batch_id, file_name, content_hash, record_id, imported_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (batch, item.file_name, item.content_hash, record_id, now),
            )
            refs.append(f"r{record_id}")
    db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return {"batch": batch, "imported": len(refs), "first_ref": refs[0] if refs else None}


def list_batches(db: Database, caller: Caller) -> list[dict[str, Any]]:
    require(caller, "import_list")
    rows = db.conn.execute(
        "SELECT b.id, b.created_at, b.file_count, b.undone_at,"
        " (SELECT count(*) FROM import_log l JOIN records r ON r.id = l.record_id"
        "  WHERE l.batch_id = b.id AND r.hidden = 0) FROM import_batches b ORDER BY b.id"
    ).fetchall()
    return [
        {"batch": r[0], "created_at": r[1], "files": r[2], "undone_at": r[3], "visible": r[4]}
        for r in rows
    ]


def undo_preview(db: Database, caller: Caller, batch: int) -> dict[str, Any]:
    require(caller, "import_list")
    row = db.conn.execute("SELECT undone_at FROM import_batches WHERE id = ?", (batch,)).fetchone()
    if row is None:
        raise EmlekError(ErrorCode.NOT_FOUND, "找不到這個批次")
    counts = db.conn.execute(
        "SELECT count(*), sum(rec.hidden = 0),"
        " sum((SELECT count(*) FROM revisions v WHERE v.record_id = rec.id) > 1)"
        " FROM import_log l JOIN records rec ON rec.id = l.record_id WHERE l.batch_id = ?",
        (batch,),
    ).fetchone()
    return {
        "batch": batch,
        "records": counts[0] or 0,
        "visible": counts[1] or 0,
        "amended_since_import": counts[2] or 0,
        "already_undone": row[0] is not None,
    }


def undo(db: Database, caller: Caller, batch: int) -> dict[str, Any]:
    """Hide every record of the batch in one statement (purging is a later milestone)."""
    require(caller, "import_undo")
    info = undo_preview(db, Caller(caller.channel), batch)  # existence and counts
    now = utc_now_iso()
    with db.transaction() as conn:
        conn.execute(
            "UPDATE records SET hidden = 1, hidden_at = ? WHERE hidden = 0 AND id IN"
            " (SELECT record_id FROM import_log WHERE batch_id = ? AND record_id IS NOT NULL)",
            (now, batch),
        )
        conn.execute(
            "UPDATE import_batches SET undone_at = ? WHERE id = ? AND undone_at IS NULL",
            (now, batch),
        )
    return {**info, "hidden": info["visible"]}
