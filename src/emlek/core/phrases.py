"""Trigger phrases: what the user says to mean "save" or "purge". They are hints for the AI, not
a matching engine; the core never compares user text against them."""

from __future__ import annotations

import logging
import sqlite3
import unicodedata
from typing import Any

from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, require
from emlek.core.timeutil import utc_now_iso

KINDS = ("save", "purge", "exclude")
MAX_CHARS = 100
_log = logging.getLogger("emlek")


def _key(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _check_text(text: str) -> str:
    cleaned = text.strip() if isinstance(text, str) else ""
    if not 1 <= len(cleaned) <= MAX_CHARS or any(ord(c) < 32 or ord(c) == 127 for c in cleaned):
        raise EmlekError(ErrorCode.INVALID_INPUT, f"語句長度須為 1–{MAX_CHARS} 字元且不含控制字元")
    return cleaned


def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise EmlekError(ErrorCode.INVALID_INPUT, f"種類必須是 {', '.join(KINDS)} 其中之一")


def _row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "kind": row[1],
        "text": row[2],
        "enabled": bool(row[3]),
        "created_at": row[4],
        "updated_at": row[5],
    }


_COLUMNS = "id, kind, text, enabled, created_at, updated_at"


def list_phrases(
    db: Database, caller: Caller, *, kind: str | None = None, enabled_only: bool = False
) -> dict[str, Any]:
    require(caller, "phrases_list" if enabled_only else "phrase_list")
    if kind is not None:
        _check_kind(kind)
    rows = db.conn.execute(
        f"SELECT {_COLUMNS} FROM phrases WHERE (? IS NULL OR kind = ?) AND (? = 0 OR enabled = 1)"
        " ORDER BY kind, id",
        (kind, kind, 1 if enabled_only else 0),
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {k: [] for k in KINDS}
    for row in rows:
        grouped[row[1]].append(_row(row))
    purge_on = db.conn.execute(
        "SELECT 1 FROM phrases WHERE kind = 'purge' AND enabled = 1 LIMIT 1"
    ).fetchone()
    return {"phrases": grouped, "purge_enabled": purge_on is not None}


def add(db: Database, caller: Caller, *, kind: str, text: str) -> dict[str, Any]:
    require(caller, "phrase_add")
    _check_kind(kind)
    cleaned = _check_text(text)
    now = utc_now_iso()
    try:
        with db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO phrases (kind, text, text_key, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (kind, cleaned, _key(cleaned), now, now),
            )
    except sqlite3.IntegrityError as exc:
        raise EmlekError(ErrorCode.CONFLICT, "這個種類已有相同的語句") from exc
    _log.info("phrase added kind=%s", kind)
    return {"id": cursor.lastrowid, "kind": kind}


def update(
    db: Database,
    caller: Caller,
    *,
    phrase_id: int,
    text: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    require(caller, "phrase_set")
    if text is None and enabled is None:
        raise EmlekError(ErrorCode.INVALID_INPUT, "請給新的語句或 --enable／--disable")
    now = utc_now_iso()
    try:
        with db.transaction() as conn:
            row = conn.execute("SELECT kind FROM phrases WHERE id = ?", (phrase_id,)).fetchone()
            if row is None:
                raise EmlekError(ErrorCode.NOT_FOUND, "找不到這個語句")
            if text is not None:
                cleaned = _check_text(text)
                conn.execute(
                    "UPDATE phrases SET text = ?, text_key = ?, updated_at = ? WHERE id = ?",
                    (cleaned, _key(cleaned), now, phrase_id),
                )
            if enabled is not None:
                conn.execute(
                    "UPDATE phrases SET enabled = ?, updated_at = ? WHERE id = ?",
                    (1 if enabled else 0, now, phrase_id),
                )
    except sqlite3.IntegrityError as exc:
        raise EmlekError(ErrorCode.CONFLICT, "這個種類已有相同的語句") from exc
    _log.info("phrase updated kind=%s", row[0])
    return {"id": phrase_id, "kind": row[0]}


def remove(db: Database, caller: Caller, *, phrase_id: int) -> dict[str, Any]:
    require(caller, "phrase_remove")
    with db.transaction() as conn:
        row = conn.execute("SELECT kind FROM phrases WHERE id = ?", (phrase_id,)).fetchone()
        if row is None:
            raise EmlekError(ErrorCode.NOT_FOUND, "找不到這個語句")
        conn.execute("DELETE FROM phrases WHERE id = ?", (phrase_id,))
    _log.info("phrase removed kind=%s", row[0])
    return {"id": phrase_id, "kind": row[0]}
