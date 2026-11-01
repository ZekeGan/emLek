"""Operations of the core. Each public function checks permission first."""

from __future__ import annotations

import logging
import re
import sqlite3
import unicodedata
from typing import Any

from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, require
from emlek.core.timeutil import infer_precision, is_valid_event_time, utc_now_iso

MAX_BODY_BYTES = 1 << 20
MAX_SOURCE_CHARS = 500
KINDS = ("original", "ai_summary", "inference")
_REF = re.compile(r"^r?(\d+)(?:\.v(\d+))?$")

_log = logging.getLogger("emlek")


def normalize_for_search(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def parse_ref(ref: str) -> tuple[int, int | None]:
    match = _REF.match(ref.strip())
    if match is None:
        raise EmlekError(ErrorCode.INVALID_INPUT, "記錄編號格式應為 r12 或 r12.v3")
    record_id, version = match.groups()
    return int(record_id), int(version) if version else None


def _check_body(body: str) -> None:
    if not isinstance(body, str) or not body.strip():
        raise EmlekError(ErrorCode.INVALID_INPUT, "內容不可為空")
    if "\x00" in body:
        raise EmlekError(ErrorCode.INVALID_INPUT, "內容不可含 NUL 字元")
    try:
        encoded = body.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise EmlekError(ErrorCode.INVALID_INPUT, "內容含無法以 UTF-8 儲存的字元") from exc
    if len(encoded) > MAX_BODY_BYTES:
        raise EmlekError(ErrorCode.INVALID_INPUT, "單版內容不可超過 1 MiB")


def _check_meta(
    kind: str, source: str | None, event_time: str | None, precision: str | None
) -> tuple[str | None, str | None]:
    if kind not in KINDS:
        raise EmlekError(ErrorCode.INVALID_INPUT, f"kind 必須是 {', '.join(KINDS)} 其中之一")
    if source is not None and len(source) > MAX_SOURCE_CHARS:
        raise EmlekError(ErrorCode.INVALID_INPUT, "來源不可超過 500 字元")
    if event_time is None:
        if precision is not None:
            raise EmlekError(ErrorCode.INVALID_INPUT, "指定精度時必須同時提供事件時間")
        return None, None
    resolved = precision or infer_precision(event_time)
    if resolved is None or not is_valid_event_time(event_time, resolved):
        raise EmlekError(ErrorCode.INVALID_INPUT, "事件時間格式不正確")
    return event_time, resolved


def _insert_record(conn: sqlite3.Connection, now: str) -> int:
    cursor = conn.execute("INSERT INTO records (created_at) VALUES (?)", (now,))
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _insert_revision(
    conn: sqlite3.Connection,
    record_id: int,
    version_no: int,
    body: str,
    kind: str,
    now: str,
    event_time: str | None,
    precision: str | None,
    source: str | None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO revisions (record_id, version_no, body, body_norm, kind, created_at,"
        " event_time, event_time_precision, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            record_id,
            version_no,
            body,
            normalize_for_search(body),
            kind,
            now,
            event_time,
            precision,
            source,
        ),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _before_commit() -> None:
    """Hook that tests replace to inject a failure after all writes, before COMMIT."""


def save(
    db: Database,
    caller: Caller,
    *,
    body: str,
    kind: str = "original",
    source: str | None = None,
    event_time: str | None = None,
    event_time_precision: str | None = None,
) -> dict[str, Any]:
    require(caller, "save")
    _check_body(body)
    event_time, precision = _check_meta(kind, source, event_time, event_time_precision)
    now = utc_now_iso()
    with db.transaction() as conn:
        record_id = _insert_record(conn, now)
        revision_id = _insert_revision(
            conn, record_id, 1, body, kind, now, event_time, precision, source
        )
        _before_commit()
    _log.info("save record=%d revision=%d channel=%s", record_id, revision_id, caller.channel)
    return {
        "record_id": record_id,
        "ref": f"r{record_id}",
        "version": 1,
        "revision_ref": f"r{record_id}.v1",
        "created_at": now,
    }


def get(db: Database, caller: Caller, *, ref: str, version: int | None = None) -> dict[str, Any]:
    require(caller, "get")
    record_id, ref_version = parse_ref(ref)
    wanted = version if version is not None else ref_version
    if wanted is not None and wanted < 1:
        raise EmlekError(ErrorCode.INVALID_INPUT, "版本必須是 1 以上的整數")
    if wanted is None:
        row = db.conn.execute(
            "SELECT * FROM revisions WHERE record_id = ? ORDER BY version_no DESC LIMIT 1",
            (record_id,),
        ).fetchone()
    else:
        row = db.conn.execute(
            "SELECT * FROM revisions WHERE record_id = ? AND version_no = ?",
            (record_id, wanted),
        ).fetchone()
    if row is None:
        raise EmlekError(ErrorCode.NOT_FOUND, "找不到這筆記錄或版本")
    columns = [d[0] for d in db.conn.execute("SELECT * FROM revisions LIMIT 0").description]
    revision = dict(zip(columns, row, strict=True))
    record = db.conn.execute(
        "SELECT created_at, hidden, sensitivity FROM records WHERE id = ?", (record_id,)
    ).fetchone()
    _log.info(
        "get record=%d version=%d channel=%s", record_id, revision["version_no"], caller.channel
    )
    return {
        "record_id": record_id,
        "ref": f"r{record_id}",
        "version": revision["version_no"],
        "revision_ref": f"r{record_id}.v{revision['version_no']}",
        "kind": revision["kind"],
        "body": revision["body"],
        "created_at": revision["created_at"],
        "record_created_at": record[0],
        "event_time": revision["event_time"],
        "event_time_precision": revision["event_time_precision"],
        "source": revision["source"],
        "hidden": bool(record[1]),
        "sensitivity": record[2],
    }
