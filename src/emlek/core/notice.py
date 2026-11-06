"""One consent for personal auto-recording. The legacy database key remains 'medium'."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from emlek.core.db import Database
from emlek.core.permissions import Caller, require
from emlek.core.timeutil import utc_now_iso

_log = logging.getLogger("emlek")


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
