"""Counts and dates about the vault. No record content."""

from __future__ import annotations

from typing import Any

from emlek.core.db import Database
from emlek.core.permissions import Caller, require
from emlek.core.search import index_status


def stats(db: Database, caller: Caller) -> dict[str, Any]:
    require(caller, "stats")
    conn = db.conn
    visible = conn.execute("SELECT count(*) FROM records WHERE hidden = 0").fetchone()[0]
    hidden = conn.execute("SELECT count(*) FROM records WHERE hidden = 1").fetchone()[0]
    revisions = conn.execute("SELECT count(*) FROM revisions").fetchone()[0]
    by_kind = dict(conn.execute("SELECT kind, count(*) FROM revisions GROUP BY kind").fetchall())
    event_first, event_last = conn.execute(
        "SELECT min(event_date_start), max(event_date_end) FROM revisions"
    ).fetchone()
    saved_first, saved_last = conn.execute(
        "SELECT min(created_at), max(created_at) FROM records"
    ).fetchone()
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    index = index_status(db)
    return {
        "records": visible,
        "hidden_records": hidden,
        "revisions": revisions,
        "revisions_by_kind": by_kind,
        "event_dates": {"first": event_first, "last": event_last},
        "saved_between": {"first": saved_first, "last": saved_last},
        "last_backup_at": meta.get("last_backup_at"),
        "last_backup_file": meta.get("last_backup_file"),
        "schema_version": db.user_version,
        "database_bytes": db.path.stat().st_size,
        "search_index_ok": index["ok"],
    }
