"""Versions, links and hiding (M5). Rules are specified in DESIGN, "版本與連結語意".

Links point from a newer revision to an older one, so a record's status is a computed value:
nothing is stored besides the links and the hidden flag.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence
from typing import Any

from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, require, sees_hidden
from emlek.core.refs import parse_ref
from emlek.core.timeutil import utc_now_iso

RELATIONS = ("supersedes", "supports", "supplements", "derived", "summarizes")
PROPAGATING = ("derived", "summarizes")  # only these carry a hidden source down to a derivative
MAX_LINKS_PER_CALL = 20
MAX_LINKED_FROM = 50
MAX_DERIVATION_DEPTH = 20

_log = logging.getLogger("emlek")


def _revision_for(
    conn: sqlite3.Connection, ref: str, *, need_visible: bool = True
) -> tuple[int, int, int]:
    """Resolve r12 / r12.v2 to (revision id, record id, version); r12 means the latest version."""
    record_id, version = parse_ref(ref)
    if version is None:
        row = conn.execute(
            "SELECT r.id, r.version_no, rec.hidden FROM revisions r JOIN records rec"
            " ON rec.id = r.record_id WHERE r.record_id = ? ORDER BY r.version_no DESC LIMIT 1",
            (record_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT r.id, r.version_no, rec.hidden FROM revisions r JOIN records rec"
            " ON rec.id = r.record_id WHERE r.record_id = ? AND r.version_no = ?",
            (record_id, version),
        ).fetchone()
    if row is None or (need_visible and row[2]):
        raise EmlekError(ErrorCode.NOT_FOUND, f"找不到連結目標 {ref}（不存在或已隱藏）")
    return int(row[0]), record_id, int(row[1])


def add_links(
    conn: sqlite3.Connection,
    revision_id: int,
    record_id: int,
    links: Sequence[dict[str, Any]] | None,
    now: str,
) -> int:
    """Validate and insert links from a new revision to older ones. Returns how many were new."""
    if not links:
        return 0
    if len(links) > MAX_LINKS_PER_CALL:
        raise EmlekError(ErrorCode.INVALID_INPUT, f"一次最多 {MAX_LINKS_PER_CALL} 條連結")
    added = 0
    for link in links:
        if not isinstance(link, dict) or set(link) - {"ref", "relation"} or "ref" not in link:
            raise EmlekError(ErrorCode.INVALID_INPUT, "連結格式應為 {ref, relation}")
        relation = link.get("relation")
        if relation is not None and relation not in RELATIONS:
            raise EmlekError(ErrorCode.INVALID_INPUT, f"relation 必須是 {', '.join(RELATIONS)}")
        target_id, target_record, _ = _revision_for(conn, str(link["ref"]))
        if target_record == record_id:
            raise EmlekError(ErrorCode.INVALID_INPUT, "不能連到自己所在的記錄；同一筆請用 amend")
        cursor = conn.execute(
            "INSERT OR IGNORE INTO links (revision_id, derived_from_revision_id, relation,"
            " created_at) VALUES (?, ?, ?, ?)",
            (revision_id, target_id, relation, now),
        )
        added += cursor.rowcount
    return added


def statuses(conn: sqlite3.Connection) -> dict[int, str]:
    """record id -> 'superseded' | 'reaffirmed' for every record that is not simply current.

    A record is superseded when a visible record's `supersedes` link points at it; it is
    reaffirmed when a visible record later added `supports` (later = a higher link id).
    """
    last: dict[str, dict[int, int]] = {"supersedes": {}, "supports": {}}
    for relation, record_id, link_id in conn.execute(
        "SELECT l.relation, tr.record_id, MAX(l.id) FROM links l"
        " JOIN revisions tr ON tr.id = l.derived_from_revision_id"
        " JOIN revisions sr ON sr.id = l.revision_id"
        " JOIN records src ON src.id = sr.record_id"
        " WHERE l.relation IN ('supersedes', 'supports') AND src.hidden = 0"
        " GROUP BY l.relation, tr.record_id"
    ):
        last[relation][int(record_id)] = int(link_id)
    result: dict[int, str] = {}
    for record_id, superseded_at in last["supersedes"].items():
        reaffirmed = last["supports"].get(record_id, 0) > superseded_at
        result[record_id] = "reaffirmed" if reaffirmed else "superseded"
    return result


def status_of(conn: sqlite3.Connection, record_id: int) -> str:
    return statuses(conn).get(record_id, "current")


def _allowed_levels(cap: str) -> str:
    order = ("none", "medium", "high")
    return ", ".join(f"'{level}'" for level in order[: order.index(cap) + 1])


def superseded_by(
    conn: sqlite3.Connection, record_id: int, *, max_sensitivity: str = "high"
) -> list[dict[str, Any]]:
    """Visible records that supersede any version of this one, oldest link first (one hop)."""
    return [
        {"ref": f"r{rec}", "revision_ref": f"r{rec}.v{ver}", "linked_at": created}
        for rec, ver, created in conn.execute(
            "SELECT sr.record_id, sr.version_no, MIN(l.created_at) FROM links l"
            " JOIN revisions tr ON tr.id = l.derived_from_revision_id"
            " JOIN revisions sr ON sr.id = l.revision_id"
            " JOIN records src ON src.id = sr.record_id"
            " WHERE l.relation = 'supersedes' AND tr.record_id = ? AND src.hidden = 0"
            f" AND src.sensitivity IN ({_allowed_levels(max_sensitivity)})"
            " GROUP BY sr.id ORDER BY MIN(l.id)",
            (record_id,),
        )
    ]


def linked_from(
    conn: sqlite3.Connection,
    record_id: int,
    *,
    include_hidden: bool = False,
    max_sensitivity: str = "high",
) -> tuple[list[dict[str, Any]], bool]:
    """Everything that points at this record (one hop, at most MAX_LINKED_FROM)."""
    rows = conn.execute(
        "SELECT sr.record_id, sr.version_no, l.relation, l.created_at, tr.version_no FROM links l"
        " JOIN revisions tr ON tr.id = l.derived_from_revision_id"
        " JOIN revisions sr ON sr.id = l.revision_id"
        " JOIN records src ON src.id = sr.record_id"
        " WHERE tr.record_id = ? AND (src.hidden = 0 OR ?)"
        f" AND src.sensitivity IN ({_allowed_levels(max_sensitivity)}) ORDER BY l.id LIMIT ?",
        (record_id, 1 if include_hidden else 0, MAX_LINKED_FROM + 1),
    ).fetchall()
    items = [
        {
            "ref": f"r{rec}",
            "revision_ref": f"r{rec}.v{ver}",
            "relation": relation,
            "target_version": target_version,
            "linked_at": created,
        }
        for rec, ver, relation, created, target_version in rows[:MAX_LINKED_FROM]
    ]
    return items, len(rows) > MAX_LINKED_FROM


def links_out(
    conn: sqlite3.Connection, revision_id: int, *, include_hidden: bool = True
) -> list[dict[str, Any]]:
    """Where a revision points. An AI reader never sees links to hidden notes (D103)."""
    return [
        {"ref": f"r{rec}", "revision_ref": f"r{rec}.v{ver}", "relation": relation}
        for rec, ver, relation in conn.execute(
            "SELECT tr.record_id, tr.version_no, l.relation FROM links l"
            " JOIN revisions tr ON tr.id = l.derived_from_revision_id"
            " JOIN records rec ON rec.id = tr.record_id"
            " WHERE l.revision_id = ? AND (? OR rec.hidden = 0) ORDER BY l.id",
            (revision_id, 1 if include_hidden else 0),
        )
    ]


def _sources_of(conn: sqlite3.Connection, record_id: int) -> list[int]:
    return [
        int(row[0])
        for row in conn.execute(
            "SELECT DISTINCT tr.record_id FROM links l"
            " JOIN revisions sr ON sr.id = l.revision_id"
            " JOIN revisions tr ON tr.id = l.derived_from_revision_id"
            " WHERE sr.record_id = ? AND l.relation IN ('derived', 'summarizes')",
            (record_id,),
        )
    ]


def hidden_sources(conn: sqlite3.Connection, record_id: int) -> list[int]:
    """Hidden records this one is (transitively) derived from; non-empty means it is invalid."""
    seen = {record_id}
    frontier = [(record_id, 0)]
    found: list[int] = []
    while frontier:
        current, depth = frontier.pop()
        if depth >= MAX_DERIVATION_DEPTH:
            continue
        for source in _sources_of(conn, current):
            if source in seen:
                continue
            seen.add(source)
            hidden = conn.execute("SELECT hidden FROM records WHERE id = ?", (source,)).fetchone()
            if hidden and hidden[0]:
                found.append(source)
            frontier.append((source, depth + 1))
    return sorted(found)


def derivatives_of(conn: sqlite3.Connection, record_id: int) -> list[int]:
    """Records that (transitively) derive from or summarize this one."""
    seen = {record_id}
    frontier = [(record_id, 0)]
    found: list[int] = []
    while frontier:
        current, depth = frontier.pop()
        if depth >= MAX_DERIVATION_DEPTH:
            continue
        for (child,) in conn.execute(
            "SELECT DISTINCT sr.record_id FROM links l"
            " JOIN revisions sr ON sr.id = l.revision_id"
            " JOIN revisions tr ON tr.id = l.derived_from_revision_id"
            " WHERE tr.record_id = ? AND l.relation IN ('derived', 'summarizes')",
            (current,),
        ):
            if child not in seen:
                seen.add(child)
                found.append(int(child))
                frontier.append((int(child), depth + 1))
    return sorted(found)


def invalidated_ids(conn: sqlite3.Connection) -> set[int]:
    """Every record derived (transitively) from a hidden one: its content is withheld from AI
    callers, so a word or tag must not be able to find it either (pre-1.0 review)."""
    if not has_links(conn):
        return set()
    found: set[int] = set()
    for (hidden_id,) in conn.execute("SELECT id FROM records WHERE hidden = 1").fetchall():
        found.update(derivatives_of(conn, int(hidden_id)))
    return found


def has_links(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM links LIMIT 1").fetchone() is not None


def describe(
    conn: sqlite3.Connection, record_id: int, status_map: dict[int, str]
) -> dict[str, Any]:
    """Status fields shared by search results and get."""
    invalid = hidden_sources(conn, record_id) if has_links(conn) else []
    return {
        "status": status_map.get(record_id, "current"),
        "invalidated": bool(invalid),
    }


def _set_hidden(db: Database, caller: Caller, ref: str, *, hide: bool) -> dict[str, Any]:
    require(caller, "hide" if hide else "unhide")
    record_id, _ = parse_ref(ref)
    now = utc_now_iso()
    with db.transaction() as conn:
        row = conn.execute("SELECT hidden FROM records WHERE id = ?", (record_id,)).fetchone()
        if row is None or (row[0] and not sees_hidden(caller)):
            raise EmlekError(ErrorCode.NOT_FOUND, "找不到這筆記錄")
        changed = bool(row[0]) != hide
        if changed:
            conn.execute(
                "UPDATE records SET hidden = ?, hidden_at = ? WHERE id = ?",
                (1 if hide else 0, now if hide else None, record_id),
            )
        affected = [
            rid
            for rid in derivatives_of(conn, record_id)
            if sees_hidden(caller)
            or not conn.execute("SELECT hidden FROM records WHERE id = ?", (rid,)).fetchone()[0]
        ]
    _log.info("%s record=%d changed=%s", "hide" if hide else "unhide", record_id, changed)
    return {
        "ref": f"r{record_id}",
        "hidden": hide,
        "changed": changed,
        "affected_derivatives": [f"r{rid}" for rid in affected],
    }


def hide(db: Database, caller: Caller, *, ref: str) -> dict[str, Any]:
    return _set_hidden(db, caller, ref, hide=True)


def unhide(db: Database, caller: Caller, *, ref: str) -> dict[str, Any]:
    return _set_hidden(db, caller, ref, hide=False)
