"""Auto-record policy (D85): which kinds of things the AI may save without asking first.

The policy only says what is *allowed*. The core checks the switch, the category, the sensitivity
scan and a rolling daily limit when a save carries `source="auto:<category>"`; it cannot check that
the content really came from the user's own words, which is why every auto-saved record is marked,
listed by `recent --auto`, and hidden (not purged) when the user takes it back.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Any

from emlek.core import notice, versions
from emlek.core import sensitivity as scanner
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, require
from emlek.core.timeutil import utc_now_iso

PREFIX = "auto:"
MODES = ("auto", "ask", "off")
MAX_NAME = 20
MAX_DESCRIPTION = 100
MAX_KEYWORD = 100
MAX_EXCLUDED = 50
LIMIT_RANGE = (1, 200)
AUTO_KINDS = ("original", "ai_summary")  # an inference is never saved on its own
EXCERPT_CHARS = 60
_log = logging.getLogger("emlek")


def _clean(text: object, limit: int, what: str) -> str:
    cleaned = text.strip() if isinstance(text, str) else ""
    if not 1 <= len(cleaned) <= limit or any(ord(c) < 32 or ord(c) == 127 for c in cleaned):
        raise EmlekError(ErrorCode.INVALID_INPUT, f"{what}長度須為 1–{limit} 字元且不含控制字元")
    return cleaned


def _name(text: object) -> str:
    cleaned = _clean(text, MAX_NAME, "類別名稱")
    if ":" in cleaned or "：" in cleaned:
        raise EmlekError(ErrorCode.INVALID_INPUT, "類別名稱不可含冒號")
    return cleaned


def _meta(conn: sqlite3.Connection, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return str(row[0]) if row else default


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _excluded(conn: sqlite3.Connection) -> list[str]:
    try:
        found = json.loads(_meta(conn, "auto_excluded", "[]"))
    except ValueError:
        return []
    return [str(item) for item in found] if isinstance(found, list) else []


def enabled(conn: sqlite3.Connection) -> bool:
    return _meta(conn, "auto_enabled", "0") == "1"


def auto_names(conn: sqlite3.Connection) -> list[str]:
    """Names of the categories that may be saved without asking (for the opening instructions)."""
    if not enabled(conn):
        return []
    rows = conn.execute("SELECT name FROM auto_categories WHERE mode = 'auto' ORDER BY id")
    return [str(r[0]) for r in rows]


def _used(conn: sqlite3.Connection) -> int:
    since = (datetime.now(UTC) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    row = conn.execute(
        "SELECT count(*) FROM revisions WHERE version_no = 1 AND source LIKE 'auto:%'"
        " AND created_at >= ?",
        (since,),
    ).fetchone()
    return int(row[0])


def marker(ref: str) -> str:
    """The one line the AI puts at the end of its answer after an automatic save."""
    return f"◆ emLek｜{ref}.✔️"


def policy(db: Database, caller: Caller) -> dict[str, Any]:
    require(caller, "auto_policy")
    conn = db.conn
    rows = conn.execute("SELECT name, description, mode FROM auto_categories ORDER BY id")
    return {
        "enabled": enabled(conn),
        "started": not notice.is_enabled(conn),
        "daily_limit": int(_meta(conn, "auto_daily_limit", "30")),
        "used_24h": _used(conn),
        "categories": [{"name": n, "description": d, "mode": m} for n, d, m in rows],
        "excluded_projects": _excluded(conn),
        "marker_format": marker("r<編號>"),
        "source_format": f"{PREFIX}<類別>",
    }


def guard(
    db: Database, *, source: str | None, kind: str, body: str, declared: str | None
) -> str | None:
    """Checked inside `save` when the source says "auto:". Returns the category, or None when the
    save is an ordinary one."""
    if source is None or not source.startswith(PREFIX):
        return None
    conn = db.conn
    category = source[len(PREFIX) :]
    if not enabled(conn):
        raise EmlekError(ErrorCode.NOT_PERMITTED, "自動記錄已關閉；不要自動儲存，也不要逐筆詢問")
    row = conn.execute("SELECT mode FROM auto_categories WHERE name = ?", (category,)).fetchone()
    if row is None or row[0] != "auto":
        raise EmlekError(
            ErrorCode.NOT_PERMITTED, f"「{category}」未啟用自動記錄；不要自動儲存，也不要逐筆詢問"
        )
    if kind not in AUTO_KINDS:
        raise EmlekError(ErrorCode.NOT_PERMITTED, "自動記錄只能存使用者的原文或你的整理，不存推論")
    level, _ = scanner.assess(body, declared or "none")
    if level == "high":  # medium (personal data) goes on to the one-time notice, then flows
        raise EmlekError(
            ErrorCode.NOT_PERMITTED,
            "內容含有最高風險資訊，不能自動記錄；不要存，也不要詢問是否存入",
        )
    limit = int(_meta(conn, "auto_daily_limit", "30"))
    if _used(conn) >= limit:
        raise EmlekError(
            ErrorCode.NOT_PERMITTED, f"24 小時內自動記錄已達上限 {limit} 筆；停止自動儲存"
        )
    return category


# --- configuration (a person at a terminal, with the PIN) -----------------------------------


def set_enabled(db: Database, caller: Caller, *, on: bool) -> dict[str, Any]:
    require(caller, "auto_config")
    with db.transaction() as conn:
        _set_meta(conn, "auto_enabled", "1" if on else "0")
    _log.info("auto enabled=%s", on)
    return {"enabled": on}


def set_mode(db: Database, caller: Caller, *, name: str, mode: str) -> dict[str, Any]:
    require(caller, "auto_config")
    if mode not in MODES:
        raise EmlekError(ErrorCode.INVALID_INPUT, f"模式必須是 {', '.join(MODES)} 其中之一")
    with db.transaction() as conn:
        done = conn.execute(
            "UPDATE auto_categories SET mode = ?, updated_at = ? WHERE name = ?",
            (mode, utc_now_iso(), _name(name)),
        )
        if done.rowcount == 0:
            raise EmlekError(ErrorCode.NOT_FOUND, "找不到這個類別")
    _log.info("auto category mode=%s", mode)
    return {"name": _name(name), "mode": mode}


def add_category(
    db: Database, caller: Caller, *, name: str, description: str = ""
) -> dict[str, Any]:
    require(caller, "auto_config")
    cleaned = _name(name)
    detail = _clean(description, MAX_DESCRIPTION, "說明") if description else ""
    now = utc_now_iso()
    try:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO auto_categories (name, description, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                (cleaned, detail, now, now),
            )
    except sqlite3.IntegrityError as exc:
        raise EmlekError(ErrorCode.CONFLICT, "已有同名的類別") from exc
    return {"name": cleaned, "mode": "ask"}


def remove_category(db: Database, caller: Caller, *, name: str) -> dict[str, Any]:
    require(caller, "auto_config")
    cleaned = _name(name)
    with db.transaction() as conn:
        done = conn.execute("DELETE FROM auto_categories WHERE name = ?", (cleaned,))
        if done.rowcount == 0:
            raise EmlekError(ErrorCode.NOT_FOUND, "找不到這個類別")
    return {"name": cleaned, "removed": True}


def set_limit(db: Database, caller: Caller, *, limit: int) -> dict[str, Any]:
    require(caller, "auto_config")
    low, high = LIMIT_RANGE
    if not isinstance(limit, int) or isinstance(limit, bool) or not low <= limit <= high:
        raise EmlekError(ErrorCode.INVALID_INPUT, f"每日上限須為 {low}–{high}")
    with db.transaction() as conn:
        _set_meta(conn, "auto_daily_limit", str(limit))
    return {"daily_limit": limit}


def exclude(db: Database, caller: Caller, *, keyword: str, remove: bool = False) -> dict[str, Any]:
    require(caller, "auto_config")
    cleaned = _clean(keyword, MAX_KEYWORD, "關鍵字")
    with db.transaction() as conn:
        items = _excluded(conn)
        key = unicodedata.normalize("NFKC", cleaned).casefold()
        kept = [i for i in items if unicodedata.normalize("NFKC", i).casefold() != key]
        if remove:
            items = kept
        elif len(kept) == len(items):
            if len(items) >= MAX_EXCLUDED:
                raise EmlekError(ErrorCode.INVALID_INPUT, f"排除清單最多 {MAX_EXCLUDED} 項")
            items = [*items, cleaned]
        _set_meta(conn, "auto_excluded", json.dumps(items, ensure_ascii=False))
    return {"excluded_projects": items}


# --- looking back and taking back ------------------------------------------------------------


def recent(
    db: Database, caller: Caller, *, days: int = 7, auto_only: bool = False, limit: int = 50
) -> dict[str, Any]:
    require(caller, "recent")
    if not 1 <= days <= 3650 or not 1 <= limit <= 200:
        raise EmlekError(ErrorCode.INVALID_INPUT, "days 須為 1–3650，limit 須為 1–200")
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    rows = db.conn.execute(
        "SELECT rec.id, first.created_at, first.source, rec.hidden, latest.body"
        " FROM records rec JOIN revisions first ON first.record_id = rec.id"
        " AND first.version_no = 1"
        " JOIN revisions latest ON latest.record_id = rec.id AND latest.version_no ="
        " (SELECT max(version_no) FROM revisions WHERE record_id = rec.id)"
        " WHERE first.created_at >= ? AND (? = 0 OR first.source LIKE 'auto:%')"
        " ORDER BY first.created_at DESC, rec.id DESC LIMIT ?",
        (since, 1 if auto_only else 0, limit),
    ).fetchall()
    items = []
    for record_id, created_at, source, hidden, body in rows:
        auto = isinstance(source, str) and source.startswith(PREFIX)
        items.append(
            {
                "ref": f"r{record_id}",
                "created_at": created_at,
                "category": source[len(PREFIX) :] if auto else None,
                "hidden": bool(hidden),
                "excerpt": " ".join(str(body).split())[:EXCERPT_CHARS],
            }
        )
    return {"records": items, "days": days, "auto_only": auto_only}


def hide_since(db: Database, caller: Caller, *, since: str) -> dict[str, Any]:
    """Hide (not purge) every auto-saved record created on or after `since` (YYYY-MM-DD)."""
    require(caller, "auto_hide")
    try:
        day = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as exc:
        raise EmlekError(ErrorCode.INVALID_INPUT, "日期格式須為 YYYY-MM-DD") from exc
    stamp = day.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    rows = db.conn.execute(
        "SELECT rec.id FROM records rec JOIN revisions first ON first.record_id = rec.id"
        " AND first.version_no = 1 WHERE first.source LIKE 'auto:%' AND first.created_at >= ?"
        " AND rec.hidden = 0 ORDER BY rec.id",
        (stamp,),
    ).fetchall()
    hidden = []
    for (record_id,) in rows:
        versions.hide(db, caller, ref=f"r{record_id}")
        hidden.append(f"r{record_id}")
    return {"hidden": hidden, "count": len(hidden), "since": since}
