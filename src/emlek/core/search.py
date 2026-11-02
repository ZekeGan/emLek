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
from collections import Counter
from collections.abc import Sequence
from datetime import date
from typing import Any

from emlek.core import tags as tagmod
from emlek.core import versions
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, require
from emlek.core.service import KINDS, normalize_for_search

MAX_QUERY_CHARS = 512
MAX_TERMS = 30
MAX_ALTERNATIVES = 20
MAX_TERM_HITS = 12  # how many words get a hit count when a query finds nothing
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
ORDERS = ("relevance", "event_time", "created_at")
DIRECTIONS = ("asc", "desc")
SENSITIVITY_LEVELS = ("none", "medium", "high")
FTS_MIN_CHARS = 3
MAX_COVERAGE_SET = 20000  # beyond this the tag-coverage count is skipped
AGGREGATE_THRESHOLD = 50  # above this many matches the response also carries a summary
MAX_SUMMARY_MONTHS = 24
SUMMARY_NOTE = "依關鍵字比對，可能漏掉不同說法的記錄；僅供縮小範圍，不代表全貌"

_SCRIPTS = {
    "kana": re.compile("[\u3040-\u30ff]"),
    "han": re.compile("[\u4e00-\u9fff]"),
    "latin": re.compile("[A-Za-z]"),
}
_TERM = re.compile(r'"([^"]+)"|(\S+)')
_DATE_PART = re.compile(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$")
_OFFSET = re.compile(r"^([+-])(\d{2}):(\d{2})$")
_log = logging.getLogger("emlek")


def parse_alternatives(query: str | None) -> list[list[str]]:
    """Split a query on a bare, uppercase OR. Inside one alternative every word must appear;
    across alternatives any one is enough. A quoted "OR" or a lowercase or is just a word."""
    if query is None or not query.strip():
        return []
    if len(query) > MAX_QUERY_CHARS:
        raise EmlekError(ErrorCode.INVALID_INPUT, "查詢不可超過 512 字元")
    alternatives: list[list[str]] = [[]]
    total = 0
    for match in _TERM.finditer(query):
        quoted, bare = match.group(1), match.group(2)
        if bare == "OR":
            if alternatives[-1]:
                alternatives.append([])
            continue
        term = normalize_for_search(quoted or bare).strip()
        if term and term not in alternatives[-1]:
            alternatives[-1].append(term)
            total += 1
    alternatives = [alt for alt in alternatives if alt]
    if total > MAX_TERMS:
        raise EmlekError(
            ErrorCode.INVALID_INPUT,
            f"查詢詞不可超過 {MAX_TERMS} 個；請挑最有代表性的詞，或分成兩次搜尋",
        )
    if len(alternatives) > MAX_ALTERNATIVES:
        raise EmlekError(
            ErrorCode.INVALID_INPUT,
            f"OR 最多 {MAX_ALTERNATIVES} 組；請挑最有代表性的說法，或分成兩次搜尋",
        )
    return alternatives


def parse_terms(query: str | None) -> list[str]:
    """All distinct words of a query (for snippets and hints), OR operators removed."""
    terms: list[str] = []
    for alternative in parse_alternatives(query):
        for term in alternative:
            if term not in terms:
                terms.append(term)
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


def _fts_expression(terms: list[str] | None, joiner: str = " AND ") -> str:
    return joiner.join('"' + t.replace('"', '""') + '"' for t in terms or [])


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
    fts_any: list[str] | None = None,
    like_any: list[str] | None = None,
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
    tag_groups: list[list[int]] | None = None,
    tag_types: list[str] | None = None,
    untagged: bool = False,
) -> list[sqlite3.Row | tuple[Any, ...]]:
    plan = _Plan(all_versions=all_versions)
    if fts_terms or fts_any:
        source = "revisions_fts f JOIN revisions r ON r.id = f.rowid"
        expression = _fts_expression(fts_terms) if fts_terms else _fts_expression(fts_any, " OR ")
        plan.add("revisions_fts MATCH ?", expression)
        rank = "bm25(revisions_fts)"
    else:
        source = "revisions r"
        rank = "NULL"
    source += " JOIN records rec ON rec.id = r.record_id"
    for term in like_terms:
        plan.add("r.body_norm LIKE ? ESCAPE '\\'", _like_pattern(term))
    if like_any:
        plan.add(
            "(" + " OR ".join("r.body_norm LIKE ? ESCAPE '\\'" for _ in like_any) + ")",
            *(_like_pattern(t) for t in like_any),
        )
    if not all_versions:
        plan.add(
            "r.version_no ="
            " (SELECT MAX(v.version_no) FROM revisions v WHERE v.record_id = r.record_id)"
        )
    if kinds:
        plan.add(f"r.kind IN ({','.join('?' * len(kinds))})", *kinds)
    if not include_hidden:
        plan.add("rec.hidden = 0")
    for group in tag_groups or []:
        plan.add(
            "EXISTS (SELECT 1 FROM record_tags rt WHERE rt.record_id = rec.id"
            f" AND rt.tag_id IN ({','.join('?' * len(group))}))",
            *group,
        )
    if untagged:
        plan.add("NOT EXISTS (SELECT 1 FROM record_tags rt WHERE rt.record_id = rec.id)")
    if tag_types:
        plan.add(
            "EXISTS (SELECT 1 FROM record_tags rt JOIN tags tg ON tg.id = rt.tag_id"
            f" WHERE rt.record_id = rec.id AND tg.type IN ({','.join('?' * len(tag_types))}))",
            *tag_types,
        )
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


def _gather(
    db: Database,
    alternatives: list[list[str]],
    *,
    stale: bool,
    notes: list[str] | None = None,
    **kwargs: Any,
) -> list[tuple[Any, ...]]:
    """Run every OR alternative and merge: a record counts once, with its best rank.

    One alternative (the usual case) is exactly the old single query."""
    order, direction = kwargs["order"], kwargs["direction"]
    if len(alternatives) <= 1:
        words = alternatives[0] if alternatives else []
        fts = [] if stale else [t for t in words if len(t) >= FTS_MIN_CHARS]
        like = words if stale else [t for t in words if len(t) < FTS_MIN_CHARS]
        return [tuple(row) for row in _run(db, fts_terms=fts, like_terms=like, **kwargs)]
    merged: dict[int, tuple[Any, ...]] = {}
    # groups of a single word are the common case (a list of synonyms): ask for all of them in
    # one query instead of one table pass each; groups of several words still run one by one
    singles = [alt[0] for alt in alternatives if len(alt) == 1]
    batched_fts = [] if stale else [t for t in singles if len(t) >= FTS_MIN_CHARS]
    batched_like = singles if stale else [t for t in singles if len(t) < FTS_MIN_CHARS]
    jobs: list[tuple[list[str], list[str], list[str], list[str], list[str]]] = []
    if len(batched_fts) > 1:
        jobs.append(([], [], batched_fts, [], batched_fts))
    if len(batched_like) > 1:
        jobs.append(([], [], [], batched_like, batched_like))
    taken = {t for job in jobs for t in job[4]}
    for words in alternatives:
        if len(words) == 1 and words[0] in taken:
            continue
        fts = [] if stale else [t for t in words if len(t) >= FTS_MIN_CHARS]
        like = words if stale else [t for t in words if len(t) < FTS_MIN_CHARS]
        jobs.append((fts, like, [], [], words))
    for fts, like, any_fts, any_like, words in jobs:
        found_rows = list(
            _run(
                db,
                fts_terms=fts,
                like_terms=like,
                fts_any=any_fts or None,
                like_any=any_like or None,
                **kwargs,
            )
        )
        if not found_rows and (fts or any_fts):
            fts = fts or any_fts
            # one group answering from the index while another group's index is stale would
            # hide records silently: an empty index answer is checked again without the index
            again = list(
                _run(
                    db,
                    fts_terms=[],
                    like_terms=[] if any_fts else words,
                    like_any=any_fts or None,
                    **kwargs,
                )
            )
            if again:
                found_rows = again
                if notes is not None and "index_stale" not in notes:
                    notes.append("index_stale")
        for found in found_rows:
            row = tuple(found)
            if order == "relevance" and row[3] is None:
                row = (*row[:3], 0.0, *row[4:])  # matched without the index: neutral rank
            known = merged.get(row[1])
            if known is None or (order == "relevance" and row[3] < known[3]):
                merged[row[1]] = row
    rows = list(merged.values())
    descending = direction == "desc"
    if order == "relevance":
        return sorted(rows, key=lambda r: (r[3], r[1]))
    if order == "event_time":
        dated = sorted(
            (r for r in rows if r[4] is not None), key=lambda r: (r[4], r[1]), reverse=descending
        )
        undated = sorted((r for r in rows if r[4] is None), key=lambda r: r[1], reverse=descending)
        return dated + undated
    return sorted(rows, key=lambda r: (r[5], r[1]), reverse=descending)


def _term_hits(
    db: Database, terms: list[str], include_hidden: bool, max_sensitivity: str, *, stale: bool
) -> dict[str, int]:
    """How many current records contain each word on its own. Words of three characters or more
    are counted through the index; the short ones share one pass over the table."""
    allowed = ",".join(
        f"'{lvl}'" for lvl in SENSITIVITY_LEVELS[: SENSITIVITY_LEVELS.index(max_sensitivity) + 1]
    )
    counts: dict[str, int] = {}
    scan = terms
    if not stale:
        scan = [t for t in terms if len(t) < FTS_MIN_CHARS]
        for term in terms:
            if len(term) < FTS_MIN_CHARS:
                continue
            counts[term] = int(
                db.conn.execute(
                    "SELECT COUNT(*) FROM revisions_fts f JOIN revisions r ON r.id = f.rowid"
                    " JOIN records rec ON rec.id = r.record_id WHERE revisions_fts MATCH ?"
                    " AND r.version_no ="
                    " (SELECT MAX(v.version_no) FROM revisions v WHERE v.record_id = r.record_id)"
                    f" AND (rec.hidden = 0 OR ?) AND rec.sensitivity IN ({allowed})",
                    [_fts_expression([term]), 1 if include_hidden else 0],
                ).fetchone()[0]
            )
    if scan:
        counts.update(_scan_hits(db, scan, include_hidden, allowed))
    return {term: counts[term] for term in terms}


def _scan_hits(
    db: Database, terms: list[str], include_hidden: bool, allowed: str
) -> dict[str, int]:
    columns = ", ".join("COALESCE(SUM(r.body_norm LIKE ? ESCAPE '\\'), 0)" for _ in terms)
    row = db.conn.execute(
        f"SELECT {columns} FROM revisions r JOIN records rec ON rec.id = r.record_id"
        " WHERE r.version_no ="
        " (SELECT MAX(v.version_no) FROM revisions v WHERE v.record_id = r.record_id)"
        f" AND (rec.hidden = 0 OR ?) AND rec.sensitivity IN ({allowed})",
        [*(_like_pattern(t) for t in terms), 1 if include_hidden else 0],
    ).fetchone()
    return {term: int(count) for term, count in zip(terms, row, strict=True)}


def _word_hint(alternatives: list[list[str]], hits: dict[str, int]) -> str:
    found = [t for t, n in hits.items() if n]
    if all(len(alt) == 1 for alt in alternatives):
        base = "各詞單獨的命中數見 term_hits。"
        if found:
            names = "、".join(found)
            return base + f"有資料的詞：{names}；其餘詞在這個記憶庫沒有出現過，不必再重送。"
        return base + "每個詞單獨都沒有命中。"
    base = "沒有一筆同時含有全部的詞（同一組的詞須全部出現）；各詞單獨命中數見 term_hits。"
    if found:
        return (
            base + f"其中 {'、'.join(found)} 有資料：用大寫 OR 表示任一（如 A OR B），或分開搜尋。"
        )
    return base + "每個詞單獨都沒有命中。"


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
    current_only: bool = False,
    max_sensitivity: str = "high",
    timezone: str = "local",
    tags: Sequence[str] | None = None,
    match: str = "any",
    tag_types: Sequence[str] | None = None,
    expand: bool = True,
    facets: bool = False,
    untagged: bool = False,
    max_response_chars: int | None = None,
) -> dict[str, Any]:
    require(caller, "search")
    alternatives = parse_alternatives(query)
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
    if match not in ("any", "all"):
        raise EmlekError(ErrorCode.INVALID_INPUT, "match 必須是 any 或 all")
    if tag_types is not None and (not tag_types or any(t not in tagmod.TYPES for t in tag_types)):
        raise EmlekError(ErrorCode.INVALID_INPUT, f"tag_types 必須是 {', '.join(tagmod.TYPES)}")
    if tags is not None and not 1 <= len(tags) <= 20:
        raise EmlekError(ErrorCode.INVALID_INPUT, "tags 一次 1–20 個")
    modifiers = tz_modifiers(timezone)
    # validate dates up front so errors do not depend on which branch runs
    for value, is_end in ((date_from, False), (date_to, True)):
        if value:
            date_bound(value, end=is_end)

    has_index_terms = any(len(t) >= FTS_MIN_CHARS for t in terms)
    wanted = order or ("relevance" if terms else "event_time")
    applied = wanted
    if wanted == "relevance" and not has_index_terms:
        applied, direction = "created_at", "desc"  # no rank without the index; newest first
    elif wanted == "relevance":
        direction = "asc"
    groups: list[list[int]] = []
    unknown: list[str] = []
    expanded: list[str] = []
    cut = False
    impossible = False
    if tags:
        groups, unknown, expanded, cut = tagmod.resolve_filter(db.conn, tags, expand=expand)
        # Unknown names are ignored (and reported). Only when nothing else narrows the
        # search is a lone unknown tag a real "no result".
        narrowed = bool(terms or date_from or date_to or kinds or tag_types)
        impossible = not groups and not narrowed
        if match == "any" and groups:
            merged = sorted({i for g in groups for i in g})
            groups = [merged]
    if impossible:
        return {
            "total": 0,
            "undated": 0,
            "withheld": 0,
            "order": applied,
            "dir": direction,
            "results": [],
            "next_cursor": None,
            "warnings": [],
            "hints": [],
            "unknown_tags": unknown,
            "expanded_tags": expanded,
            "similar_tags": sorted(
                {
                    s
                    for name in unknown
                    for s in tagmod.similar_names(db.conn, tagmod.normalize(name))
                }
            )[:5],
        }
    shared: dict[str, Any] = {
        "tag_groups": groups or None,
        "tag_types": list(tag_types) if tag_types else None,
        "untagged": untagged,
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
    rows = _gather(db, alternatives, stale=False, notes=warnings, only_undated=False, **shared)
    if not rows and has_index_terms:
        # an empty index answer is not proof of absence: look again without the index
        fallback = _gather(db, alternatives, stale=True, only_undated=False, **shared)
        if fallback:
            _log.warning("search index is stale; answered from a full scan")
            rows, warnings = fallback, ["index_stale"]
    undated = 0
    if date_field == "event_time" and (date_from or date_to):
        undated_rows = _gather(db, alternatives, stale=bool(warnings), only_undated=True, **shared)
        undated = len({r[1] for r in undated_rows})

    caps = {level: i for i, level in enumerate(SENSITIVITY_LEVELS)}
    ordered: list[dict[str, Any]] = []
    seen: set[int] = set()
    withheld = 0
    status_map = versions.statuses(db.conn) if versions.has_links(db.conn) else {}
    for rev_id, record_id, version_no, rank_value, ev_start, created_at, sensitivity in rows:
        if record_id in seen:
            continue
        seen.add(record_id)
        if caps[sensitivity] > caps[max_sensitivity]:
            withheld += 1
            continue
        if current_only and status_map.get(record_id) == "superseded":
            continue
        if applied == "relevance":
            key: list[Any] = [rank_value, record_id]
        elif applied == "event_time":
            key = [1 if ev_start is None else 0, ev_start or "", record_id]
        else:
            key = [created_at, record_id]
        ordered.append(
            {
                "rev_id": rev_id,
                "record_id": record_id,
                "version": version_no,
                "key": key,
                "ev_start": ev_start,
                "created_at": created_at,
            }
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

    results: list[dict[str, Any]] = []
    used = 0
    for row in page:
        item = _describe(db, row, terms, status_map)
        size = len(json.dumps(item, ensure_ascii=False))
        if max_response_chars and results and used + size > max_response_chars:
            break
        results.append(item)
        used += size
    trimmed = len(page) - len(results)
    if trimmed:  # the answer would be too big to read: hand back fewer, and the way to the rest
        page = page[: len(results)]
        next_cursor = _encode_cursor(applied, direction, page[-1]["key"])
    hints = _zero_result_hints(db, terms) if terms and not ordered and not warnings else []
    if trimmed:
        hints = [
            *hints,
            f"回應太長，只回了前 {len(results)} 筆（共 {len(ordered)} 筆）；"
            "先縮小日期或詞再搜；真的需要其餘結果才用下一頁游標。",
        ]
    term_hits: dict[str, int] | None = None
    if not tags and len(terms) >= 2 and (not ordered or len(alternatives) >= 2):
        # with OR the AI guesses many words: tell it which ones exist at all, hits or not
        term_hits = _term_hits(
            db,
            terms[:MAX_TERM_HITS],
            include_hidden,
            max_sensitivity,
            stale="index_stale" in warnings,
        )
        if not ordered:
            hints = [*hints, _word_hint(alternatives, term_hits)]
    summary = (
        _summary(db, ordered, date_field, modifiers) if len(ordered) > AGGREGATE_THRESHOLD else None
    )
    extra: dict[str, Any] = {}
    if tags:
        extra["expanded_tags"] = expanded
        if unknown:
            warnings = [*warnings, "unknown_tags_ignored"]
        if cut:
            extra["expanded_truncated"] = True
        if unknown:
            extra["unknown_tags"] = unknown
        plain = {**shared, "tag_groups": None, "tag_types": None, "untagged": False}
        base_rows = _gather(
            db,
            alternatives,
            stale="index_stale" in warnings,
            only_undated=False,
            **plain,
        )
        base_ids = sorted({int(r[1]) for r in base_rows})
        extra["tag_coverage"] = (
            tagmod.tagged_share(db.conn, base_ids) if len(base_ids) <= MAX_COVERAGE_SET else None
        )
    if facets:
        extra["facets"] = tagmod.facets(db.conn, [row["record_id"] for row in ordered])
    if not ordered and (terms or tags):
        near = [
            s for name in unknown for s in tagmod.similar_names(db.conn, tagmod.normalize(name))
        ]
        near += [s for term in terms for s in tagmod.similar_names(db.conn, tagmod.normalize(term))]
        if near:
            extra["similar_tags"] = list(dict.fromkeys(near))[:5]
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
        **({"summary": summary} if summary else {}),
        **({"term_hits": term_hits} if term_hits is not None else {}),
        **({"results_trimmed": trimmed} if trimmed else {}),
        **extra,
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


def _zero_result_hints(db: Database, terms: list[str]) -> list[str]:
    shares = _script_shares(db)
    labels = (("kana", "日文假名"), ("han", "漢字（中文或日文）"), ("latin", "英文字母"))
    present = [(key, label) for key, label in labels if shares[key] >= 0.05]
    tried = {key for key, _ in labels if any(_SCRIPTS[key].search(t) for t in terms)}
    missing = [label for key, label in present if key not in tried]
    if present and not missing:
        return [
            "沒有找到。查詢已涵蓋這個記憶庫用到的各種文字；請改用更上位或更下位的說法、"
            "用標籤或日期縮小範圍，試過仍沒有才能說找不到。"
        ]
    mixed = "、".join(missing or [label for _, label in present]) or "多種寫法"
    return [
        f"沒有找到。這個記憶庫的內容也含 {mixed}，查詢還沒試過；請補上這種寫法"
        "（日文要同時試平假名、片假名與漢字），試過仍沒有才能說找不到。"
    ]


def _local_day(db: Database, created_at: str, modifiers: list[str], cache: dict[str, str]) -> str:
    key = created_at[:13]
    if key not in cache:
        marks = ", ".join(["?"] * (1 + len(modifiers)))
        cache[key] = db.conn.execute(f"SELECT date({marks})", (created_at, *modifiers)).fetchone()[
            0
        ]
    return cache[key]


def _summary(
    db: Database, ordered: list[dict[str, Any]], date_field: str, modifiers: list[str]
) -> dict[str, Any]:
    """Counts and spread of everything that matched, so a reader sees the whole before a page."""
    cache: dict[str, str] = {}
    days: list[str] = []
    undated = 0
    for row in ordered:
        if date_field == "event_time":
            if row["ev_start"] is None:
                undated += 1
                continue
            days.append(row["ev_start"])
        else:
            days.append(_local_day(db, row["created_at"], modifiers, cache))
    by_month = Counter(day[:7] for day in days)
    distribution = (
        {"by_month": dict(sorted(by_month.items()))}
        if len(by_month) <= MAX_SUMMARY_MONTHS
        else {"by_year": dict(sorted(Counter(day[:4] for day in days).items()))}
    )
    return {
        "total": len(ordered),
        "date_field": date_field,
        "first": min(days) if days else None,
        "last": max(days) if days else None,
        **distribution,
        "undated": undated,
        "basis": "keyword",
        "note": SUMMARY_NOTE,
    }


def _describe(
    db: Database, row: dict[str, Any], terms: list[str], status_map: dict[int, str]
) -> dict[str, Any]:
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
        **versions.describe(db.conn, record_id, status_map),
        **_tags_field(db, record_id),
    }


def _tags_field(db: Database, record_id: int) -> dict[str, Any]:
    names = [t["name"] for t in tagmod.tags_of(db.conn, record_id)]
    return {"tags": names} if names else {}


def index_status(db: Database) -> dict[str, Any]:
    revisions = db.conn.execute("SELECT count(*) FROM revisions").fetchone()[0]
    indexed = db.conn.execute("SELECT count(*) FROM revisions_fts_docsize").fetchone()[0]
    return {"revisions": revisions, "indexed": indexed, "ok": revisions == indexed}


def reindex(db: Database, caller: Caller) -> dict[str, Any]:
    require(caller, "reindex")
    with db.transaction() as conn:
        conn.execute("INSERT INTO revisions_fts (revisions_fts) VALUES ('rebuild')")
        for (tag_id,) in conn.execute("SELECT id FROM tags").fetchall():
            tagmod.refresh_search(conn, int(tag_id))
    return index_status(db)
