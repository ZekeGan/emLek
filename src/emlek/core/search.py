"""Search: per-term routing between the trigram index and LIKE, filters, ordering, paging.

A hit is a record. By default only each record's latest version is matched.
"""

from __future__ import annotations

import base64
import binascii
import calendar
import json
import logging
import re
import sqlite3
from datetime import date
from typing import Any

from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, require
from emlek.core.service import KINDS, normalize_for_search

MAX_QUERY_CHARS = 512
MAX_TERMS = 20
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
ORDERS = ("relevance", "event_time", "created_at")
DIRECTIONS = ("asc", "desc")
SENSITIVITY_LEVELS = ("none", "medium", "high")
FTS_MIN_CHARS = 3

_TERM = re.compile(r'"([^"]+)"|(\S+)')
_DATE_PART = re.compile(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$")
_OFFSET = re.compile(r"^([+-])(\d{2}):(\d{2})$")
_log = logging.getLogger("emlek")


def parse_terms(query: str | None) -> list[str]:
    if query is None or not query.strip():
        return []
    if len(query) > MAX_QUERY_CHARS:
        raise EmlekError(ErrorCode.INVALID_INPUT, "查詢不可超過 512 字元")
    terms: list[str] = []
    for match in _TERM.finditer(query):
        term = normalize_for_search(match.group(1) or match.group(2)).strip()
        if term and term not in terms:
            terms.append(term)
    if len(terms) > MAX_TERMS:
        raise EmlekError(ErrorCode.INVALID_INPUT, "查詢詞不可超過 20 個")
    return terms


def date_bound(value: str, *, end: bool) -> str:
    """Turn 2026 / 2026-11 / 2026-11-01 into the first or last calendar day it covers."""
    if not _DATE_PART.match(value):
        raise EmlekError(ErrorCode.INVALID_INPUT, "日期格式應為 2026、2026-11 或 2026-11-01")
    parts = [int(p) for p in value.split("-")]
    try:
        if len(parts) == 1:
            return f"{parts[0]:04d}-12-31" if end else f"{parts[0]:04d}-01-01"
        if len(parts) == 2:
            last = calendar.monthrange(parts[0], parts[1])[1]
            return f"{parts[0]:04d}-{parts[1]:02d}-{last:02d}" if end else f"{value}-01"
        return date(parts[0], parts[1], parts[2]).isoformat()
    except (ValueError, calendar.IllegalMonthError) as exc:
        raise EmlekError(ErrorCode.INVALID_INPUT, "日期不存在") from exc


def tz_modifiers(timezone: str) -> list[str]:
    """SQLite date() modifiers that turn a UTC instant into the user's calendar day."""
    if timezone == "local":
        return ["localtime"]
    match = _OFFSET.match(timezone)
    if match is None:
        raise EmlekError(ErrorCode.INVALID_INPUT, "時區目前只支援 local 或 +09:00 這樣的偏移")
    sign, hours, minutes = match.groups()
    return [f"{sign}{int(hours)} hours", f"{sign}{int(minutes)} minutes"]


def _like_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _fts_expression(terms: list[str]) -> str:
    return " AND ".join('"' + t.replace('"', '""') + '"' for t in terms)


def _encode_cursor(order: str, direction: str, key: list[Any]) -> str:
    raw = json.dumps({"v": 1, "o": order, "d": direction, "k": key}, ensure_ascii=False)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str, order: str, direction: str) -> list[Any]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        key = data["k"]
        same = data["v"] == 1 and data["o"] == order and data["d"] == direction
        if not isinstance(key, list) or not same:
            raise ValueError("mismatch")
    except (ValueError, KeyError, TypeError, binascii.Error, UnicodeError) as exc:
        raise EmlekError(ErrorCode.INVALID_INPUT, "游標無效，或與目前的排序條件不符") from exc
    return key


def _after(row_key: list[Any], cursor_key: list[Any], signs: list[int]) -> bool:
    """True if row_key comes strictly after cursor_key in the result order."""
    for mine, theirs, sign in zip(row_key, cursor_key, signs, strict=True):
        if mine == theirs:
            continue
        return bool((mine > theirs) == (sign > 0))
    return False


class _Plan:
    """Builds the SELECT for one search. Placeholders stay in the order they are added."""

    def __init__(self, *, all_versions: bool) -> None:
        self.all_versions = all_versions
        self.conditions: list[str] = []
        self.params: list[Any] = []

    def add(self, condition: str, *params: Any) -> None:
        self.conditions.append(condition)
        self.params.extend(params)

    def latest(self, column: str) -> str:
        if not self.all_versions:
            return f"r.{column}"
        return (
            f"(SELECT l.{column} FROM revisions l WHERE l.record_id = r.record_id"
            " ORDER BY l.version_no DESC LIMIT 1)"
        )


def _run(
    db: Database,
    *,
    fts_terms: list[str],
    like_terms: list[str],
    kinds: list[str] | None,
    include_hidden: bool,
    all_versions: bool,
    date_field: str,
    date_from: str | None,
    date_to: str | None,
    modifiers: list[str],
    only_undated: bool,
    order: str,
    direction: str,
) -> list[sqlite3.Row | tuple[Any, ...]]:
    plan = _Plan(all_versions=all_versions)
    if fts_terms:
        source = "revisions_fts f JOIN revisions r ON r.id = f.rowid"
        plan.add("revisions_fts MATCH ?", _fts_expression(fts_terms))
        rank = "bm25(revisions_fts)"
    else:
        source = "revisions r"
        rank = "NULL"
    source += " JOIN records rec ON rec.id = r.record_id"
    for term in like_terms:
        plan.add("r.body_norm LIKE ? ESCAPE '\\'", _like_pattern(term))
    if not all_versions:
        plan.add(
            "r.version_no ="
            " (SELECT MAX(v.version_no) FROM revisions v WHERE v.record_id = r.record_id)"
        )
    if kinds:
        plan.add(f"r.kind IN ({','.join('?' * len(kinds))})", *kinds)
    if not include_hidden:
        plan.add("rec.hidden = 0")
    start, end = plan.latest("event_date_start"), plan.latest("event_date_end")
    if only_undated:
        plan.add(f"{start} IS NULL")
    elif date_field == "event_time":
        if date_from:
            plan.add(f"{end} >= ?", date_bound(date_from, end=False))
        if date_to:
            plan.add(f"{start} <= ?", date_bound(date_to, end=True))
    else:
        local_day = f"date(rec.created_at, {', '.join('?' * len(modifiers))})"
        if date_from:
            plan.add(f"{local_day} >= ?", *modifiers, date_bound(date_from, end=False))
        if date_to:
            plan.add(f"{local_day} <= ?", *modifiers, date_bound(date_to, end=True))
    sql_dir = "ASC" if direction == "asc" else "DESC"
    if order == "relevance":
        order_by = "rk ASC, rec.id ASC"
    elif order == "event_time":
        order_by = f"(ev_start IS NULL) ASC, ev_start {sql_dir}, rec.id {sql_dir}"
    else:
        order_by = f"rec.created_at {sql_dir}, rec.id {sql_dir}"
    where = " AND ".join(plan.conditions) or "1"
    sql = (
        f"SELECT r.id, r.record_id, r.version_no, {rank} AS rk, {start} AS ev_start,"
        f" rec.created_at, rec.sensitivity FROM {source} WHERE {where} ORDER BY {order_by}"
    )
    try:
        return db.conn.execute(sql, plan.params).fetchall()
    except sqlite3.Error as exc:
        _log.warning("search query failed: %s", type(exc).__name__)
        raise EmlekError(ErrorCode.INTERNAL, "搜尋時發生資料庫錯誤") from exc


def _snippet(body: str, terms: list[str]) -> str:
    flat = " ".join(body.split())
    norm = normalize_for_search(flat)
    position = -1
    length = 0
    for term in terms:
        found = norm.find(term)
        if found != -1 and (position == -1 or found < position):
            position, length = found, len(term)
    if position == -1:
        return flat[:160] + ("…" if len(flat) > 160 else "")
    if len(norm) != len(flat):  # normalization changed lengths; scale the position
        position = int(position * len(flat) / max(len(norm), 1))
    first = max(0, position - 60)
    last = min(len(flat), position + length + 100)
    return ("…" if first > 0 else "") + flat[first:last] + ("…" if last < len(flat) else "")


def search(
    db: Database,
    caller: Caller,
    *,
    query: str | None = None,
    kinds: list[str] | None = None,
    date_field: str = "event_time",
    date_from: str | None = None,
    date_to: str | None = None,
    order: str | None = None,
    direction: str = "desc",
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    all_versions: bool = False,
    include_hidden: bool = False,
    max_sensitivity: str = "high",
    timezone: str = "local",
) -> dict[str, Any]:
    require(caller, "search")
    terms = parse_terms(query)
    if kinds is not None and (not kinds or any(k not in KINDS for k in kinds)):
        raise EmlekError(ErrorCode.INVALID_INPUT, f"kinds 必須是 {', '.join(KINDS)} 其中的值")
    if date_field not in ("event_time", "created_at"):
        raise EmlekError(ErrorCode.INVALID_INPUT, "date_field 必須是 event_time 或 created_at")
    if direction not in DIRECTIONS:
        raise EmlekError(ErrorCode.INVALID_INPUT, "dir 必須是 asc 或 desc")
    if order is not None and order not in ORDERS:
        raise EmlekError(ErrorCode.INVALID_INPUT, f"order 必須是 {', '.join(ORDERS)} 其中之一")
    if max_sensitivity not in SENSITIVITY_LEVELS:
        raise EmlekError(ErrorCode.INVALID_INPUT, "max_sensitivity 必須是 none、medium 或 high")
    if not 1 <= limit <= MAX_LIMIT:
        raise EmlekError(ErrorCode.INVALID_INPUT, f"limit 必須介於 1 與 {MAX_LIMIT}")
    modifiers = tz_modifiers(timezone)
    # validate dates up front so errors do not depend on which branch runs
    for value, is_end in ((date_from, False), (date_to, True)):
        if value:
            date_bound(value, end=is_end)

    fts_terms = [t for t in terms if len(t) >= FTS_MIN_CHARS]
    like_terms = [t for t in terms if len(t) < FTS_MIN_CHARS]
    wanted = order or ("relevance" if terms else "event_time")
    applied = wanted
    if wanted == "relevance" and not fts_terms:
        applied, direction = "created_at", "desc"  # no rank without the index; newest first
    elif wanted == "relevance":
        direction = "asc"
    shared: dict[str, Any] = {
        "kinds": kinds,
        "include_hidden": include_hidden,
        "all_versions": all_versions,
        "date_field": date_field,
        "date_from": date_from,
        "date_to": date_to,
        "modifiers": modifiers,
        "order": applied,
        "direction": direction,
    }
    warnings: list[str] = []
    rows = _run(db, fts_terms=fts_terms, like_terms=like_terms, only_undated=False, **shared)
    if not rows and fts_terms:
        # an empty index answer is not proof of absence: look again without the index
        fallback = _run(db, fts_terms=[], like_terms=terms, only_undated=False, **shared)
        if fallback:
            _log.warning("search index is stale; answered from a full scan")
            rows, warnings = fallback, ["index_stale"]
    undated = 0
    if date_field == "event_time" and (date_from or date_to):
        undated_rows = _run(
            db,
            fts_terms=[] if warnings else fts_terms,
            like_terms=terms if warnings else like_terms,
            only_undated=True,
            **shared,
        )
        undated = len({r[1] for r in undated_rows})

    caps = {level: i for i, level in enumerate(SENSITIVITY_LEVELS)}
    ordered: list[dict[str, Any]] = []
    seen: set[int] = set()
    withheld = 0
    for rev_id, record_id, version_no, rank_value, ev_start, created_at, sensitivity in rows:
        if record_id in seen:
            continue
        seen.add(record_id)
        if caps[sensitivity] > caps[max_sensitivity]:
            withheld += 1
            continue
        if applied == "relevance":
            key: list[Any] = [rank_value, record_id]
        elif applied == "event_time":
            key = [1 if ev_start is None else 0, ev_start or "", record_id]
        else:
            key = [created_at, record_id]
        ordered.append(
            {"rev_id": rev_id, "record_id": record_id, "version": version_no, "key": key}
        )

    sign = 1 if direction == "asc" else -1
    signs = {"relevance": [1, 1], "event_time": [1, sign, sign], "created_at": [sign, sign]}[
        applied
    ]
    start_at = 0
    if cursor:
        cursor_key = _decode_cursor(cursor, applied, direction)
        if len(cursor_key) != len(signs):
            raise EmlekError(ErrorCode.INVALID_INPUT, "游標無效")
        start_at = next(
            (i for i, row in enumerate(ordered) if _after(row["key"], cursor_key, signs)),
            len(ordered),
        )
    page = ordered[start_at : start_at + limit]
    more = start_at + limit < len(ordered)
    next_cursor = _encode_cursor(applied, direction, page[-1]["key"]) if page and more else None

    results = [_describe(db, row, terms) for row in page]
    hints = _zero_result_hints(db) if terms and not ordered and not warnings else []
    return {
        "total": len(ordered),
        "undated": undated,
        "withheld": withheld,
        "order": applied,
        "dir": direction,
        "results": results,
        "next_cursor": next_cursor,
        "warnings": warnings,
        "hints": hints,
    }


def _script_shares(db: Database) -> dict[str, float]:
    kana = han = latin = 0
    for (body,) in db.conn.execute("SELECT body FROM revisions ORDER BY id DESC LIMIT 400"):
        for char in body[:600]:
            code = ord(char)
            if 0x3040 <= code <= 0x30FF:
                kana += 1
            elif 0x4E00 <= code <= 0x9FFF:
                han += 1
            elif char.isascii() and char.isalpha():
                latin += 1
    total = (kana + han + latin) or 1
    return {"kana": kana / total, "han": han / total, "latin": latin / total}


def _zero_result_hints(db: Database) -> list[str]:
    shares = _script_shares(db)
    labels = (("kana", "日文假名"), ("han", "漢字（中文或日文）"), ("latin", "英文字母"))
    present = [label for key, label in labels if shares[key] >= 0.05]
    mixed = "、".join(present) if present else "多種寫法"
    return [
        f"沒有找到。這個記憶庫的內容含 {mixed}；請把查詢詞換成另外的語言或寫法"
        "（日文要同時試平假名、片假名與漢字），試過仍沒有才能說找不到。"
    ]


def _describe(db: Database, row: dict[str, Any], terms: list[str]) -> dict[str, Any]:
    rev = db.conn.execute(
        "SELECT r.body, r.kind, r.source, r.event_time, r.event_time_precision, r.created_at,"
        " (SELECT MAX(version_no) FROM revisions WHERE record_id = r.record_id),"
        " rec.created_at, rec.hidden, rec.sensitivity"
        " FROM revisions r JOIN records rec ON rec.id = r.record_id WHERE r.id = ?",
        (row["rev_id"],),
    ).fetchone()
    body, kind, source, event_time, precision, _rev_created, latest, rec_created, hidden, sens = rev
    record_id, version = row["record_id"], row["version"]
    return {
        "ref": f"r{record_id}",
        "revision_ref": f"r{record_id}.v{version}",
        "matched_version": version,
        "latest_version": latest,
        "kind": kind,
        "snippet": _snippet(body, terms),
        "body_chars": len(body),
        "source": source,
        "event_time": event_time,
        "event_time_precision": precision,
        "created_at": rec_created,
        "hidden": bool(hidden),
        "sensitivity": sens,
    }


def index_status(db: Database) -> dict[str, Any]:
    revisions = db.conn.execute("SELECT count(*) FROM revisions").fetchone()[0]
    indexed = db.conn.execute("SELECT count(*) FROM revisions_fts_docsize").fetchone()[0]
    return {"revisions": revisions, "indexed": indexed, "ok": revisions == indexed}


def reindex(db: Database, caller: Caller) -> dict[str, Any]:
    require(caller, "reindex")
    with db.transaction() as conn:
        conn.execute("INSERT INTO revisions_fts (revisions_fts) VALUES ('rebuild')")
    return index_status(db)
