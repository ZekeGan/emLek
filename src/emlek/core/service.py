"""Operations of the core. Each public function checks permission first."""

from __future__ import annotations

import logging
import sqlite3
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Any

from emlek.core import notice, tokens, versions
from emlek.core import sensitivity as scanner
from emlek.core import tags as tagmod
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, require
from emlek.core.refs import parse_ref
from emlek.core.timeutil import infer_precision, is_valid_event_time, utc_now_iso

MAX_BODY_BYTES = 1 << 20
MAX_SOURCE_CHARS = 500
KINDS = ("original", "ai_summary", "inference")
CLEARABLE = ("event_time", "source")

_log = logging.getLogger("emlek")


def normalize_for_search(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


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


def _insert_record(conn: sqlite3.Connection, now: str, level: str = "none") -> int:
    cursor = conn.execute(
        "INSERT INTO records (created_at, sensitivity) VALUES (?, ?)", (now, level)
    )
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


class _Gate:
    """What a sensitive write has to pass: the level, and the token to spend (if any)."""

    def __init__(self, level: str, categories: list[str], kind: str | None, token: str | None):
        self.level = level
        self.categories = categories
        self.kind = kind
        self.token = token
        self.chash = ""

    def hint(self) -> dict[str, Any]:
        return {"level": self.level, "categories": self.categories}

    def spend(self, conn: sqlite3.Connection) -> None:
        if self.kind is None:
            return
        tokens.consume(conn, self.kind, self.token, self.chash)
        if self.kind == "notice":
            notice.acknowledge(conn)


def _sensitivity_gate(
    db: Database,
    *,
    operation: str,
    ref: str,
    body: str,
    declared: str | None,
    confirm_token: str | None,
    notice_token: str | None,
) -> _Gate:
    """Scan the text and decide whether this write needs the user's yes. Without the right token
    the write is refused and a fresh token is issued; the token is spent inside the write."""
    declared = declared or "none"
    if declared not in scanner.LEVELS:
        raise EmlekError(ErrorCode.INVALID_INPUT, "sensitivity 必須是 none、medium 或 high")
    level, categories = scanner.assess(body, declared)
    if level == "high":
        kind: str | None = "confirm"
    elif level == "medium" and notice.is_enabled(db.conn):
        kind = "notice"
    else:
        kind = None
    token = confirm_token if kind == "confirm" else notice_token
    gate = _Gate(level, categories, kind, token)
    gate.chash = tokens.content_hash(operation, ref, body)
    if kind is not None and not token:
        fresh = tokens.issue(db, kind, gate.chash)
        high = kind == "confirm"
        raise EmlekError(
            ErrorCode.NEEDS_CONFIRMATION,
            "含有最高風險資訊，須先以固定句式詢問使用者並取得「是」"
            if high
            else "含有個人資料，須先提醒使用者並取得同意",
            data={
                "state": "needs_confirmation" if high else "needs_notice",
                "confirm_token" if high else "notice_token": fresh,
                "categories": categories,
                "sensitivity": level,
                "expires_in": tokens.TTL_SECONDS,
            },
        )
    return gate


def _tag_step(
    conn: sqlite3.Connection,
    record_id: int,
    *,
    body: str,
    kind: str,
    caller: Caller,
    tags: Sequence[object] | None,
    allow_new: Sequence[str],
) -> dict[str, Any]:
    """Hashtags the user typed (original text only), then the tags the caller asked for."""
    applied: list[str] = []
    pending: list[dict[str, Any]] = []
    skipped: list[str] = []
    if kind == "original":
        for name in tagmod.parse_hashtags(body):
            try:  # a bad hashtag must never stop the text itself from being saved
                done, _ = tagmod.attach(conn, record_id, [name], actor="user", allow_new=[name])
            except EmlekError:
                skipped.append(name)
                continue
            applied.extend(done)
    if tags:
        done, pending = tagmod.attach(
            conn, record_id, tags, actor=tagmod.actor_for(caller), allow_new=allow_new
        )
        applied.extend(done)
    return {
        "tags": list(dict.fromkeys(applied)),
        "tags_pending": pending,
        **({"hashtags_skipped": skipped} if skipped else {}),
    }


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
    links: Sequence[dict[str, Any]] | None = None,
    sensitivity: str | None = None,
    confirm_token: str | None = None,
    notice_token: str | None = None,
    tags: Sequence[object] | None = None,
    allow_new: Sequence[str] = (),
) -> dict[str, Any]:
    require(caller, "save")
    _check_body(body)
    event_time, precision = _check_meta(kind, source, event_time, event_time_precision)
    gate = _sensitivity_gate(
        db,
        operation="save",
        ref="",
        body=body,
        declared=sensitivity,
        confirm_token=confirm_token,
        notice_token=notice_token,
    )
    now = utc_now_iso()
    with db.transaction() as conn:
        gate.spend(conn)
        record_id = _insert_record(conn, now, gate.level)
        revision_id = _insert_revision(
            conn, record_id, 1, body, kind, now, event_time, precision, source
        )
        added = versions.add_links(conn, revision_id, record_id, links, now)
        tag_result = _tag_step(
            conn,
            record_id,
            body=body,
            kind=kind,
            caller=caller,
            tags=tags,
            allow_new=allow_new,
        )
        _before_commit()
    _log.info("save record=%d revision=%d channel=%s", record_id, revision_id, caller.channel)
    return {
        "record_id": record_id,
        "ref": f"r{record_id}",
        "version": 1,
        "revision_ref": f"r{record_id}.v1",
        "created_at": now,
        "links_added": added,
        "sensitivity": gate.level,
        "sensitivity_hint": gate.hint(),
        **tag_result,
    }


def amend(
    db: Database,
    caller: Caller,
    *,
    ref: str,
    body: str,
    expected_version: int | None = None,
    event_time: str | None = None,
    event_time_precision: str | None = None,
    source: str | None = None,
    clear: Iterable[str] = (),
    links: Sequence[dict[str, Any]] | None = None,
    sensitivity: str | None = None,
    confirm_token: str | None = None,
    notice_token: str | None = None,
    tags: Sequence[object] | None = None,
    allow_new: Sequence[str] = (),
) -> dict[str, Any]:
    """Add the next version to an existing record. Omitted fields carry over; `clear` empties."""
    require(caller, "amend")
    record_id, _ = parse_ref(ref)
    _check_body(body)
    to_clear = set(clear)
    if to_clear - set(CLEARABLE):
        raise EmlekError(ErrorCode.INVALID_INPUT, f"clear 只能包含 {', '.join(CLEARABLE)}")
    if event_time is None and event_time_precision is not None:
        raise EmlekError(ErrorCode.INVALID_INPUT, "只改精度請同時提供事件時間")
    gate = _sensitivity_gate(
        db,
        operation="amend",
        ref=f"r{record_id}",
        body=body,
        declared=sensitivity,
        confirm_token=confirm_token,
        notice_token=notice_token,
    )
    now = utc_now_iso()
    with db.transaction() as conn:
        latest = conn.execute(
            "SELECT r.version_no, r.body, r.kind, r.event_time, r.event_time_precision,"
            " r.source, rec.hidden, rec.sensitivity FROM revisions r JOIN records rec"
            " ON rec.id = r.record_id"
            " WHERE r.record_id = ? ORDER BY r.version_no DESC LIMIT 1",
            (record_id,),
        ).fetchone()
        if latest is None:
            raise EmlekError(ErrorCode.NOT_FOUND, "找不到這筆記錄")
        version, old_body, kind, old_event, old_precision, old_source, hidden, old_level = latest
        if hidden:
            raise EmlekError(ErrorCode.CONFLICT, "這筆記錄已隱藏，請先 unhide 再修改")
        if expected_version is not None and expected_version != version:
            raise EmlekError(
                ErrorCode.CONFLICT, f"最新版本是 v{version}，不是 v{expected_version}；請先重新讀取"
            )
        if body == old_body:
            raise EmlekError(ErrorCode.INVALID_INPUT, "內容與最新版本相同，沒有需要新增的版本")
        if "event_time" in to_clear:
            event_time = event_time_precision = None
        elif event_time is None:
            event_time, event_time_precision = old_event, old_precision
        new_source = (
            None if "source" in to_clear else (source if source is not None else old_source)
        )
        event_time, precision = _check_meta(kind, new_source, event_time, event_time_precision)
        revision_id = _insert_revision(
            conn, record_id, version + 1, body, kind, now, event_time, precision, new_source
        )
        added = versions.add_links(conn, revision_id, record_id, links, now)
        tag_result = _tag_step(
            conn,
            record_id,
            body=body,
            kind=kind,
            caller=caller,
            tags=tags,
            allow_new=allow_new,
        )
        gate.spend(conn)
        record_level = scanner.higher(old_level, gate.level)
        if record_level != old_level:
            conn.execute(
                "UPDATE records SET sensitivity = ? WHERE id = ?", (record_level, record_id)
            )
    _log.info("amend record=%d version=%d channel=%s", record_id, version + 1, caller.channel)
    return {
        "record_id": record_id,
        "ref": f"r{record_id}",
        "version": version + 1,
        "revision_ref": f"r{record_id}.v{version + 1}",
        "previous_version": version,
        "created_at": now,
        "links_added": added,
        "sensitivity": record_level,
        "sensitivity_hint": gate.hint(),
        **tag_result,
    }


def get(
    db: Database,
    caller: Caller,
    *,
    ref: str,
    version: int | None = None,
    include_hidden: bool = False,
    offset: int = 0,
    max_chars: int | None = None,
    max_sensitivity: str = "high",
) -> dict[str, Any]:
    """Read one revision. `max_chars` (set by the MCP adapter) cuts long bodies; read the rest
    with `offset`."""
    require(caller, "get")
    record_id, ref_version = parse_ref(ref)
    wanted = version if version is not None else ref_version
    if wanted is not None and wanted < 1:
        raise EmlekError(ErrorCode.INVALID_INPUT, "版本必須是 1 以上的整數")
    if offset < 0:
        raise EmlekError(ErrorCode.INVALID_INPUT, "offset 不可為負數")
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
    if record[1] and not include_hidden:
        raise EmlekError(ErrorCode.NOT_FOUND, "找不到這筆記錄或版本")
    if max_sensitivity not in scanner.LEVELS:
        raise EmlekError(ErrorCode.INVALID_INPUT, "max_sensitivity 必須是 none、medium 或 high")
    if scanner.rank(record[2]) > scanner.rank(max_sensitivity):
        raise EmlekError(ErrorCode.NOT_PERMITTED, "這筆記錄的敏感度超過此入口的上限")
    _log.info(
        "get record=%d version=%d channel=%s", record_id, revision["version_no"], caller.channel
    )
    body = revision["body"]
    shown = body[offset:] if max_chars is None else body[offset : offset + max_chars]
    next_offset = offset + len(shown)
    conn = db.conn
    linked, linked_truncated = versions.linked_from(
        conn, record_id, include_hidden=include_hidden, max_sensitivity=max_sensitivity
    )
    return {
        "record_id": record_id,
        "ref": f"r{record_id}",
        "version": revision["version_no"],
        "revision_ref": f"r{record_id}.v{revision['version_no']}",
        "kind": revision["kind"],
        "body": shown,
        "body_chars": len(body),
        "truncated": next_offset < len(body),
        "next_offset": next_offset if next_offset < len(body) else None,
        "created_at": revision["created_at"],
        "record_created_at": record[0],
        "event_time": revision["event_time"],
        "event_time_precision": revision["event_time_precision"],
        "source": revision["source"],
        "hidden": bool(record[1]),
        "sensitivity": record[2],
        **versions.describe(conn, record_id, versions.statuses(conn)),
        "superseded_by": versions.superseded_by(conn, record_id, max_sensitivity=max_sensitivity),
        "linked_from": linked,
        "linked_from_truncated": linked_truncated,
        "links_out": versions.links_out(conn, revision["id"]),
        "tags": tagmod.tags_of(conn, record_id),
    }


def set_sensitivity(db: Database, caller: Caller, *, ref: str, level: str) -> dict[str, Any]:
    """Set a record's level directly (up or down). Needs the person and their PIN."""
    require(caller, "sensitivity_set")
    if level not in scanner.LEVELS:
        raise EmlekError(ErrorCode.INVALID_INPUT, "等級必須是 none、medium 或 high")
    record_id, _ = parse_ref(ref)
    with db.transaction() as conn:
        row = conn.execute("SELECT sensitivity FROM records WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise EmlekError(ErrorCode.NOT_FOUND, "找不到這筆記錄")
        conn.execute("UPDATE records SET sensitivity = ? WHERE id = ?", (level, record_id))
    _log.info("sensitivity set record=%d %s->%s", record_id, row[0], level)
    return {"ref": f"r{record_id}", "previous": row[0], "sensitivity": level}
