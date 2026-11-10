"""One consent for personal auto-recording. The legacy database key remains 'medium'."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from emlek.core import auto, tokens
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, require
from emlek.core.timeutil import utc_now_iso

_log = logging.getLogger("emlek")

TERMS = (
    "emLek 可以自動記錄你分享的生活、想法、工作摘要與個資，供之後回想查找。"
    "資料以明文保存在本機，備份與匯出也可能包含；密碼與金鑰不會儲存。"
    "你可以按筆記編號隱藏誤存內容。是否同意並啟用？**同意／不同意**"
)


def start(db: Database, caller: Caller, *, notice_token: str | None = None) -> dict[str, Any]:
    """Only an explicit start requests terms. Accepting never saves preceding conversation."""
    require(caller, "start")
    chash = tokens.content_hash("start", "", TERMS)
    if notice_token is not None:
        with db.transaction() as conn:
            tokens.consume(conn, "notice", notice_token, chash)
            acknowledge(conn)
    elif is_enabled(db.conn):
        token = tokens.issue(db, "notice", chash)
        raise EmlekError(
            ErrorCode.NEEDS_CONFIRMATION,
            "首次啟用須同意條款",
            data={
                "state": "needs_notice",
                "notice_token": token,
                "ask_user": TERMS,
                "expires_in": tokens.TTL_SECONDS,
            },
        )
    on = auto.enabled(db.conn)
    return {
        "started": True,
        "auto_enabled": on,
        "message": "emLek 已啟用。" if on else "emLek 已完成同意；自動記錄目前關閉。",
    }


def is_enabled(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT enabled FROM notice_settings WHERE level = 'medium'").fetchone()
    return row is None or bool(row[0])  # a missing row means "ask", never "don't ask"


def acknowledge(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO notice_settings (level, enabled, acknowledged_at)"
        " VALUES ('medium', 0, ?)",
        (utc_now_iso(),),
    )


def status(db: Database, caller: Caller) -> dict[str, Any]:
    require(caller, "notice_status")
    row = db.conn.execute(
        "SELECT enabled, acknowledged_at FROM notice_settings WHERE level = 'medium'"
    ).fetchone()
    return {
        "medium_notice_enabled": is_enabled(db.conn),
        "medium_acknowledged_at": row[1] if row else None,
        "personal_notice_enabled": is_enabled(db.conn),
    }


def enable_medium(db: Database, caller: Caller) -> dict[str, Any]:
    require(caller, "notice_enable")
    with db.transaction() as conn:
        conn.execute("DELETE FROM confirm_tokens WHERE kind = 'notice'")
        conn.execute(
            "INSERT OR REPLACE INTO notice_settings (level, enabled, acknowledged_at)"
            " VALUES ('medium', 1, NULL)"
        )
    _log.info("notice medium re-enabled")
    return {"medium_notice_enabled": True}
