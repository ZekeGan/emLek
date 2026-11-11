"""Counts and dates about the vault. No record content."""

from __future__ import annotations

from typing import Any

from emlek.core.db import Database
from emlek.core.permissions import Caller, require, sees_hidden
from emlek.core.search import index_status


def stats(db: Database, caller: Caller) -> dict[str, Any]:
    require(caller, "stats")
    conn = db.conn
    everything = sees_hidden(caller)  # D103: an AI counts only notes it can see
    seen = "" if everything else " WHERE hidden = 0"
    seen_rev = "" if everything else " WHERE record_id IN (SELECT id FROM records WHERE hidden = 0)"
    visible = conn.execute("SELECT count(*) FROM records WHERE hidden = 0").fetchone()[0]
    hidden = conn.execute("SELECT count(*) FROM records WHERE hidden = 1").fetchone()[0]
    revisions = conn.execute(f"SELECT count(*) FROM revisions{seen_rev}").fetchone()[0]
    by_kind = dict(
        conn.execute(f"SELECT kind, count(*) FROM revisions{seen_rev} GROUP BY kind").fetchall()
    )
    event_first, event_last = conn.execute(
        f"SELECT min(event_date_start), max(event_date_end) FROM revisions{seen_rev}"
    ).fetchone()
    saved_first, saved_last = conn.execute(
        f"SELECT min(created_at), max(created_at) FROM records{seen}"
    ).fetchone()
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    purges, last_purge = conn.execute("SELECT count(*), max(at) FROM purge_log").fetchone()
    index = index_status(db)
    return {
        "records": visible,
        **({"hidden_records": hidden} if everything else {}),
        "revisions": revisions,
        "revisions_by_kind": by_kind,
        "event_dates": {"first": event_first, "last": event_last},
        "saved_between": {"first": saved_first, "last": saved_last},
        "last_backup_at": meta.get("last_backup_at"),
        "last_backup_file": meta.get("last_backup_file"),
        "purges": {"count": purges, "last_at": last_purge},
        "schema_version": db.user_version,
        "database_bytes": db.path.stat().st_size,
        "search_index_ok": index["ok"],
    }
